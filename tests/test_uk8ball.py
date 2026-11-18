"""UK eight-ball. The mechanics that differ from the American game are the
two-visit foul penalty and the free shot; those are what these test."""
from helpers import TABLE, events, state

from poolarena.ballset import ENGLISH
from poolarena.rules import get_game
from poolarena.rules.base import ShotContext


def play(game, before, after, ev):
    return game.apply(ShotContext(before=before, after=after, events=ev,
                                  table=TABLE, shooter=game.turn))


def uk(name="uk8", **opts):
    g = get_game(name)(players=["A", "B"], table=TABLE, ball_set=ENGLISH,
                       options=opts)
    g.broken = True
    return g


OPEN = dict(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))


# --- two visits -----------------------------------------------------------
def test_a_foul_gives_the_opponent_two_shots():
    g = uk()
    g.assign(0, "reds")
    before = state(**OPEN)
    res = play(g, before, before, events(first=11, rails=1))
    assert res.foul and "yellow" in res.foul
    assert g.turn == 1
    assert g.players[1].visits == 2, "English 8-ball gives two visits for a foul"


def test_a_miss_on_the_first_of_two_visits_keeps_you_at_the_table():
    g = uk()
    g.assign(1, "yellows")          # B is yellows, A is reds
    g.players[0].visits = 2
    before = state(**OPEN)
    res = play(g, before, before, events(first=3, rails=1))   # legal, no pot
    assert not res.foul
    assert not res.turn_passes, "the second of two visits must stay with you"
    assert g.players[0].visits == 1
    assert "second shot" in res.message


def test_the_turn_passes_once_both_visits_are_spent():
    g = uk()
    g.assign(0, "reds")
    g.players[0].visits = 1
    before = state(**OPEN)
    res = play(g, before, before, events(first=3, rails=1))
    assert res.turn_passes
    assert g.turn == 1
    assert g.players[1].visits == 1, "a safe does not hand over two shots"


def test_potting_does_not_consume_a_visit():
    g = uk()
    g.assign(0, "reds")
    g.players[0].visits = 2
    before = state(**OPEN)
    after = state(b0=(1600, 350), b11=(900, 200), b8=(1200, 500))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}, first=3))
    assert not res.turn_passes
    assert g.players[0].visits == 2, "a pot keeps the unused second shot"


# --- free shot ------------------------------------------------------------
def test_blackball_gives_one_visit_with_a_free_shot():
    g = uk("blackball")
    g.assign(0, "reds")
    before = state(**OPEN)
    res = play(g, before, before, events(first=11, rails=1))
    assert res.foul
    assert g.players[1].visits == 1, "Blackball is one visit, not two"
    assert g.free_shot is True


def test_on_a_free_shot_any_ball_may_be_struck_first():
    g = uk("blackball")
    g.assign(0, "reds")
    g.assign(1, "yellows")
    before = state(**OPEN)
    play(g, before, before, events(first=11, rails=1))      # A fouls
    assert g.turn == 1 and g.free_shot
    # B is yellows and strikes a red first: legal, because of the free shot
    res = play(g, before, before, events(first=3, rails=1))
    assert res.foul is None
    assert g.free_shot is False, "the free shot is spent after one shot"


def test_english_eight_ball_has_no_free_shot():
    g = uk("uk8")
    g.assign(0, "reds")
    g.assign(1, "yellows")
    before = state(**OPEN)
    play(g, before, before, events(first=11, rails=1))      # A fouls
    assert not g.free_shot
    res = play(g, before, before, events(first=3, rails=1))  # B hits a red
    assert res.foul, "without a free shot, hitting the wrong colour still fouls"


# --- UK-specific fouls ----------------------------------------------------
def test_potting_the_opponents_ball_is_a_foul():
    g = uk()
    g.assign(0, "reds")
    before = state(**OPEN)
    after = state(b0=(1600, 350), b3=(1800, 300), b8=(1200, 500))
    res = play(g, before, after, events(pocketed=[11], pockets={11: "TR"}, first=3))
    assert res.foul and "yellow" in res.foul
    assert g.players[1].visits == 2


def test_no_called_pocket_on_the_black():
    """Unlike American 8-ball, the black needs no nominated pocket."""
    g = uk()
    g.assign(0, "reds")
    before = state(b0=(400, 600), b8=(1800, 300), b11=(900, 200))
    after = state(b0=(1600, 350), b11=(900, 200))
    res = play(g, before, after, events(pocketed=[8], pockets={8: "BL"}, first=8))
    assert res.game_over and res.winner == 0


def test_black_potted_early_loses_the_frame():
    g = uk()
    g.assign(0, "reds")
    before = state(**OPEN)
    after = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200))
    res = play(g, before, after, events(pocketed=[8], pockets={8: "BM"}, first=3))
    assert res.game_over and res.winner == 1


def test_in_off_is_a_foul():
    g = uk()
    g.assign(0, "reds")
    before = state(**OPEN)
    after = state(b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    res = play(g, before, after, events(scratch=True, first=3, pockets={0: "BM"}))
    assert res.foul == "in off"
    assert res.ball_in_hand and g.players[1].visits == 2


def test_break_needs_balls_to_a_cushion():
    g = get_game("uk8")(players=["A", "B"], table=TABLE, ball_set=ENGLISH)
    before = state(b0=(400, 600), b1=(1800, 300))
    res = play(g, before, before, events(first=1, rails=1))
    assert res.foul and "cushion" in res.foul


def test_rule_variations_are_options_not_assumptions():
    g = uk("uk8", foul_visits=1)
    g.assign(0, "reds")
    before = state(**OPEN)
    play(g, before, before, events(first=11, rails=1))
    assert g.players[1].visits == 1, "leagues that play one shot can set that"
