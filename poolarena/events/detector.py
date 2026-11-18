"""Turn a stream of TableStates into one ShotEvents per shot.

The approach is rest-state driven, which is what makes 30 fps hardware such as
a Kinect v2 usable: we do not try to read physics every frame. We snapshot the
table when it is still, watch the motion, and read the result when it is still
again. Everything that needs sub-frame accuracy (exact contact point, spin) is
deliberately out of scope.

First contact is inferred from *motion onset order* rather than proximity: at
30 fps a ball travelling 3 m/s moves 100 mm between frames, so a proximity test
misses collisions outright, while "which object ball twitched first" survives a
low frame rate well.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..geometry import Table
from ..types import Contact, ShotEvents, TableState

# Tuning. All distances in mm, all times in seconds.
MOVE_EPS = 6.0          # per-frame displacement that counts as moving
SETTLE_FRAMES = 4       # consecutive still frames before the table is "at rest"
MAX_SHOT = 25.0         # a shot longer than this is treated as a glitch
RAIL_BAND = 45.0        # centre this close to a cushion counts as touching it


@dataclass
class ShotWindow:
    """One shot, from cue strike to everything at rest."""

    before: TableState
    after: TableState
    events: ShotEvents
    table: Table


@dataclass
class _Track:
    first_moved: float | None = None
    last_moved: float | None = None
    points: list[tuple[float, float]] = field(default_factory=list)
    rails: list[tuple[str, float]] = field(default_factory=list)


class ShotDetector:
    """Feed it every TableState; it returns a ShotWindow when a shot completes."""

    def __init__(self, table: Table) -> None:
        self.table = table
        self.resting: TableState | None = None
        self._still = 0
        self._shooting = False
        self._t0 = 0.0
        self._prev: TableState | None = None
        self._tracks: dict[int, _Track] = {}

    # --- public ------------------------------------------------------------
    def push(self, state: TableState) -> ShotWindow | None:
        if state.obstructed:
            # Arm or cue over the cloth: positions are unreliable, but the shot
            # clock keeps running so we do not lose a shot that started here.
            self._prev = None
            return None

        moving = self._moving_balls(state)

        if not self._shooting:
            if self.resting is None:
                self.resting = state
                self._prev = state
                return None
            if moving:
                self._begin(state)
            else:
                self.resting = state
            self._prev = state
            return None

        # mid-shot
        self._accumulate(state, moving)
        self._prev = state

        if moving:
            self._still = 0
        else:
            self._still += 1

        timed_out = state.ts - self._t0 > MAX_SHOT
        if self._still >= SETTLE_FRAMES or timed_out:
            return self._finish(state)
        return None

    def reset(self, state: TableState | None = None) -> None:
        self.resting = state
        self._shooting = False
        self._still = 0
        self._tracks.clear()
        self._prev = state

    # --- internals ---------------------------------------------------------
    def _moving_balls(self, state: TableState) -> set[int]:
        if self._prev is None:
            return set()
        prev = self._prev.by_number()
        out: set[int] = set()
        for b in state.balls:
            p = prev.get(b.number)
            if p is None:
                continue
            if math.hypot(b.x - p.x, b.y - p.y) > MOVE_EPS:
                out.add(b.number)
        # A ball that vanished between frames is on its way into a pocket.
        out |= (prev.keys() - state.numbers())
        return out

    def _begin(self, state: TableState) -> None:
        self._shooting = True
        self._t0 = state.ts
        self._still = 0
        self._tracks = {}

    def _accumulate(self, state: TableState, moving: set[int]) -> None:
        t = state.ts - self._t0
        for b in state.balls:
            tr = self._tracks.setdefault(b.number, _Track())
            tr.points.append((b.x, b.y))
            if b.number in moving:
                if tr.first_moved is None:
                    tr.first_moved = t
                tr.last_moved = t
                rail = self._rail_touch(b.number, b.x, b.y)
                if rail and (not tr.rails or tr.rails[-1][0] != rail or t - tr.rails[-1][1] > 0.35):
                    tr.rails.append((rail, t))
        for n in moving - state.numbers():
            self._tracks.setdefault(n, _Track()).first_moved = (
                self._tracks[n].first_moved if self._tracks.get(n) and self._tracks[n].first_moved is not None else t
            )

    def _rail_touch(self, number: int, x: float, y: float) -> str | None:
        t = self.table
        if x < RAIL_BAND:
            return "left"
        if x > t.length - RAIL_BAND:
            return "right"
        if y < RAIL_BAND:
            return "top"
        if y > t.width - RAIL_BAND:
            return "bottom"
        return None

    def _finish(self, state: TableState) -> ShotWindow:
        before = self.resting or state
        ev = ShotEvents(duration=state.ts - self._t0)

        gone = before.numbers() - state.numbers()
        prior = before.by_number()
        for n in sorted(gone):
            b = prior[n]
            last = self._tracks.get(n)
            px, py = (last.points[-1] if last and last.points else (b.x, b.y))
            pid = self.table.in_pocket(px, py) or self.table.nearest_pocket(px, py)[0]
            if n == 0:
                ev.cue_scratched = True
                ev.pocketed_in[0] = pid
            else:
                ev.pocketed.append(n)
                ev.pocketed_in[n] = pid

        cue_track = self._tracks.get(0)
        ev.cue_struck = bool(cue_track and cue_track.first_moved is not None) or ev.cue_scratched

        # First contact: earliest object ball to start moving.
        onsets = [
            (tr.first_moved, n)
            for n, tr in self._tracks.items()
            if n != 0 and tr.first_moved is not None
        ]
        if onsets:
            onsets.sort()
            ev.first_contact = onsets[0][1]
            ev.contacts.append(Contact(a=0, b=onsets[0][1], t=onsets[0][0] or 0.0))

        # Rails after contact, pooled across every ball (the common "four rails
        # or a ball to a cushion" legality test in most rule sets).
        contact_t = onsets[0][0] if onsets else 0.0
        rails = 0
        for n, tr in self._tracks.items():
            for name, t in tr.rails:
                if t >= (contact_t or 0.0):
                    rails += 1
                    ev.contacts.append(Contact(a=n, b=name, t=t))
        ev.rails_after_contact = rails

        ev.trace = {n: tr.points for n, tr in self._tracks.items() if len(tr.points) > 1}

        window = ShotWindow(before=before, after=state, events=ev, table=self.table)
        self.resting = state
        self._shooting = False
        self._still = 0
        self._tracks = {}
        return window
