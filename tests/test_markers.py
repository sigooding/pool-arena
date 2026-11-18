"""Calibration from printed markers.

Clicking corners is the largest error source in the system. These tests
check that four printed ArUco markers beat a careful human at it, and keep
beating them in a dim, noisy, slightly out-of-focus pool room.
"""
import math

import pytest

cv2 = pytest.importorskip("cv2", reason="marker tests need opencv-python")
import numpy as np

from poolarena.geometry import Calibration, Table, apply_h, homography
from poolarena.vision.markers import (CORNER_IDS, MarkerWatch, calibrate,
                                      find_markers, sheet)

TABLE = Table("8ft")
CORNERS = [(250.0, 210.0), (1700.0, 150.0), (1810.0, 915.0), (160.0, 860.0)]
HM = homography([(0, 0), (TABLE.length, 0), (TABLE.length, TABLE.width),
                 (0, TABLE.width)], CORNERS)
TRUTH = apply_h(HM, [(0, 0), (TABLE.length, 0), (TABLE.length, TABLE.width),
                     (0, TABLE.width)])
QUIET = 0.25        # the white paper border a real printout has


def scene(size_mm=140.0, noise=0.0, blur=0.0, dark=1.0, drop=(), shift=None):
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    img = np.zeros((1080, 1920, 3), np.uint8)
    img[:] = (38, 30, 24)
    corners = CORNERS if shift is None else [(x + shift[0], y + shift[1])
                                             for x, y in CORNERS]
    hm = homography([(0, 0), (TABLE.length, 0), (TABLE.length, TABLE.width),
                     (0, TABLE.width)], corners)
    cv2.fillPoly(img, [np.array([[int(x), int(y)] for x, y in corners], np.int32)],
                 (86, 120, 40))
    tcs = [(0, 0), (TABLE.length, 0), (TABLE.length, TABLE.width), (0, TABLE.width)]
    inward = [(1, 1), (-1, 1), (-1, -1), (1, -1)]
    for mid, tc, (dx, dy) in zip(CORNER_IDS, tcs, inward):
        if mid in drop:
            continue
        pad = int(200 * QUIET)
        paper = np.full((200 + 2 * pad, 200 + 2 * pad, 3), 255, np.uint8)
        paper[pad:pad + 200, pad:pad + 200] = cv2.cvtColor(
            cv2.aruco.generateImageMarker(d, mid, 200), cv2.COLOR_GRAY2BGR)
        total = size_mm * (1 + 2 * QUIET)
        off = pad / 200 * size_mm
        x0 = tc[0] - off if dx > 0 else tc[0] - size_mm - off
        y0 = tc[1] - off if dy > 0 else tc[1] - size_mm - off
        quad = [(x0, y0), (x0 + total, y0), (x0 + total, y0 + total), (x0, y0 + total)]
        n = paper.shape[0]
        hq = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [n, 0], [n, n], [0, n]]),
            np.float32(apply_h(hm, quad)))
        w = cv2.warpPerspective(paper, hq, (1920, 1080))
        mask = cv2.warpPerspective(np.full((n, n), 255, np.uint8), hq, (1920, 1080))
        img[mask > 0] = w[mask > 0]
    img = np.clip(img.astype(np.float32) * dark, 0, 255).astype(np.uint8)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    if noise:
        rng = np.random.default_rng(1)
        img = np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape),
                      0, 255).astype(np.uint8)
    return img


def ball_error(calib):
    exact = Calibration.from_corners([tuple(t) for t in TRUTH], TABLE)
    spots = [(x, y) for x in range(150, 2150, 250) for y in range(120, 1050, 220)]
    got = calib.to_table(exact.to_image(spots))
    errs = sorted(math.dist(g, s) for g, s in zip(got, spots))
    return errs[len(errs) // 2], errs[-1]


def test_all_four_markers_are_found():
    res = find_markers(scene())
    assert res.complete, f"missing {res.missing}"
    assert sorted(res.found) == list(CORNER_IDS)


def test_it_beats_a_careful_human_click():
    """A person clicking to within one pixel gets 1.6 mm median, 5.7 mm worst.
    This has to be at least that good to be worth the paper."""
    calib, _ = calibrate(scene(), TABLE)
    median, worst = ball_error(calib)
    assert median < 1.6
    assert worst < 5.7


@pytest.mark.parametrize("label,kw", [
    ("small markers", {"size_mm": 60.0}),
    ("dim room", {"dark": 0.4}),
    ("noisy sensor", {"noise": 14.0}),
    ("out of focus", {"blur": 2.4}),
    ("all at once", {"size_mm": 90.0, "dark": 0.5, "noise": 10.0, "blur": 1.5}),
])
def test_it_holds_up_in_a_real_pool_room(label, kw):
    calib, res = calibrate(scene(**kw), TABLE)
    assert calib is not None, f"{label}: missing {res.missing}"
    median, worst = ball_error(calib)
    assert worst < 6.0, f"{label}: {worst:.1f} mm"


def test_a_missing_marker_is_named_not_guessed():
    """Three corners cannot define the plane, and a silent bad calibration
    would be far worse than a refusal."""
    calib, res = calibrate(scene(drop=(2,)), TABLE)
    assert calib is None
    assert res.missing == [2]
    assert "bottom-right" in res.to_json()["missing_names"]


def test_the_printable_sheet_is_written_and_readable_back(tmp_path):
    out = sheet(tmp_path / "sheet.png")
    assert out.is_file()
    img = cv2.imread(str(out))
    res = find_markers(img)
    assert sorted(res.found) == list(CORNER_IDS), "the sheet must contain all four"


# --- the real payoff: a knocked camera heals itself ----------------------
def test_a_nudged_camera_is_noticed_and_re_solved():
    watch = MarkerWatch(TABLE, tolerance_px=3.0, every=1)
    assert watch.check(scene()) is not None          # first solve
    assert watch.check(scene()) is None, "a still camera should not re-solve"
    moved = watch.check(scene(shift=(14, -9)))
    assert moved is not None, "a knock must be caught"
    assert watch.updates == 2


def test_small_wobble_does_not_cause_churn():
    watch = MarkerWatch(TABLE, tolerance_px=6.0, every=1)
    watch.check(scene())
    assert watch.check(scene(shift=(1, 1))) is None


def test_the_watch_only_looks_occasionally():
    """Detecting markers every frame would be a waste; it is a slow failure."""
    watch = MarkerWatch(TABLE, every=5)
    frame = scene()
    assert [watch.check(frame) is not None for _ in range(5)] == [
        False, False, False, False, True]
