"""The game interface. A game never touches vision code — it sees two resting
table states and a ShotEvents, and returns a verdict plus projector effects.

That boundary is the whole point of the architecture: a new game is one file
and needs no camera, no calibration and no pixels.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ballset import AMERICAN, BallSet
from ..geometry import Table
from ..types import Effect, Player, ShotEvents, ShotResult, TableState


@dataclass
class ShotContext:
    """Everything a game needs to judge one shot."""

    before: TableState
    after: TableState
    events: ShotEvents
    table: Table
    shooter: int                 # index into players
    shot_number: int = 0

    def pocketed_kinds(self) -> list[int]:
        return list(self.events.pocketed)


class Game(ABC):
    """Base class for every game mode.

    Subclasses implement `on_shot`. Optional hooks: `on_start`, `on_rack`,
    `on_turn_start`, `idle_effects`, `on_tick`.
    """

    name: str = "game"
    title: str = "Game"
    description: str = ""
    min_players: int = 1
    max_players: int = 8
    # True when the game needs to tell one ball of a group from another. False
    # for anything that only cares about colour or count, which is what makes
    # it playable with an English reds-and-yellows set.
    needs_numbered_balls: bool = True

    #: Where the cue ball may be put back after a foul: "anywhere" (American
    #: ball in hand, and UK World Rules), "baulk" (traditional UK pub rules)
    #: or "in_d". Pub rules vary, so it is an option.
    ball_in_hand_area: str = "anywhere"

    #: True when the game's guides are the game — zones to roll through, a
    #: nominated pocket, a ring to stop the cue ball in. Without a projector
    #: these are still playable, but the player has to read them off the
    #: tablet instead of off the cloth.
    needs_projector: bool = False

    @classmethod
    def supports(cls, ball_set: BallSet) -> bool:
        return ball_set.has_numbers or not cls.needs_numbered_balls

    @classmethod
    def describe(cls, ball_set: BallSet) -> str:
        """Description for the menu. Overridden where the wording depends on
        what is actually racked — "solids or stripes" is wrong at a table of
        reds and yellows."""
        return cls.description

    def __init__(self, players: list[str] | None = None, table: Table | None = None,
                 options: dict[str, Any] | None = None,
                 ball_set: BallSet | None = None) -> None:
        names = players or ["Player 1", "Player 2"]
        self.players = [Player(name=n) for n in names]
        self.table = table or Table()
        self.ball_set = ball_set or AMERICAN
        self.options = options or {}
        self.turn = 0
        self.shot_number = 0
        self.over = False
        self.winner: int | None = None
        self.log: list[str] = []

    # --- hooks -------------------------------------------------------------
    def start_note(self) -> str:
        """The line under the title when a game begins.

        A hook rather than a second banner: two banners in one batch land on
        top of each other and neither can be read.
        """
        return self.description

    def on_start(self) -> list[Effect]:
        """Effects to play when the game is racked and ready."""
        return [Effect("banner", {"text": self.title.upper(),
                                  "subtitle": self.start_note()}, layer="hud")]

    def on_turn_start(self, state: TableState) -> list[Effect]:
        """Effects at the start of a turn: aiming guides, target highlights."""
        return []

    @abstractmethod
    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ...

    def idle_effects(self, state: TableState) -> list[Effect]:
        """Ambient effects while nothing is happening. Keep these cheap."""
        return []

    def on_tick(self, now: float, settled: bool) -> ShotResult | None:
        """Called roughly once a second while the game is live, whether or
        not anybody is shooting.

        Every other hook here hangs off a shot, which is right for games
        decided by what happens on the cloth. A game decided by a clock needs
        to be asked the question when nothing is happening at all — that is
        exactly when its clock runs out. Return None for "nothing to report",
        which is what all but a timed game will ever do.

        `settled` says whether the balls are currently at rest, so a clock can
        choose to stop while they roll.
        """
        return None

    # --- helpers for subclasses -------------------------------------------
    @property
    def shooter(self) -> Player:
        return self.players[self.turn]

    def next_turn(self) -> None:
        for _ in range(len(self.players)):
            self.turn = (self.turn + 1) % len(self.players)
            if not self.players[self.turn].out:
                return

    def pocket_pos(self, pocket: str) -> tuple[float, float]:
        return self.table.pockets()[pocket]

    def celebrate(self, ctx: ShotContext, intensity: float = 1.0,
                  palette: str = "fire") -> list[Effect]:
        """Standard pocket feedback: a glow in the pocket plus a burst."""
        fx: list[Effect] = []
        for ball in ctx.events.pocketed:
            pid = ctx.events.pocketed_in.get(ball)
            if not pid:
                continue
            x, y = self.pocket_pos(pid)
            fx.append(Effect("pocket_glow", {"pocket": pid, "duration": 900,
                                             "color": "#ffc24a", "intensity": intensity}))
            fx.append(Effect("explosion", {"x": x, "y": y, "intensity": intensity,
                                           "palette": palette, "ball": ball}))
        return fx

    def foul_effects(self, reason: str) -> list[Effect]:
        return [
            Effect("table_flash", {"color": "#ff2d55", "duration": 450, "pulses": 2}),
            Effect("banner", {"text": "FOUL", "subtitle": reason, "tone": "bad"}, layer="hud"),
        ]

    def win_effects(self, winner: int) -> list[Effect]:
        return [
            Effect("fireworks", {"duration": 4000, "palette": "rainbow"}),
            Effect("banner", {"text": f"{self.players[winner].name} WINS",
                              "subtitle": self.title, "tone": "good", "duration": 5000}, layer="hud"),
        ]

    # --- plumbing ----------------------------------------------------------
    def apply(self, ctx: ShotContext) -> ShotResult:
        """Run on_shot, then fold the verdict into game state."""
        ctx.shooter = self.turn
        ctx.shot_number = self.shot_number
        res = self.on_shot(ctx)
        self.shot_number += 1
        if res.message:
            self.log.append(f"{self.shooter.name}: {res.message}")
        if res.game_over:
            self.over = True
            self.winner = res.winner
            if res.winner is not None:
                res.effects.extend(self.win_effects(res.winner))
        elif res.turn_passes:
            self.next_turn()
        return res

    def scoreboard(self) -> dict[str, Any]:
        return {
            "game": self.name,
            "title": self.title,
            "turn": self.turn,
            "shot_number": self.shot_number,
            "over": self.over,
            "winner": self.winner,
            "players": [p.to_json() for p in self.players],
            "log": self.log[-12:],
        }


# --- registry -------------------------------------------------------------
_REGISTRY: dict[str, type[Game]] = {}


def register(cls: type[Game]) -> type[Game]:
    _REGISTRY[cls.name] = cls
    return cls


def get_game(name: str) -> type[Game]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown game {name!r}; have {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available(ball_set: BallSet | None = None) -> list[dict[str, Any]]:
    bs = ball_set or AMERICAN
    return [
        {"name": c.name, "title": c.title, "description": c.describe(bs),
         "min_players": c.min_players, "max_players": c.max_players,
         "supported": c.supports(bs),
         "needs_numbered_balls": c.needs_numbered_balls,
         "needs_projector": c.needs_projector}
        for c in sorted(_REGISTRY.values(), key=lambda c: c.title)
    ]
