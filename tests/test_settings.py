"""The settings on the Check tab, exercised through the service.

Through the service rather than a browser, deliberately: clicking these
controls writes to the real config, and a test that edits the config it is
run from is a test that changes the thing it is checking.
"""
import json
import shutil
from pathlib import Path

import pytest
from helpers import TABLE

from poolarena.camera import CameraService

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def svc(tmp_path):
    for name in ("table.json", "detector.json"):
        shutil.copy(REPO / "config" / name, tmp_path / name)
    return CameraService(table=TABLE, calibration_path=tmp_path / "calibration.json")


def cfg(svc, name):
    return json.loads((svc.calibration_path.parent / name).read_text())


# --- which balls ----------------------------------------------------------
def test_the_ball_set_is_written_to_both_configs(svc):
    """table.json picks the games, detector.json picks the colour model.
    Setting one and not the other scores an English rack with a seven-hue
    American classifier."""
    assert svc.set_ball_set("american")["ok"]
    assert cfg(svc, "table.json")["ball_set"] == "american"
    assert cfg(svc, "detector.json")["ball_set"] == "american"

    svc.set_ball_set("english")
    assert cfg(svc, "table.json")["ball_set"] == "english"
    assert cfg(svc, "detector.json")["ball_set"] == "english"


def test_an_unknown_ball_set_is_refused(svc):
    r = svc.set_ball_set("snooker")
    assert not r["ok"] and "english or american" in r["error"]


def test_setting_the_ball_set_keeps_the_rest_of_the_config(svc):
    before = cfg(svc, "table.json")
    svc.set_ball_set("american")
    after = cfg(svc, "table.json")
    for k, v in before.items():
        if k != "ball_set":
            assert after[k] == v, f"{k} was lost"


# --- ball size ------------------------------------------------------------
@pytest.mark.parametrize("mm", [25.4, 28.6, 26.2])
def test_a_plausible_ball_radius_is_saved(svc, mm):
    assert svc.set_ball_radius(mm)["ok"]
    assert cfg(svc, "table.json")["ball_radius"] == pytest.approx(mm)


@pytest.mark.parametrize("mm", [50.8, 0, -3, 200])
def test_a_diameter_or_nonsense_is_refused(svc, mm):
    """50.8 is the commonest: it is the diameter of an English ball."""
    r = svc.set_ball_radius(mm)
    assert not r["ok"]
    assert "radius" in r["error"]


# --- where the camera is --------------------------------------------------
def test_overhead_puts_the_nadir_at_the_table_centre(svc):
    r = svc.set_camera_position(2200, "overhead")
    assert r["ok"]
    assert r["nadir"] == [pytest.approx(TABLE.length / 2),
                          pytest.approx(TABLE.width / 2)]


def test_a_side_mount_puts_the_nadir_outside_the_cushion(svc):
    """Which is right: it is a reference point for the geometry, not a place
    a ball can be."""
    r = svc.set_camera_position(2200, "long-side", 1000)
    assert r["ok"]
    assert r["nadir"][1] == pytest.approx(-1000)
    assert r["nadir"][0] == pytest.approx(TABLE.length / 2)


def test_an_end_mount_puts_it_past_the_baulk_end(svc):
    r = svc.set_camera_position(1800, "end", 900)
    assert r["nadir"][0] == pytest.approx(-900)
    assert r["nadir"][1] == pytest.approx(TABLE.width / 2)


def test_it_reports_how_much_parallax_it_takes_out(svc):
    """The number is the point — 26 mm against a 70 mm pocket is the
    difference between a hanging ball counting and not."""
    overhead = svc.set_camera_position(2200, "overhead")["corrects_up_to_mm"]
    side = svc.set_camera_position(2200, "long-side", 1000)["corrects_up_to_mm"]
    assert 10 < overhead < 25
    assert side > overhead, "further off-centre means more to correct"


@pytest.mark.parametrize("height", [2.2, 220, 499])
def test_a_height_in_the_wrong_units_is_refused(svc, height):
    """2.2 for metres is likelier than a camera 2 mm over the cloth."""
    r = svc.set_camera_position(height, "overhead")
    assert not r["ok"]
    assert "millimetres" in r["error"]


def test_an_absurd_height_is_refused(svc):
    assert not svc.set_camera_position(12000, "overhead")["ok"]


def test_an_unknown_position_is_refused(svc):
    assert not svc.set_camera_position(2200, "ceiling")["ok"]


def test_zero_height_turns_the_correction_off_again(svc):
    svc.set_camera_position(2200, "long-side", 1000)
    assert (svc.calibration_path.parent / "cameras.json").exists()
    r = svc.set_camera_position(0, "overhead")
    assert r["ok"] and not r["enabled"]
    assert "defaults" not in cfg(svc, "cameras.json")


def test_the_saved_position_survives_a_round_trip(svc):
    svc.set_camera_position(2200, "long-side", 1000)
    saved = cfg(svc, "cameras.json")["defaults"]
    assert saved["height_mm"] == 2200
    assert saved["where"] == "long-side"
    assert saved["out_mm"] == 1000
    assert saved["nadir"] == [pytest.approx(TABLE.length / 2), -1000]


def test_a_saved_position_does_not_clobber_a_camera_list(svc):
    """cameras.json may already list two cameras; the position is a separate
    key and must not take the list with it."""
    path = svc.calibration_path.parent / "cameras.json"
    path.write_text(json.dumps({"cameras": [{"name": "a", "source": "cam:0"}]}))
    svc.set_camera_position(2200, "overhead")
    after = json.loads(path.read_text())
    assert after["cameras"] == [{"name": "a", "source": "cam:0"}]
    assert after["defaults"]["height_mm"] == 2200


# --- does any of it reach the pipeline? -----------------------------------
# The reason camera_specs had to change: cameras.json was only read when
# --source was absent, so `start.bat --source kinect` silently threw the
# saved position away — and with it the parallax correction.
class Args:
    def __init__(self, **kw):
        self.source = None
        self.cameras = None
        self.calibration = "config/calibration.json"
        self.camera_height = 0.0
        self.camera_nadir = None
        self.__dict__.update(kw)


def test_the_saved_position_is_used_when_a_source_is_given(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps(
        {"defaults": {"height_mm": 2200, "nadir": [1117.5, -1000.0],
                      "where": "long-side", "out_mm": 1000}}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)

    spec = m.camera_specs(Args(source="kinect"))[0]
    assert spec["height_mm"] == 2200, "--source must not discard the position"
    assert spec["nadir"] == [1117.5, -1000.0]


def test_the_flags_still_win_over_the_saved_position(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps(
        {"defaults": {"height_mm": 2200, "nadir": [1117.5, -1000.0]}}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)

    spec = m.camera_specs(Args(source="cam:0", camera_height=1800,
                               camera_nadir="500,600"))[0]
    assert spec["height_mm"] == 1800
    assert spec["nadir"] == [500.0, 600.0]


def test_no_saved_position_means_no_correction(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    spec = m.camera_specs(Args(source="cam:0"))[0]
    assert spec["height_mm"] == 0.0
    assert "nadir" not in spec


def test_a_full_camera_list_still_takes_priority(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps(
        {"cameras": [{"name": "kinect", "source": "kinect",
                      "calibration": "x.json", "height_mm": 2500}]}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    specs = m.camera_specs(Args())          # no --source
    assert len(specs) == 1 and specs[0]["height_mm"] == 2500


# --- depth: the half that was missing -------------------------------------
# Ball-finding in depth was written, tested, and documented in the CLI help,
# and could not be switched on by anybody: it needs config/calibration-depth
# .json and nothing in the project could produce that file. These cover the
# path that was added, so it cannot quietly become unreachable again.
import numpy as np


def depth_frame():
    """A cloth plane at 2.2 m with cushions standing proud and three balls."""
    H, W = 424, 512
    d = np.full((H, W), 6500.0, np.float32)       # beyond range = unread
    y0, y1, x0, x1 = 90, 340, 40, 470
    d[y0:y1, x0:x1] = 2200.0
    rail = 12
    d[y0:y0 + rail, x0:x1] = d[y1 - rail:y1, x0:x1] = 2130.0
    d[y0:y1, x0:x0 + rail] = d[y0:y1, x1 - rail:x1] = 2130.0
    for cx, cy in ((200, 200), (260, 180), (330, 250)):
        yy, xx = np.ogrid[:H, :W]
        d[(xx - cx) ** 2 + (yy - cy) ** 2 < 25] = 2200 - 51
    return d


class FakeKinect:
    def read(self):
        return (np.zeros((1080, 1920, 3), np.uint8), depth_frame())


class ColourOnly:
    def read(self):
        return (np.zeros((1080, 1920, 3), np.uint8), None)


def test_a_depth_frame_renders_to_something_you_can_click_on(svc):
    pytest.importorskip("cv2")
    svc.source = FakeKinect()
    shot = svc.depth_snapshot(warm=2)
    assert shot["ok"]
    assert (shot["width"], shot["height"]) == (512, 424)
    assert shot["image"].startswith("data:image/png;base64,")
    # scaled to the table's own depth range, not the sensor's whole 0.5-4.5 m,
    # or the cloth and the cushions come out the same shade
    assert 2000 < shot["near_mm"] < shot["far_mm"] < 2400


def test_unread_pixels_render_dark_not_bright(svc):
    """They used to come out white, which merged the floor around the table
    with the bright cushions and left nothing to aim a corner at."""
    cv2 = pytest.importorskip("cv2")
    import base64
    svc.source = FakeKinect()
    shot = svc.depth_snapshot(warm=2)
    raw = base64.b64decode(shot["image"].split(",", 1)[1])
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    corner = float(img[5:40, 5:30].mean())     # outside the table: unread
    rail = float(img[95:100, 100:400].mean())  # the cushion: nearest thing
    assert corner < 40, "unread has to be dark"
    assert rail > corner + 60, "and the rail has to stand out from it"


def test_a_camera_with_no_depth_says_so_usefully(svc):
    pytest.importorskip("cv2")
    svc.source = ColourOnly()
    r = svc.depth_snapshot(warm=2)
    assert not r["ok"]
    assert "kinect" in r["hint"].lower()


def test_depth_calibration_writes_its_own_file(svc):
    """Its own, not the colour one: different sensor, different field of
    view, so one homography cannot serve both."""
    r = svc.calibrate_depth([(40, 90), (470, 90), (470, 340), (40, 340)])
    assert r["ok"]
    assert Path(r["path"]).name == "calibration-depth.json"
    assert not svc.calibration_path.exists(), "the colour calibration is untouched"


def test_four_corners_are_required(svc):
    assert not svc.calibrate_depth([(0, 0), (1, 1)])["ok"]


def test_depth_status_follows_the_file(svc):
    assert not svc.depth_status()["calibrated"]
    svc.calibrate_depth([(40, 90), (470, 90), (470, 340), (40, 340)])
    assert svc.depth_status()["calibrated"]


def test_turning_depth_on_without_calibrating_warns_rather_than_lying(svc):
    r = svc.set_depth_balls(True)
    assert r["ok"] and r["depth_balls"] is True
    assert not r["calibrated"]
    assert "not calibrated" in r["note"], "it would silently do nothing"


def test_turning_depth_on_after_calibrating_is_clean(svc):
    svc.calibrate_depth([(40, 90), (470, 90), (470, 340), (40, 340)])
    r = svc.set_depth_balls(True)
    assert r["ok"] and r["calibrated"] and not r["note"]


def test_the_depth_toggle_reaches_the_run_loop(tmp_path, monkeypatch):
    """The setting is useless unless camera_specs carries it through."""
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps(
        {"defaults": {"height_mm": 2200, "depth_balls": True}}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    spec = m.camera_specs(Args(source="kinect"))[0]
    assert spec.get("depth_balls") is True


def test_depth_off_is_not_carried_through(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps(
        {"defaults": {"height_mm": 2200, "depth_balls": False}}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    assert "depth_balls" not in m.camera_specs(Args(source="kinect"))[0]


# --- which camera ---------------------------------------------------------
# `auto` opens the first camera that answers, which on a laptop is the lid.
# Anyone using a phone as a webcam — Camo, Continuity, OBS — has at least two
# and wants the second. The choice has to survive into `run`, or you pick it
# on the tablet and the next start grabs the laptop again.
def test_a_chosen_camera_is_saved(svc):
    assert svc.set_camera_source("cam:2")["ok"]
    assert cfg(svc, "cameras.json")["defaults"]["source"] == "cam:2"


def test_auto_clears_the_choice_rather_than_storing_it(svc):
    svc.set_camera_source("cam:2")
    svc.set_camera_source("auto")
    assert "source" not in cfg(svc, "cameras.json").get("defaults", {})


@pytest.mark.parametrize("spec", ["cam:0", "kinect", "video:/tmp/x.mp4"])
def test_the_real_kinds_are_accepted(svc, spec):
    assert svc.set_camera_source(spec)["ok"]


@pytest.mark.parametrize("spec", ["0", "my phone", "http://x"])
def test_nonsense_is_refused_with_the_shapes_that_work(svc, spec):
    r = svc.set_camera_source(spec)
    assert not r["ok"] and "cam:0" in r["error"]


def test_choosing_a_camera_does_not_lose_the_camera_position(svc):
    svc.set_camera_position(2200, "long-side", 1000)
    svc.set_camera_source("cam:2")
    d = cfg(svc, "cameras.json")["defaults"]
    assert d["source"] == "cam:2" and d["height_mm"] == 2200


def test_the_saved_camera_is_what_run_opens(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps({"defaults": {"source": "cam:2"}}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    assert m.camera_specs(Args())[0]["source"] == "cam:2"


def test_an_explicit_source_still_wins(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    (tmp_path / "cameras.json").write_text(json.dumps({"defaults": {"source": "cam:2"}}))
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    assert m.camera_specs(Args(source="kinect"))[0]["source"] == "kinect"


def test_with_nothing_saved_it_still_falls_back_to_auto(tmp_path, monkeypatch):
    import poolarena.__main__ as m
    monkeypatch.setattr(m, "CONFIG", tmp_path)
    assert m.camera_specs(Args())[0]["source"] == "auto"


# --- finding the camera at all --------------------------------------------
class FakeCapture:
    """Stands in for cv2.VideoCapture over a set of indices that exist."""

    present: set[int] = set()

    def __init__(self, index):
        self.index = index

    def isOpened(self):
        return self.index in self.present

    def get(self, _prop):
        return 1920

    def release(self):
        pass


def with_cameras(monkeypatch, present):
    import cv2

    from poolarena import camera

    FakeCapture.present = set(present)
    monkeypatch.setattr(cv2, "VideoCapture", FakeCapture)
    # no Kinect in the way
    monkeypatch.setattr(camera, "probe", camera.probe)
    return camera


def test_the_probe_looks_past_a_gap(monkeypatch):
    """It used to stop at the first index that would not open. A virtual
    camera — Camo, OBS, Continuity — often sits above the built-in one with
    empty indices in between, so that meant never finding the camera the
    table is actually pointed at.

    Behaviour, not the source: the first version of this test grepped for a
    variable name and passed with the bug put back.
    """
    camera = with_cameras(monkeypatch, {0, 3})
    specs = [c["spec"] for c in camera.probe()["cameras"] if c["spec"].startswith("cam:")]
    assert specs == ["cam:0", "cam:3"], "it has to keep looking past 1 and 2"


def test_the_probe_still_stops_eventually(monkeypatch):
    camera = with_cameras(monkeypatch, set())
    assert [c for c in camera.probe()["cameras"] if c["spec"].startswith("cam:")] == []


def test_a_camera_right_at_the_top_of_the_range_is_found(monkeypatch):
    camera = with_cameras(monkeypatch, {0, camera_max := 4})
    specs = [c["spec"] for c in camera.probe()["cameras"] if c["spec"].startswith("cam:")]
    assert f"cam:{camera_max}" in specs


def test_more_than_one_camera_is_called_out():
    import inspect

    from poolarena import camera

    assert "built-in" in inspect.getsource(camera.probe)
