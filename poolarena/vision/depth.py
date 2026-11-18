"""Finding balls in a depth map.

Colour detection fails in the ways a pool room fails: a lamp's hot centre, a
player's shadow, glare on a ball, cloth that is nearly the colour of a green
ball. Depth fails in none of those ways. A shadow has no depth, glare has no
depth, and the cloth's colour is irrelevant — a ball is simply 57 mm of
"closer to the sensor than the cloth is", everywhere, under any lighting,
including none.

What depth cannot do is tell a red from a yellow or a 3 from an 11. So the
natural division of labour is: **depth says where the balls are, colour says
which ball each one is.** Both produce table millimetres, so they fuse in the
same way two cameras do.

A Kinect v2's depth stream is 512x424. At 2.2 m that is about 6 mm per pixel,
so a ball is ~9 px across — around 70 pixels to work with — standing 57 mm
proud of the cloth against a few mm of sensor noise. Coarse, but the signal
is enormous.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..geometry import Calibration, Table
from ..types import Ball, Kind, TableState

#: A ball's apex stands 57 mm up. Anything this far above the cloth is not
#: cloth; well above sensor noise, well below the ball's full height so a
#: ball is still a solid blob rather than a ring.
BALL_MIN_MM = 18.0
#: Above this it is an arm, a cue, a body — not a ball.
OBSTRUCTION_MM = 120.0


def fit_plane(points: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares plane through (x, y, z) samples; returns normal and offset."""
    centroid = points.mean(axis=0)
    # full_matrices=False matters enormously here. The default builds a U of
    # (n x n) — for the ~13,000 depth samples a cloth fit uses, that is a
    # 13,000-square matrix and over a gigabyte of memory, to extract one
    # three-element normal. The thin form does the same job in milliseconds.
    _, _, vh = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vh[2]
    if normal[2] < 0:
        normal = -normal
    return normal, float(np.dot(normal, centroid))


@dataclass
class ClothPlane:
    """The cloth, as the depth sensor sees it.

    Learned once from an empty table. Everything after that is "how far above
    this plane is each pixel", which is the only question depth needs to
    answer.
    """

    normal: np.ndarray
    offset: float
    valid: np.ndarray | None = None

    @classmethod
    def learn(cls, depth: np.ndarray, step: int = 4,
              zmin: float = 300.0, zmax: float = 6000.0) -> "ClothPlane":
        d = np.asarray(depth, np.float32)
        h, w = d.shape
        ys, xs = np.mgrid[0:h:step, 0:w:step]
        zs = d[::step, ::step]
        ok = (zs > zmin) & (zs < zmax)
        pts = np.stack([xs[ok], ys[ok], zs[ok]], axis=1).astype(np.float32)
        if len(pts) < 100:
            raise ValueError("not enough valid depth samples to find the cloth")
        normal, offset = fit_plane(pts)
        # One robust pass: drop whatever is far off the first fit (balls, rails,
        # a person who wandered through) and fit again to the cloth alone.
        resid = pts @ normal - offset
        keep = np.abs(resid) < max(12.0, 2.5 * float(np.std(resid)))
        if keep.sum() > 100:
            normal, offset = fit_plane(pts[keep])
        return cls(normal=normal, offset=offset)

    def height_map(self, depth: np.ndarray) -> np.ndarray:
        """Millimetres above the cloth, per pixel. Invalid pixels read 0."""
        d = np.asarray(depth, np.float32)
        h, w = d.shape
        ys, xs = np.mgrid[0:h, 0:w]
        # Distance from the plane, signed so that closer to the sensor (a
        # smaller z) comes out positive — i.e. "how far it sticks up".
        plane_z = (self.offset - self.normal[0] * xs - self.normal[1] * ys) / self.normal[2]
        out = plane_z - d
        out[(d <= 300) | (d >= 6000)] = 0.0
        return out


@dataclass
class DepthBallFinder:
    """Balls from a depth map, as table millimetres.

    Uses its own calibration: the depth camera has different optics from the
    colour camera, so rather than registering one to the other — which is
    fiddly and sensor-specific — each is calibrated to the table and they
    meet in millimetres.
    """

    table: Table
    calibration: Calibration
    plane: ClothPlane | None = None
    min_mm: float = BALL_MIN_MM
    name: str = "depth"
    _last: TableState | None = field(default=None, repr=False)

    def learn_cloth(self, depth: np.ndarray) -> None:
        self.plane = ClothPlane.learn(depth)

    def obstructed(self, heights: np.ndarray) -> bool:
        tall = heights > OBSTRUCTION_MM
        return float(tall.mean()) > 0.02

    def find(self, depth: np.ndarray) -> list[tuple[float, float, float]]:
        """Blob centroids as (x_mm, y_mm, area_px)."""
        import cv2
        if self.plane is None:
            self.learn_cloth(depth)
        heights = self.plane.height_map(depth)
        mask = ((heights > self.min_mm) & (heights < OBSTRUCTION_MM)).astype(np.uint8) * 255
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)

        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        out: list[tuple[float, float, float]] = []
        for i in range(1, n):
            area = float(stats[i, cv2.CC_STAT_AREA])
            if area < 8:                      # smaller than a ball at any height
                continue
            cx, cy = cents[i]
            mm = self.calibration.to_table([(float(cx), float(cy))])[0]
            if not self.table.on_table(*mm, margin=40):
                continue
            out.append((mm[0], mm[1], area))
        return out

    def process(self, color: Any = None, depth: Any = None) -> TableState:
        """Same shape as VisionPipeline.process, so it drops into a CameraView."""
        if depth is None:
            return TableState(balls=[], ts=time.time(), settled=False, obstructed=True)
        if self.plane is None:
            self.learn_cloth(depth)
        heights = self.plane.height_map(depth)
        if self.obstructed(heights):
            last = self._last
            st = TableState(balls=last.balls if last else [], ts=time.time(),
                            settled=False, obstructed=True)
            self._last = st
            return st
        balls = [
            # -1 means "something is here but I cannot say what": depth has no
            # colour, so identity has to come from somewhere else.
            Ball(number=-1, x=x, y=y, kind=Kind.UNKNOWN,
                 radius=self.table.ball_radius, confidence=0.55)
            for x, y, _area in self.find(depth)
        ]
        st = TableState(balls=balls, ts=time.time(), settled=True, obstructed=False)
        self._last = st
        return st

    @property
    def nadir(self) -> tuple[float, float]:
        return (self.table.length / 2, self.table.width / 2)
