import time

from poolarena.events import ShotDetector
from poolarena.geometry import Table
from poolarena.types import Ball, TableState, kind_of

TABLE = Table("8ft")


def frame(balls, ts, obstructed=False):
    return TableState(
        balls=[Ball(n, x, y, kind_of(n)) for n, x, y in balls],
        ts=ts, settled=True, obstructed=obstructed)


def run(frames):
    det = ShotDetector(TABLE)
    out = []
    for f in frames:
        w = det.push(f)
        if w:
            out.append(w)
    return out


def still(balls, t0, n=6, step=0.033):
    return [frame(balls, t0 + i * step) for i in range(n)]


def test_detects_a_pot_and_the_pocket():
    start = [(0, 400, 600), (3, 1800, 300)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 900, 500), (3, 1800, 300)], 0.1),
               frame([(0, 1500, 380), (3, 2000, 180)], 0.2),
               frame([(0, 1650, 350)], 0.3)]
    frames += still([(0, 1650, 350)], 0.4)
    windows = run(frames)
    assert len(windows) == 1
    ev = windows[0].events
    assert ev.pocketed == [3]
    assert ev.pocketed_in[3] == "TR"
    assert not ev.cue_scratched
    assert ev.first_contact == 3


def test_detects_a_scratch():
    # The cue ball has to be seen approaching the pocket. A ball that is
    # mid-table one frame and gone the next was doing about 14 m/s, which
    # does not happen, and the detector is right to disbelieve it.
    start = [(0, 400, 600), (3, 1800, 300)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 800, 520), (3, 1900, 250)], 0.10),
               frame([(0, 1050, 300), (3, 1950, 230)], 0.16),
               frame([(0, 1110, 90), (3, 1950, 230)], 0.22),
               frame([(3, 1950, 230)], 0.28)]
    frames += still([(3, 1950, 230)], 0.35)
    ev = run(frames)[0].events
    assert ev.cue_scratched, f"lost={ev.lost} unreliable={ev.unreliable!r}"
    assert ev.pocketed == []
    assert ev.pocketed_in[0] == "TM"


def test_first_contact_is_the_first_ball_to_move():
    """At 30 fps a proximity test misses the collision; motion onset does not."""
    start = [(0, 300, 560), (2, 1200, 560), (7, 1900, 560)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 700, 560), (2, 1200, 560), (7, 1900, 560)], 0.10),
               frame([(0, 1100, 560), (2, 1400, 560), (7, 1900, 560)], 0.16),  # 2 moves
               frame([(0, 1150, 560), (2, 1750, 560), (7, 2000, 560)], 0.22)]  # then 7
    frames += still([(0, 1150, 560), (2, 1750, 560), (7, 2000, 560)], 0.3)
    ev = run(frames)[0].events
    assert ev.first_contact == 2


def test_no_shot_when_nothing_moves():
    assert run(still([(0, 400, 600), (3, 1800, 300)], 0.0, 12)) == []


def test_obstruction_does_not_start_a_shot():
    base = [(0, 400, 600), (3, 1800, 300)]
    frames = still(base, 0.0, 3)
    frames.append(frame([(0, 1100, 500), (3, 1800, 300)], 0.1, obstructed=True))
    frames += still(base, 0.2, 6)
    # the obstructed frame is ignored, and the table never actually changed
    assert run(frames) == []


def test_counts_rails():
    start = [(0, 300, 560), (5, 1200, 560)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 800, 560), (5, 1200, 560)], 0.1),
               frame([(0, 1100, 560), (5, 2100, 100)], 0.2),     # 5 near top-right rail
               frame([(0, 1150, 560), (5, 2150, 20)], 0.3),
               frame([(0, 1150, 560), (5, 1800, 600)], 0.45)]
    frames += still([(0, 1150, 560), (5, 1800, 600)], 0.6)
    ev = run(frames)[0].events
    assert ev.rails_after_contact >= 1


# --- disbelieving the camera ---------------------------------------------
# A ball cannot leave the table from open cloth. When one does, the detector
# has lost it — a flicker of light, a dropped frame, a shadow — and scoring
# it as potted would clear balls nobody struck.
def test_a_blind_frame_is_not_a_cleared_table():
    start = [(0, 400, 600), (3, 1800, 300), (11, 900, 200), (8, 1200, 500)]
    frames = still(start, 0.0, 3)
    frames += [TableState(balls=[], ts=0.1 + i * 0.05, settled=True)
               for i in range(8)]
    ev = run(frames)[0].events
    assert ev.pocketed == [], "nothing was potted; the camera went blind"
    assert sorted(ev.lost) == [0, 3, 8, 11]
    assert ev.unreliable


def test_a_stationary_ball_that_blinks_out_is_not_potted():
    """Even sitting in the jaws. It never moved, so it cannot have dropped."""
    start = [(0, 400, 600), (3, 1800, 300), (7, 1000, 150)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 800, 540), (3, 1800, 300), (7, 1000, 150)], 0.10),
               frame([(0, 1200, 450), (3, 1800, 300)], 0.16)]
    frames += still([(0, 1200, 450), (3, 1800, 300), (7, 1000, 150)], 0.25)
    windows = run(frames)
    if windows:
        assert 7 not in windows[0].events.pocketed


def test_a_ball_heading_into_a_pocket_survives_a_dropped_frame():
    """Two missed frames at speed is over a quarter of a metre, so the slack
    has to follow the direction of travel rather than be a flat radius."""
    start = [(0, 400, 600), (5, 1400, 700)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 800, 640), (5, 1600, 800)], 0.10),
               frame([(0, 1000, 660), (5, 1850, 940)], 0.16),   # heading at BR
               frame([(0, 1000, 660)], 0.26)]                   # frame dropped
    frames += still([(0, 1000, 660)], 0.33)
    ev = run(frames)[0].events
    assert ev.pocketed == [5], f"lost={ev.lost} unreliable={ev.unreliable!r}"
    assert ev.pocketed_in[5] == "BR"


def test_a_ball_that_teleports_sideways_is_still_disbelieved():
    """Moving fast is not enough: it has to be moving towards the pocket."""
    start = [(0, 400, 600), (5, 1400, 560)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 800, 580), (5, 1400, 560)], 0.10),
               frame([(0, 1000, 570), (5, 1150, 560)], 0.16),   # going LEFT
               frame([(0, 1000, 570)], 0.22)]
    frames += still([(0, 1000, 570)], 0.3)
    ev = run(frames)[0].events
    assert 5 in ev.lost and ev.pocketed == []


def test_the_first_moving_frame_is_kept_in_the_trace():
    """It was being dropped, which shortened every replayed shot and left
    fast pots with a single-point path."""
    start = [(0, 400, 600), (3, 1800, 300)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 700, 560), (3, 1800, 300)], 0.10),
               frame([(0, 1100, 470), (3, 1870, 240)], 0.16),
               frame([(0, 1300, 430), (3, 1950, 180)], 0.22)]
    frames += still([(0, 1300, 430), (3, 1950, 180)], 0.3)
    ev = run(frames)[0].events
    assert len(ev.trace.get(0, [])) >= 3, ev.trace
