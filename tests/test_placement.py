"""Ball in hand.

The engine could always say "ball in hand". What it could not do was notice
that the cue ball came back touching the black, or in the wrong half, or
quietly a foot further up the table than it went off.
"""
from helpers import TABLE, events, state

from poolarena.engine import Engine
from poolarena.placement import (PlacementRule, area_outline, check,
                                 d_centre, d_radius, moved_balls,
                                 nearest_legal)
from poolarena.rules.base import ShotContext
from poolarena.server.ws import Hub

OTHERS = [(600.0, 559.0), (900.0, 200.0)]


# --- the rules ------------------------------------------------------------
def test_anywhere_means_anywhere_on_the_cloth():
    r = PlacementRule("anywhere")
    assert check(TABLE, r, 1117.0, 559.0, OTHERS).ok
    assert check(TABLE, r, 100.0, 100.0, OTHERS).ok


def test_the_cue_ball_must_be_on_the_table():
    c = check(TABLE, PlacementRule(), -50.0, 559.0, OTHERS)
    assert not c.ok and "on the table" in c.reason


def test_it_may_not_be_touching_another_ball():
    near = (OTHERS[0][0] + 40.0, OTHERS[0][1])
    c = check(TABLE, PlacementRule(), *near, OTHERS)
    assert not c.ok and "touching" in c.reason
    assert c.suggestion is not None
    assert check(TABLE, PlacementRule(), *c.suggestion, OTHERS).ok


def test_baulk_rejects_the_wrong_half():
    r = PlacementRule("baulk")
    assert check(TABLE, r, 400.0, 559.0, OTHERS).ok
    bad = check(TABLE, r, 1800.0, 600.0, OTHERS)
    assert not bad.ok and "baulk" in bad.reason


def test_the_d_is_tighter_than_baulk():
    r = PlacementRule("in_d")
    cx, cy = d_centre(TABLE)
    assert check(TABLE, r, cx - 50, cy, OTHERS).ok
    outside = check(TABLE, r, 100.0, 100.0, OTHERS)
    assert not outside.ok and "D" in outside.reason


def test_a_suggestion_is_always_itself_legal():
    """A suggestion that would also be a foul is worse than none."""
    for area in ("anywhere", "baulk", "in_d"):
        r = PlacementRule(area)
        bad = check(TABLE, r, 1800.0, 600.0, OTHERS)
        if bad.ok:
            continue
        assert bad.suggestion, area
        assert check(TABLE, r, *bad.suggestion, OTHERS).ok, area


def test_a_distant_illegal_spot_still_gets_a_suggestion():
    """Spiralling out from the far end of the table would never reach baulk,
    so the search starts from the legal area instead."""
    s = nearest_legal(TABLE, PlacementRule("baulk"), 2200.0, 1050.0, OTHERS)
    assert s is not None and s[0] <= TABLE.head_string


def test_the_legal_area_can_be_drawn():
    assert area_outline(TABLE, PlacementRule("anywhere"))["kind"] == "table"
    assert area_outline(TABLE, PlacementRule("baulk"))["kind"] == "rect"
    d = area_outline(TABLE, PlacementRule("in_d"))
    assert d["kind"] == "halfcircle" and abs(d["r"] - d_radius(TABLE)) < 1e-6


def test_knocking_other_balls_while_placing_is_noticed():
    before = state(b0=(400, 600), b3=(1800, 300), b9=(900, 200)).balls
    after = state(b0=(500, 600), b3=(1860, 300), b9=(900, 200)).balls
    assert moved_balls(before, after) == [3]
    assert moved_balls(before, before) == []


# --- through the engine ---------------------------------------------------
def foul_then_place(area, put_at):
    hub = Hub()
    sent = []
    hub.broadcast = lambda m, sticky_key=None: sent.append(m)   # type: ignore
    e = Engine(table=TABLE, hub=hub, idle_after=0)
    g = e.start_game("uk8", players=["A", "B"], options={"ball_in_hand_area": area})
    g.broken = True
    g.assign(0, "solids")
    before = state(b0=(400, 600), b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    after = state(b3=(1800, 300), b11=(900, 200), b8=(1200, 500))
    res = g.apply(ShotContext(before=before, after=after,
                              events=events(scratch=True, first=3,
                                            pockets={0: "BM"}),
                              table=TABLE, shooter=0))
    assert res.ball_in_hand
    e._begin_placement(after)
    sent.clear()
    e.feed(state(b0=put_at, b3=(1800, 300), b11=(900, 200), b8=(1200, 500)))
    e.close()
    return [m for m in sent if m.get("type") == "placement"]


def test_a_legal_replacement_is_accepted():
    msgs = foul_then_place("baulk", (400.0, 600.0))
    assert msgs and msgs[-1]["ok"] is True


def test_an_illegal_replacement_is_called_out_with_a_reason():
    msgs = foul_then_place("baulk", (1800.0, 600.0))
    assert msgs and msgs[-1]["ok"] is False
    assert "baulk" in msgs[-1]["reason"]
    assert msgs[-1]["suggestion"] is not None


def test_placing_the_ball_is_not_mistaken_for_a_shot():
    """The cue ball appearing from nowhere must not read as a stroke."""
    hub = Hub()
    e = Engine(table=TABLE, hub=hub, idle_after=0)
    g = e.start_game("uk8", players=["A", "B"])
    g.broken = True
    after = state(b3=(1800, 300), b8=(1200, 500))
    e._begin_placement(after)
    shots_before = g.shot_number
    for _ in range(8):
        e.feed(state(b0=(400, 600), b3=(1800, 300), b8=(1200, 500)))
    assert g.shot_number == shots_before
    e.close()
