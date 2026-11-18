"""Camera frames in, TableState out.

Order of operations, and why:
  1. warp the frame to a top-down view using the calibration homography, so
     detection and tracking work in a space where a ball is the same size
     everywhere and 1 px is a fixed number of mm;
  2. detect balls;
  3. carry identities forward from the previous frame, because a stripe showing
     only its white band is unclassifiable on its own but perfectly trackable;
  4. decide whether the view is obstructed, and if so emit the last known
     positions flagged as unreliable rather than garbage.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..geometry import Calibration, Table
from ..types import Ball, Kind, TableState, kind_of
from .detect import BallDetector, Detection

WARP_PX_PER_MM = 0.5          # 1118 mm wide table -> 559 px: plenty for a ball


@dataclass
class TrackedBall:
    number: int
    x: float
    y: float
    kind: Kind
    confidence: float
    votes: dict[int, int] = field(default_factory=dict)
    missing: int = 0

    def vote(self, number: int | None, weight: int = 1) -> None:
        if number is None:
            return
        self.votes[number] = self.votes.get(number, 0) + weight

    def settle(self) -> None:
        """Adopt the number with the most votes seen so far."""
        if self.votes:
            best = max(self.votes.items(), key=lambda kv: kv[1])
            if best[1] >= 3 and best[0] != self.number:
                self.number = best[0]
                self.kind = kind_of(best[0])


class VisionPipeline:
    def __init__(self, table: Table, calibration: Calibration,
                 detector: BallDetector, px_per_mm: float = WARP_PX_PER_MM,
                 obstruction_depth: Any = None,
                 camera_height_mm: float = 0.0,
                 nadir: tuple[float, float] | None = None,
                 name: str = "cam") -> None:
        import cv2
        self.cv2 = cv2
        self.table = table
        self.calib = calibration
        self.detector = detector
        self.px_per_mm = px_per_mm
        self.name = name
        self.camera_height_mm = float(camera_height_mm or 0.0)
        self._nadir = tuple(nadir) if nadir else None
        self.W = int(table.length * px_per_mm)
        self.H = int(table.width * px_per_mm)
        # image px -> warped px: table mm scaled by px_per_mm
        S = np.array([[px_per_mm, 0, 0], [0, px_per_mm, 0], [0, 0, 1]], float)
        self.warp_H = S @ calibration.H
        self.tracks: list[TrackedBall] = []
        self.missing_limit = 3
        self.obstructed_frames = 0
        self._last_state = TableState(balls=[], ts=time.time())
        self._cloth_ref: np.ndarray | None = None

    # --- frame handling ----------------------------------------------------
    def warp(self, frame: np.ndarray) -> np.ndarray:
        return self.cv2.warpPerspective(frame, self.warp_H, (self.W, self.H))

    def learn_cloth(self, frame: np.ndarray) -> None:
        """Show it an empty table once; detection gets much steadier."""
        w = self.warp(frame)
        self.detector.learn_background(w)
        self._cloth_ref = self.cv2.cvtColor(w, self.cv2.COLOR_BGR2GRAY)

    def to_mm(self, x: float, y: float) -> tuple[float, float]:
        return (x / self.px_per_mm, y / self.px_per_mm)

    # --- parallax --------------------------------------------------------
    @property
    def nadir(self) -> tuple[float, float]:
        """The point on the cloth directly below the camera, in table mm.

        When not given, this is guessed by mapping the centre of the camera
        image through the calibration. That guess is exact for a camera
        pointing straight down and fair for one that is merely near-vertical.

        **It is wrong for a camera mounted off to one side and tilted**, which
        is the normal arrangement when a hanging pool light occupies the
        middle of the ceiling: the image centre then lands wherever the camera
        is AIMED, not underneath it, and the two can be a metre apart. Off-axis
        mounting is also where parallax matters most, so set `nadir`
        explicitly in that case — measure it with a plumb line from the lens.
        """
        if self._nadir is None:
            w = self.W / self.px_per_mm
            h = self.H / self.px_per_mm
            try:
                img_centre = self.calib.to_image([(w / 2, h / 2)])[0]
                self._nadir = tuple(self.calib.to_table([img_centre])[0])
            except Exception:
                self._nadir = (self.table.length / 2, self.table.width / 2)
        return self._nadir

    def correct_parallax(self, x: float, y: float) -> tuple[float, float]:
        """Undo the outward shift caused by a ball being a sphere.

        The detector finds the centre of a ball, which sits one radius ABOVE
        the cloth, while the homography maps the cloth itself. The ray from
        the camera through the ball's centre therefore meets the cloth
        further out than the ball really is, by a factor of h/(h-r) measured
        from the point under the camera.

        At 2.2 m this is about 16 mm in the far corner of an 8 ft table —
        nearly a third of a ball, and enough to put a hanging ball on the
        wrong side of a pocket's capture radius. It is pure geometry, so it
        costs nothing to remove.
        """
        h = self.camera_height_mm
        if h <= self.table.ball_radius * 2:
            return (x, y)                 # not configured, or nonsense
        nx, ny = self.nadir
        k = (h - self.table.ball_radius) / h
        return (nx + (x - nx) * k, ny + (y - ny) * k)

    def process(self, frame: np.ndarray, depth: np.ndarray | None = None,
                ts: float | None = None) -> TableState:
        ts = ts if ts is not None else time.time()
        warped = self.warp(frame)

        obstructed = self._obstructed(warped, depth)
        if obstructed:
            self.obstructed_frames += 1
            st = TableState(balls=self._last_state.balls, ts=ts,
                            settled=False, obstructed=True)
            self._last_state = st
            return st
        self.obstructed_frames = 0

        dets = self.detector.detect(warped)
        self._associate(dets)
        balls = [
            Ball(t.number, *self.correct_parallax(*self.to_mm(t.x, t.y)), t.kind,
                 self.table.ball_radius, t.confidence)
            for t in self.tracks if t.missing == 0
        ]
        st = TableState(balls=balls, ts=ts, settled=True, obstructed=False)
        self._last_state = st
        return st

    # --- obstruction -------------------------------------------------------
    def _obstructed(self, warped: np.ndarray, depth: np.ndarray | None) -> bool:
        """An arm or cue over the cloth.

        With a Kinect, depth answers this directly and cheaply: anything far
        above the cloth plane is not a ball. Without depth, fall back to "a big
        chunk of the frame changed at once", which catches a leaning player.
        """
        if depth is not None:
            return self._depth_obstructed(depth)
        if self._cloth_ref is None:
            return False
        cv2 = self.cv2
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray, self._cloth_ref)
        changed = float((diff > 45).mean())
        # 16 balls cover roughly 2% of an 8 ft table in this warp.
        return changed > 0.12

    def _depth_obstructed(self, depth: np.ndarray, above_mm: float = 90.0) -> bool:
        d = depth.astype(np.float32)
        valid = d[(d > 300) & (d < 5000)]
        if valid.size < 500:
            return False
        cloth = float(np.percentile(valid, 85))     # the cloth is the far plane
        above = (d > 300) & (d < cloth - above_mm)
        return float(above.mean()) > 0.02

    # --- identity ----------------------------------------------------------
    def _associate(self, dets: list[Detection]) -> None:
        """Greedy nearest-neighbour matching in warped pixels.

        Balls move far between frames at 30 fps, but they are never at rest
        anywhere near each other, and this pipeline only publishes at rest, so
        greedy matching on a generous radius is enough. The gate scales with
        ball size rather than being a magic number.
        """
        gate = self.detector.__dict__.get("ball_px", 36.0) * 2.5
        unmatched = list(dets)
        for t in self.tracks:
            best, best_d = None, gate
            for d in unmatched:
                dist = float(np.hypot(d.x - t.x, d.y - t.y))
                if dist < best_d:
                    best, best_d = d, dist
            if best is None:
                t.missing += 1
                continue
            unmatched.remove(best)
            t.x, t.y = best.x, best.y
            t.missing = 0
            t.confidence = max(t.confidence * 0.7, best.confidence)
            t.vote(best.number, 2 if best.confidence > 0.6 else 1)
            t.settle()

        for d in unmatched:
            num = d.number if d.number is not None else self._free_number(d)
            tb = TrackedBall(num, d.x, d.y, d.kind, d.confidence)
            tb.vote(d.number, 2)
            self.tracks.append(tb)
            if d.group:
                # An unnumbered set: the number is a label this tracker hands
                # out, so it must not be revised by later votes.
                tb.votes.clear()

        self.tracks = [t for t in self.tracks if t.missing <= self.missing_limit]

    # Reds take 1-7 and yellows 9-15, matching the internal convention in
    # ballset.py, so the 8-ball rule set needs no idea which set is on the
    # cloth. Within a colour the choice is arbitrary, which is correct: one
    # red is not distinguishable from another, by camera or by player.
    GROUP_RANGES = {"reds": range(1, 8), "yellows": range(9, 16)}

    def _free_number(self, d: Detection) -> int:
        used = {t.number for t in self.tracks}
        candidates = self.GROUP_RANGES.get(d.group or "", range(1, 16))
        for n in candidates:
            if n not in used:
                return n
        for n in range(1, 16):          # group full: fall back to anything free
            if n not in used:
                return n
        return -1

    def reset_tracks(self) -> None:
        self.tracks = []

    def debug_overlay(self, frame: np.ndarray) -> np.ndarray:
        """Warped view annotated with what the detector sees. For calibration."""
        cv2 = self.cv2
        warped = self.warp(frame)
        for t in self.tracks:
            if t.missing:
                continue
            color = (255, 255, 255) if t.number == 0 else (60, 220, 255)
            cv2.circle(warped, (int(t.x), int(t.y)),
                       int(self.table.ball_radius * self.px_per_mm), color, 2)
            cv2.putText(warped, str(t.number), (int(t.x) - 8, int(t.y) + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        for pid, (px, py) in self.table.pockets().items():
            cv2.circle(warped, (int(px * self.px_per_mm), int(py * self.px_per_mm)),
                       10, (0, 0, 255), 2)
        return warped
