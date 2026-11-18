"""Cut-throat: three players own five balls each, last one with balls wins."""
from __future__ import annotations

from ..types import Effect, ShotResult
from .base import Game, ShotContext, register

GROUPS = [set(range(1, 6)), set(range(6, 11)), set(range(11, 16))]
COLORS = ["#60a5fa", "#4ade80", "#fb923c"]


@register
class CutThroat(Game):
    name = "cutthroat"
    title = "Cut-Throat"
    description = "Own five balls, pot everyone else's"
    min_players = 3
    max_players = 3

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        for i, p in enumerate(self.players):
            p.group = f"{min(GROUPS[i])}-{max(GROUPS[i])}"
            p.balls_left = sorted(GROUPS[i])

    def owner(self, ball: int) -> int | None:
        for i, g in enumerate(GROUPS):
            if ball in g:
                return i
        return None

    def on_start(self):
        fx = super().on_start()
        for i, g in enumerate(GROUPS):
            fx.append(Effect("highlight_balls", {"balls": sorted(g), "color": COLORS[i],
                                                 "style": "ring", "label": self.players[i].name,
                                                 "persist": True}, layer="guide"))
        return fx

    def on_turn_start(self, state):
        # Light every ball that is not mine: those are the legal targets.
        mine = GROUPS[self.turn]
        targets = sorted(n for n in state.numbers() if n and n not in mine)
        return [
            Effect("highlight_balls", {"balls": sorted(mine & state.numbers()),
                                       "color": COLORS[self.turn], "style": "ring",
                                       "label": "yours"}, layer="guide"),
            Effect("highlight_balls", {"balls": targets, "color": "#ef4444",
                                       "style": "crosshair"}, layer="guide"),
        ]

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        mine = GROUPS[self.turn]
        pocketed = set(ev.pocketed)
        foul = None
        if ev.first_contact is None:
            foul = "no ball hit"
        elif ev.first_contact in mine:
            foul = f"hit your own {ev.first_contact} first"
        elif ev.cue_scratched:
            foul = "scratch"
        elif not pocketed and ev.rails_after_contact == 0:
            foul = "no rail after contact"

        for i, g in enumerate(GROUPS):
            self.players[i].balls_left = sorted(g & ctx.after.numbers())
            self.players[i].score = len(self.players[i].balls_left)
            self.players[i].out = not self.players[i].balls_left

        if foul:
            # Fouls in cut-throat put one ball back for every player you hurt.
            res.foul = foul
            res.turn_passes = True
            res.ball_in_hand = True
            res.message = foul
            res.effects += self.foul_effects(foul)
            return res

        hurt = {self.owner(b) for b in pocketed} - {None}
        res.effects += self.celebrate(ctx, intensity=1.0 + 0.3 * len(pocketed), palette="neon")
        for who in sorted(x for x in hurt if x is not None):
            res.effects.append(Effect("player_hit", {"player": who, "name": self.players[who].name,
                                                     "remaining": self.players[who].score,
                                                     "color": COLORS[who]}, layer="hud"))
            if self.players[who].out:
                res.effects.append(Effect("banner", {"text": f"{self.players[who].name} OUT",
                                                     "tone": "bad"}, layer="hud"))

        alive = [i for i, p in enumerate(self.players) if not p.out]
        if len(alive) == 1:
            res.winner = alive[0]
            res.game_over = True
            res.message = "last one standing"
            return res

        res.turn_passes = not pocketed
        res.message = f"potted {sorted(pocketed)}" if pocketed else "safe"
        return res
