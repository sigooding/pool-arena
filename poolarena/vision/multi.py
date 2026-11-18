"""Two or more cameras over one table.

What a second camera is actually for, in order of how much it helps:

  1. **Occlusion.** One overhead camera is blocked whenever a player leans
     across the cloth. With two, something usually still sees each ball, and
     the table is only "obstructed" when every camera is.
  2. **Glare.** A specular highlight that ruins a ball in one view is rarely
     in the same place in the other.
  3. **Coverage.** On a 9 ft table under a low ceiling, one camera may not
     see all four corners, or balls at the far end are too few pixels. Two
     cameras each covering half the table roughly double the pixels on a
     ball.
  4. **Accuracy.** Real but the smallest of the four, and the cheapest to
     get another way: most of the position error a single camera has at the
     far end is parallax, which is geometry and can be corrected in software
     with one camera (see `VisionPipeline.correct_parallax`).

So: add a second camera to see past people and around glare, not to make the
numbers better.

Each camera keeps its own calibration, so they need not be matched, aligned,
or even the same kind of camera — every pipeline reports table millimetres,
and fusion happens there rather than in pixels.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from ..geometry import Table
from ..types import Ball, Kind, TableState

#: Two cameras rarely agree to the millimetre; detections closer than this
#: are the same ball. Comfortably under a ball diameter so two touching
#: balls are never merged into one.
MERGE_MM = 45.0


@dataclass
class CameraView:
    """One camera: its source, its pipeline, and what it last saw."""

    name: str
    source: Any
    pipeline: Any
    last: TableState | None = None
    frames: int = 0
    failures: int = 0

    def read(self) -> TableState | None:
        got = self.source.read()
        if not got or got[0] is None:
            self.failures += 1
            return None
        color, depth = got
        self.frames += 1
        self.last = self.pipeline.process(color, depth)
        return self.last

    def close(self) -> None:
        try:
            self.source.close()
        except Exception:
            pass

    def weight_at(self, x: float, y: float) -> float:
        """How much to trust this camera about a ball at this spot.

        Directly under a camera a ball is biggest, roundest and least
        affected by parallax; at the far end it is small and oblique. So a
        camera's vote falls off with distance from the point beneath it.
        """
        try:
            nx, ny = self.pipeline.nadir
        except Exception:
            return 1.0
        d = math.hypot(x - nx, y - ny)
        return 1.0 / (1.0 + (d / 900.0) ** 2)


class MultiPipeline:
    """Several cameras, one table state."""

    def __init__(self, table: Table, views: Sequence[CameraView]) -> None:
        if not views:
            raise ValueError("a multi-camera pipeline needs at least one camera")
        self.table = table
        self.views = list(views)

    # --- reading -----------------------------------------------------------
    def read(self) -> TableState:
        states: list[tuple[CameraView, TableState]] = []
        for v in self.views:
            st = v.read()
            if st is not None:
                states.append((v, st))
        if not states:
            return TableState(balls=[], ts=time.time(), settled=False,
                              obstructed=True)
        return self.fuse(states)

    # --- fusion ------------------------------------------------------------
    def fuse(self, states: Sequence[tuple[CameraView, TableState]]) -> TableState:
        """Combine per-camera states into one.

        Obstruction is the interesting case. A single camera has to say "I
        cannot see, ignore this frame"; with two, one blocked view is simply
        outvoted, and the table only counts as obstructed when nothing can
        see it. That is the whole reason to hang a second camera.
        """
        usable = [(v, s) for v, s in states if not s.obstructed]
        if not usable:
            return TableState(balls=[], ts=max(s.ts for _, s in states),
                              settled=False, obstructed=True)

        clusters: list[list[tuple[CameraView, Ball]]] = []
        for v, st in usable:
            for b in st.balls:
                for c in clusters:
                    # Same number, or close enough to be the same object.
                    cx = sum(bb.x for _, bb in c) / len(c)
                    cy = sum(bb.y for _, bb in c) / len(c)
                    same_cam = any(vv is v for vv, _ in c)
                    if same_cam:
                        continue
                    if math.hypot(b.x - cx, b.y - cy) <= MERGE_MM:
                        c.append((v, b))
                        break
                else:
                    clusters.append([(v, b)])

        balls = [self._merge(c) for c in clusters]
        return TableState(
            balls=balls,
            ts=max(s.ts for _, s in usable),
            settled=all(s.settled for _, s in usable),
            obstructed=False,
        )

    def _merge(self, cluster: list[tuple[CameraView, Ball]]) -> Ball:
        """One ball from several views, weighted by how well each sees it."""
        if len(cluster) == 1:
            return cluster[0][1]
        wx = wy = total = 0.0
        for v, b in cluster:
            w = v.weight_at(b.x, b.y) * max(0.05, b.confidence)
            wx += b.x * w
            wy += b.y * w
            total += w
        total = total or 1.0

        # Identity goes to whichever camera was most confident, rather than
        # to an average: a number is a label, and averaging labels is
        # meaningless.
        best_cam, best = max(cluster, key=lambda vb: vb[1].confidence
                             * vb[0].weight_at(vb[1].x, vb[1].y))
        agree = sum(1 for _, b in cluster if b.number == best.number)
        confidence = min(1.0, best.confidence * (1.0 + 0.25 * (agree - 1)))
        return Ball(number=best.number, x=wx / total, y=wy / total,
                    kind=best.kind if best.number is not None else Kind.UNKNOWN,
                    radius=best.radius, confidence=confidence)

    # --- housekeeping ------------------------------------------------------
    def learn_cloth(self, frames: int = 1) -> None:
        for v in self.views:
            for _ in range(frames):
                got = v.source.read()
                if got and got[0] is not None:
                    v.pipeline.learn_cloth(got[0])
                    break

    def status(self) -> list[dict[str, Any]]:
        out = []
        for v in self.views:
            out.append({
                "name": v.name,
                "frames": v.frames,
                "failures": v.failures,
                "obstructed": bool(v.last and v.last.obstructed),
                "balls": len(v.last.balls) if v.last else 0,
            })
        return out

    def close(self) -> None:
        for v in self.views:
            v.close()
