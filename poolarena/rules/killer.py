"""Killer: pot a ball on your turn or lose a life. Brutal with six players."""
from __future__ import annotations

from ..types import Effect, ShotResult
from .base import Game, ShotContext, register


@register
class Killer(Game):
    name = "killer"
    title = "Killer"
    description = "Pot or lose a life"
    min_players = 2
    max_players = 8
    needs_numbered_balls = False

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        lives = int(self.options.get("lives", 3))
        for p in self.players:
            p.lives = lives
            p.score = lives

    def on_turn_start(self, state):
        return [
            Effect("lives_bar", {"players": [p.to_json() for p in self.players],
                                 "turn": self.turn}, layer="hud"),
            Effect("spotlight", {"text": f"{self.shooter.name} — {self.shooter.lives} lives",
                                 "color": "#f59e0b"}, layer="hud"),
        ]

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        pocketed = set(ev.pocketed)
        lost = False
        reason = ""

        if ev.cue_scratched:
            lost, reason = True, "scratch"
        elif not pocketed:
            lost, reason = True, "no pot"

        if lost:
            self.shooter.lives -= 1
            self.shooter.score = self.shooter.lives
            res.message = f"{reason} — {self.shooter.lives} lives left"
            res.effects.append(Effect("life_lost", {"player": self.turn,
                                                    "name": self.shooter.name,
                                                    "lives": self.shooter.lives,
                                                    "reason": reason}, layer="hud"))
            res.effects.append(Effect("table_flash", {"color": "#ef4444", "duration": 400}))
            if self.shooter.lives <= 0:
                self.shooter.out = True
                res.effects.append(Effect("banner", {"text": f"{self.shooter.name} ELIMINATED",
                                                     "tone": "bad"}, layer="hud"))
                res.effects.append(Effect("shatter", {"player": self.turn}))
            res.turn_passes = True
        else:
            res.effects += self.celebrate(ctx, intensity=1.2, palette="electric")
            res.message = f"potted {sorted(pocketed)}"
            res.turn_passes = True     # killer always rotates

        alive = [i for i, p in enumerate(self.players) if not p.out]
        if len(alive) == 1:
            res.winner = alive[0]
            res.game_over = True
            res.turn_passes = False
        # Re-rack hook: when the table empties, the operator racks again.
        elif not (ctx.after.numbers() - {0}):
            res.effects.append(Effect("banner", {"text": "RE-RACK",
                                                 "subtitle": "table cleared"}, layer="hud"))
        return res
