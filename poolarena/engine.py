"""The conductor: state in, game verdicts and projector effects out.

Deliberately knows nothing about cameras or canvases. It takes TableStates from
anywhere (vision pipeline, simulator, recorded log) and pushes messages into a
Hub that anything can subscribe to.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .events import ShotDetector, ShotWindow
from .geometry import Table
from .rules import Game, ShotContext, available, get_game
from .server.ws import Hub
from .types import Effect, TableState


@dataclass
class Engine:
    table: Table
    hub: Hub
    game: Game | None = None
    log_path: Path | None = None
    detector: ShotDetector = field(init=False)
    history: list[dict[str, Any]] = field(default_factory=list)
    on_shot: Callable[[ShotWindow], None] | None = None

    def __post_init__(self) -> None:
        self.detector = ShotDetector(self.table)
        self.hub.on_message = self.handle_client_message
        self._last_push = 0.0
        self._awaiting_turn_fx = True

    # --- game lifecycle ----------------------------------------------------
    def start_game(self, name: str, players: list[str] | None = None,
                   options: dict[str, Any] | None = None) -> Game:
        cls = get_game(name)
        self.game = cls(players=players, table=self.table, options=options or {})
        self.detector.reset(self.detector.resting)
        self.history.clear()
        self._awaiting_turn_fx = True
        self.hub.broadcast({"type": "table", "table": self.table.to_json()}, sticky_key="table")
        self.emit_effects(self.game.on_start())
        self.push_scoreboard()
        return self.game

    def push_scoreboard(self) -> None:
        if self.game:
            self.hub.broadcast({"type": "scoreboard", "scoreboard": self.game.scoreboard()},
                               sticky_key="scoreboard")

    def emit_effects(self, effects: list[Effect]) -> None:
        if not effects:
            return
        self.hub.broadcast({"type": "effects", "effects": [e.to_json() for e in effects]})

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

        self.hub.broadcast({"type": "shot", "shot": record})
        self.emit_effects(result.effects)
        self.push_scoreboard()
        self._awaiting_turn_fx = True

        if self.on_shot:
            self.on_shot(window)
        return window

    # --- client commands ---------------------------------------------------
    def handle_client_message(self, msg: dict[str, Any], client: Any = None) -> None:
        """Commands from the overlay, the tablet scoreboard, or a curl.

        Kept to a tiny verb set on purpose: a wall-mounted tablet with four
        buttons should be able to run the whole night.
        """
        kind = msg.get("type") or msg.get("cmd")
        if kind == "start_game":
            self.start_game(msg.get("game", "8ball"), msg.get("players"), msg.get("options"))
        elif kind == "games":
            self.hub.broadcast({"type": "games", "games": available()})
        elif kind == "call_pocket" and self.game and hasattr(self.game, "call"):
            self.game.call(msg["pocket"])          # type: ignore[attr-defined]
            self.emit_effects([Effect("pocket_glow", {"pocket": msg["pocket"],
                                                      "color": "#f472b6", "persist": True},
                                      layer="guide")])
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
        elif kind == "ping":
            self.hub.broadcast({"type": "pong", "t": time.time()})

    # --- logging -----------------------------------------------------------
    def _append_log(self, record: dict[str, Any]) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
