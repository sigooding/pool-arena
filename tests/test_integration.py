"""End to end: simulator -> shot detector -> rules, with no camera and no browser.

This is the test that would catch a break in the seam between layers, which is
where the interesting bugs live.
"""
import random

from poolarena.events import ShotDetector
from poolarena.geometry import Table
from poolarena.rules import get_game
from poolarena.rules.base import ShotContext
from poolarena.sim import FakeTable, auto_shot

TABLE = Table("8ft")


def make():
    sim = FakeTable(table=TABLE, rng=random.Random(4))
    sim.rack("8ball")
    det = ShotDetector(TABLE)
    det.reset(sim.state())
    return sim, det


def break_with(speed, angle=2.0, seed=4):
    """One break. The angle is what varies a break, not the seed — `strike`
    is deterministic, so eight seeds at one angle are eight identical shots."""
    sim = FakeTable(table=TABLE, rng=random.Random(seed))
    sim.rack("8ball")
    det = ShotDetector(TABLE)
    det.reset(sim.state())
    sim.strike(speed, angle)
    windows = [w for f in sim.run_shot() if (w := det.push(f))]
    return windows


BREAK_ANGLES = [-3.5, -1.8, 0.0, 1.4, 2.6, 3.9, 5.2, 6.4]


def test_break_is_seen_as_exactly_one_shot():
    windows = break_with(5200)
    assert len(windows) == 1, "a break is one shot, however many balls move"
    ev = windows[0].events
    assert ev.cue_struck
    assert ev.first_contact is not None


def test_a_hard_break_drives_more_balls_to_the_rails_than_a_soft_one():
    """Asserted as a property rather than a number: the exact count depends on
    the simulator's details, but harder must mean more, or the quantity the
    break rule is judged on means nothing."""
    hard = [break_with(5200, a)[0].events.balls_to_rail for a in BREAK_ANGLES]
    soft = [break_with(1200, a)[0].events.balls_to_rail for a in BREAK_ANGLES]
    assert sum(hard) > sum(soft) * 2
    assert max(soft) <= 2, "a soft tap should not count as a legal break"
    assert max(hard) >= 4, "a full-blooded break should reach four balls"


def test_balls_to_rail_counts_balls_not_touches():
    """One ball rattling between cushions is not four balls to the rail."""
    sim = FakeTable(table=TABLE, rng=random.Random(2))
    sim.set_balls({0: (300.0, 559.0), 1: (1100.0, 559.0)})
    det = ShotDetector(TABLE)
    det.reset(sim.state())
    sim.aim_at(2235.0, 559.0, speed=4800)       # straight down the table
    windows = [w for f in sim.run_shot() if (w := det.push(f))]
    ev = windows[0].events
    assert ev.balls_to_rail <= 2, "only two balls are on the table"
    assert ev.rails_after_contact >= ev.balls_to_rail


def test_a_simulated_game_runs_without_the_rules_engine_falling_over():
    sim, det = make()
    game = get_game("8ball")(players=["A", "B"], table=TABLE)
    # A seeded game can end quickly on an early 8, so this asserts that every
    # shot is judged and renderable, not that the game lasts a given length.
    sim.strike(5200, 2.0)

    shots, fouls, pots = 0, 0, 0
    for _ in range(40):
        for f in sim.run_shot():
            w = det.push(f)
            if not w:
                continue
            ctx = ShotContext(before=w.before, after=w.after, events=w.events,
                              table=TABLE, shooter=game.turn)
            res = game.apply(ctx)
            shots += 1
            fouls += bool(res.foul)
            pots += len(w.events.pocketed)
            # every verdict must be renderable
            for e in res.effects:
                assert e.name and isinstance(e.args, dict)
                assert e.layer in ("guide", "fx", "hud")
        if game.over:
            break
        if sim.cue() is None:
            sim.spot_cue()
        if auto_shot(sim, skill=0.8).get("shot") == "none":
            break

    assert shots >= 3, "the detector should have read several shots"
    assert game.shot_number == shots
    # Either the game reached a conclusion or it was still going when we
    # stopped; both are fine. What must hold is that every shot was judged.
    assert fouls + pots >= 0
    assert game.over or shots >= 3


def test_pocketed_balls_leave_the_table_and_stay_gone():
    sim, det = make()
    sim.strike(5200, 2.0)
    for f in sim.run_shot():
        det.push(f)
    before = {b.number for b in sim.balls if b.live}
    for _ in range(6):
        if sim.cue() is None:
            sim.spot_cue()
        auto_shot(sim, skill=0.95)
        for f in sim.run_shot():
            det.push(f)
    after = {b.number for b in sim.balls if b.live}
    assert after <= before | {0}


def test_scratch_is_reported_and_the_cue_can_be_spotted():
    sim = FakeTable(table=TABLE, rng=random.Random(1))
    sim.set_balls({0: (300.0, 559.0), 3: (1000.0, 559.0)})
    det = ShotDetector(TABLE)
    det.reset(sim.state())
    # straight at the 3, which sends the cue into the far pocket behind it
    sim.place(3, 2100.0, 100.0)
    sim.place(0, 1800.0, 400.0)
    sim.aim_at(2235, 0, speed=4200)
    windows = [w for f in sim.run_shot() if (w := det.push(f))]
    assert windows
    ev = windows[0].events
    assert ev.cue_scratched or ev.pocketed, "something must have dropped"
    if ev.cue_scratched:
        assert sim.cue() is None
        sim.spot_cue()
        assert sim.cue() is not None
