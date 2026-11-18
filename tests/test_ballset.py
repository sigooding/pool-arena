"""An English set is reds and yellows with no numbers on the balls.

The internal representation stays numeric (reds 1-7, yellows 9-15, black 8)
so the rule sets and the event detector need no special case. What must not
leak is the pretence that those numbers mean anything.
"""
import pytest
from helpers import TABLE, events, state

from poolarena.ballset import AMERICAN, ENGLISH, get_ball_set
from poolarena.engine import Engine
from poolarena.rules import get_game
from poolarena.rules.base import ShotContext, available
from poolarena.server.ws import Hub


def play(game, before, after, ev):
    return game.apply(ShotContext(before=before, after=after, events=ev,
                                  table=TABLE, shooter=game.turn))


def test_aliases():
    assert get_ball_set("uk") is ENGLISH
    assert get_ball_set("blackball") is ENGLISH
    assert get_ball_set(None) is AMERICAN
    with pytest.raises(ValueError):
        get_ball_set("marbles")


def test_colour_mapping():
    assert ENGLISH.colour_of(1) == "red" and ENGLISH.colour_of(7) == "red"
    assert ENGLISH.colour_of(9) == "yellow" and ENGLISH.colour_of(15) == "yellow"
    assert ENGLISH.colour_of(8) == "black"
    assert ENGLISH.group_of(3) == "reds" and ENGLISH.group_of(11) == "yellows"
    assert ENGLISH.group_of(8) is None


def test_numbers_never_shown_for_an_unnumbered_set():
    assert ENGLISH.describe_balls({11, 14}) == "two yellows"
    assert ENGLISH.describe_balls({1}) == "one red"
    assert ENGLISH.describe_balls({2, 3, 11}) == "two reds and one yellow"
    assert ENGLISH.a_ball(4) == "a red"
    assert ENGLISH.a_ball(8) == "the black"
    # the numbered set still reads naturally
    assert AMERICAN.describe_balls({11, 14}) == "11, 14"
    assert AMERICAN.a_ball(4) == "the 4"


def test_eight_ball_plays_identically_with_reds_and_yellows():
    g = get_game("8ball")(players=["A", "B"], table=TABLE, ball_set=ENGLISH)
    g.broken = True
    assert g.low_group == "reds" and g.high_group == "yellows"

    before = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    after = state(b0=(1600, 350), b11=(900, 200), b8=(1200, 500))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}, first=3))
    assert g.players[0].group == "reds"
    assert g.players[1].group == "yellows"
    assert "red" in res.message and "[" not in res.message


def test_eight_ball_foul_text_uses_colours_not_numbers():
    g = get_game("8ball")(players=["A", "B"], table=TABLE, ball_set=ENGLISH)
    g.broken = True
    g.assign(0, "reds")
    before = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    res = play(g, before, before, events(first=11, rails=1))
    assert res.foul == "hit a yellow first, needed reds"


def test_games_needing_identity_are_refused_not_mis_scored():
    assert get_game("9ball").supports(AMERICAN)
    assert not get_game("9ball").supports(ENGLISH)
    assert not get_game("cutthroat").supports(ENGLISH)
    # everything that only cares about colour or count still works
    for name in ("8ball", "killer", "hotspots", "roulette", "position"):
        assert get_game(name).supports(ENGLISH), name


def test_engine_refuses_a_game_the_set_cannot_support():
    e = Engine(table=TABLE, hub=Hub(), ball_set=ENGLISH)
    with pytest.raises(ValueError, match="numbered balls"):
        e.start_game("9ball", players=["A", "B"])
    assert e.start_game("8ball", players=["A", "B"]).name == "8ball"


def test_menu_marks_what_is_playable():
    eng = {g["name"]: g for g in available(ENGLISH)}
    assert eng["9ball"]["supported"] is False
    assert eng["8ball"]["supported"] is True
    assert eng["8ball"]["description"] == "Reds or yellows, then the black"
    us = {g["name"]: g for g in available(AMERICAN)}
    assert us["9ball"]["supported"] is True
    assert us["8ball"]["description"] == "Solids or stripes, then the 8"


def test_tracker_allocates_numbers_within_the_right_colour():
    """Reds must land in 1-7 and yellows in 9-15, or 8-ball's groups break."""
    from poolarena.vision.pipeline import VisionPipeline

    ranges = VisionPipeline.GROUP_RANGES
    assert list(ranges["reds"]) == list(range(1, 8))
    assert list(ranges["yellows"]) == list(range(9, 16))
    assert 8 not in ranges["reds"] and 8 not in ranges["yellows"]
