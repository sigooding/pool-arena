"""Finding the cue, and the line the player is actually on.

Everything else in this system reads the table when it is still. The cue is
the opposite: it only exists in the frames that get thrown away, while
somebody is leaning over the cloth and the obstruction detector is saying
"ignore this". So this runs on exactly those frames.

A cue is the easiest shape on the table to describe and one of the harder
ones to find. It is very long, very straight, very thin, and it comes in from
outside the cushion — but so does an arm, and the edge of a shadow is also a
long straight line. The filters below are therefore about what a cue *is*
relative to the table, not about how it looks:

  * it is long — over a third of the table's length;
  * it is straight, by construction (a line segment detector only returns
    straight things);
  * one end is near the cue ball, because that is what aiming means;
  * the other end is off the table, because the player is holding it.

The last two are what separate a cue from an arm, and they cost nothing.

This is the one part of the project I have not been able to test against a
real table, and a line detector is exactly the kind of thing that behaves
differently on real pixels. Treat it as a starting point with the dials
exposed, not as a finished feature.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ..geometry import Table

Point = tuple[float, float]


@dataclass
class CueLine:
    """A cue, in table millimetres, pointing the way it is aimed."""

    butt: Point           # the end the player holds, usually off the table
    tip: Point            # the end near the cue ball
    length_mm: float
    confidence: float

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.tip[1] - self.butt[1],
                                       self.tip[0] - self.butt[0]))

    def project(self, distance: float) -> Point:
        """Where the line goes, `distance` mm past the tip."""
        a = math.radians(self.angle_deg)
        return (self.tip[0] + math.cos(a) * distance,
                self.tip[1] + math.sin(a) * distance)

    def to_json(self) -> dict[str, Any]:
        return {"butt": [round(self.butt[0], 1), round(self.butt[1], 1)],
                "tip": [round(self.tip[0], 1), round(self.tip[1], 1)],
                "angle": round(self.angle_deg, 1),
                "length_mm": round(self.length_mm),
                "confidence": round(self.confidence, 2)}


@dataclass
class CueTracker:
    """Looks for a cue in the warped top-down view."""

    table: Table
    px_per_mm: float = 0.5
    #: Shortest thing that can be a cue, as a fraction of the table length.
    #: Deliberately modest: the warped view is cropped to the cloth, so only
    #: the part of the cue actually over the table is visible. A cue aimed
    #: from the baulk cushion may show barely half a metre of itself.
    min_length: float = 0.18
    #: how close the tip must come to the cue ball
    tip_radius_mm: float = 260.0
    #: smoothing, because a hand shake should not swing the projected line
    smoothing: float = 0.45
    last: CueLine | None = None

    def find(self, warped: np.ndarray, cue_ball: Point | None) -> CueLine | None:
        import cv2
        if cue_ball is None:
            self.last = None
            return None

        gray = (cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
                if warped.ndim == 3 else warped)
        # A cue is a hard edge against cloth; blurring first kills the cloth
        # texture without touching an object this big.
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        min_px = self.table.length * self.px_per_mm * self.min_length
        lines = cv2.HoughLinesP(
            cv2.Canny(gray, 40, 120), 1, np.pi / 360,
            threshold=55, minLineLength=int(min_px), maxLineGap=int(min_px * 0.4))
        if lines is None:
            return self._smooth(None)

        # OpenCV 4 returns (N, 1, 4); OpenCV 5 returns (N, 4). Accept either
        # rather than pinning a version.
        segs = np.asarray(lines)
        segs = segs.reshape(-1, 4) if segs.ndim in (2, 3) else segs
        best, best_score = None, 0.0
        for x1, y1, x2, y2 in segs:
            a = (x1 / self.px_per_mm, y1 / self.px_per_mm)
            b = (x2 / self.px_per_mm, y2 / self.px_per_mm)
            cand = self._score(a, b, cue_ball)
            if cand and cand[1] > best_score:
                best, best_score = cand[0], cand[1]
        return self._smooth(best)

    def _score(self, a: Point, b: Point, cue_ball: Point):
        length = math.dist(a, b)
        if length < self.table.length * self.min_length:
            return None
        # Which end is the tip: the one nearer the cue ball.
        da, db = math.dist(a, cue_ball), math.dist(b, cue_ball)
        tip, butt = (a, b) if da < db else (b, a)
        near = min(da, db)
        if near > self.tip_radius_mm:
            return None
        # The butt should be off the table, or at least out near a cushion —
        # this is what rejects a long edge lying across the middle.
        if self.table.on_table(*butt, margin=-80):
            return None
        # Prefer long lines whose tip is closest to the ball.
        score = (1 - near / self.tip_radius_mm) * min(1.0, length / self.table.length)
        return CueLine(butt=butt, tip=tip, length_mm=length,
                       confidence=round(min(1.0, score * 1.6), 2)), score

    def _smooth(self, found: CueLine | None) -> CueLine | None:
        """Ease towards the new line, so the projection does not jitter."""
        if found is None:
            self.last = None
            return None
        if self.last is None:
            self.last = found
            return found
        k = self.smoothing
        mix = lambda p, q: (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)
        self.last = CueLine(butt=mix(self.last.butt, found.butt),
                            tip=mix(self.last.tip, found.tip),
                            length_mm=found.length_mm,
                            confidence=found.confidence)
        return self.last


def aim_targets(table: Table, cue: CueLine, balls: Sequence[tuple[int, float, float]]):
    """What the line hits first, and where that ball would then go.

    Only geometry — no physics beyond the fact that an object ball leaves
    along the line of centres. That is enough for an aiming line and honest
    about what it is.
    """
    r = table.ball_radius
    a = math.radians(cue.angle_deg)
    d = (math.cos(a), math.sin(a))
    best = None
    for num, bx, by in balls:
        if num == 0:
            continue
        ox, oy = bx - cue.tip[0], by - cue.tip[1]
        along = ox * d[0] + oy * d[1]
        if along <= 0:
            continue
        perp = abs(ox * d[1] - oy * d[0])
        if perp > 2 * r:
            continue
        if best is None or along < best[0]:
            best = (along, num, (bx, by), perp)
    if best is None:
        return None
    along, num, pos, perp = best
    contact = (cue.tip[0] + d[0] * along, cue.tip[1] + d[1] * along)
    out_angle = math.atan2(pos[1] - contact[1], pos[0] - contact[0])
    return {
        "ball": num,
        "contact": [round(contact[0], 1), round(contact[1], 1)],
        "object_path": [list(pos),
                        [round(pos[0] + math.cos(out_angle) * 900, 1),
                         round(pos[1] + math.sin(out_angle) * 900, 1)]],
        "cut_offset_mm": round(perp, 1),
    }
