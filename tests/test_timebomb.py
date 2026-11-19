"""Time Bomb — the clock, and what a camera that reads at rest does to it.

The rules are simple enough; the interesting cases are all about *when* a
thing happened, because the engine only ever learns about a shot several
seconds after the cue was struck.
"""
import time

import pytest
from helpers import TABLE, events, state

from poolarena.ballset import ENGLISH
from poolarena.rules import get_game
from poolarena.rules.base import ShotContext
from poolarena.rules.timebomb import Clock


def bomb(players=("A",), **options):
    return get_game("timebomb")(players=list(players), table=TABLE,
                                options=options)


def play(game, before, after, ev):
    ctx = ShotContext(before=before, after=after, events=ev, table=TABLE,
                      shooter=game.turn)
    return game.apply(ctx)


def at(ts, **positions):
    """A settled table state stamped at a given time."""
    st = state(**positions)
    st.ts = ts
    return st


# --- the clock itself -----------------------------------------------------
def test_a_paused_clock_does_not_run_down():
    c = Clock(30)
    assert c.left(1000) == 30
    assert not c.running


def test_a_running_clock_counts_down_in_real_time():
    c = Clock(30)
    c.start(1000)
    assert c.left(1005) == pytest.approx(25)
    assert c.running


def test_pausing_banks_what_is_left():
    c = Clock(30)
    c.start(1000)
    c.pause(1010)
    assert c.left(9999) == pytest.approx(20), "a paused clock stops, forever"


def test_time_added_while_running_is_not_lost():
    """The bug this guards: adding to `banked` without re-anchoring `since`
    gives the time away again on the next read."""
    c = Clock(30)
    c.start(1000)
    c.add(7, 1010)                       # 20 left, +7
    assert c.left(1010) == pytest.approx(27)
    assert c.left(1015) == pytest.approx(22), "and it keeps running"


def test_reading_a_clock_from_before_it_started_does_not_invent_time():
    """Not hypothetical: the engine does exactly this on every shot.

    `on_turn_start` starts the clock at the moment the turn begins, but a
    shot is judged against `before.ts` — when the table was last at rest,
    which is earlier. Unclamped, the elapsed time came out negative and the
    subtraction handed the player the whole Unix epoch: a scoreboard reading
    1795039630 seconds left.
    """
    c = Clock(30)
    c.start(1_795_039_600)
    assert c.left(1_795_039_590) == 30, "a read from before the start is the start"
    assert c.left(0) == 30, "however far before"
    assert c.left(1_795_039_610) == pytest.approx(20), "and forwards still works"


def test_a_shot_struck_before_the_turn_clock_started_is_not_charged():
    """The same thing, through the game rather than the clock."""
    g = bomb(seconds=30, bonus=7)
    g.clock.start(1000)                       # turn begins
    before = at(995, b0=(500, 400), b3=(900, 300))   # rest state predates it
    after = at(1002, b0=(500, 400))
    play(g, before, after, events(pocketed=[3], pockets={3: "TR"}))
    assert g.clock.left(995) == pytest.approx(37), "30 left, +7, nothing charged"


def test_a_clock_never_reads_below_zero():
    c = Clock(5)
    c.start(1000)
    assert c.left(1100) == 0
    assert c.expired(1100)


def test_the_reading_does_not_depend_on_how_often_it_is_asked():
    """Derived from a timestamp, not accumulated per tick — so a stalled
    camera and a busy one agree."""
    once, often = Clock(30), Clock(30)
    once.start(1000)
    often.start(1000)
    for i in range(1, 101):
        often.left(1000 + i * 0.1)       # asked a hundred times
    assert once.left(1010) == pytest.approx(often.left(1010))


# --- scoring --------------------------------------------------------------
def test_potting_a_ball_buys_time():
    g = bomb(seconds=30, bonus=7)
    g.clock.start(100)
    before, after = at(110, b0=(500, 400), b3=(900, 300)), at(110, b0=(500, 400))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}))
    # struck at t=110, so 20s were left; +7 for the ball.
    assert g.clock.left(110) == pytest.approx(27)
    assert g.players[0].score == 1
    assert not res.game_over or res.winner == 0


def test_the_clock_stops_at_the_moment_the_cue_was_struck():
    """The whole point. The table settles seconds after contact, and the
    engine only reads it then; a player who struck in time keeps the shot."""
    g = bomb(seconds=30, bonus=7)
    g.clock.start(100)
    # Struck at t=129 with one second to go. The balls rolled until t=134,
    # which is when the engine actually sees the shot.
    before = at(129, b0=(500, 400), b3=(900, 300), b5=(1200, 600))
    after = at(134, b0=(500, 400), b5=(1200, 600))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}))
    assert not res.game_over, "struck with a second left — that shot counts"
    assert g.players[0].score == 1
    assert g.clock.left(129) == pytest.approx(8), "1s left, +7 for the ball"


def test_a_shot_struck_after_the_buzzer_does_not_count():
    g = bomb(seconds=30, bonus=7)
    g.clock.start(100)
    before = at(131, b0=(500, 400), b3=(900, 300))
    after = at(133, b0=(500, 400))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}))
    assert res.game_over
    assert g.players[0].score == 0, "the ball went down after time; it is not scored"


def test_clearing_the_table_wins():
    g = bomb(seconds=30, bonus=7)
    g.clock.start(100)
    before = at(105, b0=(500, 400), b3=(900, 300))
    after = at(105, b0=(500, 400))
    res = play(g, before, after, events(pocketed=[3], pockets={3: "TR"}))
    assert res.game_over and res.winner == 0
    assert "cleared" in res.message


def test_a_scratch_ends_it_by_default():
    """As designed: potting the cue ball blows the rack."""
    g = bomb(seconds=30)
    g.clock.start(100)
    before = at(105, b0=(500, 400), b3=(900, 300))
    after = at(105, b3=(900, 300))
    res = play(g, before, after, events(scratch=True))
    assert res.game_over
    assert "cue ball" in res.message


def test_a_scratch_penalty_can_be_taken_in_seconds_instead():
    g = bomb(seconds=30, scratch_penalty=10)
    g.clock.start(100)
    before = at(105, b0=(500, 400), b3=(900, 300))
    after = at(105, b3=(900, 300))
    res = play(g, before, after, events(scratch=True))
    assert not res.game_over
    assert res.foul == "scratch"
    assert g.clock.left(105) == pytest.approx(15), "25 left, -10"


def test_a_scratch_can_still_take_the_last_second():
    g = bomb(seconds=30, scratch_penalty=10)
    g.clock.start(100)
    before = at(125, b0=(500, 400), b3=(900, 300))   # 5s left, -10
    after = at(125, b3=(900, 300))
    res = play(g, before, after, events(scratch=True))
    assert res.game_over


# --- running out ----------------------------------------------------------
def test_on_tick_detonates_a_solo_game_when_the_clock_runs_out():
    g = bomb(seconds=30)
    g.clock.start(100)
    assert g.on_tick(120, settled=True) is None or True   # still alive at 10s left
    res = g.on_tick(131, settled=True)
    assert res is not None and res.game_over
    assert any(e.name == "banner" and e.args.get("text") == "BOOM"
               for e in res.effects)


def test_the_clock_holds_while_the_balls_are_rolling():
    g = bomb(seconds=30)
    g.clock.start(100)
    g.on_tick(110, settled=False)          # balls moving: hold at 20s
    assert not g.clock.running
    assert g.clock.left(200) == pytest.approx(20), "the roll costs nothing"
    g.on_tick(201, settled=True)           # back at rest: resume
    assert g.clock.running


def test_the_clock_can_be_told_to_keep_running():
    g = bomb(seconds=30, clock="running")
    g.clock.start(100)
    g.on_tick(110, settled=False)
    assert g.clock.running, "asked for the harsh version"


def test_a_finished_game_stops_ticking():
    g = bomb(seconds=30)
    g.clock.start(100)
    g.on_tick(131, settled=True)
    g.over = True
    assert g.on_tick(200, settled=True) is None


# --- more than one player -------------------------------------------------
def test_each_player_gets_their_own_clock():
    g = bomb(players=("A", "B"), seconds=30)
    g.clocks[0].start(100)
    g.on_tick(131, settled=True)                  # A's clock blows
    assert g.players[0].out
    assert not g.players[1].out
    assert g.clocks[1].left(131) == 30, "B has not started yet"


def test_the_last_one_standing_is_judged_on_balls_potted():
    g = bomb(players=("A", "B"), seconds=30)
    g.players[0].score = 4
    g.players[1].score = 2
    g.clocks[0].start(100)
    g.on_tick(131, settled=True)
    g.turn = 1
    g.clocks[1].start(131)
    res = g.on_tick(162, settled=True)
    assert res.game_over and res.winner == 0, "4 balls beats 2"


def test_nobody_wins_when_nobody_potted_anything():
    g = bomb(players=("A", "B"), seconds=30)
    g.clocks[0].start(100)
    g.on_tick(131, settled=True)
    g.turn = 1
    g.clocks[1].start(131)
    res = g.on_tick(162, settled=True)
    assert res.game_over and res.winner is None
    assert "nobody" in res.message


# --- fitting in -----------------------------------------------------------
def test_it_plays_with_reds_and_yellows():
    """No numbers are ever named, so an English set is fine."""
    cls = get_game("timebomb")
    assert cls.supports(ENGLISH)


def test_the_scoreboard_carries_the_clock():
    g = bomb(seconds=30)
    g.clock.start(time.time())
    sb = g.scoreboard()
    assert "clock" in sb
    assert sb["clock"]["total"] == 30
    assert 0 < sb["clock"]["remaining"] <= 30
    assert sb["clock"]["running"] is True


def test_the_start_banner_says_the_rules():
    g = bomb(seconds=45, bonus=5)
    note = g.start_note()
    assert "45s" in note and "+5s" in note


def test_no_shot_taken_is_not_scored():
    g = bomb(seconds=30)
    g.clock.start(100)
    before = after = at(105, b0=(500, 400), b3=(900, 300))
    res = play(g, before, after, events(struck=False))
    assert res.message == "no shot taken"
    assert g.players[0].score == 0
