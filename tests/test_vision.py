"""End-to-end vision, on a synthetic overhead photograph.

This cannot tell you the detector will cope with your cloth and your lights —
only a real table can. What it does prove is that the chain holds together:
a camera that is not square to the table, a four-corner calibration, a warp,
detection, classification, and positions in millimetres that land on the balls.

Skipped when OpenCV is not installed, which is the normal state for the rules
and overlay work.
"""
import math

import pytest

cv2 = pytest.importorskip("cv2", reason="vision tests need opencv-python")
import numpy as np

from poolarena.geometry import Calibration, Table, apply_h, homography
from poolarena.vision.detect import ColorBallDetector
from poolarena.vision.pipeline import VisionPipeline

TABLE = Table("8ft")

# A camera mounted off to one side, which is the realistic case.
IMAGE_CORNERS = [(250.0, 210.0), (1700.0, 150.0), (1810.0, 915.0), (160.0, 860.0)]

LAYOUT = {0: (560, 620), 1: (1500, 380), 3: (1700, 300), 8: (1240, 560),
          11: (900, 760), 14: (1850, 840), 5: (700, 300), 12: (1300, 900)}

BGR = {0: (242, 241, 247), 1: (60, 200, 245), 2: (190, 70, 20), 3: (40, 40, 210),
       4: (140, 40, 110), 5: (30, 120, 240), 6: (70, 120, 30), 7: (40, 30, 110),
       8: (26, 26, 26)}


def synthetic_frame(uneven_light=True):
    """A 1080p photo of a table seen from an awkward angle."""
    W, H = 1920, 1080
    Hm = homography([(0, 0), (TABLE.length, 0), (TABLE.length, TABLE.width),
                     (0, TABLE.width)], IMAGE_CORNERS)
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (38, 30, 24)
    cv2.fillPoly(img, [np.array([[int(x), int(y)] for x, y in IMAGE_CORNERS], np.int32)],
                 (86, 120, 40))
    if uneven_light:
        # A pool light: hot in the middle, shadowed in the corners.
        Y, X = np.mgrid[0:H, 0:W]
        fall = np.clip(1.25 - ((X - 980) ** 2 / 900.0 ** 2 + (Y - 520) ** 2 / 520.0 ** 2),
                       0.45, 1.25)
        img = np.clip(img * fall[:, :, None], 0, 255).astype(np.uint8)
    for num, mm in LAYOUT.items():
        p = apply_h(Hm, [mm])[0]
        r = int(28.6 * 0.62)
        base = BGR[num if num < 9 else num - 8]
        c = (int(p[0]), int(p[1]))
        if num > 8:
            cv2.circle(img, c, r, (238, 240, 245), -1)
            cv2.ellipse(img, c, (r, int(r * 0.55)), 0, 0, 360, base, -1)
        else:
            cv2.circle(img, c, r, base, -1)
        cv2.circle(img, (c[0] - int(r * 0.3), c[1] - int(r * 0.35)),
                   max(1, int(r * 0.3)), (255, 255, 255), -1)
    return img


def run(cloth_model="local", normalise_light=True):
    calib = Calibration.from_corners(IMAGE_CORNERS, TABLE)
    pipe = VisionPipeline(TABLE, calib,
                          ColorBallDetector(ball_px=28.6, cloth_model=cloth_model,
                                            normalise_light=normalise_light))
    state = pipe.process(synthetic_frame())
    matched, errors = {}, []
    for b in state.balls:
        num, mm = min(LAYOUT.items(), key=lambda kv: math.dist((b.x, b.y), kv[1]))
        d = math.dist((b.x, b.y), mm)
        if d < 40:
            matched[num] = b
            errors.append(d)
    return state, matched, errors


def test_calibration_recovers_the_corners_exactly():
    calib = Calibration.from_corners(IMAGE_CORNERS, TABLE)
    assert calib.error_mm < 0.01


def test_every_ball_is_found_and_placed_within_a_ball_width():
    state, matched, errors = run()
    assert len(matched) == len(LAYOUT), f"missed {sorted(set(LAYOUT) - set(matched))}"
    assert max(errors) < 15, "a ball is 57 mm across; 15 mm is well inside it"


def test_the_local_cloth_model_beats_a_single_global_colour():
    """A pool light leaves the corners far darker than the middle, and one
    colour threshold for the whole table cannot hold across that."""
    _, local, _ = run(cloth_model="local")
    _, glob, _ = run(cloth_model="hue")
    assert len(local) >= len(glob)
    assert len(local) == len(LAYOUT), f"missed {sorted(set(LAYOUT) - set(local))}"


def test_the_local_model_also_copes_with_perfectly_even_cloth():
    """The opposite failure: dividing a flat frame by a blur of itself leaves
    hue noise, which is how an earlier version lost its own cloth."""
    import numpy as np
    flat = synthetic_frame(uneven_light=False)
    calib = Calibration.from_corners(IMAGE_CORNERS, TABLE)
    det = ColorBallDetector(ball_px=28.6, cloth_model="local")
    pipe = VisionPipeline(TABLE, calib, det)
    mask = det.cloth_mask(pipe.warp(flat))
    assert float((mask > 0).mean()) < 0.1, "most of the cloth must read as cloth"
    assert len(pipe.process(flat).balls) >= len(LAYOUT) - 1


def test_the_cue_and_the_black_are_told_apart_from_the_rest():
    _, matched, _ = run()
    assert matched[0].kind.value == "cue"
    assert matched[8].kind.value == "eight"


def test_solids_and_stripes_are_distinguished():
    _, matched, _ = run()
    assert matched[1].kind.value == "solid"
    assert matched[5].kind.value == "solid"
    assert matched[11].kind.value == "stripe"
    assert matched[12].kind.value == "stripe"
