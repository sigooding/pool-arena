"""Undo has to put back everything a shot changed, not just the number.

A shot can assign ball groups, flip whose turn it is, hand out two visits,
end the frame, and re-light the zones. Anything the rewind misses shows up as
a game that is subtly wrong for the rest of the night, so these tests check
the awkward cases rather than the score alone.
"""
from helpers import TABLE, events, state

from poolarena.ballset import ENGLISH
from poolarena.engine import Engine
from poolarena.server.ws import Hub
from poolarena.types import Ball, Kind, TableState


def engine(game="8ball", players=("A", "B"), ball_set=None):
    e = Engine(table=TABLE, hub=Hub())
    if ball_set:
        e.ball_set = ball_set
    e.start_game(game, players=list(players))
    e.game.broken = True
    return e


def shoot(e, before, after, ev):
    """Drive a shot through the engine the way the detector would."""
    e.detector.reset(before)
    e.feed(before)
    moving = TableState(balls=list(after.balls), ts=before.ts + 0.1, settled=False)
    e.feed(moving)
    # the engine judges once the table is still again
    from poolarena.events.detector import SETTLE_FRAMES
    for i in range(SETTLE_FRAMES + 2):
        e.feed(TableState(balls=list(after.balls), ts=before.ts + 0.2 + i * 0.05))
    return e


OPEN = dict(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))


def apply_shot(e, before, after, ev):
    """Judge one shot directly, keeping the engine's undo bookkeeping."""
    from poolarena.rules.base import ShotContext
    snapshot = e._snapshot(e.game)
    ctx = ShotContext(before=before, after=after, events=ev, table=TABLE,
                      shooter=e.game.turn)
    result = e.game.apply(ctx)
    record = {"shot": e.game.shot_number - 1, "shooter": ctx.shooter,
              "events": ev.to_json(), "result": result.to_json()}
    e.history.append(record)
    e._undo.append((snapshot, record))
    e._redo.clear()
    return result


def test_nothing_to_undo_is_reported_not_crashed():
    e = engine()
    r = e.undo()
    assert r["ok"] is False and "nothing" in r["error"]
    assert e.redo()["ok"] is False


def test_undo_restores_the_score():
    e = engine("9ball")
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    after = state(b0=(1600, 350), b9=(900, 200))
    apply_shot(e, before, after, events(pocketed=[2], pockets={2: "TR"}, first=2))
    assert e.game.players[0].score == 1
    assert e.undo()["ok"]
    assert e.game.players[0].score == 0


def test_undo_restores_group_assignment():
    """The hardest thing to unpick by hand: an 8-ball shot that decided who
    owns which half of the table."""
    e = engine()
    before = state(**OPEN)
    after = state(b0=(1600, 350), b11=(900, 200), b8=(1200, 500))
    apply_shot(e, before, after, events(pocketed=[3], pockets={3: "TR"}, first=3))
    assert e.game.players[0].group == "solids"
    assert e.game.open_table is False

    assert e.undo()["ok"]
    assert e.game.players[0].group is None
    assert e.game.players[1].group is None
    assert e.game.open_table is True


def test_undo_restores_whose_turn_it_is():
    e = engine()
    e.game.assign(0, "solids")
    before = state(**OPEN)
    apply_shot(e, before, before, events(first=11, rails=1))     # foul
    assert e.game.turn == 1
    assert e.undo()["ok"]
    assert e.game.turn == 0


def test_undo_restores_uk_two_visit_state():
    e = engine("uk8", ball_set=ENGLISH)
    e.game.assign(0, "reds")
    before = state(**OPEN)
    apply_shot(e, before, before, events(first=11, rails=1))     # foul
    assert e.game.players[1].visits == 2
    assert e.undo()["ok"]
    assert e.game.players[1].visits == 1


def test_undo_un_ends_a_finished_frame():
    """The one that matters most: the table called the black and it was wrong."""
    e = engine()
    e.game.assign(0, "solids")
    e.game.call("TR")
    before = state(b0=(400, 600), b8=(1800, 300), b11=(900, 200))
    after = state(b0=(1600, 350), b11=(900, 200))
    apply_shot(e, before, after, events(pocketed=[8], pockets={8: "TR"}, first=8))
    assert e.game.over and e.game.winner == 0

    assert e.undo()["ok"]
    assert e.game.over is False
    assert e.game.winner is None


def test_undo_then_redo_round_trips():
    e = engine("9ball")
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    after = state(b0=(1600, 350), b9=(900, 200))
    apply_shot(e, before, after, events(pocketed=[2], pockets={2: "TR"}, first=2))
    e.undo()
    assert e.can_redo
    assert e.redo()["ok"]
    assert e.game.players[0].score == 1
    assert not e.can_redo


def test_a_new_shot_abandons_the_redo_branch():
    e = engine("9ball")
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    after = state(b0=(1600, 350), b9=(900, 200))
    apply_shot(e, before, after, events(pocketed=[2], pockets={2: "TR"}, first=2))
    e.undo()
    assert e.can_redo
    apply_shot(e, before, before, events(first=2, rails=1))
    assert not e.can_redo


def test_several_shots_undo_in_order():
    e = engine("9ball")
    # Each shot must start from the table as the previous one left it, or the
    # lowest-ball rule makes the second shot a foul and nothing is scored.
    first_before = state(b0=(400, 600), b2=(1800, 300), b4=(1000, 700), b9=(900, 200))
    first_after = state(b0=(1600, 350), b4=(1000, 700), b9=(900, 200))
    apply_shot(e, first_before, first_after,
               events(pocketed=[2], pockets={2: "TR"}, first=2))
    second_after = state(b0=(1200, 500), b9=(900, 200))
    apply_shot(e, first_after, second_after,
               events(pocketed=[4], pockets={4: "BR"}, first=4))
    assert e.game.players[0].score == 2
    e.undo()
    assert e.game.players[0].score == 1
    e.undo()
    assert e.game.players[0].score == 0
    assert not e.can_undo


def test_the_undo_stack_is_bounded():
    e = engine("9ball")
    e.undo_depth = 3
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    for _ in range(10):
        apply_shot(e, before, before, events(first=2, rails=1))
        del e._undo[:-e.undo_depth]
    assert len(e._undo) == 3


def test_undo_does_not_rewind_the_table_itself():
    """Undo fixes the score; the balls are wherever they physically are."""
    e = engine("9ball")
    before = state(b0=(400, 600), b2=(1800, 300), b9=(900, 200))
    after = state(b0=(1600, 350), b9=(900, 200))
    e.detector.resting = after
    apply_shot(e, before, after, events(pocketed=[2], pockets={2: "TR"}, first=2))
    e.undo()
    assert e.detector.resting is after


def test_the_snapshot_shares_the_table_rather_than_copying_it():
    e = engine()
    clone = e._snapshot(e.game)
    assert clone.table is TABLE
    assert clone is not e.game
    assert clone.players is not e.game.players


# --- manual correction ----------------------------------------------------
def test_score_can_be_set_by_hand():
    """Undo restores the old score but cannot know the right one; this can."""
    e = engine("9ball")
    assert e.adjust_score(0, delta=3)["score"] == 3
    assert e.game.players[0].score == 3
    assert e.adjust_score(0, delta=-1)["score"] == 2
    assert e.adjust_score(0, value=10)["score"] == 10


def test_scores_do_not_go_negative_by_accident():
    e = engine("9ball")
    assert e.adjust_score(0, delta=-5)["score"] == 0


def test_adjusting_an_unknown_player_is_refused():
    e = engine("9ball")
    r = e.adjust_score(7, delta=1)
    assert r["ok"] is False and "no player" in r["error"]
