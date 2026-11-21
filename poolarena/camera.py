"""Camera discovery, snapshots and calibration, driven from the browser.

The command-line calibrator opens an OpenCV window and wants four clicks. That
is fine if you are already in a terminal, and useless if you are not. This
module puts the same job behind the web UI: probe for a camera, hand the
browser a still, take four clicked corners back, solve the homography and save
it. No terminal, no Python.

Everything here is lazy. The camera is only opened when someone asks for a
frame, so running the simulator does not fight the live system for the device.
"""
from __future__ import annotations

import base64
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .geometry import Calibration, Table


#: How far up the indices to look for a camera.
MAX_CAMERA_INDEX = 8
#: Stop after this many empty indices in a row.
CAMERA_SCAN_GIVE_UP = 4


def probe() -> dict[str, Any]:
    """What camera, if any, is plugged in — without claiming it.

    Ordered by preference: a Kinect v2 is better than a random webcam, and a
    webcam is better than nothing.
    """
    found: list[dict[str, Any]] = []

    kinect_backend = None
    try:
        from .vision.source import KinectV2Source
        kinect_backend = KinectV2Source._pick_backend()
    except Exception:
        kinect_backend = "none"
    if kinect_backend and kinect_backend != "none":
        found.append({
            "spec": "kinect",
            "label": f"Kinect v2 ({kinect_backend})",
            "backend": kinect_backend,
        })

    try:
        import cv2
        try:                        # probing absent indices is noisy otherwise
            cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
        except Exception:
            pass
        # Keep looking past a gap. Indices are not contiguous on Windows — a
        # virtual camera like Camo or OBS often sits above the built-in one
        # with nothing in between, and stopping at the first miss means never
        # finding the camera the table is actually pointed at. Bounded by a
        # run of empties rather than a hard limit, because opening a missing
        # index is slow.
        misses = 0
        for index in range(MAX_CAMERA_INDEX + 1):
            cap = cv2.VideoCapture(index)
            ok = cap.isOpened()
            if ok:
                misses = 0
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                found.append({"spec": f"cam:{index}",
                              "label": f"Camera {index} ({w}x{h})" if w else f"Camera {index}",
                              "backend": "opencv"})
            else:
                misses += 1
            cap.release()
            if misses >= CAMERA_SCAN_GIVE_UP:
                break
    except ImportError:
        return {"cameras": found, "opencv": False,
                "hint": "OpenCV is not installed, so cameras cannot be opened. "
                        "Install it with: pip install opencv-python"}
    except Exception as exc:
        return {"cameras": found, "opencv": True, "hint": str(exc)}

    hint = ""
    if len(found) > 1:
        hint = ("More than one camera. `auto` takes the first, which is "
                "usually the built-in one — pick the right one below if the "
                "picture is of your laptop lid.")
    if not found:
        hint = ("No camera detected. For a Kinect v2: check it is on a USB 3 "
                "port with its power supply, and that the driver is installed "
                "(Kinect for Windows SDK 2.0 plus pykinect2, or libfreenect2 "
                "plus pylibfreenect2 on Linux). See docs/HARDWARE.md.")
    return {"cameras": found, "opencv": True, "hint": hint}


@dataclass
class CameraService:
    """Holds at most one open camera, and the calibration for it."""

    table: Table
    calibration_path: Path
    source: Any = None
    spec: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    last_error: str = ""

    # --- lifecycle ---------------------------------------------------------
    def open(self, spec: str = "auto") -> dict[str, Any]:
        from .vision.source import open_source
        with self._lock:
            self.close_locked()
            if spec == "auto":
                cams = probe().get("cameras", [])
                if not cams:
                    self.last_error = "no camera detected"
                    return {"ok": False, "error": self.last_error}
                spec = cams[0]["spec"]
            try:
                self.source = open_source(spec)
                self.spec = spec
                self.last_error = ""
                return {"ok": True, "spec": spec, "name": self.source.name}
            except Exception as exc:
                self.last_error = str(exc)
                self.source = None
                return {"ok": False, "error": self.last_error}

    def close_locked(self) -> None:
        if self.source is not None:
            try:
                self.source.close()
            except Exception:
                pass
            self.source = None

    def close(self) -> None:
        with self._lock:
            self.close_locked()

    # --- frames ------------------------------------------------------------
    def snapshot(self, warm: int = 12) -> tuple[bytes | None, dict[str, Any]]:
        """A JPEG of the current view, plus its real pixel size.

        `warm` frames are pulled first: webcams and the Kinect both need a
        moment for auto-exposure to settle, and calibrating against a dark
        first frame is how you end up clicking the wrong corners.
        """
        import cv2
        with self._lock:
            if self.source is None:
                return None, {"error": "camera not open"}
            frame = None
            for _ in range(max(1, warm)):
                got = self.source.read()
                if got and got[0] is not None:
                    frame = got[0]
            if frame is None:
                return None, {"error": "no frame from camera"}
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if not ok:
                return None, {"error": "could not encode frame"}
            h, w = frame.shape[:2]
            return buf.tobytes(), {"width": w, "height": h}

    def snapshot_json(self) -> dict[str, Any]:
        blob, meta = self.snapshot()
        if blob is None:
            return {"ok": False, **meta}
        return {
            "ok": True,
            "width": meta["width"],
            "height": meta["height"],
            "image": "data:image/jpeg;base64," + base64.b64encode(blob).decode(),
        }

    # --- pre-flight --------------------------------------------------------
    def run_check(self, frames: int = 40, expect: int = 16,
                  detector_cfg: dict | None = None) -> dict[str, Any]:
        """The same checks as `python -m poolarena doctor`, from the browser.

        Reuses whichever camera the Camera tab already opened, so the person
        setting up a table does not have to find a terminal to answer "is
        this going to work" — which is the question they actually have, and
        the one the tablet is in their hands for.
        """
        from .doctor import Doctor
        from .vision.calibrate import Calibration
        from .vision.detect import build_detector
        from .vision.pipeline import VisionPipeline

        if self.source is None:
            return {"ok": False, "error": "camera not open",
                    "hint": "Connect the camera first, on the Camera tab."}
        if not self.calibration_path.exists():
            return {"ok": False, "error": "no calibration",
                    "hint": "Calibrate the camera first — the printed "
                            "markers are the quick way."}
        try:
            calib = Calibration.load(self.calibration_path)
        except Exception as exc:
            return {"ok": False, "error": f"calibration will not load: {exc}"}

        pipe = VisionPipeline(self.table, calib,
                              build_detector(detector_cfg or {}, self.table),
                              name=self.spec or "camera")

        service = self

        class _Rig:
            """One camera, read under the service's lock."""
            views = [type("V", (), {"pipeline": pipe})()]

            def read(self):
                with service._lock:
                    if service.source is None:
                        return None
                    got = service.source.read()
                if not got or got[0] is None:
                    return None
                return pipe.process(got[0], got[1] if len(got) > 1 else None)

        checks = Doctor(self.table, _Rig(), expected_balls=expect,
                        frames=frames).run()
        return {
            "ok": True,
            "ready": not any(c.status == "fail" for c in checks),
            "checks": [{"name": c.name, "status": c.status,
                        "detail": c.detail, "remedy": c.remedy,
                        "numbers": {k: (round(v, 2) if isinstance(v, float) else v)
                                    for k, v in c.numbers.items()}}
                       for c in checks],
        }

    def set_ball_radius(self, mm: float) -> dict[str, Any]:
        """Write the ball size to config/table.json.

        A caliper beats the camera: the measurement in the pre-flight is good
        to under a millimetre, which is enough to tell the two standard sets
        apart but not as good as just measuring one. Either way it has to end
        up in the config, and editing JSON by hand on the night is exactly
        the kind of friction that loses an evening.
        """
        if not 15.0 <= mm <= 40.0:
            return {"ok": False,
                    "error": f"{mm:g} mm is not a pool ball. "
                             "English balls are 25.4, American 28.6 — and "
                             "this is the radius, not the diameter."}
        path = self.calibration_path.parent / "table.json"
        try:
            cfg = json.loads(path.read_text()) if path.exists() else {}
        except ValueError as exc:
            return {"ok": False, "error": f"config/table.json will not parse: {exc}"}
        was = cfg.get("ball_radius")
        cfg["ball_radius"] = round(float(mm), 2)
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        # The live pipeline sized its detector at startup, so this takes
        # effect next time it runs. Say so rather than letting someone
        # wonder why nothing changed.
        return {"ok": True, "was": was, "now": cfg["ball_radius"],
                "restart_needed": True}

    def set_ball_set(self, name: str) -> dict[str, Any]:
        """Reds and yellows, or numbered and striped.

        Written to both configs on purpose. table.json decides which games
        are playable; detector.json decides which colour model reads the
        cloth. Setting one and not the other is how you end up with an
        English rack being scored by a seven-hue American classifier.
        """
        name = str(name).strip().lower()
        if name not in ("english", "american"):
            return {"ok": False,
                    "error": f"no such ball set {name!r} — english or american"}
        cfgdir = self.calibration_path.parent
        for fname, key in (("table.json", "ball_set"),
                           ("detector.json", "ball_set")):
            path = cfgdir / fname
            try:
                cfg = json.loads(path.read_text()) if path.exists() else {}
            except ValueError as exc:
                return {"ok": False, "error": f"config/{fname} will not parse: {exc}"}
            cfg[key] = name
            path.write_text(json.dumps(cfg, indent=2) + "\n")
        return {"ok": True, "ball_set": name, "restart_needed": True}

    def set_camera_source(self, spec: str) -> dict[str, Any]:
        """Remember which camera to open.

        Saved rather than left in the browser, because the choice has to
        survive into `run` — otherwise you pick the phone on the tablet and
        the next start grabs the laptop lid again.
        """
        spec = str(spec or "").strip()
        if spec and spec != "auto" and not spec.startswith(("cam:", "kinect", "video:")):
            return {"ok": False, "error": f"{spec!r} is not a camera: "
                                          "auto, cam:0, kinect or video:path"}
        path = self.calibration_path.parent / "cameras.json"
        try:
            cfg = json.loads(path.read_text()) if path.exists() else {}
        except ValueError as exc:
            return {"ok": False, "error": f"config/cameras.json will not parse: {exc}"}
        defaults = cfg.setdefault("defaults", {})
        if not spec or spec == "auto":
            defaults.pop("source", None)
        else:
            defaults["source"] = spec
        if not defaults:
            cfg.pop("defaults", None)
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        return {"ok": True, "source": spec or "auto"}

    def set_camera_position(self, height_mm: float, where: str = "overhead",
                            out_mm: float = 0.0) -> dict[str, Any]:
        """Where the camera is, so parallax can be taken out.

        Given as a place and a distance rather than as coordinates, because
        nobody mounting a camera on a Saturday wants to work out that the
        point under the lens is at x=1117, y=-1000. The arithmetic is here.

        A ball's centre sits one radius above the cloth, so the camera sees
        it pushed outward from the point directly beneath the lens. Knowing
        the height and that point removes it exactly — 26 mm to nothing on a
        side mount. Not knowing them leaves it, and 26 mm against a 70 mm
        pocket capture radius decides whether a hanging ball counts.
        """
        places = ("overhead", "long-side", "end")
        if where not in places:
            return {"ok": False, "error": f"where must be one of {places}"}
        try:
            height_mm = float(height_mm)
            out_mm = float(out_mm or 0.0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "height and distance must be numbers"}

        # The floor is here to catch a unit mistake, not to be a physical
        # limit: someone typing 2.2 for metres, or 220 for centimetres, is
        # far likelier than someone genuinely mounting a camera half a metre
        # over the cloth — and either would silently ruin the correction.
        if 0 < height_mm < 500:
            return {"ok": False,
                    "error": f"{height_mm:g} is too low to be a camera height. "
                             "This is millimetres above the cloth, so about "
                             "2200 for a ceiling mount — not metres."}
        if height_mm > 10000:
            return {"ok": False,
                    "error": f"{height_mm:g} mm is over ten metres. "
                             "Millimetres above the cloth, not from the floor "
                             "of the building."}

        L, W = self.table.length, self.table.width
        if where == "overhead":
            nadir = [L / 2, W / 2]
        elif where == "long-side":
            # Outside the cushion, which is fine: it is a reference point for
            # the geometry, not somewhere a ball can be.
            nadir = [L / 2, -abs(out_mm)]
        else:
            nadir = [-abs(out_mm), W / 2]

        path = self.calibration_path.parent / "cameras.json"
        try:
            cfg = json.loads(path.read_text()) if path.exists() else {}
        except ValueError as exc:
            return {"ok": False, "error": f"config/cameras.json will not parse: {exc}"}
        if height_mm <= 0:
            cfg.pop("defaults", None)      # turning the correction off again
        else:
            cfg["defaults"] = {"height_mm": round(height_mm, 1),
                               "nadir": [round(n, 1) for n in nadir],
                               "where": where, "out_mm": round(abs(out_mm), 1)}
        path.write_text(json.dumps(cfg, indent=2) + "\n")

        # What it is worth, so the number is not taken on faith.
        r = float(self.table.ball_radius)
        worst = 0.0
        if height_mm > r:
            far = max(((cx - nadir[0]) ** 2 + (cy - nadir[1]) ** 2) ** 0.5
                      for cx, cy in ((0, 0), (L, 0), (0, W), (L, W)))
            worst = r * far / (height_mm - r)
        return {"ok": True, "nadir": nadir, "height_mm": height_mm,
                "where": where, "corrects_up_to_mm": round(worst, 1),
                "enabled": height_mm > 0, "restart_needed": True}

    # --- calibration -------------------------------------------------------
    def calibrate(self, points, image_size=None) -> dict[str, Any]:
        """Four clicked corners (TL, TR, BR, BL) in image pixels -> homography.

        Points may be given in the coordinates of a scaled-down preview; pass
        the preview size as `image_size` and they are scaled back up.
        """
        if not points or len(points) != 4:
            return {"ok": False, "error": "need exactly four corners"}
        pts = [(float(p[0]), float(p[1])) for p in points]

        if image_size:
            blob, meta = self.snapshot(warm=1)
            if blob is not None and meta.get("width"):
                sx = meta["width"] / float(image_size[0])
                sy = meta["height"] / float(image_size[1])
                pts = [(x * sx, y * sy) for x, y in pts]

        calib = Calibration.from_corners(pts, self.table)
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        calib.save(self.calibration_path)
        return {
            "ok": True,
            "error_mm": round(calib.error_mm, 2),
            "path": str(self.calibration_path),
            "quality": ("good" if calib.error_mm < 5
                        else "usable" if calib.error_mm < 15 else "poor"),
        }

    def set_depth_balls(self, on: bool) -> dict[str, Any]:
        """Turn depth ball-finding on or off, and say if it cannot run yet."""
        path = self.calibration_path.parent / "cameras.json"
        try:
            cfg = json.loads(path.read_text()) if path.exists() else {}
        except ValueError as exc:
            return {"ok": False, "error": f"config/cameras.json will not parse: {exc}"}
        defaults = cfg.setdefault("defaults", {})
        defaults["depth_balls"] = bool(on)
        path.write_text(json.dumps(cfg, indent=2) + "\n")
        ready = (self.calibration_path.parent / "calibration-depth.json").exists()
        return {"ok": True, "depth_balls": bool(on), "calibrated": ready,
                "restart_needed": True,
                "note": "" if (ready or not on) else
                        "Saved, but the depth sensor is not calibrated yet, so "
                        "it will not take effect. Calibrate it below first."}

    # --- the depth sensor --------------------------------------------------
    def depth_snapshot(self, warm: int = 12) -> dict[str, Any]:
        """The depth stream as a picture you can click on.

        Depth finding balls was implemented and tested and then could not be
        switched on, because it needs its own calibration and nothing could
        produce one: the depth sensor is 512x424 with a different field of
        view from the colour camera, so the colour homography does not
        transfer. This is the missing half.

        Rendered as near-to-far grey over the table's own depth range rather
        than the sensor's full half-metre-to-four-metres, or the cushions and
        the cloth come out the same shade and there is nothing to aim at.
        """
        import cv2
        import numpy as np
        with self._lock:
            if self.source is None:
                return {"ok": False, "error": "camera not open"}
            depth = None
            for _ in range(max(1, warm)):
                got = self.source.read()
                if got and len(got) > 1 and got[1] is not None:
                    depth = got[1]
            if depth is None:
                return {"ok": False,
                        "error": "no depth frame",
                        "hint": "This camera has no depth stream. Depth needs "
                                "a Kinect v2 and its driver — run kinect.bat."}
        d = np.asarray(depth, dtype=np.float32)
        live = d[(d > 300) & (d < 6000)]
        if live.size < 100:
            return {"ok": False, "error": "the depth frame is empty"}
        # 5th to 95th percentile: the table fills most of the frame, so this
        # spans cloth to cushion and ignores a stray reflection.
        lo, hi = float(np.percentile(live, 5)), float(np.percentile(live, 95))
        if hi - lo < 1.0:
            lo, hi = live.min(), live.min() + 1.0
        img = np.clip((d - lo) / (hi - lo), 0, 1)
        grey = (255 * (1.0 - img)).astype(np.uint8)   # near is bright
        # Black for anything the sensor did not read, and it has to be set
        # after the inversion: doing it before turns "no reading" into the
        # brightest thing in the frame, which merges the floor around the
        # table with the cushions and leaves nothing to aim a corner at.
        grey[(d <= 300) | (d >= 6000)] = 0
        grey = cv2.applyColorMap(grey, cv2.COLORMAP_BONE)
        ok, buf = cv2.imencode(".png", grey)
        if not ok:
            return {"ok": False, "error": "could not encode the depth frame"}
        h, w = d.shape[:2]
        return {"ok": True, "width": w, "height": h,
                "near_mm": round(lo), "far_mm": round(hi),
                "image": "data:image/png;base64," + base64.b64encode(
                    buf.tobytes()).decode()}

    def calibrate_depth(self, points, image_size=None) -> dict[str, Any]:
        """Four corners clicked on the depth picture -> its own homography."""
        if not points or len(points) != 4:
            return {"ok": False, "error": "need exactly four corners"}
        pts = [(float(p[0]), float(p[1])) for p in points]
        if image_size:
            shot = self.depth_snapshot(warm=1)
            if shot.get("ok"):
                sx = shot["width"] / float(image_size[0])
                sy = shot["height"] / float(image_size[1])
                pts = [(x * sx, y * sy) for x, y in pts]
        calib = Calibration.from_corners(pts, self.table)
        out = self.calibration_path.parent / "calibration-depth.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        calib.save(out)
        return {"ok": True, "error_mm": round(calib.error_mm, 2),
                "path": str(out),
                "quality": ("good" if calib.error_mm < 8
                            else "usable" if calib.error_mm < 20 else "poor"),
                "note": "Depth is 512x424, so a pixel is about 6 mm at 2.2 m "
                        "and a few millimetres of error here is expected — it "
                        "says where a ball is, colour says which one."}

    def depth_status(self) -> dict[str, Any]:
        """Whether depth ball-finding is available and set up."""
        out = self.calibration_path.parent / "calibration-depth.json"
        return {"calibrated": out.exists(), "path": str(out)}

    def calibrate_markers(self) -> dict[str, Any]:
        """Calibrate from four printed markers instead of four clicks.

        Clicking is the biggest error source in the system and has to be
        redone whenever the camera moves. Markers are found to sub-pixel
        accuracy by something that does not get bored, in the same place
        every time.
        """
        from .vision.markers import calibrate as marker_calibrate
        import cv2
        import numpy as np

        blob, meta = self.snapshot()
        if blob is None:
            return {"ok": False, **meta}
        frame = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
        calib, res = marker_calibrate(frame, self.table)
        if calib is None:
            names = ", ".join(res.to_json()["missing_names"])
            return {"ok": False,
                    "error": f"found {len(res.found)} of 4 markers — missing "
                             f"{names}. Check they are flat, unobstructed and "
                             f"inside the frame.",
                    "markers": res.to_json()}
        self.calibration_path.parent.mkdir(parents=True, exist_ok=True)
        calib.save(self.calibration_path)
        return {"ok": True, "error_mm": round(calib.error_mm, 2),
                "quality": "good", "markers": res.to_json(),
                "path": str(self.calibration_path),
                "note": "leave the markers up and the camera can re-calibrate "
                        "itself if it is ever knocked"}

    def status(self) -> dict[str, Any]:
        saved = self.calibration_path.exists()
        err = None
        if saved:
            try:
                err = round(Calibration.load(self.calibration_path).error_mm, 2)
            except Exception:
                saved = False
        return {
            "open": self.source is not None,
            "spec": self.spec,
            "calibrated": saved,
            "error_mm": err,
            "last_error": self.last_error,
            **probe(),
        }
