"""Depth-based ball finding.

The reason this exists: colour detection fails in exactly the ways a pool
room fails — a lamp's hot centre, a player's shadow, glare on a ball. Depth
fails in none of them, because a shadow has no depth. These tests synthesise
what a Kinect v2 would return, including noise far worse than the real
sensor, and check that the balls are still found.
"""
import math

import pytest

cv2 = pytest.importorskip("cv2", reason="depth tests need opencv-python")
import numpy as np

from poolarena.geometry import Calibration, Table, apply_h, homography
from poolarena.vision.depth import ClothPlane, DepthBallFinder

TABLE = Table("8ft")
W, H = 512, 424                 # Kinect v2 depth resolution
CAM_H = 2200.0
CORNERS = [(70.0, 60.0), (452.0, 48.0), (470.0, 372.0), (52.0, 360.0)]
HM = homography([(0, 0), (TABLE.length, 0), (TABLE.length, TABLE.width),
                 (0, TABLE.width)], CORNERS)
CALIB = Calibration.from_corners(CORNERS, TABLE)
LAYOUT = {0: (420, 620), 1: (1500, 380), 3: (1950, 300), 8: (1240, 560),
          11: (900, 760), 14: (2050, 860), 5: (700, 300), 12: (1300, 900)}


def cloth(noise=3.0, seed=1):
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    d = CAM_H + (xs - W / 2) * 0.22 + (ys - H / 2) * 0.12
    return (d + rng.normal(0, noise, d.shape)).astype(np.float32)


def frame(layout=None, noise=3.0, arm=False, seed=2):
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    d = CAM_H + (xs - W / 2) * 0.22 + (ys - H / 2) * 0.12
    px_mm = 2 * CAM_H * math.tan(math.radians(35.3)) / W
    r_px = TABLE.ball_radius / px_mm
    for mm in (layout if layout is not None else LAYOUT).values():
        bx, by = apply_h(HM, [mm])[0]
        rr = np.hypot(xs - bx, ys - by)
        frac = np.clip(1 - (rr / r_px) ** 2, 0, 1)
        d[rr < r_px] -= (TABLE.ball_radius * (1 + np.sqrt(frac)))[rr < r_px]
    if arm:
        d[80:200, 300:460] -= 700.0
    return (d + rng.normal(0, noise, d.shape)).astype(np.float32)


def finder():
    f = DepthBallFinder(table=TABLE, calibration=CALIB)
    f.learn_cloth(cloth())
    return f


def matched(state, layout=None):
    layout = layout if layout is not None else LAYOUT
    hit, errs = set(), []
    for b in state.balls:
        n, mm = min(layout.items(), key=lambda kv: math.dist((b.x, b.y), kv[1]))
        d = math.dist((b.x, b.y), mm)
        if d < 60:
            hit.add(n)
            errs.append(d)
    return hit, errs


# --- the plane ------------------------------------------------------------
def test_the_cloth_plane_is_found_even_though_it_is_tilted():
    plane = ClothPlane.learn(cloth())
    resid = plane.height_map(cloth())
    assert abs(float(np.mean(resid))) < 2.0
    assert float(np.std(resid)) < 6.0


def test_balls_do_not_drag_the_plane_fit():
    """The fit happens on a table that may not be empty, so it has to reject
    the balls rather than average them in."""
    with_balls = ClothPlane.learn(frame())
    bare = ClothPlane.learn(cloth())
    h1 = with_balls.height_map(cloth())
    h2 = bare.height_map(cloth())
    assert abs(float(np.mean(h1)) - float(np.mean(h2))) < 3.0


# --- finding balls --------------------------------------------------------
def test_every_ball_is_found():
    hit, errs = matched(finder().process(depth=frame()))
    assert len(hit) == len(LAYOUT), f"missed {sorted(set(LAYOUT) - hit)}"
    assert max(errs) < 25


def test_it_survives_noise_far_worse_than_the_real_sensor():
    """A Kinect v2 is good to a few mm. Ten is pessimistic by a wide margin."""
    for noise in (1.0, 3.0, 6.0, 10.0):
        hit, _ = matched(finder().process(depth=frame(noise=noise, seed=int(noise))))
        assert len(hit) >= len(LAYOUT) - 1, f"{len(hit)}/{len(LAYOUT)} at {noise} mm"


def test_lighting_is_irrelevant():
    """The whole point. There is no illumination term anywhere in the input,
    so a shadow, a glare spot and a dark corner are all simply absent."""
    hit, _ = matched(finder().process(depth=frame()))
    assert len(hit) == len(LAYOUT)


def test_an_arm_over_the_table_reads_as_obstructed_not_as_balls():
    st = finder().process(depth=frame(arm=True))
    assert st.obstructed is True


def test_balls_are_not_named():
    """Depth has no colour. Reporting a number would be a lie."""
    st = finder().process(depth=frame())
    assert st.balls and all(b.number == -1 for b in st.balls)


def test_an_empty_table_yields_no_balls():
    st = finder().process(depth=cloth())
    assert st.balls == []


def test_detections_off_the_table_are_dropped():
    """Rails, the floor and a pint glass on the side are not balls."""
    beyond = dict(LAYOUT)
    beyond["off"] = (TABLE.length + 400, TABLE.width + 300)
    hit, _ = matched(finder().process(depth=frame(beyond)), beyond)
    assert "off" not in hit


def test_no_depth_frame_is_reported_as_obstructed():
    st = finder().process(depth=None)
    assert st.obstructed and not st.balls


# --- depth and colour together -------------------------------------------
def test_depth_rescues_balls_colour_lost_without_renaming_the_rest():
    """The arrangement that matters in a badly lit room: colour finds some of
    the balls and names them, depth finds all of them and names none."""
    from poolarena.types import Ball, Kind, TableState
    from poolarena.vision.multi import ColourAndDepth

    spots = {0: (420, 620), 1: (1500, 380), 8: (1240, 560), 11: (900, 760)}

    class Colour:
        nadir = (TABLE.length / 2, TABLE.width / 2)

        def learn_cloth(self, f):
            pass

        def process(self, color, depth=None):
            seen = [0, 1]                      # the other two are in shadow
            return TableState(balls=[Ball(n, *spots[n], Kind.SOLID, 28.6, 0.75)
                                     for n in seen], ts=1.0, settled=True)

    class Depth:
        nadir = (TABLE.length / 2, TABLE.width / 2)

        def process(self, color, depth=None):
            return TableState(balls=[Ball(-1, x + 3, y - 2, Kind.UNKNOWN, 28.6, 0.55)
                                     for x, y in spots.values()],
                              ts=1.0, settled=True)

    st = ColourAndDepth(TABLE, Colour(), Depth()).process(color=object(),
                                                          depth=object())
    assert len(st.balls) == len(spots), "every ball present, however lit"
    named = sorted(b.number for b in st.balls if b.number >= 0)
    assert named == [0, 1], "colour keeps naming the ones it could see"
    assert sum(1 for b in st.balls if b.number < 0) == 2


def test_colour_alone_still_works_when_there_is_no_depth_frame():
    from poolarena.types import Ball, Kind, TableState
    from poolarena.vision.multi import ColourAndDepth

    class Colour:
        nadir = (TABLE.length / 2, TABLE.width / 2)

        def learn_cloth(self, f):
            pass

        def process(self, color, depth=None):
            return TableState(balls=[Ball(3, 1000, 500, Kind.SOLID, 28.6, 0.8)],
                              ts=1.0, settled=True)

    class Depth:
        nadir = (TABLE.length / 2, TABLE.width / 2)

        def process(self, color, depth=None):
            raise AssertionError("must not be called without a depth frame")

    st = ColourAndDepth(TABLE, Colour(), Depth()).process(color=object(), depth=None)
    assert [b.number for b in st.balls] == [3]
