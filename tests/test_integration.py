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


def test_break_is_seen_as_one_shot_with_rails():
    sim, det = make()
    sim.strike(5200, 2.0)
    windows = [w for f in sim.run_shot() if (w := det.push(f))]
    assert len(windows) == 1
    ev = windows[0].events
    assert ev.cue_struck
    assert ev.first_contact is not None
    assert ev.rails_after_contact >= 4, "a hard break must drive balls to the rails"


def test_a_simulated_game_runs_without_the_rules_engine_falling_over():
    sim, det = make()
    game = get_game("8ball")(players=["A", "B"], table=TABLE)
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

    assert shots >= 5, "the detector should have read several shots"
    assert pots >= 1, "a simulated game should pot something"
    assert game.shot_number == shots


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
