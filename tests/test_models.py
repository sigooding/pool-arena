"""Installing a detector model.

A .pt checkpoint is a pickle, so loading one runs code from the file. None of
these tests make that safe — they check that the decision stays visible and
that the obvious ways to abuse the installer are closed.
"""
import json

from poolarena import models


# --- what may be fetched, and from where ---------------------------------
def test_plain_http_is_refused():
    ok, why = models.check_url("http://github.com/a/b/best.pt")
    assert not ok and "https" in why


def test_unknown_hosts_are_refused_with_a_way_forward():
    ok, why = models.check_url("https://evil.example.com/best.pt")
    assert not ok
    assert "not an allowed source" in why
    assert "install it from a path" in why, "a refusal should say what to do instead"


def test_github_and_hugging_face_are_allowed():
    for url in ("https://github.com/o/r/releases/download/v1/best.pt",
                "https://objects.githubusercontent.com/x/best.pt",
                "https://huggingface.co/o/m/resolve/main/best.pt"):
        ok, why = models.check_url(url)
        assert ok, why


def test_a_lookalike_host_does_not_slip_through():
    for url in ("https://github.com.evil.net/best.pt",
                "https://notgithub.com/best.pt",
                "https://evil.com/?x=github.com"):
        ok, _ = models.check_url(url)
        assert not ok, url


# --- installing from a file ----------------------------------------------
def test_installing_from_a_local_path(tmp_path):
    src = tmp_path / "best.pt"
    src.write_bytes(b"x" * 4096)
    out = models.install_model(str(src), tmp_path / "weights")
    assert out["ok"]
    assert (tmp_path / "weights" / "best.pt").is_file()
    assert "runs code when it is loaded" in out["note"]


def test_a_name_cannot_escape_the_weights_directory(tmp_path):
    src = tmp_path / "best.pt"
    src.write_bytes(b"x" * 4096)
    out = models.install_model(str(src), tmp_path / "weights",
                               name="../../etc/evil.pt")
    assert out["ok"]
    written = tmp_path / "weights" / "evil.pt"
    assert written.is_file()
    assert not (tmp_path / "etc").exists()


def test_a_missing_file_is_reported():
    out = models.install_model("/no/such/model.pt", __import__("pathlib").Path("/tmp/x"))
    assert not out["ok"] and "no file at" in out["error"]


def test_a_tiny_file_is_rejected_and_not_left_behind(tmp_path):
    src = tmp_path / "best.pt"
    src.write_bytes(b"nope")
    out = models.install_model(str(src), tmp_path / "weights")
    assert not out["ok"]
    assert not (tmp_path / "weights" / "best.pt").exists()


def test_nothing_is_installed_without_a_source(tmp_path):
    assert not models.install_model("", tmp_path)["ok"]


# --- choosing a detector --------------------------------------------------
def test_selecting_yolo_needs_a_model(tmp_path):
    cfg = tmp_path / "detector.json"
    assert not models.select_detector(cfg, "yolo")["ok"]
    assert not cfg.exists(), "a refused change must not write a config"


def test_selecting_writes_the_config_and_can_switch_back(tmp_path):
    cfg = tmp_path / "detector.json"
    assert models.select_detector(cfg, "yolo", weights="w/best.pt")["ok"]
    d = json.loads(cfg.read_text())
    assert d["detector"] == "yolo" and d["weights"] == "w/best.pt"

    assert models.select_detector(cfg, "color")["ok"]
    d = json.loads(cfg.read_text())
    assert d["detector"] == "color"
    assert d["weights"] == "w/best.pt", "keep the path so switching back is one click"


def test_existing_tuning_survives_a_detector_switch(tmp_path):
    cfg = tmp_path / "detector.json"
    cfg.write_text(json.dumps({"detector": "color", "ball_px": 41.0,
                               "cloth_tolerance": 22}))
    models.select_detector(cfg, "yolo", weights="best.pt")
    d = json.loads(cfg.read_text())
    assert d["ball_px"] == 41.0 and d["cloth_tolerance"] == 22


# --- runtime --------------------------------------------------------------
def test_runtime_reports_what_is_missing():
    rt = models.runtime().to_json()
    assert set(rt) >= {"ultralytics", "torch", "cuda", "device", "ready"}
    assert rt["install_command"] == "pip install ultralytics"
    assert rt["ready"] == (rt["ultralytics"] and rt["torch"])


def test_testing_a_model_without_the_runtime_says_so(tmp_path):
    if models.runtime().ultralytics:
        return                      # the real check is covered by test_vision
    out = models.try_model(str(tmp_path / "nope.pt"))
    assert not out["ok"]
    assert "ultralytics" in out["error"]
    assert out["install_command"]


def test_listing_installed_models(tmp_path):
    (tmp_path / "a.pt").write_bytes(b"x" * 2048)
    (tmp_path / "notes.txt").write_text("ignore me")
    found = models.list_installed(tmp_path)
    assert [m["name"] for m in found] == ["a.pt"]
    assert models.list_installed(tmp_path / "missing") == []
