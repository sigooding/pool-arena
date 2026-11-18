"""Core data types. Pure stdlib + dataclasses so every layer can import this."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Kind(str, Enum):
    CUE = "cue"
    SOLID = "solid"
    STRIPE = "stripe"
    EIGHT = "eight"
    UNKNOWN = "unknown"


# Pocket identifiers, viewed with the long axis horizontal.
POCKETS = ("TL", "TM", "TR", "BL", "BM", "BR")


@dataclass(frozen=True)
class Ball:
    """A ball at rest, in table millimetres from the top-left inside corner."""

    number: int            # 0 == cue ball
    x: float
    y: float
    kind: Kind = Kind.UNKNOWN
    radius: float = 28.6   # 57.15 mm ball / 2
    confidence: float = 1.0

    @property
    def is_cue(self) -> bool:
        return self.number == 0

    def pos(self) -> tuple[float, float]:
        return (self.x, self.y)

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "kind": self.kind.value,
            "r": round(self.radius, 1),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class TableState:
    """Everything on the cloth at one instant."""

    balls: list[Ball] = field(default_factory=list)
    ts: float = field(default_factory=time.time)
    settled: bool = True          # all balls at rest
    obstructed: bool = False      # arm/cue over the table, detection unreliable

    def by_number(self) -> dict[int, Ball]:
        return {b.number: b for b in self.balls}

    def numbers(self) -> set[int]:
        return {b.number for b in self.balls}

    def cue(self) -> Ball | None:
        return next((b for b in self.balls if b.is_cue), None)

    def get(self, number: int) -> Ball | None:
        return next((b for b in self.balls if b.number == number), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "settled": self.settled,
            "obstructed": self.obstructed,
            "balls": [b.to_json() for b in self.balls],
        }


@dataclass
class Contact:
    """One ball-to-ball or ball-to-rail touch seen during a shot."""

    a: int                 # ball number
    b: int | str           # ball number, or a rail name: "top"/"bottom"/"left"/"right"
    t: float               # seconds since shot start
    speed: float = 0.0     # mm/s at impact, 0 when unknown


@dataclass
class ShotEvents:
    """What the event detector read out of one shot."""

    pocketed: list[int] = field(default_factory=list)
    pocketed_in: dict[int, str] = field(default_factory=dict)   # ball -> pocket id
    cue_scratched: bool = False
    first_contact: int | None = None    # first ball the cue ball touched
    rails_after_contact: int = 0        # total cushion touches after contact
    balls_to_rail: int = 0              # distinct balls that reached a cushion
    cue_struck: bool = True             # False == no shot taken / cue never moved
    #: balls that disappeared nowhere near a pocket — lost by the detector
    #: rather than potted
    lost: list[int] = field(default_factory=list)
    #: set when the frame cannot be believed, so nothing should be scored
    unreliable: str = ""
    contacts: list[Contact] = field(default_factory=list)
    trace: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    duration: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "pocketed": self.pocketed,
            "pocketed_in": self.pocketed_in,
            "cue_scratched": self.cue_scratched,
            "first_contact": self.first_contact,
            "rails_after_contact": self.rails_after_contact,
            "balls_to_rail": self.balls_to_rail,
            "cue_struck": self.cue_struck,
            "lost": self.lost,
            "unreliable": self.unreliable,
            "duration": round(self.duration, 2),
        }


@dataclass
class Effect:
    """A projector directive. Games emit these; the overlay renders them."""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    layer: str = "fx"      # "guide" (under balls) | "fx" (over) | "hud"

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "args": self.args, "layer": self.layer}


@dataclass
class Player:
    name: str
    score: int = 0
    group: str | None = None       # "solids"/"stripes" in 8-ball, or None
    balls_left: list[int] = field(default_factory=list)
    lives: int = 0                 # killer, and other elimination games
    visits: int = 1                # shots remaining this turn (UK two-shot rules)
    out: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "group": self.group,
            "balls_left": self.balls_left,
            "lives": self.lives,
            "visits": self.visits,
            "out": self.out,
        }


@dataclass
class ShotResult:
    """A game's verdict on one shot."""

    foul: str | None = None            # human-readable reason, None when legal
    turn_passes: bool = False
    message: str = ""
    effects: list[Effect] = field(default_factory=list)
    winner: int | None = None          # index into players
    game_over: bool = False
    ball_in_hand: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "foul": self.foul,
            "turn_passes": self.turn_passes,
            "message": self.message,
            "effects": [e.to_json() for e in self.effects],
            "winner": self.winner,
            "game_over": self.game_over,
            "ball_in_hand": self.ball_in_hand,
        }


def rack_numbers(include_cue: bool = True) -> Iterable[int]:
    return range(0 if include_cue else 1, 16)


def kind_of(number: int) -> Kind:
    if number == 0:
        return Kind.CUE
    if number == 8:
        return Kind.EIGHT
    if 1 <= number <= 7:
        return Kind.SOLID
    if 9 <= number <= 15:
        return Kind.STRIPE
    return Kind.UNKNOWN
