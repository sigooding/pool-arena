"""Attract mode: what the table does when nobody is playing.

A dark table in the corner of a room is invisible. A table quietly playing a
ghost game of pool with itself, captioned with how to start, is the whole
reason to have put a projector above it.

Three things matter in the design:

  * it must stop instantly. The moment a ball moves or someone leans over the
    cloth, this gets out of the way — a player should never have to dismiss
    anything, and light crawling over the table during a real shot would be
    worse than no attract mode at all;
  * it must not touch the real game. The ghost balls come from a separate
    simulator, so nothing here can corrupt a frame that is paused mid-match;
  * it must say how to play. Pretty lights that do not tell you to rack up
    are decoration, not an invitation.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .ballset import AMERICAN, BallSet
from .geometry import Table

FPS = 30.0


@dataclass
class AttractMode:
    """Drives the ghost game and the captions on a daemon thread."""

    table: Table
    broadcast: Callable[[dict[str, Any]], None]
    ball_set: BallSet = AMERICAN
    games: list[dict[str, Any]] = field(default_factory=list)
    headline: str = "POOL ARENA"
    seed: int | None = None

    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _active: bool = False

    @property
    def active(self) -> bool:
        return self._active

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="attract", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._stop.set()
        t, self._thread = self._thread, None
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        # Tell the overlay to clear, even if the thread was already gone.
        self.broadcast({"type": "attract", "active": False})

    # --- the loop ----------------------------------------------------------
    def _run(self) -> None:
        from .sim import FakeTable, auto_shot

        rng = random.Random(self.seed)
        sim = FakeTable(table=self.table, rng=rng)
        sim.rack("8ball")
        captions = self._captions()
        caption_at = time.time()
        caption_i = 0
        frame = 1.0 / FPS
        shot_rest = 0.0

        while not self._stop.is_set():
            started = time.time()

            if not sim.moving():
                shot_rest += frame
                # A beat between shots, so it reads as a game rather than a
                # physics demo.
                if shot_rest > 2.2:
                    shot_rest = 0.0
                    if sim.cue() is None:
                        sim.spot_cue()
                    live = [b for b in sim.balls if b.live and b.number != 0]
                    if len(live) <= 2:
                        sim.rack("8ball")
                        sim.spot_cue()
                        self.broadcast({"type": "attract", "active": True,
                                        "event": "rack"})
                    elif auto_shot(sim, skill=rng.uniform(0.7, 0.95)).get("shot") == "none":
                        sim.rack("8ball")
                        sim.spot_cue()
            else:
                shot_rest = 0.0
                sim.step_frame()

            now = time.time()
            if now - caption_at > 6.0:
                caption_at = now
                caption_i = (caption_i + 1) % len(captions)

            state = sim.state()
            self.broadcast({
                "type": "attract",
                "active": True,
                "balls": [{"n": b.number, "x": round(b.x, 1), "y": round(b.y, 1)}
                          for b in state.balls],
                "caption": captions[caption_i],
                "cloth": self.table.cloth,
            })

            # Pace it, and wake promptly when told to stop.
            self._stop.wait(max(0.0, frame - (time.time() - started)))

    def _captions(self) -> list[dict[str, str]]:
        """What the table says while it waits. Rotated every few seconds."""
        out: list[dict[str, str]] = [
            {"title": self.headline, "sub": "rack up to play"},
            {"title": "RACK UP", "sub": "the table starts the game itself"},
        ]
        playable = [g for g in self.games if g.get("supported", True)]
        for g in playable[:6]:
            out.append({"title": g["title"].upper(), "sub": g.get("description", "")})
        if len(out) > 2:
            out.append({"title": f"{len(playable)} GAMES", "sub": "rack up to choose"})
        return out


class IdleWatch:
    """Decides when the table counts as abandoned.

    Deliberately conservative about *starting*: a player lining up a long shot
    can be still for a minute, and a table that lights up mid-stance would be
    infuriating. Instantly aggressive about *stopping*.
    """

    def __init__(self, after_seconds: float = 90.0) -> None:
        self.after = after_seconds
        self.last_activity = time.time()
        self._last_positions: dict[int, tuple[float, float]] = {}

    def note_activity(self) -> None:
        self.last_activity = time.time()

    def observe(self, state) -> bool:
        """Feed a table state; returns True when something is happening."""
        if state.obstructed or not state.settled:
            self.note_activity()
            return True
        positions = {b.number: (b.x, b.y) for b in state.balls}
        moved = False
        if self._last_positions:
            if set(positions) != set(self._last_positions):
                moved = True
            else:
                for n, (x, y) in positions.items():
                    px, py = self._last_positions[n]
                    if abs(x - px) > 8 or abs(y - py) > 8:
                        moved = True
                        break
        self._last_positions = positions
        if moved:
            self.note_activity()
        return moved

    @property
    def idle_for(self) -> float:
        return time.time() - self.last_activity

    def should_attract(self) -> bool:
        return self.idle_for >= self.after
