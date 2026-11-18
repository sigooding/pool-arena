"""Table geometry: millimetre coordinate space, pockets, and homography.

Coordinate space: origin at the top-left inside corner of the cushions,
+x along the long rail, +y across the table, millimetres. Every layer above
vision speaks only this space, so swapping cameras changes nothing downstream.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np

from .types import POCKETS

Point = tuple[float, float]

# Playing-surface sizes, inside the cushions, in millimetres.
TABLE_SIZES = {
    "7ft": (1981.0, 991.0),
    "8ft": (2235.0, 1118.0),
    "8ft-pro": (2337.0, 1168.0),
    "9ft": (2540.0, 1270.0),
    "10ft": (2845.0, 1422.0),
    "snooker": (3569.0, 1778.0),
}


@dataclass
class Table:
    """Table dimensions plus pocket geometry."""

    size: str = "8ft"
    length: float = 0.0
    width: float = 0.0
    ball_radius: float = 28.6
    corner_mouth: float = 115.0   # pocket mouth width, corner
    side_mouth: float = 130.0     # pocket mouth width, side
    pocket_capture: float = 70.0  # a ball centre within this of a pocket mouth counts as pocketed

    def __post_init__(self) -> None:
        if not self.length or not self.width:
            self.length, self.width = TABLE_SIZES.get(self.size, TABLE_SIZES["8ft"])

    # --- pockets -----------------------------------------------------------
    def pockets(self) -> dict[str, Point]:
        L, W = self.length, self.width
        return {
            "TL": (0.0, 0.0),
            "TM": (L / 2, 0.0),
            "TR": (L, 0.0),
            "BL": (0.0, W),
            "BM": (L / 2, W),
            "BR": (L, W),
        }

    def pocket_mouth(self, pocket: str) -> float:
        return self.side_mouth if pocket in ("TM", "BM") else self.corner_mouth

    def nearest_pocket(self, x: float, y: float) -> tuple[str, float]:
        """Closest pocket id and the distance to it, in mm."""
        best, best_d = "TL", float("inf")
        for pid, (px, py) in self.pockets().items():
            d = math.hypot(x - px, y - py)
            if d < best_d:
                best, best_d = pid, d
        return best, best_d

    def in_pocket(self, x: float, y: float) -> str | None:
        pid, d = self.nearest_pocket(x, y)
        return pid if d <= self.pocket_capture + self.pocket_mouth(pid) / 2 else None

    def on_table(self, x: float, y: float, margin: float = 0.0) -> bool:
        return -margin <= x <= self.length + margin and -margin <= y <= self.width + margin

    # --- useful spots ------------------------------------------------------
    @property
    def foot_spot(self) -> Point:
        return (self.length * 0.75, self.width / 2)

    @property
    def head_spot(self) -> Point:
        return (self.length * 0.25, self.width / 2)

    @property
    def head_string(self) -> float:
        return self.length * 0.25

    @property
    def centre(self) -> Point:
        return (self.length / 2, self.width / 2)

    def diamonds(self) -> list[Point]:
        """The 18 rail diamonds, handy as calibration references."""
        L, W = self.length, self.width
        out: list[Point] = []
        for i in range(1, 8):
            out.append((L * i / 8, 0.0))
            out.append((L * i / 8, W))
        for i in range(1, 5):
            out.append((0.0, W * i / 4))
            out.append((L, W * i / 4))
        return out

    def to_json(self) -> dict:
        return {
            "size": self.size,
            "length": self.length,
            "width": self.width,
            "ball_radius": self.ball_radius,
            "pockets": {k: list(v) for k, v in self.pockets().items()},
            "corner_mouth": self.corner_mouth,
            "side_mouth": self.side_mouth,
            "foot_spot": list(self.foot_spot),
            "head_spot": list(self.head_spot),
            "head_string": self.head_string,
        }


# --- homography -----------------------------------------------------------

def homography(src: Sequence[Point], dst: Sequence[Point]) -> np.ndarray:
    """Least-squares 3x3 homography mapping src -> dst. Needs >= 4 pairs.

    Pure numpy, so calibration maths is testable without OpenCV.
    """
    if len(src) != len(dst) or len(src) < 4:
        raise ValueError("need at least 4 matching point pairs")
    A: list[list[float]] = []
    b: list[float] = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    h, *_ = np.linalg.lstsq(np.asarray(A, float), np.asarray(b, float), rcond=None)
    return np.append(h, 1.0).reshape(3, 3)


def apply_h(H: np.ndarray, pts: Sequence[Point]) -> list[Point]:
    """Map points through a homography."""
    p = np.asarray(pts, float).reshape(-1, 2)
    hom = np.hstack([p, np.ones((len(p), 1))])
    out = hom @ H.T
    w = np.where(np.abs(out[:, 2:3]) < 1e-12, 1e-12, out[:, 2:3])
    out = out[:, :2] / w
    return [(float(a), float(bb)) for a, bb in out]


def reprojection_error(H: np.ndarray, src: Sequence[Point], dst: Sequence[Point]) -> float:
    """RMS error in dst units. Print this after calibrating: under ~3 mm is good."""
    got = apply_h(H, src)
    errs = [math.hypot(g[0] - d[0], g[1] - d[1]) for g, d in zip(got, dst)]
    return float(math.sqrt(sum(e * e for e in errs) / len(errs)))


@dataclass
class Calibration:
    """Image-pixel <-> table-millimetre mapping, plus where it came from."""

    image_points: list[Point] = field(default_factory=list)
    table_points: list[Point] = field(default_factory=list)
    label: str = "corners"
    error_mm: float = 0.0
    _H: np.ndarray | None = None

    def solve(self) -> np.ndarray:
        self._H = homography(self.image_points, self.table_points)
        self.error_mm = reprojection_error(self._H, self.image_points, self.table_points)
        return self._H

    @property
    def H(self) -> np.ndarray:
        if self._H is None:
            self.solve()
        assert self._H is not None
        return self._H

    def to_table(self, pts: Sequence[Point]) -> list[Point]:
        return apply_h(self.H, pts)

    def to_image(self, pts: Sequence[Point]) -> list[Point]:
        return apply_h(np.linalg.inv(self.H), pts)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "image_points": self.image_points,
            "table_points": self.table_points,
            "label": self.label,
            "error_mm": self.error_mm,
        }, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Calibration":
        d = json.loads(Path(path).read_text())
        c = cls(
            image_points=[tuple(p) for p in d["image_points"]],
            table_points=[tuple(p) for p in d["table_points"]],
            label=d.get("label", "corners"),
        )
        c.solve()
        return c

    @classmethod
    def from_corners(cls, image_corners: Sequence[Point], table: Table) -> "Calibration":
        """image_corners in order TL, TR, BR, BL."""
        L, W = table.length, table.width
        c = cls(
            image_points=[tuple(p) for p in image_corners],
            table_points=[(0.0, 0.0), (L, 0.0), (L, W), (0.0, W)],
            label="corners",
        )
        c.solve()
        return c


# --- aiming maths, used by the trajectory overlay -------------------------

def ghost_ball(cue: Point, target: Point, pocket: Point, r: float = 28.6) -> Point:
    """Where the cue ball must end up to send `target` at `pocket`."""
    dx, dy = pocket[0] - target[0], pocket[1] - target[1]
    d = math.hypot(dx, dy) or 1e-9
    return (target[0] - 2 * r * dx / d, target[1] - 2 * r * dy / d)


def cut_angle(cue: Point, target: Point, pocket: Point) -> float:
    """Cut angle in degrees. 0 == straight in, 90 == impossible."""
    a = (target[0] - cue[0], target[1] - cue[1])
    b = (pocket[0] - target[0], pocket[1] - target[1])
    na = math.hypot(*a) or 1e-9
    nb = math.hypot(*b) or 1e-9
    cos = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (na * nb)))
    return math.degrees(math.acos(cos))


def path_blocked(start: Point, end: Point, blockers: Sequence[Point], r: float = 28.6) -> bool:
    """True when any blocker centre sits within 2r of the segment."""
    sx, sy = start
    ex, ey = end
    vx, vy = ex - sx, ey - sy
    seg2 = vx * vx + vy * vy or 1e-9
    for bx, by in blockers:
        t = max(0.0, min(1.0, ((bx - sx) * vx + (by - sy) * vy) / seg2))
        px, py = sx + t * vx, sy + t * vy
        if math.hypot(bx - px, by - py) < 2 * r - 1.0:
            return True
    return False


def shot_candidates(cue: Point, target: Point, table: Table,
                    blockers: Sequence[Point] = ()) -> list[dict]:
    """Every pocket this target ball could go in, best first.

    Feeds the projected aiming line in practice games: the overlay draws the
    ghost ball and the two path segments for the top candidate.
    """
    out = []
    for pid, pocket in table.pockets().items():
        gb = ghost_ball(cue, target, pocket, table.ball_radius)
        if not table.on_table(*gb, margin=-table.ball_radius * 0.5):
            continue
        angle = cut_angle(cue, target, pocket)
        if angle >= 85.0:
            continue
        others = [b for b in blockers if b != target and b != cue]
        blocked = (path_blocked(cue, gb, others, table.ball_radius)
                   or path_blocked(target, pocket, others, table.ball_radius))
        out.append({
            "pocket": pid,
            "ghost": gb,
            "cut_angle": round(angle, 1),
            "blocked": blocked,
            "distance": round(math.dist(target, pocket), 1),
            "difficulty": round(angle / 85.0 * 0.6 + min(math.dist(target, pocket) / table.length, 1) * 0.4, 3),
        })
    out.sort(key=lambda c: (c["blocked"], c["difficulty"]))
    return out
