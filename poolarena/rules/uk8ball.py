"""UK eight-ball: English 8-Ball (World Rules) and Blackball.

These are not American 8-ball with different coloured balls. The differences
that matter in play:

  * no called pocket on the black (American 8-ball calls it);
  * potting an opponent's ball is a foul, not merely a wasted shot;
  * the penalty for a foul is not simply ball in hand. In English 8-ball the
    incoming player gets **two visits**: miss on the first and you shoot
    again. In Blackball the penalty is one visit with a **free shot**, on
    which you may strike any ball first.

A warning worth reading before anyone argues over a frame: UK pub and league
rules genuinely vary — by league, by county, and by pub. What is implemented
here is the two common published codes, and the points they differ on are
options rather than assumptions baked into the code. Check `OPTIONS` below
against whatever your table plays to and set them accordingly.
"""
from __future__ import annotations

from ..types import Effect, ShotResult
from .base import Game, ShotContext, register

LOW = set(range(1, 8))       # reds
HIGH = set(range(9, 16))     # yellows
BLACK = 8


class UKEightBall(Game):
    """Shared machinery. The two published codes differ only in the options."""

    name = "uk8-base"
    title = "UK 8-Ball"
    description = "Reds or yellows, then the black"
    min_players = 2
    max_players = 2
    needs_numbered_balls = False

    # --- the knobs the codes disagree about -------------------------------
    #: shots the incoming player gets after an opponent's foul
    foul_visits = 2
    #: may the first ball struck be anything on the shot after a foul?
    foul_free_shot = False
    #: balls that must reach a cushion on the break when nothing is potted
    break_balls_to_rail = 2
    #: is potting the opponent's ball a foul?
    opponent_pot_is_foul = True

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.open_table = True
        self.broken = False
        self.free_shot = False
        self.foul_visits = int(self.options.get("foul_visits", self.foul_visits))
        self.foul_free_shot = bool(self.options.get("free_shot", self.foul_free_shot))
        self.break_balls_to_rail = int(
            self.options.get("break_balls_to_rail", self.break_balls_to_rail))
        # World Rules give ball in hand anywhere; plenty of pubs still play
        # it from baulk, so it is a setting rather than a decision.
        self.ball_in_hand_area = str(
            self.options.get("ball_in_hand_area", self.ball_in_hand_area))
        for p in self.players:
            p.visits = 1

    # --- groups ------------------------------------------------------------
    @property
    def low_name(self) -> str:
        return self.ball_set.group_names[0]

    @property
    def high_name(self) -> str:
        return self.ball_set.group_names[1]

    def group_of(self, player: int) -> set[int] | None:
        g = self.players[player].group
        if g == self.low_name:
            return LOW
        if g == self.high_name:
            return HIGH
        return None

    def assign(self, player: int, group: str) -> None:
        self.players[player].group = group
        self.players[1 - player].group = (
            self.high_name if group == self.low_name else self.low_name)
        self.open_table = False
        for i, p in enumerate(self.players):
            p.balls_left = sorted(self.group_of(i) or [])

    def on_black(self, player: int, state) -> bool:
        grp = self.group_of(player)
        return bool(grp) and not (grp & state.numbers())

    # --- guides ------------------------------------------------------------
    def on_turn_start(self, state):
        fx = []
        me = self.turn
        grp = self.group_of(me)
        if self.free_shot:
            fx.append(Effect("banner", {"text": "FREE SHOT",
                                        "subtitle": "hit anything first",
                                        "tone": "good"}, layer="hud"))
        if self.players[me].visits > 1:
            fx.append(Effect("spotlight", {
                "text": f"{self.shooter.name} — two shots", "color": "#38bdf8"},
                layer="hud"))
        if grp and not self.on_black(me, state):
            fx.append(Effect("highlight_balls", {
                "balls": sorted(grp & state.numbers()),
                "color": "#DC2626" if grp is LOW else "#F2B705",
                "style": "ring"}, layer="guide"))
        elif grp:
            fx.append(Effect("highlight_balls", {"balls": [BLACK], "color": "#f472b6",
                                                 "style": "pulse-ring"}, layer="guide"))
        return fx

    # --- the shot ----------------------------------------------------------
    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        me = self.turn
        pocketed = set(ev.pocketed)
        res = ShotResult()
        was_free = self.free_shot
        self.free_shot = False

        if not ev.cue_struck:
            return ShotResult(message="no shot taken")

        if not self.broken:
            return self._break(ctx, res, pocketed)

        grp = self.group_of(me)
        on_black = self.on_black(me, ctx.before)
        foul = self._foul_reason(ctx, grp, on_black, pocketed, was_free)

        # --- the black ------------------------------------------------------
        if BLACK in pocketed:
            if on_black and not foul and not (pocketed - {BLACK}):
                return self._win(ctx, res, me, "black, frame")
            reason = foul or ("black potted early" if not on_black
                              else "black with another ball")
            return self._lose(ctx, res, me, reason)

        if foul:
            return self._foul(ctx, res, foul)

        # --- a legal shot ----------------------------------------------------
        if self.open_table and pocketed:
            mine, theirs = pocketed & LOW, pocketed & HIGH
            if mine and not theirs:
                self.assign(me, self.low_name)
            elif theirs and not mine:
                self.assign(me, self.high_name)
            if not self.open_table:
                res.effects.append(Effect("assign_group", {
                    "player": me, "group": self.players[me].group,
                    "balls": sorted(self.group_of(me) or [])}, layer="hud"))
            grp = self.group_of(me)

        self._recount(ctx.after)
        own = pocketed & (grp or set())
        res.effects += self.celebrate(ctx, intensity=1.0 + 0.3 * len(pocketed))

        if own:
            # Potting keeps you at the table; an unused second visit is kept.
            res.message = f"potted {self.ball_set.describe_balls(own)}"
            res.turn_passes = False
            if self.on_black(me, ctx.after):
                res.effects.append(Effect("banner", {"text": "ON THE BLACK",
                                                     "tone": "good"}, layer="hud"))
        else:
            # A legal miss spends one visit. With two, you simply shoot again.
            self.shooter.visits -= 1
            if self.shooter.visits > 0:
                res.message = "miss — second shot"
                res.turn_passes = False
                res.effects.append(Effect("banner", {"text": "SECOND SHOT",
                                                     "tone": "good"}, layer="hud"))
            else:
                res.message = "safe"
                res.turn_passes = True
                self.players[1 - me].visits = 1
                self.shooter.visits = 1
        return res

    # --- pieces ------------------------------------------------------------
    def _foul_reason(self, ctx, grp, on_black, pocketed, was_free) -> str | None:
        ev = ctx.events
        hit = ev.first_contact
        if hit is None:
            return "no ball hit"
        if ev.cue_scratched:
            return "in off"
        if not was_free:
            if on_black:
                if hit != BLACK:
                    return f"hit {self.ball_set.a_ball(hit)} first, needed the black"
            elif grp is None:
                if hit == BLACK:
                    return "hit the black on an open table"
            elif hit not in grp:
                return (f"hit {self.ball_set.a_ball(hit)} first, "
                        f"needed {self.players[self.turn].group}")
        if self.opponent_pot_is_foul and grp is not None:
            theirs = pocketed & (HIGH if grp is LOW else LOW)
            if theirs:
                return f"potted {self.ball_set.describe_balls(theirs)}"
        if not pocketed and ev.rails_after_contact == 0:
            return "no rail after contact"
        return None

    def _break(self, ctx, res, pocketed) -> ShotResult:
        ev = ctx.events
        self.broken = True
        res.effects += self.celebrate(ctx, intensity=1.4, palette="electric")
        if ev.cue_scratched:
            return self._foul(ctx, res, "in off on the break")
        if BLACK in pocketed:
            res.message = "black on the break — re-rack"
            res.effects.append(Effect("banner", {"text": "BLACK ON THE BREAK",
                                                 "subtitle": "re-rack"}, layer="hud"))
            self.broken = False
            return res
        if not pocketed and ev.balls_to_rail < self.break_balls_to_rail:
            return self._foul(
                ctx, res,
                f"illegal break (only {ev.balls_to_rail} to a cushion)")
        res.message = (f"break: {self.ball_set.describe_balls(pocketed)} down"
                       if pocketed else "break")
        res.turn_passes = not pocketed
        if res.turn_passes:
            self.players[1 - self.turn].visits = 1
        return res

    def _foul(self, ctx, res, reason: str) -> ShotResult:
        other = 1 - self.turn
        res.foul = reason
        res.message = reason
        res.turn_passes = True
        res.ball_in_hand = True
        self.players[self.turn].visits = 1
        self.players[other].visits = self.foul_visits
        self.free_shot = self.foul_free_shot
        res.effects += self.foul_effects(reason)
        label = ("free shot + ball in hand" if self.foul_free_shot
                 else f"{self.foul_visits} shots to {self.players[other].name}")
        res.effects.append(Effect("banner", {"text": "FOUL", "subtitle": label,
                                             "tone": "bad"}, layer="hud"))
        self._recount(ctx.after)
        return res

    def _win(self, ctx, res, me, message) -> ShotResult:
        res.winner = me
        res.game_over = True
        res.message = message
        res.effects += self.celebrate(ctx, intensity=2.0, palette="gold")
        return res

    def _lose(self, ctx, res, me, reason) -> ShotResult:
        res.winner = 1 - me
        res.game_over = True
        res.message = f"loss: {reason}"
        res.effects += self.foul_effects(reason)
        return res

    def _recount(self, state) -> None:
        for i, p in enumerate(self.players):
            g = self.group_of(i)
            if g:
                p.balls_left = sorted(g & state.numbers())
                p.score = len(g) - len(p.balls_left)


@register
class EnglishEightBall(UKEightBall):
    """WEPF-style World Rules, the usual UK league and pub game.

    The signature mechanic is two visits after a foul: miss with the first and
    you are still at the table. Cue ball in hand anywhere.
    """

    name = "uk8"
    title = "English 8-Ball"
    description = "UK World Rules — two shots after a foul"
    foul_visits = 2
    foul_free_shot = False
    break_balls_to_rail = 2
    opponent_pot_is_foul = True


@register
class Blackball(UKEightBall):
    """WPA Blackball, the international code.

    One visit after a foul, but it carries a free shot: the first ball struck
    may be any ball, which is what makes snookers worth less here than in
    English 8-ball.
    """

    name = "blackball"
    title = "Blackball"
    description = "International code — free shot after a foul"
    foul_visits = 1
    foul_free_shot = True
    break_balls_to_rail = 2
    opponent_pot_is_foul = True
