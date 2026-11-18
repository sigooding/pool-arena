"""Shared builders so a test reads as a shot, not as plumbing."""
from __future__ import annotations

from poolarena.geometry import Table
from poolarena.types import Ball, ShotEvents, TableState, kind_of

TABLE = Table("8ft")


def state(**positions: tuple[float, float]) -> TableState:
    """state(b0=(100,200), b3=(900,400)) -> a settled TableState."""
    balls = []
    for key, (x, y) in positions.items():
        n = int(key.lstrip("b"))
        balls.append(Ball(n, x, y, kind_of(n)))
    return TableState(balls=balls, ts=0.0, settled=True)


def events(pocketed=(), pockets=None, scratch=False, first=None, rails=1,
           struck=True, trace=None) -> ShotEvents:
    return ShotEvents(
        pocketed=list(pocketed),
        pocketed_in=dict(pockets or {}),
        cue_scratched=scratch,
        first_contact=first,
        rails_after_contact=rails,
        cue_struck=struck,
        trace=trace or {},
    )
