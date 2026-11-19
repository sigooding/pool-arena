"""Time Bomb — beat the clock before the rack blows.

A countdown instead of an opponent. You start with thirty seconds; every ball
you pot buys you more. Clear the table and you win, run the clock down and the
rack goes up.

Two decisions in here are worth knowing about, because both of them are about
a camera that can only read a table when it is still.

**When does the clock stop?** Not when the balls stop rolling — when the cue
was struck. The engine judges a shot once the table settles, which can be
several seconds after contact, and a player who struck with two seconds left
should not be punished for a ball that rolled for three. Every shot is
therefore judged against `ctx.before.ts`, the last moment the table was at
rest before the cue moved.

**Does the clock run while the balls roll?** By default, no. Watching a ball
roll is not a decision, and a slow table should not cost you the game; the
pressure in this game comes from choosing and striking quickly. Pass
`clock="running"` for the harsher version where it never stops.
"""
from __future__ import annotations

import time

from ..types import Effect, ShotResult
from .base import Game, ShotContext, register


class Clock:
    """A countdown that can be paused, added to, and read.

    Everything is derived from a start timestamp rather than accumulated a
    tick at a time, so the reading does not drift and does not depend on how
    often anybody asks.
    """

    def __init__(self, seconds: float) -> None:
        self.banked = float(seconds)    # time left as of `since`
        self.since: float | None = None  # when it last started running

    @property
    def running(self) -> bool:
        return self.since is not None

    def start(self, now: float) -> None:
        if self.since is None:
            self.since = now

    def pause(self, now: float) -> None:
        if self.since is not None:
            self.banked = self.left(now)
            self.since = None

    def add(self, seconds: float, now: float) -> None:
        """Bank time. Re-anchors first so the addition is not lost."""
        if self.since is not None:
            self.banked = self.left(now)
            self.since = now
        self.banked = max(0.0, self.banked + seconds)

    def left(self, now: float) -> float:
        if self.since is None:
            return max(0.0, self.banked)
        # Clamped, because this clock is read at times that are not now. A
        # shot is judged against the moment the table was last at rest, and
        # that moment is *earlier* than the turn that started the clock — so
        # the elapsed time comes out negative and, unclamped, hands the
        # player the whole of the Unix epoch. Time only ever runs forwards
        # here; a read from before the start simply reads as the start.
        return max(0.0, self.banked - max(0.0, now - self.since))

    def expired(self, now: float) -> bool:
        return self.left(now) <= 0.0


@register
class TimeBomb(Game):
    name = "timebomb"
    title = "Time Bomb"
    description = "Beat the clock before the rack blows"
    min_players = 1
    max_players = 6
    #: reds and yellows are fine — it only ever counts balls, never names them
    needs_numbered_balls = False
    needs_projector = False

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        o = self.options
        self.start_seconds = float(o.get("seconds", 30))
        self.bonus = float(o.get("bonus", 7))
        #: seconds knocked off for a scratch. 0 means a scratch ends it
        #: outright, which is the game as designed; set it for a pub where
        #: one unlucky in-off should not end the night.
        self.scratch_penalty = float(o.get("scratch_penalty", 0))
        self.pause_while_rolling = str(o.get("clock", "paused")) != "running"
        self.clocks = [Clock(self.start_seconds) for _ in self.players]
        self.detonated: list[int] = []
        self._last_sync = 0.0

    # --- clock plumbing ----------------------------------------------------
    @property
    def clock(self) -> Clock:
        return self.clocks[self.turn]

    def _clock_effect(self, now: float, tone: str = "") -> Effect:
        """The countdown, sent as remaining seconds rather than a deadline.

        A wall-clock deadline would need the browser's clock to agree with
        this machine's, and it does not have to. Remaining time needs no
        agreement: the overlay starts from the number it is given and counts
        down on its own, and every shot re-syncs it.
        """
        return Effect("countdown", {
            "remaining": round(self.clock.left(now), 2),
            "running": self.clock.running,
            "total": self.start_seconds,
            "player": self.turn,
            "name": self.shooter.name,
            "tone": tone,
            "persist": True,
        }, layer="hud")

    def _resume(self, now: float) -> None:
        self.clock.start(now)

    # --- hooks -------------------------------------------------------------
    def start_note(self) -> str:
        return (f"{int(self.start_seconds)}s on the clock, "
                f"+{int(self.bonus)}s a ball")

    def on_turn_start(self, state) -> list[Effect]:
        now = time.time()
        self._resume(now)
        return [self._clock_effect(now)]

    def on_tick(self, now: float, settled: bool):
        if self.over:
            return None
        clock = self.clock
        # Hold the clock while the balls are moving: time spent watching a
        # ball roll is not time spent deciding.
        if self.pause_while_rolling and not settled:
            if clock.running:
                clock.pause(now)
                return self._sync(now, force=True)
            return None
        if not clock.running and not clock.expired(now):
            clock.start(now)
            return self._sync(now, force=True)
        if clock.expired(now):
            return self._detonate(now)
        # The overlay is counting this down on its own, so a reading every
        # second would be a message a second to say what it already knows.
        # This only corrects drift.
        return self._sync(now)

    def _sync(self, now: float, force: bool = False):
        if not force and now - self._last_sync < 5.0:
            return None
        self._last_sync = now
        return ShotResult(effects=[self._clock_effect(now)])

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        # Judged against the moment the cue was struck, not the moment the
        # balls stopped. See the module docstring.
        struck = ctx.before.ts
        clock = self.clock
        if clock.expired(struck):
            return self._detonate(struck)
        # The shot is legal on time, so the time it took is not charged.
        clock.pause(struck)

        if ev.cue_scratched:
            if self.scratch_penalty <= 0:
                res = self._detonate(struck, reason="cue ball potted")
                return res
            clock.add(-self.scratch_penalty, struck)
            res.foul = "scratch"
            res.turn_passes = True
            res.message = (f"{self.shooter.name}: scratch, "
                           f"-{int(self.scratch_penalty)}s")
            res.effects += self.foul_effects(
                f"scratch: -{int(self.scratch_penalty)}s")
            if clock.expired(struck):
                return self._detonate(struck, reason="scratched the last second away")
            res.effects.append(self._clock_effect(struck, tone="bad"))
            return res

        potted = len(ev.pocketed)
        if potted:
            self.shooter.score += potted
            clock.add(self.bonus * potted, struck)
            res.effects += self.celebrate(ctx, intensity=1.0 + 0.3 * potted,
                                          palette="fire")
            res.effects.append(Effect("score_pop", {
                "player": self.turn, "delta": potted,
                "total": self.shooter.score}, layer="hud"))
            res.message = (f"{self.shooter.name}: +{potted} "
                           f"(+{int(self.bonus * potted)}s)")
        else:
            res.message = f"{self.shooter.name}: missed"

        # Cleared the table — the whole point of the game.
        if not [b for b in ctx.after.balls if not b.is_cue]:
            res.winner = self.turn
            res.game_over = True
            res.message = (f"{self.shooter.name} cleared the table with "
                           f"{clock.left(struck):.1f}s to spare")
            return res

        res.turn_passes = not potted
        res.effects.append(self._clock_effect(struck))
        return res

    # --- the bang ----------------------------------------------------------
    def _detonate(self, now: float, reason: str = "out of time") -> ShotResult:
        """This player's clock has run out. In a solo game that is the end;
        with other players still live, it is their turn."""
        clock = self.clock
        clock.banked = 0.0
        clock.since = None
        blown = self.turn
        self.players[blown].out = True
        if blown not in self.detonated:
            self.detonated.append(blown)

        fx = [
            Effect("table_flash", {"color": "#ff2d55", "duration": 700, "pulses": 3}),
            Effect("fireworks", {"duration": 2200, "palette": "fire",
                                 "origin": "centre"}),
            Effect("banner", {"text": "BOOM",
                              "subtitle": f"{self.players[blown].name} — {reason}",
                              "tone": "bad", "duration": 3200}, layer="hud"),
            Effect("countdown", {"remaining": 0, "running": False,
                                 "total": self.start_seconds, "player": blown,
                                 "name": self.players[blown].name,
                                 "tone": "bad", "persist": True}, layer="hud"),
        ]
        res = ShotResult(effects=fx,
                         message=f"{self.players[blown].name}: {reason}")

        live = [i for i, p in enumerate(self.players) if not p.out]
        if live:
            res.turn_passes = True
            return res

        # Everybody has blown up. Most balls potted takes it; a tie is a tie.
        res.game_over = True
        best = max(p.score for p in self.players)
        leaders = [i for i, p in enumerate(self.players) if p.score == best]
        res.winner = leaders[0] if len(leaders) == 1 and best > 0 else None
        if res.winner is None:
            # Keep the reason this player went up — it is the last thing that
            # happened, and "nobody won" on its own explains nothing.
            tally = (f"nobody beat the clock — {best} ball"
                     f"{'' if best == 1 else 's'} apiece")
            res.message = f"{res.message}; {tally}" if len(self.players) > 1 else res.message
        return res

    # --- display -----------------------------------------------------------
    def scoreboard(self) -> dict:
        now = time.time()
        sb = super().scoreboard()
        sb["clock"] = {
            "remaining": round(self.clock.left(now), 2),
            "running": self.clock.running,
            "total": self.start_seconds,
            "bonus": self.bonus,
            "per_player": [round(c.left(now), 2) for c in self.clocks],
        }
        return sb
