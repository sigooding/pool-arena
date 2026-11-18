"""9-ball: always hit the lowest ball first, pot the 9 to win."""
from __future__ import annotations

from ..types import Effect, ShotResult
from .base import Game, ShotContext, register


@register
class NineBall(Game):
    name = "9ball"
    title = "9-Ball"
    description = "Lowest ball first, pot the 9"
    min_players = 2
    max_players = 4

    def lowest(self, state) -> int | None:
        nums = sorted(n for n in state.numbers() if n != 0)
        return nums[0] if nums else None

    def on_turn_start(self, state):
        low = self.lowest(state)
        fx = []
        if low is not None:
            fx.append(Effect("highlight_balls", {"balls": [low], "color": "#38bdf8",
                                                 "style": "pulse-ring", "label": str(low)},
                             layer="guide"))
            cue = state.cue()
            ball = state.get(low)
            if cue and ball and self.options.get("show_aim", False):
                fx.append(Effect("aim_assist", {"cue": [cue.x, cue.y], "target": [ball.x, ball.y]},
                                 layer="guide"))
        return fx

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        low = self.lowest(ctx.before)
        pocketed = set(ev.pocketed)
        foul = None

        if ev.first_contact is None:
            foul = "no ball hit"
        elif low is not None and ev.first_contact != low:
            foul = f"hit the {ev.first_contact} first, needed the {low}"
        elif ev.cue_scratched:
            foul = "scratch"
        elif not pocketed and ev.rails_after_contact == 0:
            foul = "no rail after contact"

        if 9 in pocketed and not foul:
            res.winner = self.turn
            res.game_over = True
            res.message = "9-ball, game"
            res.effects += self.celebrate(ctx, intensity=2.0, palette="gold")
            return res

        if foul:
            res.foul = foul
            res.turn_passes = True
            res.ball_in_hand = True
            res.message = foul
            res.effects += self.foul_effects(foul)
            if 9 in pocketed:
                res.effects.append(Effect("banner", {"text": "9 RE-SPOTTED",
                                                     "subtitle": foul}, layer="hud"))
            return res

        self.shooter.score += len(pocketed)
        res.effects += self.celebrate(ctx, intensity=1.0 + 0.25 * len(pocketed), palette="neon")
        if pocketed:
            res.message = f"potted {sorted(pocketed)}, continues"
            if len(pocketed) > 1:
                res.effects.append(Effect("banner", {"text": f"{len(pocketed)} DOWN",
                                                     "tone": "good"}, layer="hud"))
            nxt = self.lowest(ctx.after)
            if nxt is not None:
                res.effects.append(Effect("highlight_balls", {"balls": [nxt], "color": "#38bdf8",
                                                              "style": "pulse-ring"}, layer="guide"))
        else:
            res.message = "safe"
            res.turn_passes = True
        return res
