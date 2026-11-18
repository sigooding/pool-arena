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
#: A ball on its way into a pocket is last seen near one. At 30 fps a ball
#: at 2 m/s covers 66 mm between frames, so this allows several frames of
#: slack and still rules out a ball that vanished from open cloth.
POCKET_SLACK = 320.0
#: More than this many balls disappearing from open cloth at once is not a
#: shot, it is the detector having lost the table.
MAX_LOST = 2
#: A ball that was never seen to move cannot have been potted. Low enough to
#: allow a ball struck and pocketed almost between frames, high enough to
#: reject detector jitter on a stationary ball.
MIN_TRAVEL_TO_POT = 35.0


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
                self._accumulate(state, moving)   # the first moving frame counts
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

    def _last_step(self, number: int) -> tuple[float, float] | None:
        """The ball's displacement over its final observed frame."""
        tr = self._tracks.get(number)
        if not tr or len(tr.points) < 2:
            return None
        (x1, y1), (x2, y2) = tr.points[-2], tr.points[-1]
        return (x2 - x1, y2 - y1)

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
            pid, dist = self.table.nearest_pocket(px, py)
            # How far it moved between where it sat before the shot and where
            # it was last seen. A ball that never moved cannot have been
            # potted, whatever it was sitting next to — physics, not a
            # threshold. Measured against the resting position rather than
            # along the track, because a ball struck hard may only be caught
            # once on its way in, and a one-point track has no length.
            travelled = math.hypot(px - b.x, py - b.y)

            # How far from a pocket a ball may vanish depends on whether it
            # was heading there. A flat distance cut would reject a genuine
            # pot whenever the camera drops a frame — two missed frames at
            # 4 m/s is over a quarter of a metre — while still accepting a
            # ball that teleported sideways. So: generous along the
            # direction of travel, strict across it.
            allowed = POCKET_SLACK
            step = self._last_step(n)
            if step is not None:
                pocket = self.table.pockets()[pid]
                to_pocket = (pocket[0] - px, pocket[1] - py)
                sn = math.hypot(*step) or 1e-9
                pn = math.hypot(*to_pocket) or 1e-9
                heading = (step[0] * to_pocket[0] + step[1] * to_pocket[1]) / (sn * pn)
                if heading > 0.7:            # within about 45 degrees
                    allowed = max(POCKET_SLACK, sn * 4)

            if dist > allowed or travelled < MIN_TRAVEL_TO_POT:
                # It did not go in a pocket, because it was not near one. A
                # ball cannot leave the table from open cloth, so this is the
                # detector losing it — a flicker of light, a dropped frame, a
                # shadow across the cloth. Scoring it as potted would clear
                # balls nobody struck.
                ev.lost.append(n)
                continue
            if n == 0:
                ev.cue_scratched = True
                ev.pocketed_in[0] = pid
            else:
                ev.pocketed.append(n)
                ev.pocketed_in[n] = pid

        if len(ev.lost) > MAX_LOST:
            ev.unreliable = (f"{len(ev.lost)} balls vanished from open cloth; "
                             f"the camera lost the table rather than anything "
                             f"being potted")
        elif ev.lost and not ev.pocketed and not ev.cue_scratched:
            ev.unreliable = (f"ball {ev.lost[0]} disappeared away from any "
                             f"pocket")

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
        reached: set[int] = set()
        for n, tr in self._tracks.items():
            for name, t in tr.rails:
                if t >= (contact_t or 0.0):
                    rails += 1
                    reached.add(n)
                    ev.contacts.append(Contact(a=n, b=name, t=t))
        ev.rails_after_contact = rails
        # The break rule is about distinct balls reaching a cushion, not about
        # how many times cushions were struck: one ball rattling between two
        # rails is not four balls to the rail.
        ev.balls_to_rail = len(reached)

        ev.trace = {n: tr.points for n, tr in self._tracks.items() if len(tr.points) > 1}

        window = ShotWindow(before=before, after=state, events=ev, table=self.table)
        self.resting = state
        self._shooting = False
        self._still = 0
        self._tracks = {}
        return window
