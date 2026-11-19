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
