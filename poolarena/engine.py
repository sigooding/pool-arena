"""The conductor: state in, game verdicts and projector effects out.

Deliberately knows nothing about cameras or canvases. It takes TableStates from
anywhere (vision pipeline, simulator, recorded log) and pushes messages into a
Hub that anything can subscribe to.
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .ballset import AMERICAN, BallSet
from .events import ShotDetector, ShotWindow
from .geometry import Table
from .rules import Game, ShotContext, available, get_game
from .server.ws import Hub
from .types import Effect, TableState


@dataclass
class Engine:
    table: Table
    hub: Hub
    ball_set: BallSet = AMERICAN
    game: Game | None = None
    log_path: Path | None = None
    detector: ShotDetector = field(init=False)
    history: list[dict[str, Any]] = field(default_factory=list)
    on_shot: Callable[[ShotWindow], None] | None = None
    #: how many shots can be taken back
    undo_depth: int = 50

    def __post_init__(self) -> None:
        self.detector = ShotDetector(self.table)
        self.hub.on_message = self.handle_client_message
        self._last_push = 0.0
        self._awaiting_turn_fx = True
        # A snapshot of the game taken before each shot is judged. Rewinding
        # a score is not something that can be computed backwards — a foul may
        # have changed whose turn it is, which group each player owns, how many
        # visits they hold and which zones were lit — so the honest way to undo
        # is to keep the state that existed before, and put it back.
        self._undo: list[tuple[Game, dict[str, Any]]] = []
        self._redo: list[tuple[Game, dict[str, Any]]] = []

    # --- game lifecycle ----------------------------------------------------
    def start_game(self, name: str, players: list[str] | None = None,
                   options: dict[str, Any] | None = None) -> Game:
        cls = get_game(name)
        if not cls.supports(self.ball_set):
            raise ValueError(
                f"{cls.title} needs individually numbered balls, and this table "
                f"is set up for {self.ball_set.title.lower()}. Playable here: "
                + ", ".join(g["title"] for g in available(self.ball_set) if g["supported"]))
        names = [n for n in (players or []) if n] or ["Player 1", "Player 2"]
        if not (cls.min_players <= len(names) <= cls.max_players):
            want = (str(cls.min_players) if cls.min_players == cls.max_players
                    else f"{cls.min_players}-{cls.max_players}")
            raise ValueError(
                f"{cls.title} needs {want} players, got {len(names)}: "
                f"{', '.join(names)}")

        self.game = cls(players=names, table=self.table, options=options or {},
                        ball_set=self.ball_set)
        self.detector.reset(self.detector.resting)
        self.history.clear()
        self._undo.clear()
        self._redo.clear()
        self._awaiting_turn_fx = True
        self.hub.broadcast({"type": "table", "table": self.table.to_json(),
                            "ball_set": self.ball_set.to_json()}, sticky_key="table")
        # Wipe every persistent effect before the new game draws anything. A new
        # game's opening batch may contain no persistent guides at all (8-ball
        # shows nothing until groups are assigned), so without an explicit clear
        # the previous game's zones or highlights stay lit on the cloth.
        self.emit_effects(self.game.on_start(), clear="all")
        self.push_history()
        self.push_scoreboard()
        return self.game

    def push_scoreboard(self) -> None:
        if self.game:
            board = self.game.scoreboard()
            board["can_undo"] = self.can_undo
            board["can_redo"] = self.can_redo
            self.hub.broadcast({"type": "scoreboard", "scoreboard": board},
                               sticky_key="scoreboard")

    def push_history(self) -> None:
        """The shot list, replayed to anyone who connects.

        Sticky because the scoreboard builds its feed from this rather than
        from live shot messages: open the page in the middle of a frame and
        you should see what has happened, not an empty panel. It also means
        undo needs no special case in the client — the list simply gets
        shorter.
        """
        self.hub.broadcast({"type": "history", "history": self.history[-25:],
                            "can_undo": self.can_undo, "can_redo": self.can_redo},
                           sticky_key="history")

    def emit_effects(self, effects: list[Effect], clear: str | None = None) -> None:
        """Send a batch. `clear` drops existing persistent effects first:
        "all", or a single layer name ("guide" / "fx" / "hud")."""
        if not effects and not clear:
            return
        msg: dict[str, Any] = {"type": "effects",
                               "effects": [e.to_json() for e in effects]}
        if clear:
            msg["clear"] = clear
        self.hub.broadcast(msg)

    # --- the main loop -----------------------------------------------------
    def feed(self, state: TableState) -> ShotWindow | None:
        """Push one observed table state through the whole chain."""
        now = time.time()
        if now - self._last_push > 1.0 / 30.0:
            self.hub.broadcast({"type": "state", "state": state.to_json()}, sticky_key="state")
            self._last_push = now

        window = self.detector.push(state)

        if window is None:
            # Turn-start guides are emitted once the table is at rest again.
            if (self.game and self._awaiting_turn_fx and state.settled
                    and not state.obstructed and state.balls):
                self.emit_effects(self.game.on_turn_start(state))
                self._awaiting_turn_fx = False
            return None

        if self.game is None:
            return window

        ctx = ShotContext(before=window.before, after=window.after,
                          events=window.events, table=self.table, shooter=self.game.turn)
        snapshot = self._snapshot(self.game)
        result = self.game.apply(ctx)

        record = {
            "shot": self.game.shot_number,
            "shooter": ctx.shooter,
            "events": window.events.to_json(),
            "result": result.to_json(),
            "before": window.before.to_json(),
            "after": window.after.to_json(),
        }
        self.history.append(record)
        self._append_log(record)
        self._undo.append((snapshot, record))
        del self._undo[:-self.undo_depth]
        self._redo.clear()          # a new shot abandons any redo branch

        self.hub.broadcast({"type": "shot", "shot": record})
        self.push_history()
        self.emit_effects(result.effects)
        self.push_scoreboard()
        self._awaiting_turn_fx = True

        if self.on_shot:
            self.on_shot(window)
        return window

    # --- undo ---------------------------------------------------------------
    def _snapshot(self, game: Game) -> Game:
        """A deep copy of the game, sharing the table.

        The table is geometry and never changes during a frame, so copying it
        would only waste memory and leave the restored game pointing at a
        different object than the engine.
        """
        table = game.table
        game.table = None                    # type: ignore[assignment]
        try:
            clone = copy.deepcopy(game)
        finally:
            game.table = table
        clone.table = table
        return clone

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> dict[str, Any]:
        """Take back the last judged shot.

        This rewinds the *score*, not the table. The balls are wherever they
        physically are, and the detector keeps its current resting state — so
        after an undo the next real shot is judged from where the table
        actually is, which is what you want when the system got one wrong.
        """
        if not self._undo:
            return {"ok": False, "error": "nothing to undo"}
        snapshot, record = self._undo.pop()
        self._redo.append((self._snapshot(self.game), record))
        self.game = snapshot
        if self.history:
            self.history.pop()
        self._awaiting_turn_fx = True
        self._after_rewind(f"undid shot {record.get('shot', 0) + 1}")
        return {"ok": True, "undone": record, "can_undo": self.can_undo}

    def redo(self) -> dict[str, Any]:
        if not self._redo:
            return {"ok": False, "error": "nothing to redo"}
        snapshot, record = self._redo.pop()
        self._undo.append((self._snapshot(self.game), record))
        self.game = snapshot
        self.history.append(record)
        self._awaiting_turn_fx = True
        self._after_rewind(f"redid shot {record.get('shot', 0) + 1}")
        return {"ok": True, "redone": record, "can_redo": self.can_redo}

    def adjust_score(self, player: int, delta: int = 0,
                     value: int | None = None) -> dict[str, Any]:
        """Set a score by hand.

        Undo on its own only half-fixes a misread shot: it puts the old score
        back, but nothing re-judges what really happened. This is the other
        half — the override for when the camera called it wrong and the right
        answer is simply a different number.
        """
        if not self.game:
            return {"ok": False, "error": "no game running"}
        if not 0 <= player < len(self.game.players):
            return {"ok": False, "error": f"no player {player}"}
        p = self.game.players[player]
        before = p.score
        p.score = int(value) if value is not None else max(0, p.score + int(delta))
        self.push_scoreboard()
        self.emit_effects([Effect("score_pop", {"player": player,
                                                "delta": p.score - before,
                                                "total": p.score}, layer="hud")])
        return {"ok": True, "player": player, "score": p.score}

    def _after_rewind(self, message: str) -> None:
        self.hub.broadcast({"type": "table", "table": self.table.to_json(),
                            "ball_set": self.ball_set.to_json()}, sticky_key="table")
        # Clear the cloth: the effects on it belong to a shot that no longer
        # counts, and leaving a win banner up after undoing the winning shot
        # would be worse than showing nothing.
        self.emit_effects([Effect("banner", {"text": "UNDO", "subtitle": message,
                                             "tone": "bad", "duration": 2200},
                                  layer="hud")], clear="all")
        self.push_scoreboard()
        self.push_history()

    # --- client commands ---------------------------------------------------
    def handle_client_message(self, msg: dict[str, Any], client: Any = None) -> None:
        """Commands from the overlay, the tablet scoreboard, or a curl.

        Kept to a tiny verb set on purpose: a wall-mounted tablet with four
        buttons should be able to run the whole night.
        """
        kind = msg.get("type") or msg.get("cmd")
        if kind == "start_game":
            try:
                self.start_game(msg.get("game", "8ball"), msg.get("players"),
                                msg.get("options"))
            except (ValueError, KeyError) as exc:
                # Broadcast rather than reply: the click came from the tablet,
                # but the person is probably looking at the table.
                self.hub.broadcast({"type": "error", "error": str(exc),
                                    "context": "start_game"})
        elif kind == "games":
            self.hub.broadcast({"type": "games", "games": available(self.ball_set),
                                "ball_set": self.ball_set.to_json()})
        elif kind == "call_pocket" and self.game and hasattr(self.game, "call"):
            self.game.call(msg["pocket"])          # type: ignore[attr-defined]
            self.emit_effects([Effect("pocket_glow", {"pocket": msg["pocket"],
                                                      "color": "#f472b6", "persist": True},
                                      layer="guide")])
        elif kind == "undo":
            self.hub.broadcast({"type": "undo_result", **self.undo()})
        elif kind == "redo":
            self.hub.broadcast({"type": "undo_result", **self.redo()})
        elif kind == "adjust_score":
            self.adjust_score(int(msg.get("player", 0)),
                              delta=int(msg.get("delta", 0)),
                              value=msg.get("value"))
        elif kind == "next_turn" and self.game:
            self.game.next_turn()
            self.push_scoreboard()
            self._awaiting_turn_fx = True
        elif kind == "test_effect":
            self.emit_effects([Effect(msg.get("name", "explosion"), msg.get("args", {}),
                                      msg.get("layer", "fx"))])
        elif kind == "projector_calibration":
            # The overlay owns its own keystone; we just store and rebroadcast it
            # so a second screen picks up the same mapping.
            self.hub.broadcast({"type": "projector_calibration",
                                "corners": msg.get("corners")},
                               sticky_key="projector_calibration")
            if msg.get("save"):
                Path(msg.get("path", "config/projector.json")).write_text(
                    json.dumps({"corners": msg.get("corners")}, indent=2))
        elif kind == "calibrate":
            # Relayed, not acted on: the overlay owns the projector mapping.
            # This lets the person stand at the table with a tablet instead of
            # being at the PC keyboard, which is the only place the hotkeys
            # could ever be used from.
            self.hub.broadcast({"type": "calibrate", "on": bool(msg.get("on", True))})
        elif kind == "projector_nudge":
            self.hub.broadcast({"type": "projector_nudge",
                                "corner": int(msg.get("corner", 0)),
                                "dx": float(msg.get("dx", 0)),
                                "dy": float(msg.get("dy", 0)),
                                "reset": bool(msg.get("reset", False))})
        elif kind == "ping":
            self.hub.broadcast({"type": "pong", "t": time.time()})

    # --- logging -----------------------------------------------------------
    def _append_log(self, record: dict[str, Any]) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
