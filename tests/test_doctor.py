"""The pre-flight check, driven by rigs that fail on purpose.

A diagnostic that only ever says "ok" is worse than none: it is read as
proof when it is really silence. So every check here is shown a rig built
to break it, and asked to notice.
"""
import pytest
from helpers import TABLE, state

from poolarena.doctor import FAIL, OK, SKIP, WARN, Doctor, report
from poolarena.types import Ball, Kind, TableState


def rack(n=16, jitter=0.0, seed=0, obstructed=False, unknown=0):
    """A settled table of n balls, optionally wobbling."""
    import random
    rng = random.Random(seed)
    balls = []
    for i in range(n):
        x = 400 + (i % 4) * 120 + (rng.uniform(-jitter, jitter) if jitter else 0)
        y = 300 + (i // 4) * 120 + (rng.uniform(-jitter, jitter) if jitter else 0)
        kind = Kind.UNKNOWN if i < unknown else (Kind.CUE if i == 0 else Kind.SOLID)
        balls.append(Ball(i, x, y, kind, confidence=0.9))
    return TableState(balls=balls, settled=True, obstructed=obstructed)


class FakeRig:
    """Stands in for MultiPipeline. No camera, no numpy, no pipelines."""

    def __init__(self, states, fail_after=None, error=False):
        self._states = states
        self._i = 0
        self.fail_after = fail_after
        self.error = error
        self.views = []

    def read(self):
        i, self._i = self._i, self._i + 1
        if self.error:
            raise OSError("camera gone")
        if self.fail_after is not None and i >= self.fail_after:
            return None
        return self._states[i % len(self._states)]

    def close(self):
        pass


def find(checks, name):
    return next(c for c in checks if c.name == name)


# --- the source -----------------------------------------------------------
def test_a_camera_that_never_opens_fails_and_stops_there():
    checks = Doctor(TABLE, FakeRig([], error=True), 16, frames=5).run()
    assert find(checks, "source").status == FAIL
    # And nothing downstream pretends to know anything.
    for name in ("cloth", "balls", "stability"):
        assert find(checks, name).status == SKIP, name


def test_the_source_check_counts_dropped_frames():
    checks = Doctor(TABLE, FakeRig([rack()], fail_after=3), 16, frames=10).run()
    src = find(checks, "source")
    assert src.numbers["frames"] == 3
    assert src.numbers["dropped"] == 7


def test_a_healthy_rig_passes_the_source_check():
    checks = Doctor(TABLE, FakeRig([rack()]), 16, frames=30).run()
    assert find(checks, "source").status == OK


# --- balls ----------------------------------------------------------------
def test_missing_balls_are_a_failure_not_a_warning():
    """The case that matters: balls the camera cannot see get scored as
    potted, so this must shout."""
    checks = Doctor(TABLE, FakeRig([rack(n=12)]), 16, frames=20).run()
    b = find(checks, "balls")
    assert b.status == FAIL
    assert b.numbers["found"] == 12 and b.numbers["expected"] == 16


def test_a_full_rack_passes():
    checks = Doctor(TABLE, FakeRig([rack()]), 16, frames=20).run()
    assert find(checks, "balls").status == OK


def test_an_unsteady_count_warns_even_when_the_median_is_right():
    frames = [rack(16), rack(16), rack(15), rack(16), rack(16), rack(15)]
    checks = Doctor(TABLE, FakeRig(frames), 16, frames=24).run()
    assert find(checks, "balls").status == WARN


def test_no_balls_at_all_says_so_plainly():
    checks = Doctor(TABLE, FakeRig([TableState(balls=[], settled=True)]),
                    16, frames=10).run()
    b = find(checks, "balls")
    assert b.status == FAIL
    assert "no balls" in b.detail


# --- stability ------------------------------------------------------------
def test_a_still_table_reads_as_still():
    checks = Doctor(TABLE, FakeRig([rack()]), 16, frames=30).run()
    s = find(checks, "stability")
    assert s.status == OK
    assert s.numbers["worst_mm"] == pytest.approx(0, abs=0.01)


def test_jittering_balls_are_caught():
    """The number that predicts phantom shots all evening."""
    frames = [rack(jitter=12, seed=i) for i in range(12)]
    checks = Doctor(TABLE, FakeRig(frames), 16, frames=12).run()
    s = find(checks, "stability")
    assert s.status == FAIL
    assert s.numbers["worst_mm"] > 8


def test_mild_jitter_only_warns():
    frames = [rack(jitter=4, seed=i) for i in range(12)]
    checks = Doctor(TABLE, FakeRig(frames), 16, frames=12).run()
    assert find(checks, "stability").status in (OK, WARN)


# --- colour and view ------------------------------------------------------
def test_unidentifiable_balls_fail_the_colour_check():
    checks = Doctor(TABLE, FakeRig([rack(unknown=3)]), 16, frames=10).run()
    assert find(checks, "colour separation").status == FAIL


def test_a_blocked_view_is_reported():
    checks = Doctor(TABLE, FakeRig([rack(obstructed=True)]), 16, frames=10).run()
    v = find(checks, "view")
    assert v.status == FAIL
    assert v.numbers["obstructed_frames"] == 10


def test_an_occasional_lean_over_the_table_only_warns():
    frames = [rack(), rack(), rack(), rack(), rack(), rack(),
              rack(), rack(obstructed=True), rack(obstructed=True), rack()]
    checks = Doctor(TABLE, FakeRig(frames), 16, frames=10).run()
    assert find(checks, "view").status == WARN, "2 frames in 10 is a lean, not a fault"


def test_one_frame_in_ten_obstructed_is_not_worth_mentioning():
    frames = [rack()] * 9 + [rack(obstructed=True)]
    checks = Doctor(TABLE, FakeRig(frames), 16, frames=10).run()
    assert find(checks, "view").status == OK


# --- the report -----------------------------------------------------------
def test_the_report_leads_with_the_worst_news():
    checks = Doctor(TABLE, FakeRig([rack(n=10)]), 16, frames=10).run()
    out = report(checks, "test")
    assert "Not ready" in out
    assert "FAIL" in out


def test_a_clean_report_says_ready():
    checks = Doctor(TABLE, FakeRig([rack()]), 16, frames=20).run()
    out = report(checks)
    assert "Ready" in out
    assert "FAIL" not in out


def test_every_failure_carries_something_to_do_about_it():
    """A diagnostic that names a problem and not a remedy just relocates the
    confusion."""
    for rig in (FakeRig([rack(n=9)]),
                FakeRig([rack(jitter=20, seed=i) for i in range(12)]),
                FakeRig([rack(obstructed=True)]),
                FakeRig([rack(unknown=4)])):
        for c in Doctor(TABLE, rig, 16, frames=12).run():
            if c.status in (FAIL, WARN):
                assert c.remedy, f"{c.name} says what is wrong but not what to do"


def test_the_report_prints_the_remedy_only_when_it_is_needed():
    good = report(Doctor(TABLE, FakeRig([rack()]), 16, frames=20).run())
    bad = report(Doctor(TABLE, FakeRig([rack(n=8)]), 16, frames=20).run())
    assert len(bad.splitlines()) > len(good.splitlines())


# --- the checks that need real pipeline objects ---------------------------
# The rig above has no views at all, which is why it never noticed that the
# calibration check was reading an attribute that does not exist: the check
# silently skipped on every real table instead of reporting anything.
class FakeCalib:
    def __init__(self, error_mm):
        self.error_mm = error_mm


class FakePipe:
    def __init__(self, error_mm, name="cam"):
        self.calib = FakeCalib(error_mm)
        self.name = name
        self.last_warped = None
        self.detector = None


class FakeView:
    def __init__(self, pipeline):
        self.pipeline = pipeline


class FakeDepthWrapper:
    """ColourAndDepth holds its colour pipeline in `.colour`."""
    def __init__(self, colour):
        self.colour = colour


class RigWithViews(FakeRig):
    def __init__(self, states, pipelines):
        super().__init__(states)
        self.views = [FakeView(p) for p in pipelines]


def test_the_calibration_check_actually_runs():
    """It reads `calib`, which is what the pipeline calls it."""
    rig = RigWithViews([rack()], [FakePipe(2.1)])
    c = find(Doctor(TABLE, rig, 16, frames=10).run(), "calibration")
    assert c.status == OK, "a 2.1 mm calibration is a good one"
    assert c.numbers["worst_rms_mm"] == pytest.approx(2.1)


def test_a_bad_calibration_fails_loudly():
    rig = RigWithViews([rack()], [FakePipe(22.0)])
    c = find(Doctor(TABLE, rig, 16, frames=10).run(), "calibration")
    assert c.status == FAIL
    assert "markers" in c.remedy, "and points at the fix that actually works"


def test_the_worst_of_two_cameras_is_the_one_reported():
    rig = RigWithViews([rack()], [FakePipe(1.0, "a"), FakePipe(9.0, "b")])
    c = find(Doctor(TABLE, rig, 16, frames=10).run(), "calibration")
    assert c.numbers["camera"] == "b"
    assert c.status == WARN


def test_a_depth_wrapped_pipeline_is_still_inspected():
    """With --depth-balls the colour pipeline is one level down."""
    rig = RigWithViews([rack()], [FakeDepthWrapper(FakePipe(19.0, "kinect"))])
    c = find(Doctor(TABLE, rig, 16, frames=10).run(), "calibration")
    assert c.status == FAIL, "the wrapper must not hide a bad calibration"
    assert c.numbers["camera"] == "kinect"


# --- ball size: the wrong set in the cupboard -----------------------------
# Two sets of balls and one config is an easy way to get a quiet, miserable
# fault: American balls are 2.25 inches and English are 2, and the detector
# does not measure — it is told how big a ball is and reads each one's colour
# from a patch that size. Tell it the wrong size and every patch picks up a
# ring of cloth. Nothing errors; the scoring just gets worse.
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")


def table_photo(ball_radius_mm, corners, table, bgr, layout):
    from poolarena.geometry import apply_h, homography
    W, H = 1920, 1080
    Hm = homography([(0, 0), (table.length, 0),
                     (table.length, table.width), (0, table.width)], corners)
    img = np.zeros((H, W, 3), np.uint8)
    img[:] = (38, 30, 24)
    cv2.fillPoly(img, [np.array([[int(x), int(y)] for x, y in corners], np.int32)],
                 (86, 120, 40))
    scale = abs(corners[1][0] - corners[0][0]) / table.length
    for num, mm in layout.items():
        p = apply_h(Hm, [mm])[0]
        cv2.circle(img, (int(p[0]), int(p[1])),
                   max(2, int(ball_radius_mm * scale)),
                   bgr[num if num < 9 else num - 8], -1)
    return img


class OneCameraRig:
    def __init__(self, pipe, img):
        self.views = [FakeView(pipe)]
        self._pipe, self._img = pipe, img

    def read(self):
        return self._pipe.process(self._img)

    def close(self):
        pass


def size_check(configured_mm, real_mm):
    from test_vision import BGR, IMAGE_CORNERS, LAYOUT
    from poolarena.geometry import Table
    from poolarena.vision.calibrate import Calibration
    from poolarena.vision.detect import ColorBallDetector, ball_px_for
    from poolarena.vision.pipeline import VisionPipeline

    t = Table("8ft")
    t.ball_radius = configured_mm
    pipe = VisionPipeline(t, Calibration.from_corners(IMAGE_CORNERS, t),
                          ColorBallDetector(ball_px=ball_px_for(t, 0.5),
                                            cloth_model="local"))
    img = table_photo(real_mm, IMAGE_CORNERS, t, BGR, LAYOUT)
    checks = Doctor(t, OneCameraRig(pipe, img), 8, frames=4).run()
    return find(checks, "ball size")


def test_the_right_balls_for_the_config_pass():
    assert size_check(28.6, 28.6).status == OK
    assert size_check(25.4, 25.4).status == OK


def test_english_balls_under_an_american_config_are_caught():
    c = size_check(28.6, 25.4)
    assert c.status == FAIL
    assert "25.4" in c.remedy, "and it says what to set it to"
    assert c.numbers["looks_like"].startswith("English")


def test_american_balls_under_an_english_config_are_caught():
    c = size_check(25.4, 28.6)
    assert c.status == FAIL
    assert "28.6" in c.remedy
    assert c.numbers["looks_like"].startswith("American")


def test_the_measurement_is_accurate_enough_to_name_the_set():
    """The mask is opened and closed before anything is counted, which shaves
    about 4% off every blob. That is compensated; this is what pins it."""
    for real in (25.4, 28.6):
        c = size_check(real, real)
        assert c.numbers["measured_radius_mm"] == pytest.approx(real, abs=0.6)


def test_it_says_so_rather_than_guessing_when_it_cannot_measure():
    checks = Doctor(TABLE, FakeRig([rack()]), 16, frames=10).run()
    assert find(checks, "ball size").status == SKIP
