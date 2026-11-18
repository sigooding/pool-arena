"""Projected zones on the cloth, and the tests that score them.

A zone only exists because something is drawing light on the table, so these
are the primitives behind every projection-native game mode.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Sequence

from .geometry import Table

Point = tuple[float, float]


@dataclass
class Zone:
    id: str
    shape: str = "circle"            # "circle" | "rect"
    x: float = 0.0
    y: float = 0.0
    r: float = 150.0                 # circle radius, mm
    w: float = 300.0                 # rect size, mm
    h: float = 300.0
    color: str = "#38bdf8"
    points: int = 1
    label: str = ""
    state: str = "active"            # active | hit | spent

    def contains(self, x: float, y: float) -> bool:
        if self.shape == "circle":
            return math.hypot(x - self.x, y - self.y) <= self.r
        return abs(x - self.x) <= self.w / 2 and abs(y - self.y) <= self.h / 2

    def crossed_by(self, trace: Sequence[Point], step: float = 20.0) -> bool:
        """True when a ball path passes through the zone.

        Traces from a 30 fps camera are coarse, so each segment is walked in
        `step` mm increments rather than tested only at the sampled points.
        """
        pts = list(trace)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            d = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(d / step))
            for i in range(n + 1):
                t = i / n
                if self.contains(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t):
                    return True
        return False

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "shape": self.shape, "x": round(self.x, 1), "y": round(self.y, 1),
            "r": self.r, "w": self.w, "h": self.h, "color": self.color,
            "points": self.points, "label": self.label, "state": self.state,
        }


def random_zones(table: Table, count: int = 3, radius: float = 150.0,
                 avoid: Sequence[Point] = (), clearance: float = 90.0,
                 rng: random.Random | None = None,
                 colors: Sequence[str] = ("#38bdf8", "#a78bfa", "#fb7185"),
                 points: Sequence[int] = (1, 2, 3)) -> list[Zone]:
    """Scatter zones on open cloth, clear of the given ball positions."""
    rng = rng or random.Random()
    margin = radius + 60.0
    out: list[Zone] = []
    for i in range(count):
        for _ in range(200):
            x = rng.uniform(margin, table.length - margin)
            y = rng.uniform(margin, table.width - margin)
            if any(math.hypot(x - bx, y - by) < radius + clearance for bx, by in avoid):
                continue
            if any(math.hypot(x - z.x, y - z.y) < radius * 2.2 for z in out):
                continue
            out.append(Zone(id=f"z{i}", x=x, y=y, r=radius,
                            color=colors[i % len(colors)],
                            points=points[i % len(points)],
                            label=f"{points[i % len(points)]}"))
            break
    return out
