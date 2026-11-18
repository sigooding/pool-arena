"""Cue tracking.

The cue only exists in the frames everything else throws away, and it has to
be told apart from an arm, a shadow edge and the cushion. These tests check
the geometry on synthetic frames — which is the honest limit of what can be
checked without a real table, and the module says so.
"""
import math

import pytest

cv2 = pytest.importorskip("cv2", reason="cue tests need opencv-python")
import numpy as np

from poolarena.geometry import Table
from poolarena.vision.cue import CueTracker, aim_targets

TABLE = Table("8ft")
PPM = 0.5
W, H = int(TABLE.length * PPM), int(TABLE.width * PPM)
CUE_BALL = (700.0, 560.0)
OTHERS = [(1750.0, 330.0, (40, 40, 210)), (1200.0, 700.0, (60, 200, 245))]


def frame(angle=20.0, length=1450.0, thick=11, noise=0.0, arm=False, cue=True):
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (86, 120, 40)
    cv2.circle(img, (int(CUE_BALL[0] * PPM), int(CUE_BALL[1] * PPM)),
               int(TABLE.ball_radius * PPM), (242, 241, 247), -1)
    for bx, by, c in OTHERS:
        cv2.circle(img, (int(bx * PPM), int(by * PPM)),
                   int(TABLE.ball_radius * PPM), c, -1)
    if cue:
        a = math.radians(angle)
        tip = (CUE_BALL[0] - math.cos(a) * 90, CUE_BALL[1] - math.sin(a) * 90)
        butt = (tip[0] - math.cos(a) * length, tip[1] - math.sin(a) * length)
        cv2.line(img, (int(butt[0] * PPM), int(butt[1] * PPM)),
                 (int(tip[0] * PPM), int(tip[1] * PPM)), (150, 190, 215), thick)
    if arm:
        cv2.line(img, (int(1500 * PPM), int(60 * PPM)),
                 (int(1900 * PPM), int(500 * PPM)), (120, 105, 95), 34)
    if noise:
        rng = np.random.default_rng(2)
        img = np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape),
                      0, 255).astype(np.uint8)
    return img


def tracker():
    return CueTracker(table=TABLE, px_per_mm=PPM)


@pytest.mark.parametrize("angle", [0.0, 12.0, 25.0, -18.0, 40.0, -35.0])
def test_the_angle_is_recovered(angle):
    line = tracker().find(frame(angle), CUE_BALL)
    assert line is not None, f"no cue found at {angle}"
    assert abs(line.angle_deg - angle) < 2.0


def test_the_tip_is_the_end_near_the_cue_ball():
    line = tracker().find(frame(20.0), CUE_BALL)
    assert math.dist(line.tip, CUE_BALL) < math.dist(line.butt, CUE_BALL)


def test_nothing_is_reported_on_an_empty_table():
    """A cloth with no cue on it must not produce an aiming line."""
    assert tracker().find(frame(cue=False), CUE_BALL) is None


def test_nothing_is_reported_without_a_cue_ball():
    """Aiming means aiming at something; with no cue ball there is no line."""
    assert tracker().find(frame(20.0), None) is None


def test_an_arm_across_the_cloth_is_not_mistaken_for_a_cue():
    line = tracker().find(frame(20.0, arm=True), CUE_BALL)
    assert line is not None
    assert abs(line.angle_deg - 20.0) < 3.0, "it followed the arm, not the cue"


@pytest.mark.parametrize("label,kw", [
    ("a thin cue", {"thick": 7}),
    ("a noisy frame", {"noise": 12.0}),
    ("a short backswing", {"length": 900.0}),
])
def test_it_survives_an_imperfect_frame(label, kw):
    line = tracker().find(frame(20.0, **kw), CUE_BALL)
    assert line is not None, label
    assert abs(line.angle_deg - 20.0) < 3.0, label


def test_smoothing_damps_a_shaking_hand():
    t = tracker()
    t.find(frame(20.0), CUE_BALL)
    jittered = t.find(frame(34.0), CUE_BALL)
    assert jittered is not None
    # eased towards the new angle, not snapped to it
    assert 20.0 < jittered.angle_deg < 34.0


def test_losing_the_cue_clears_the_line_rather_than_leaving_it_up():
    t = tracker()
    assert t.find(frame(20.0), CUE_BALL) is not None
    assert t.find(frame(cue=False), CUE_BALL) is None
    assert t.last is None


# --- what the line points at ---------------------------------------------
def test_the_first_ball_on_the_line_is_found():
    line = tracker().find(frame(12.0), CUE_BALL)
    hit = aim_targets(TABLE, line, [(0, *CUE_BALL), (3, 1750, 330), (9, 1200, 700)])
    assert hit is not None and hit["ball"] == 9


def test_balls_behind_the_cue_ball_are_ignored():
    line = tracker().find(frame(12.0), CUE_BALL)
    behind = [(0, *CUE_BALL), (5, 200.0, 460.0)]
    assert aim_targets(TABLE, line, behind) is None


def test_a_line_that_hits_nothing_says_so():
    line = tracker().find(frame(-35.0), CUE_BALL)
    assert aim_targets(TABLE, line, [(0, *CUE_BALL), (3, 1750, 330)]) is None


def test_the_object_ball_leaves_along_the_line_of_centres():
    line = tracker().find(frame(12.0), CUE_BALL)
    hit = aim_targets(TABLE, line, [(0, *CUE_BALL), (9, 1200, 700)])
    start, end = hit["object_path"]
    out = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
    expected = math.degrees(math.atan2(start[1] - hit["contact"][1],
                                       start[0] - hit["contact"][0]))
    assert abs(out - expected) < 1.0
