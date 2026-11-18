"""8-ball, BCA-ish. Open table, group assignment on the first legal pot."""
from __future__ import annotations

from ..types import Effect, Kind, ShotResult, kind_of
from .base import Game, ShotContext, register

SOLIDS = set(range(1, 8))
STRIPES = set(range(9, 16))


@register
class EightBall(Game):
    name = "8ball"
    title = "8-Ball"
    description = "Solids or stripes, then the 8"
    min_players = 2
    max_players = 2
    # Only the two groups matter, never which ball within one, so this plays
    # exactly the same with an English reds-and-yellows set.
    needs_numbered_balls = False

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.open_table = True
        self.broken = False
        self.call_pocket: bool = bool(self.options.get("call_pocket", True))
        self.called: str | None = None     # pocket id called for the 8

    # --- helpers -----------------------------------------------------------
    @property
    def low_group(self) -> str:
        return self.ball_set.group_names[0]      # solids, or reds

    @property
    def high_group(self) -> str:
        return self.ball_set.group_names[1]      # stripes, or yellows

    def group_of(self, player: int) -> set[int] | None:
        g = self.players[player].group
        if g == self.low_group:
            return SOLIDS
        if g == self.high_group:
            return STRIPES
        return None

    def assign(self, player: int, group: str) -> None:
        other = self.high_group if group == self.low_group else self.low_group
        self.players[player].group = group
        self.players[1 - player].group = other
        self.open_table = False
        for i, p in enumerate(self.players):
            p.balls_left = sorted(self.group_of(i) or [])

    def on_eight(self, player: int, state) -> bool:
        grp = self.group_of(player)
        if grp is None:
            return False
        return not (grp & state.numbers())

    @classmethod
    def describe(cls, ball_set):
        a, b = ball_set.group_names
        last = "the 8" if ball_set.has_numbers else "the black"
        return f"{a.capitalize()} or {b}, then {last}"

    def on_start(self):
        self.description = self.describe(self.ball_set)
        return super().on_start()

    def on_turn_start(self, state):
        fx = []
        grp = self.group_of(self.turn)
        if grp and not self.on_eight(self.turn, state):
            targets = sorted(grp & state.numbers())
            fx.append(Effect("highlight_balls", {"balls": targets, "color": "#4ade80",
                                                 "style": "ring"}, layer="guide"))
        elif grp:
            eight = state.get(8)
            fx.append(Effect("highlight_balls", {"balls": [8], "color": "#f472b6",
                                                 "style": "pulse-ring"}, layer="guide"))
            if eight and self.call_pocket:
                fx.append(Effect("call_pocket_prompt", {"ball": 8}, layer="guide"))
        return fx

    # --- the shot ----------------------------------------------------------
    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        me = self.turn
        grp = self.group_of(me)
        pocketed = set(ev.pocketed)
        res = ShotResult()

        if not ev.cue_struck:
            return ShotResult(turn_passes=False, message="no shot taken")

        # --- the break -----------------------------------------------------
        if not self.broken:
            self.broken = True
            res.effects += self.celebrate(ctx, intensity=1.4, palette="electric")
            if 8 in pocketed and not ev.cue_scratched:
                res.message = "8 on the break — re-spotted"
                res.effects.append(Effect("banner", {"text": "8 ON THE BREAK",
                                                     "subtitle": "spot it and carry on"}, layer="hud"))
                return res
            if ev.cue_scratched:
                res.foul = "scratch on the break"
                res.turn_passes = True
                res.ball_in_hand = True
                res.effects += self.foul_effects(res.foul)
                return res
            if not pocketed and ev.balls_to_rail < 4:
                res.foul = (f"illegal break (only {ev.balls_to_rail} "
                            f"ball{'' if ev.balls_to_rail == 1 else 's'} to a rail)")
                res.turn_passes = True
                res.effects += self.foul_effects(res.foul)
                return res
            res.message = f"break: {len(pocketed)} down" if pocketed else "break"
            res.turn_passes = not pocketed
            return res

        legal_target = self._legal_first_contact(ctx, grp)
        foul = None

        if ev.first_contact is None:
            foul = "no ball hit"
        elif not legal_target:
            hit = ev.first_contact
            want = ("the black" if self.on_eight(me, ctx.before)
                    else (self.players[me].group or "any ball"))
            foul = f"hit {self.ball_set.a_ball(hit)} first, needed {want}"
        elif ev.cue_scratched:
            foul = "scratch"
        elif not pocketed and ev.rails_after_contact == 0:
            foul = "no rail after contact"

        # --- the 8 ---------------------------------------------------------
        if 8 in pocketed:
            if self.on_eight(me, ctx.before) and not foul:
                called_ok = True
                if self.call_pocket and self.called:
                    called_ok = ev.pocketed_in.get(8) == self.called
                if called_ok and not (pocketed - {8}):
                    res.winner = me
                    res.game_over = True
                    res.message = "black, game"
                    res.effects += self.celebrate(ctx, intensity=2.0, palette="gold")
                    return res
                reason = "wrong pocket" if not called_ok else "black with another ball"
                res.winner = 1 - me
                res.game_over = True
                res.message = f"loss: {reason}"
                res.effects += self.foul_effects(reason)
                return res
            res.winner = 1 - me
            res.game_over = True
            res.message = ("black pocketed early" if not foul
                           else f"black pocketed on a foul ({foul})")
            res.effects += self.foul_effects("black off the table")
            return res

        if foul:
            res.foul = foul
            res.turn_passes = True
            res.ball_in_hand = True
            res.message = foul
            res.effects += self.foul_effects(foul)
            res.effects += self.celebrate(ctx, intensity=0.4, palette="ash")
            return res

        # --- legal shot ----------------------------------------------------
        if self.open_table and pocketed:
            mine = pocketed & SOLIDS
            theirs = pocketed & STRIPES
            if mine and not theirs:
                self.assign(me, self.low_group)
            elif theirs and not mine:
                self.assign(me, self.high_group)
            # both groups down on one shot leaves the table open
            if not self.open_table:
                res.effects.append(Effect("assign_group", {
                    "player": me, "group": self.players[me].group,
                    "balls": sorted(self.group_of(me) or []),
                }, layer="hud"))
            grp = self.group_of(me)

        own = pocketed & (grp or set())
        for p_i, p in enumerate(self.players):
            g = self.group_of(p_i)
            if g:
                p.balls_left = sorted(g & ctx.after.numbers())
                p.score = len(g) - len(p.balls_left)

        res.effects += self.celebrate(ctx, intensity=1.0 + 0.3 * len(pocketed))
        if own:
            res.message = f"potted {self.ball_set.describe_balls(own)}"
            res.turn_passes = False
            if self.on_eight(me, ctx.after):
                res.effects.append(Effect("banner", {"text": "ON THE 8", "tone": "good"}, layer="hud"))
                res.effects.append(Effect("highlight_balls", {"balls": [8], "color": "#f472b6",
                                                             "style": "pulse-ring"}, layer="guide"))
        else:
            res.message = ("safe" if not pocketed
                           else f"potted opponent's {self.ball_set.describe_balls(pocketed)}")
            res.turn_passes = True
        self.called = None
        return res

    def _legal_first_contact(self, ctx: ShotContext, grp: set[int] | None) -> bool:
        hit = ctx.events.first_contact
        if hit is None:
            return False
        if self.on_eight(self.turn, ctx.before):
            return hit == 8
        if grp is None:
            return hit != 8            # open table: anything but the 8
        return hit in grp

    def call(self, pocket: str) -> None:
        """Called pocket for the 8, set from the UI."""
        self.called = pocket
