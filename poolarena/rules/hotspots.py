"""Hotspots — a game that cannot exist without a projector.

Three glowing zones sit on the cloth. Pot a ball and you score it; route the
object ball *through* a zone on the way and the zone's value is added, then it
goes dark and a new one lights somewhere else. Stop the cue ball in a zone for
a bonus. Every shot the table re-lights, so position play is the whole game.
"""
from __future__ import annotations

import random

from ..types import Effect, ShotResult
from ..zones import Zone, random_zones
from .base import Game, ShotContext, register


@register
class Hotspots(Game):
    name = "hotspots"
    title = "Hotspots"
    description = "Roll object balls through the glowing zones"
    min_players = 1
    max_players = 6
    needs_numbered_balls = False

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.rng = random.Random(self.options.get("seed"))
        self.zone_count = int(self.options.get("zones", 3))
        self.target_score = int(self.options.get("target", 25))
        self.zones: list[Zone] = []

    def _relight(self, state) -> list[Effect]:
        avoid = [(b.x, b.y) for b in state.balls]
        self.zones = random_zones(self.table, self.zone_count,
                                  radius=float(self.options.get("radius", 150)),
                                  avoid=avoid, rng=self.rng)
        return [Effect("zones", {"zones": [z.to_json() for z in self.zones],
                                 "transition": "bloom"}, layer="guide")]

    def on_start(self):
        return super().on_start() + [
            Effect("banner", {"text": "HOTSPOTS",
                              "subtitle": f"first to {self.target_score}"}, layer="hud")
        ]

    def on_turn_start(self, state):
        fx = self._relight(state) if not self.zones else [
            Effect("zones", {"zones": [z.to_json() for z in self.zones]}, layer="guide")
        ]
        return fx + [Effect("spotlight", {"text": f"{self.shooter.name} — {self.shooter.score}",
                                          "color": "#a78bfa"}, layer="hud")]

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        res = ShotResult()
        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        gained = 0
        notes: list[str] = []

        if ev.cue_scratched:
            self.shooter.score = max(0, self.shooter.score - 2)
            res.foul = "scratch"
            res.turn_passes = True
            res.effects += self.foul_effects("scratch: -2")
            res.effects += self._relight(ctx.after)
            return res

        for ball in ev.pocketed:
            gained += 1
            trace = ev.trace.get(ball, [])
            for z in self.zones:
                if z.state == "active" and trace and z.crossed_by(trace):
                    gained += z.points
                    z.state = "hit"
                    notes.append(f"zone {z.label} x{z.points}")
                    res.effects.append(Effect("zone_hit", {
                        "zone": z.to_json(), "ball": ball,
                        "path": [[round(p[0]), round(p[1])] for p in trace[::2]],
                    }))

        cue = ctx.after.cue()
        if cue:
            for z in self.zones:
                if z.state == "active" and z.contains(cue.x, cue.y):
                    gained += z.points * 2
                    z.state = "hit"
                    notes.append(f"cue parked in {z.label} x2")
                    res.effects.append(Effect("zone_park", {"zone": z.to_json(),
                                                            "x": cue.x, "y": cue.y}))

        if ev.pocketed:
            res.effects += self.celebrate(ctx, intensity=1.0 + 0.2 * gained, palette="neon")

        self.shooter.score += gained
        res.message = (f"+{gained}" + (" (" + ", ".join(notes) + ")" if notes else "")) if gained else "nothing"
        res.effects.append(Effect("score_pop", {"player": self.turn, "delta": gained,
                                                "total": self.shooter.score}, layer="hud"))

        if self.shooter.score >= self.target_score:
            res.winner = self.turn
            res.game_over = True
            res.message = f"{self.shooter.score} points, game"
            return res

        res.turn_passes = not ev.pocketed
        res.effects += self._relight(ctx.after)
        return res
