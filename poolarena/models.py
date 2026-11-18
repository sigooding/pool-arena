"""Installing and swapping the ball detector.

The colour detector needs nothing and works on a well-lit table. A YOLO model
trained on real pool footage is more robust in a tight rack and under bad
light, and several exist on GitHub — but using one means two things this
project otherwise avoids: a large dependency (torch), and running somebody
else's model file.

That second point deserves plain language rather than a shrug. A `.pt`
checkpoint is a pickled Python object, and loading one **executes code from
that file**. Installing a model from the internet is running a stranger's
program on the machine next to your pool table. This module therefore:

  * refuses hosts outside a small allowlist;
  * shows the exact URL before anything is fetched;
  * will happily take a local path instead, which needs no network at all;
  * never installs anything on its own initiative.

None of that makes an untrusted checkpoint safe. It makes the decision
visible, which is the most software can honestly do here.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Hosts a model may be fetched from. GitHub release assets and raw files
#: cover every pool model I am aware of; anything else is a local-file job.
ALLOWED_HOSTS = {
    "github.com", "objects.githubusercontent.com",
    "raw.githubusercontent.com", "release-assets.githubusercontent.com",
    "huggingface.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.huggingface.co",
}

MAX_BYTES = 600 * 1024 * 1024       # a detection model is tens of MB, not GB


@dataclass
class Runtime:
    """What is installed, and what a model would need."""

    ultralytics: bool
    torch: bool
    torch_version: str = ""
    cuda: bool = False
    device: str = "cpu"

    def to_json(self) -> dict[str, Any]:
        return {
            "ultralytics": self.ultralytics, "torch": self.torch,
            "torch_version": self.torch_version, "cuda": self.cuda,
            "device": self.device, "ready": self.ultralytics and self.torch,
            "install_command": "pip install ultralytics",
        }


def runtime() -> Runtime:
    try:
        import ultralytics  # noqa: F401
        has_u = True
    except Exception:
        has_u = False
    try:
        import torch
        return Runtime(ultralytics=has_u, torch=True,
                       torch_version=getattr(torch, "__version__", ""),
                       cuda=bool(torch.cuda.is_available()),
                       device="cuda" if torch.cuda.is_available() else "cpu")
    except Exception:
        return Runtime(ultralytics=has_u, torch=False)


def install_runtime(timeout: float = 1800) -> dict[str, Any]:
    """pip install ultralytics, which drags in torch. Big and slow."""
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
           "ultralytics"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "pip timed out; run it in a terminal instead",
                "command": " ".join(cmd)}
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-6:]
    return {"ok": proc.returncode == 0, "command": " ".join(cmd),
            "log": "\n".join(tail), "runtime": runtime().to_json()}


# --- fetching -------------------------------------------------------------
def check_url(url: str) -> tuple[bool, str]:
    try:
        u = urllib.parse.urlparse(url)
    except Exception as exc:
        return False, str(exc)
    if u.scheme != "https":
        return False, "model downloads must use https"
    host = (u.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return False, (f"{host or 'that host'} is not an allowed source. "
                       f"Allowed: {', '.join(sorted(ALLOWED_HOSTS))}. "
                       f"Download the file yourself and install it from a path "
                       f"instead.")
    return True, ""


def install_model(source: str, weights_dir: Path, name: str = "",
                  progress=None) -> dict[str, Any]:
    """Put a model file in `weights_dir`. `source` is an https URL or a path."""
    weights_dir.mkdir(parents=True, exist_ok=True)
    source = (source or "").strip()
    if not source:
        return {"ok": False, "error": "no model given"}

    if source.lower().startswith(("http://", "https://")):
        ok, why = check_url(source)
        if not ok:
            return {"ok": False, "error": why}
        filename = name or Path(urllib.parse.urlparse(source).path).name or "model.pt"
        target = weights_dir / _safe_name(filename)
        try:
            req = urllib.request.Request(source, headers={"User-Agent": "poolarena"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                if total > MAX_BYTES:
                    return {"ok": False,
                            "error": f"that file is {total // (1024*1024)} MB; "
                                     f"a detection model should be far smaller"}
                got = 0
                tmp = target.with_suffix(target.suffix + ".part")
                with tmp.open("wb") as fh:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        got += len(chunk)
                        if got > MAX_BYTES:
                            tmp.unlink(missing_ok=True)
                            return {"ok": False, "error": "download exceeded the size cap"}
                        fh.write(chunk)
                        if progress:
                            progress(got, total)
                tmp.replace(target)
        except Exception as exc:
            return {"ok": False, "error": f"download failed: {exc}"}
    else:
        src = Path(source).expanduser()
        if not src.is_file():
            return {"ok": False, "error": f"no file at {src}"}
        target = weights_dir / _safe_name(name or src.name)
        if src.resolve() != target.resolve():
            shutil.copy2(src, target)

    size = target.stat().st_size
    if size < 1024:
        target.unlink(missing_ok=True)
        return {"ok": False, "error": "that file is too small to be a model"}
    return {"ok": True, "path": str(target), "name": target.name,
            "size_mb": round(size / (1024 * 1024), 1),
            "note": "a .pt checkpoint runs code when it is loaded; only install "
                    "models from a source you trust"}


def _safe_name(name: str) -> str:
    """No directory traversal, and keep it to something file-like."""
    clean = Path(name).name.replace("\\", "_")
    return clean or "model.pt"


# --- wiring it into the detector -----------------------------------------
def select_detector(config_path: Path, kind: str, weights: str = "",
                    conf: float = 0.4) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
    if kind == "yolo":
        if not weights:
            return {"ok": False, "error": "a YOLO detector needs a model file"}
        cfg["detector"] = "yolo"
        cfg["weights"] = weights
        cfg["conf"] = conf
    else:
        cfg["detector"] = "color"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(cfg, indent=2) + "\n")
    return {"ok": True, "detector": cfg["detector"], "config": str(config_path)}


def list_installed(weights_dir: Path) -> list[dict[str, Any]]:
    if not weights_dir.is_dir():
        return []
    out = []
    for f in sorted(weights_dir.glob("*")):
        if f.suffix.lower() in (".pt", ".onnx", ".engine") and f.is_file():
            out.append({"name": f.name, "path": str(f),
                        "size_mb": round(f.stat().st_size / (1024 * 1024), 1)})
    return out


def try_model(weights: str, sample=None) -> dict[str, Any]:
    """Load a model and, if given a frame, run it once.

    Worth doing before a match rather than during one: this is the moment a
    bad download, a missing dependency or a model that wants a different
    input size shows itself.
    """
    rt = runtime()
    if not (rt.ultralytics and rt.torch):
        return {"ok": False, "error": "ultralytics is not installed",
                "install_command": "pip install ultralytics"}
    try:
        from .vision.detect import YoloDetector
        det = YoloDetector(weights)
    except Exception as exc:
        return {"ok": False, "error": f"the model would not load: {exc}"}
    out: dict[str, Any] = {"ok": True, "device": rt.device,
                           "classes": getattr(det.model, "names", None)}
    if sample is not None:
        import time
        t0 = time.time()
        try:
            dets = det.detect(sample)
        except Exception as exc:
            return {"ok": False, "error": f"the model loaded but would not run: {exc}"}
        out["found"] = len(dets)
        out["ms"] = round((time.time() - t0) * 1000)
        out["numbers"] = sorted({d.number for d in dets if d.number is not None})
    return out
