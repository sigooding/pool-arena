"""Which balls are on the table.

Two worlds, and they are not interchangeable:

  American / "pool"   15 numbered balls, 1-7 solid, 9-15 striped, 8 black.
                      Every ball is individually identifiable, so games that
                      care about order (9-ball, rotation) are possible.

  English / "blackball"  7 reds, 7 yellows, 1 black, plus the cue. The balls
                      carry no numbers and the ones within a colour are
                      genuinely identical — no camera can tell one red from
                      another, and neither can a player.

The internal representation stays numeric either way: reds take 1-7, yellows
take 9-15, black is 8. That is a deliberate choice — it means the 8-ball rule
set, the event detector and every projected effect work unchanged across both
sets, and only the labels and the detector's colour model differ.

What it cannot paper over is that the numbers in an English set are arbitrary
labels the tracker assigns, not identities. A game that needs real identity
(9-ball's lowest-ball-first, cut-throat's three groups of five) is impossible
with reds and yellows, so those games are refused rather than quietly scored
wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .types import Kind


@dataclass(frozen=True)
class BallSet:
    name: str
    title: str
    has_numbers: bool          # can one ball be told from another of its group?
    group_names: tuple[str, str]
    colours: dict[str, str] = field(default_factory=dict)

    # --- membership --------------------------------------------------------
    def group_of(self, number: int) -> str | None:
        if number == 0 or number == 8:
            return None
        return self.group_names[0] if 1 <= number <= 7 else self.group_names[1]

    def colour_of(self, number: int) -> str:
        if number == 0:
            return "white"
        if number == 8:
            return "black"
        if self.has_numbers:
            return "solid" if number < 8 else "stripe"
        return "red" if number < 8 else "yellow"

    def label(self, number: int) -> str:
        """What to call a ball out loud."""
        if number == 0:
            return "cue"
        if number == 8:
            return "black"
        if self.has_numbers:
            return str(number)
        return self.colour_of(number)

    def describe_balls(self, numbers) -> str:
        """Phrase a set of balls for a human. "3 and 11" on a numbered set;
        "two yellows" where the balls carry no numbers to read out."""
        nums = sorted(numbers)
        if not nums:
            return "nothing"
        if self.has_numbers:
            return ", ".join(str(n) for n in nums)
        words = {1: "one", 2: "two", 3: "three", 4: "four",
                 5: "five", 6: "six", 7: "seven"}
        parts = []
        for colour in ("red", "yellow"):
            group = [n for n in nums
                     if self.colour_of(n) == colour]
            if group:
                n = len(group)
                parts.append(f"{words.get(n, n)} {colour}{'' if n == 1 else 's'}")
        if 8 in nums:
            parts.append("the black")
        return " and ".join(parts) or "nothing"

    def a_ball(self, number: int) -> str:
        """How to refer to one ball: "the 7", or "a red"."""
        if number == 0:
            return "the cue ball"
        if number == 8:
            return "the black"
        return f"the {number}" if self.has_numbers else f"a {self.colour_of(number)}"

    def kind_of(self, number: int) -> Kind:
        if number == 0:
            return Kind.CUE
        if number == 8:
            return Kind.EIGHT
        return Kind.SOLID if number < 8 else Kind.STRIPE

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "has_numbers": self.has_numbers,
            "group_names": list(self.group_names),
            "colours": self.colours,
        }


AMERICAN = BallSet(
    name="american",
    title="American (numbered 1-15)",
    has_numbers=True,
    group_names=("solids", "stripes"),
    colours={"solids": "#F2B705", "stripes": "#0B5FD8"},
)

ENGLISH = BallSet(
    name="english",
    title="English (reds and yellows)",
    has_numbers=False,
    group_names=("reds", "yellows"),
    colours={"reds": "#DC2626", "yellows": "#F2B705"},
)

SETS = {s.name: s for s in (AMERICAN, ENGLISH)}


def get_ball_set(name: str | None) -> BallSet:
    if not name:
        return AMERICAN
    key = str(name).lower()
    aliases = {
        "pool": "american", "us": "american", "numbered": "american",
        "uk": "english", "blackball": "english", "red-yellow": "english",
        "reds-and-yellows": "english", "english8": "english",
    }
    key = aliases.get(key, key)
    if key not in SETS:
        raise ValueError(f"unknown ball set {name!r}; have {sorted(SETS)}")
    return SETS[key]
