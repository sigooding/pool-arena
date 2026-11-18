"""Ball in hand: checking where the cue ball is put back.

The engine has always been able to say "ball in hand". What it could not do
is notice that the cue ball was then placed touching the black, or behind the
wrong line, or — the common one in a pub — quietly nudged forward a foot
while nobody was looking. A rule nobody enforces is a rule you may as well
not have.

What counts as legal depends on the code being played, so this takes the
constraint as data rather than assuming one:

  anywhere   American ball-in-hand, and UK World Rules
  baulk      traditional UK: behind the head string, the "D"
  in_d       strictly inside the semicircle, as in blooker and some leagues

In every code the cue ball must be on the table and not overlapping another
ball, which is the part that actually catches mistakes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from .geometry import Table

Point = tuple[float, float]

#: Radius of the D, as a fraction of the table width. The standard is the
#: baulk line at a quarter of the length and a D of a sixth of the width.
D_RADIUS_FRACTION = 1.0 / 6.0


@dataclass
class PlacementRule:
    """Where the cue ball may go."""

    area: str = "anywhere"          # anywhere | baulk | in_d

    def describe(self, table: Table) -> str:
        if self.area == "baulk":
            return "behind the baulk line"
        if self.area == "in_d":
            return "inside the D"
        return "anywhere on the table"


@dataclass
class PlacementCheck:
    ok: bool
    reason: str = ""
    suggestion: Point | None = None

    def to_json(self) -> dict:
        return {"ok": self.ok, "reason": self.reason,
                "suggestion": list(self.suggestion) if self.suggestion else None}


def d_centre(table: Table) -> Point:
    return (table.head_string, table.width / 2)


def d_radius(table: Table) -> float:
    return table.width * D_RADIUS_FRACTION


def in_area(table: Table, rule: PlacementRule, x: float, y: float) -> bool:
    if rule.area == "baulk":
        return x <= table.head_string + 1e-6
    if rule.area == "in_d":
        cx, cy = d_centre(table)
        return (x <= table.head_string + 1e-6
                and math.hypot(x - cx, y - cy) <= d_radius(table) + 1e-6)
    return True


def check(table: Table, rule: PlacementRule, x: float, y: float,
          others: Sequence[Point]) -> PlacementCheck:
    """Is this a legal spot for the cue ball?"""
    r = table.ball_radius
    if not (r <= x <= table.length - r and r <= y <= table.width - r):
        return PlacementCheck(False, "the cue ball must be on the table",
                              suggestion=nearest_legal(table, rule, x, y, others))
    for ox, oy in others:
        if math.hypot(x - ox, y - oy) < 2 * r - 0.5:
            return PlacementCheck(
                False, "the cue ball is touching another ball",
                suggestion=nearest_legal(table, rule, x, y, others))
    if not in_area(table, rule, x, y):
        return PlacementCheck(False, f"the cue ball must be {rule.describe(table)}",
                              suggestion=nearest_legal(table, rule, x, y, others))
    return PlacementCheck(True)


def nearest_legal(table: Table, rule: PlacementRule, x: float, y: float,
                  others: Sequence[Point], step: float = 25.0) -> Point | None:
    """The closest spot that would have been legal.

    Offered rather than imposed: the projector can show it and the player can
    use it or not. Spiralling outwards from where they actually put the ball
    keeps the suggestion close to their intent.
    """
    r = table.ball_radius
    # Start from the nearest point that satisfies the AREA, then spiral out
    # from there to dodge other balls. Spiralling from an illegal spot only
    # works when the legal area happens to be close: a cue ball put down at
    # the far end of the table is well over a metre from baulk, and a search
    # radius large enough to cover that would be mostly wasted effort.
    x, y = _into_area(table, rule, x, y)
    for ring in range(0, 40):
        radius = ring * step
        steps = max(1, int(2 * math.pi * radius / step)) if ring else 1
        for i in range(steps):
            a = 2 * math.pi * i / steps
            cx = x + math.cos(a) * radius
            cy = y + math.sin(a) * radius
            if not (r <= cx <= table.length - r and r <= cy <= table.width - r):
                continue
            if not in_area(table, rule, cx, cy):
                continue
            if any(math.hypot(cx - ox, cy - oy) < 2 * r for ox, oy in others):
                continue
            return (round(cx, 1), round(cy, 1))
    return None


def _into_area(table: Table, rule: PlacementRule, x: float, y: float) -> Point:
    """Nearest point inside the legal area, ignoring other balls."""
    r = table.ball_radius
    x = min(max(x, r), table.length - r)
    y = min(max(y, r), table.width - r)
    if rule.area == "anywhere":
        return (x, y)
    x = min(x, table.head_string - r * 0.5)
    if rule.area == "baulk":
        return (max(x, r), y)
    cx, cy = d_centre(table)
    rad = d_radius(table)
    dx, dy = x - cx, y - cy
    dist = math.hypot(dx, dy)
    if dist > rad:
        scale = (rad - r * 0.5) / dist
        x, y = cx + dx * scale, cy + dy * scale
    return (min(max(x, r), table.length - r), min(max(y, r), table.width - r))


def area_outline(table: Table, rule: PlacementRule) -> dict:
    """A shape the overlay can draw, so the legal area is visible on the cloth."""
    if rule.area == "anywhere":
        return {"kind": "table"}
    if rule.area == "baulk":
        return {"kind": "rect", "x": table.head_string / 2, "y": table.width / 2,
                "w": table.head_string, "h": table.width}
    cx, cy = d_centre(table)
    return {"kind": "halfcircle", "x": cx, "y": cy, "r": d_radius(table),
            "facing": "left"}


def moved_balls(before: Iterable, after: Iterable, tolerance: float = 12.0) -> list[int]:
    """Which balls other than the cue ball shifted between two rest states.

    Placing the cue ball should not disturb anything else. If it did, either
    the player knocked something or the detector lost track — both worth
    saying out loud rather than silently accepting.
    """
    b = {x.number: (x.x, x.y) for x in before if x.number != 0}
    a = {x.number: (x.x, x.y) for x in after if x.number != 0}
    out = []
    for n, (bx, by) in b.items():
        if n in a and math.hypot(a[n][0] - bx, a[n][1] - by) > tolerance:
            out.append(n)
    return sorted(out)
