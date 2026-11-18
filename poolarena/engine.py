"""The conductor: state in, game verdicts and projector effects out.

Deliberately knows nothing about cameras or canvases. It takes TableStates from
anywhere (vision pipeline, simulator, recorded log) and pushes messages into a
Hub that anything can subscribe to.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .attract import AttractMode, IdleWatch
from .ballset import AMERICAN, BallSet
from .events import ShotDetector, ShotWindow
from .geometry import Table
from .placement import PlacementRule, area_outline, check as check_placement
from .recording import Recorder
from .rules import Game, ShotContext, available, get_game
from .server.ws import Hub
from .types import Effect, TableState


@dataclass
class Engine:
    table: Table
    hub: Hub
    ball_set: BallSet = AMERICAN
    #: False when the table states are coming from the simulator rather than
    #: a camera. Nothing behaves differently — but a person looking at the
    #: screen must be able to tell, or they will believe a simulated score.
    live: bool = True
    #: False when nothing is projecting. The engine behaves identically —
    #: the scoreboard draws the guides instead — but the UI stops suggesting
    #: games whose guides belong on the cloth.
    projector: bool = True
    game: Game | None = None
    log_path: Path | None = None
    detector: ShotDetector = field(init=False)
    history: list[dict[str, Any]] = field(default_factory=list)
    on_shot: Callable[[ShotWindow], None] | None = None
    #: how many shots can be taken back
    undo_depth: int = 50
    #: where finished games are kept, so they can be watched back. None
    #: turns recording off.
    recordings: Path | None = None
    #: seconds of a still, unattended table before the attract mode starts.
    #: 0 turns it off. Generous on purpose: a player lining up a long shot can
    #: be motionless for a minute, and a table that lights up mid-stance is
    #: worse than one that never does.
    idle_after: float = 90.0

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
        # After a foul the cue ball is picked up. Until it comes back we are
        # watching for where it is put down, not for a shot.
        self._awaiting_placement = False
        self._placement_from: TableState | None = None
        self._undo: list[tuple[Game, dict[str, Any]]] = []
        self._redo: list[tuple[Game, dict[str, Any]]] = []
        self.recorder = Recorder(self.recordings) if self.recordings else None
        self.idle = IdleWatch(self.idle_after)
        self.attract = AttractMode(table=self.table,
                                   broadcast=self.hub.broadcast,
                                   ball_set=self.ball_set,
                                   games=available(self.ball_set))
        # Idle cannot be judged only when a frame arrives. A camera that has
        # stalled, or a run loop that is sleeping between shots, would never
        # ask the question — and "no frames at all" is about as idle as a
        # table gets. So a heartbeat asks once a second regardless.
        self._heart = threading.Thread(target=self._heartbeat, name="idle-watch",
                                       daemon=True)
        self._heart_stop = threading.Event()
        if self.idle_after > 0:
            self._heart.start()

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

        # A new frame means somebody is at the table, so the attract loop has
        # to go: a ghost game crawling over a live rack is worse than nothing.
        self.wake()
        if self.recorder:
            self.recorder.finish()          # close any game left hanging
        self.game = cls(players=names, table=self.table, options=options or {},
                        ball_set=self.ball_set)
        if self.recorder:
            self.recorder.start(self.game, self.table, self.ball_set)
        self.detector.reset(self.detector.resting)
        self.history.clear()
        self._undo.clear()
        self._redo.clear()
        self._awaiting_turn_fx = True
        self.hub.broadcast({"type": "table", "table": self.table.to_json(),
                            "ball_set": self.ball_set.to_json(),
                            "projector": self.projector,
                            "live": self.live}, sticky_key="table")
        # Wipe every persistent effect before the new game draws anything. A new
        # game's opening batch may contain no persistent guides at all (8-ball
        # shows nothing until groups are assigned), so without an explicit clear
        # the previous game's zones or highlights stay lit on the cloth.
        self.emit_effects(self.game.on_start(), clear="all")
        self.push_history()
        self.push_scoreboard()
        return self.game

    def resume_last(self) -> dict[str, Any] | None:
        """Pick up a frame that was interrupted rather than finished.

        Only the score is restored, never the table: the balls are wherever
        they physically are now, which is the same reasoning as undo. If the
        rack was disturbed in the meantime the scores are still right and the
        operator can correct them with the +/- buttons.
        """
        from .recording import unfinished
        if not self.recordings:
            return None
        prior = unfinished(self.recordings)
        if not prior:
            return None
        try:
            game = self.start_game(prior["game"], players=prior.get("players"))
        except (ValueError, KeyError):
            return None
        for shot in prior.get("shots", []):
            res = shot.get("result", {})
            i = shot.get("shooter", 0)
            if 0 <= i < len(game.players):
                ev = shot.get("events", {})
                game.players[i].score += len(ev.get("pocketed") or [])
            if res.get("turn_passes"):
                game.next_turn()
            game.shot_number += 1
            self.history.append(shot)
        self.push_history()
        self.push_scoreboard()
        return {"id": prior.get("id"), "shots": len(prior.get("shots", [])),
                "players": prior.get("players")}

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
        # A batch carrying persistent guides is replayed to anyone who
        # connects later. Without that, a scoreboard or overlay opened in the
        # middle of a frame shows no zones and no nominated pocket until the
        # next shot ends — and with no projector attached, those guides only
        # exist on the scoreboard, so the game would look broken.
        sticky = any(e.args.get("persist") or e.args.get("duration") == 0
                     for e in effects)
        self.hub.broadcast(msg, sticky_key="guides" if sticky else None)

    # --- the main loop -----------------------------------------------------
    def feed(self, state: TableState) -> ShotWindow | None:
        """Push one observed table state through the whole chain."""
        self._tick_attract(state)
        now = time.time()
        if now - self._last_push > 1.0 / 30.0:
            self.hub.broadcast({"type": "state", "state": state.to_json()}, sticky_key="state")
            self._last_push = now

        if self._check_placement(state):
            # Re-seat the detector so putting the ball down is not then read
            # as a shot that moved it from nowhere.
            self.detector.reset(state)
            return None

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

        if window.events.unreliable:
            # Better to score nothing than to score fiction. The operator can
            # see what happened and put it right with +/- if it mattered.
            self.hub.broadcast({"type": "unreliable",
                                "reason": window.events.unreliable,
                                "lost": window.events.lost})
            self.emit_effects([
                Effect("banner", {"text": "SHOT NOT READ",
                                  "subtitle": window.events.unreliable,
                                  "tone": "bad", "duration": 3500}, layer="hud")])
            self._awaiting_turn_fx = True
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
        if self.recorder:
            self.recorder.add_shot(record, window.events)
            if result.game_over:
                self.recorder.finish(result.winner)
        self._undo.append((snapshot, record))
        del self._undo[:-self.undo_depth]
        self._redo.clear()          # a new shot abandons any redo branch

        if result.ball_in_hand and not result.game_over:
            self._begin_placement(window.after)

        self.hub.broadcast({"type": "shot", "shot": record})
        self.push_history()
        self.emit_effects(result.effects)
        self.push_scoreboard()
        self._awaiting_turn_fx = True

        if self.on_shot:
            self.on_shot(window)
        return window

    # --- ball in hand ---------------------------------------------------------
    @property
    def placement_rule(self) -> PlacementRule:
        area = getattr(self.game, "ball_in_hand_area", "anywhere") if self.game \
            else "anywhere"
        return PlacementRule(area=area)

    def _begin_placement(self, after: TableState) -> None:
        """Start watching for where the cue ball is put back."""
        self._awaiting_placement = True
        self._placement_from = after
        rule = self.placement_rule
        self.emit_effects([
            Effect("placement_area", {
                "area": rule.area,
                "shape": area_outline(self.table, rule),
                "label": f"ball in hand — {rule.describe(self.table)}",
            }, layer="guide"),
        ])
        self.hub.broadcast({"type": "placement", "active": True,
                            "area": rule.area,
                            "shape": area_outline(self.table, rule),
                            "label": rule.describe(self.table)},
                           sticky_key="placement")

    def _check_placement(self, state: TableState) -> bool:
        """Judge a cue ball that has just reappeared. True when handled."""
        if not self._awaiting_placement or not state.settled or state.obstructed:
            return False
        cue = state.cue()
        if cue is None:
            return False                      # still in somebody's hand

        rule = self.placement_rule
        others = [(b.x, b.y) for b in state.balls if not b.is_cue]
        verdict = check_placement(self.table, rule, cue.x, cue.y, others)

        self._awaiting_placement = False
        self._placement_from = None
        # Clear the legal-area marking whatever the verdict; the moment has
        # passed either way.
        self.emit_effects([], clear="guide")
        self.hub.broadcast({"type": "placement", "active": False,
                            **verdict.to_json()}, sticky_key="placement")

        if verdict.ok:
            self.emit_effects([Effect("placement_ok", {"x": cue.x, "y": cue.y})])
        else:
            fx = [Effect("placement_bad", {"x": cue.x, "y": cue.y,
                                           "reason": verdict.reason}),
                  Effect("banner", {"text": "NOT THERE", "subtitle": verdict.reason,
                                    "tone": "bad"}, layer="hud")]
            if verdict.suggestion:
                fx.append(Effect("placement_suggest",
                                 {"x": verdict.suggestion[0],
                                  "y": verdict.suggestion[1]}, layer="guide"))
            self.emit_effects(fx)
        self._awaiting_turn_fx = True
        return True

    # --- attract mode --------------------------------------------------------
    def _tick_attract(self, state: TableState) -> None:
        """Start the attract loop on an abandoned table; kill it on contact.

        Stopping comes first and is unconditional: a ball moving, or an arm
        over the cloth, means a person is there, and nothing should be
        crawling across the table while they shoot.
        """
        if self.idle.observe(state):
            if self.attract.active:
                self.attract.stop()
                self._awaiting_turn_fx = True      # put the game's guides back
            return
        if self.idle_after > 0 and not self.attract.active and self.idle.should_attract():
            self.attract.games = available(self.ball_set)
            self.attract.start()

    def _heartbeat(self) -> None:
        while not self._heart_stop.wait(1.0):
            try:
                if (self.idle_after > 0 and not self.attract.active
                        and self.idle.should_attract()):
                    self.attract.games = available(self.ball_set)
                    self.attract.start()
            except Exception:
                # A background watcher must never take the engine down.
                pass

    def close(self) -> None:
        self._heart_stop.set()
        self.attract.stop()

    def wake(self) -> None:
        """Any deliberate interaction counts as someone being there."""
        self.idle.note_activity()
        if self.attract.active:
            self.attract.stop()
            self._awaiting_turn_fx = True

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
        if self.recorder and self.recorder.session:
            shots = self.recorder.session["shots"]
            if shots:
                shots.pop()
                self.recorder._flush()
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
                            "ball_set": self.ball_set.to_json(),
                            "projector": self.projector,
                            "live": self.live}, sticky_key="table")
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
        if kind not in ("ping", "games"):
            self.wake()
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
                                "ball_set": self.ball_set.to_json(),
                                "projector": self.projector,
                                "live": self.live})
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
        elif kind == "attract":
            # Lets the UI preview it without waiting out the idle timer.
            if msg.get("on"):
                self.attract.games = available(self.ball_set)
                self.attract.start()
            else:
                self.attract.stop()
        elif kind == "ping":
            self.hub.broadcast({"type": "pong", "t": time.time()})

    # --- logging -----------------------------------------------------------
    def _append_log(self, record: dict[str, Any]) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
