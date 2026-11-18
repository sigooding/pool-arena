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
    start = [(0, 400, 600), (3, 1800, 300)]
    frames = still(start, 0.0, 3)
    frames += [frame([(0, 1200, 450), (3, 1900, 250)], 0.1),
               frame([(3, 1950, 230)], 0.2)]
    frames += still([(3, 1950, 230)], 0.3)
    ev = run(frames)[0].events
    assert ev.cue_scratched
    assert ev.pocketed == []


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
