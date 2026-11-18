"""Solo practice modes. The projector is the coach: it draws where the cue ball
has to stop, then grades you on how close you got.
"""
from __future__ import annotations

import math
import random

from ..types import Effect, ShotResult
from ..zones import Zone, random_zones
from .base import Game, ShotContext, register


@register
class PositionDrill(Game):
    name = "position"
    title = "Position Drill"
    description = "Pot a ball, stop the cue in the ring"
    min_players = 1
    max_players = 4
    needs_numbered_balls = False
    needs_projector = True

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.rng = random.Random(self.options.get("seed"))
        self.radius = float(self.options.get("radius", 170))
        self.shots = int(self.options.get("shots", 10))
        self.zone: Zone | None = None
        self.distances: list[float] = []

    def _new_target(self, state) -> list[Effect]:
        avoid = [(b.x, b.y) for b in state.balls]
        zs = random_zones(self.table, 1, radius=self.radius, avoid=avoid, rng=self.rng,
                          colors=("#34d399",), points=(1,))
        self.zone = zs[0] if zs else Zone("z0", x=self.table.centre[0], y=self.table.centre[1],
                                          r=self.radius, color="#34d399")
        self.zone.label = "STOP HERE"
        return [Effect("target_zone", {"zone": self.zone.to_json(), "transition": "sweep"},
                       layer="guide")]

    def on_start(self):
        return super().on_start() + [
            Effect("banner", {"text": "POSITION DRILL",
                              "subtitle": f"{self.shots} shots"}, layer="hud")]

    def on_turn_start(self, state):
        fx = self._new_target(state) if self.zone is None else [
            Effect("target_zone", {"zone": self.zone.to_json()}, layer="guide")]
        # Draw the aiming line for the easiest available pot: this is a coach,
        # not a match, so the help is the feature.
        cue = state.cue()
        objs = [b for b in state.balls if not b.is_cue]
        if cue and objs and self.options.get("show_aim", True):
            from ..geometry import shot_candidates
            blockers = [(b.x, b.y) for b in state.balls]
            best = None
            for o in objs:
                for c in shot_candidates((cue.x, cue.y), (o.x, o.y), self.table, blockers):
                    if c["blocked"]:
                        continue
                    if best is None or c["difficulty"] < best[0]["difficulty"]:
                        best = (c, o)
                    break
            if best:
                c, o = best
                fx.append(Effect("aim_line", {
                    "cue": [cue.x, cue.y], "target": [o.x, o.y],
                    "ghost": [round(v, 1) for v in c["ghost"]],
                    "pocket": c["pocket"], "cut_angle": c["cut_angle"],
                }, layer="guide"))
        return fx

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        cue = ctx.after.cue()
        potted = bool(ev.pocketed)
        dist = None
        if cue and self.zone:
            dist = math.hypot(cue.x - self.zone.x, cue.y - self.zone.y)

        if ev.cue_scratched or not potted:
            res.message = "scratch" if ev.cue_scratched else "missed the pot"
            res.effects.append(Effect("table_flash", {"color": "#f87171", "duration": 300}))
        else:
            inside = dist is not None and dist <= self.zone.r
            grade = max(0.0, 1.0 - (dist or 0) / (self.zone.r * 3)) if dist is not None else 0.0
            pts = int(round(grade * 10))
            self.shooter.score += pts
            self.distances.append(dist or 0.0)
            res.effects += self.celebrate(ctx, intensity=0.8 + grade, palette="mint")
            res.effects.append(Effect("zone_grade", {
                "zone": self.zone.to_json(), "inside": inside,
                "distance": round(dist or 0, 1), "points": pts,
                "cue": [cue.x, cue.y] if cue else None,
            }))
            res.message = f"{'in the ring' if inside else f'{dist:.0f} mm out'} — +{pts}"

        res.effects.append(Effect("score_pop", {"player": self.turn,
                                                "total": self.shooter.score}, layer="hud"))
        if self.shot_number + 1 >= self.shots:
            avg = sum(self.distances) / len(self.distances) if self.distances else 0
            res.game_over = True
            res.winner = max(range(len(self.players)), key=lambda i: self.players[i].score)
            res.message = f"drill over — {self.shooter.score}/{self.shots * 10}, avg {avg:.0f} mm"
            return res

        res.effects += self._new_target(ctx.after)
        res.turn_passes = len(self.players) > 1
        return res
