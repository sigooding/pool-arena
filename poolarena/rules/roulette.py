"""Pocket Roulette — the projector spins a wheel and names your pocket.

Before every shot, a wheel animation runs across the cloth and one pocket
lights up. Pot anything in that pocket to score; pot it anywhere else and the
ball stays down but you get nothing and the turn passes. Impossible to run
without projection, and it wrecks good players' habits, which is the point.
"""
from __future__ import annotations

import random

from ..geometry import POCKETS
from ..types import Effect, ShotResult
from .base import Game, ShotContext, register


@register
class PocketRoulette(Game):
    name = "roulette"
    title = "Pocket Roulette"
    description = "The table picks your pocket"
    min_players = 1
    max_players = 6
    needs_numbered_balls = False

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.rng = random.Random(self.options.get("seed"))
        self.target_score = int(self.options.get("target", 10))
        self.pocket: str | None = None
        self.streak = 0

    def _spin(self) -> list[Effect]:
        previous = self.pocket
        choices = [p for p in POCKETS if p != previous] or list(POCKETS)
        self.pocket = self.rng.choice(choices)
        x, y = self.pocket_pos(self.pocket)
        return [
            Effect("roulette_spin", {"pockets": list(POCKETS), "landed": self.pocket,
                                     "duration": 2200}),
            Effect("pocket_glow", {"pocket": self.pocket, "duration": 0, "persist": True,
                                   "color": "#22d3ee", "intensity": 1.3, "label": "YOUR POCKET"},
                   layer="guide"),
            Effect("pocket_arrows", {"pocket": self.pocket, "x": x, "y": y}, layer="guide"),
        ]

    def on_start(self):
        return super().on_start() + self._spin()

    def on_turn_start(self, state):
        fx = [] if self.pocket else self._spin()
        return fx + [Effect("spotlight", {
            "text": f"{self.shooter.name} → {self.pocket}", "color": "#22d3ee"}, layer="hud")]

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        if ev.cue_scratched:
            self.streak = 0
            self.shooter.score = max(0, self.shooter.score - 1)
            res.foul = "scratch"
            res.turn_passes = True
            res.effects += self.foul_effects("scratch: -1")
            res.effects += self._spin()
            return res

        right = [b for b in ev.pocketed if ev.pocketed_in.get(b) == self.pocket]
        wrong = [b for b in ev.pocketed if ev.pocketed_in.get(b) != self.pocket]

        if right:
            self.streak += 1
            gained = len(right) * (1 + (self.streak - 1) // 2)
            self.shooter.score += gained
            res.message = f"{self.pocket} hit, +{gained} (streak {self.streak})"
            res.effects += self.celebrate(ctx, intensity=1.2 + 0.3 * self.streak, palette="electric")
            if self.streak >= 3:
                res.effects.append(Effect("banner", {"text": f"{self.streak} IN A ROW",
                                                     "tone": "good"}, layer="hud"))
                res.effects.append(Effect("lightning", {"pocket": self.pocket}))
        else:
            self.streak = 0
            res.message = f"wrong pocket ({', '.join(ev.pocketed_in.get(b, '?') for b in wrong)})" if wrong else "no pot"
            res.effects.append(Effect("table_flash", {"color": "#64748b", "duration": 300}))
            for b in wrong:
                pid = ev.pocketed_in.get(b)
                if pid:
                    res.effects.append(Effect("pocket_reject", {"pocket": pid, "ball": b}))

        res.effects.append(Effect("score_pop", {"player": self.turn,
                                                "total": self.shooter.score}, layer="hud"))
        if self.shooter.score >= self.target_score:
            res.winner = self.turn
            res.game_over = True
            return res

        res.turn_passes = not right
        res.effects += self._spin()
        return res
