"""Frame sources. One interface, so the rest of the system cannot tell a Kinect
from a webcam from a recorded clip.

Adding a camera means adding a class here and nothing else.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterator


class FrameSource(ABC):
    """Yields BGR frames as numpy arrays, plus an optional depth frame."""

    name = "source"
    fps: float = 30.0

    @abstractmethod
    def read(self) -> tuple[Any, Any | None] | None:
        """Return (color, depth) or None when the stream has ended."""

    def frames(self) -> Iterator[tuple[Any, Any | None]]:
        while True:
            got = self.read()
            if got is None:
                return
            yield got

    def close(self) -> None:
        pass

    def __enter__(self) -> "FrameSource":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class WebcamSource(FrameSource):
    """Any UVC camera. The simplest thing that works for an overhead rig."""

    name = "webcam"

    def __init__(self, index: int = 0, width: int = 1920, height: int = 1080,
                 fps: float = 30.0, fourcc: str = "MJPG") -> None:
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index)
        if fourcc:
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        # Manual exposure matters more than resolution: auto-exposure under
        # pool-room lighting silently drops the frame rate and smears the balls.
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
        self.fps = fps
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open camera {index}")

    def read(self):
        ok, frame = self.cap.read()
        return (frame, None) if ok else None

    def close(self) -> None:
        self.cap.release()


class VideoFileSource(FrameSource):
    """A recorded clip. The only honest way to regression-test detection."""

    name = "video"

    def __init__(self, path: str | Path, loop: bool = False, realtime: bool = False) -> None:
        import cv2
        self.cv2 = cv2
        self.path = str(path)
        self.cap = cv2.VideoCapture(self.path)
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open {path}")
        self.loop = loop
        self.realtime = realtime
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self._last = 0.0

    def read(self):
        ok, frame = self.cap.read()
        if not ok:
            if not self.loop:
                return None
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.cap.read()
            if not ok:
                return None
        if self.realtime:
            gap = 1.0 / self.fps - (time.time() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.time()
        return (frame, None)

    def close(self) -> None:
        self.cap.release()


class ImageSource(FrameSource):
    """A single still, repeated. Useful for calibration and unit tests."""

    name = "image"

    def __init__(self, path: str | Path, repeat: int = -1) -> None:
        import cv2
        self.frame = cv2.imread(str(path))
        if self.frame is None:
            raise RuntimeError(f"cannot read {path}")
        self.left = repeat

    def read(self):
        if self.left == 0:
            return None
        if self.left > 0:
            self.left -= 1
        return (self.frame.copy(), None)


class KinectV2Source(FrameSource):
    """Kinect v2 (Xbox One sensor): 1080p colour at 30 fps, 512x424 depth.

    Two backends, picked automatically:
      * pylibfreenect2 (Linux/macOS, needs libfreenect2 built with OpenCL/CUDA)
      * pykinect2      (Windows, needs the Kinect for Windows SDK 2.0)

    The depth stream is far too coarse to resolve balls (a ball is ~7 px), so it
    is used only to tell whether something — an arm, a cue, a body — is over the
    cloth, which is exactly when colour detection should be ignored.
    """

    name = "kinect2"

    def __init__(self, want_depth: bool = True, backend: str | None = None) -> None:
        self.want_depth = want_depth
        self.backend = backend or self._pick_backend()
        self.fps = 30.0
        if self.backend == "freenect2":
            self._init_freenect2()
        elif self.backend == "pykinect2":
            self._init_pykinect2()
        else:
            raise RuntimeError(
                "no Kinect v2 backend found. Install pylibfreenect2 (Linux) or "
                "pykinect2 + Kinect SDK 2.0 (Windows); see docs/HARDWARE.md"
            )

    @staticmethod
    def _pick_backend() -> str:
        try:
            import pylibfreenect2  # noqa: F401
            return "freenect2"
        except Exception:
            pass
        try:
            import pykinect2  # noqa: F401
            return "pykinect2"
        except Exception:
            return "none"

    # --- libfreenect2 -----------------------------------------------------
    def _init_freenect2(self) -> None:
        from pylibfreenect2 import Freenect2, FrameType, SyncMultiFrameListener
        try:
            from pylibfreenect2 import OpenCLPacketPipeline as Pipeline
        except Exception:
            from pylibfreenect2 import CpuPacketPipeline as Pipeline
        self._fn = Freenect2()
        if self._fn.enumerateDevices() == 0:
            raise RuntimeError("no Kinect v2 found on USB 3")
        serial = self._fn.getDeviceSerialNumber(0)
        self._dev = self._fn.openDevice(serial, pipeline=Pipeline())
        types = FrameType.Color | (FrameType.Depth if self.want_depth else 0)
        self._listener = SyncMultiFrameListener(types)
        self._dev.setColorFrameListener(self._listener)
        if self.want_depth:
            self._dev.setIrAndDepthFrameListener(self._listener)
        self._dev.start()
        self._FrameType = FrameType

    # --- pykinect2 --------------------------------------------------------
    def _init_pykinect2(self) -> None:
        from pykinect2 import PyKinectRuntime, PyKinectV2
        flags = PyKinectV2.FrameSourceTypes_Color
        if self.want_depth:
            flags |= PyKinectV2.FrameSourceTypes_Depth
        self._kin = PyKinectRuntime.PyKinectRuntime(flags)

    def read(self):
        import numpy as np
        if self.backend == "freenect2":
            frames = self._listener.waitForNewFrame()
            color = frames[self._FrameType.Color].asarray()      # BGRX, 1080p
            depth = frames[self._FrameType.Depth].asarray() if self.want_depth else None
            out = (color[:, :, :3].copy(), None if depth is None else depth.copy())
            self._listener.release(frames)
            return out
        # pykinect2
        if not self._kin.has_new_color_frame():
            return (None, None)
        buf = self._kin.get_last_color_frame()
        color = buf.reshape((1080, 1920, 4))[:, :, :3].copy()
        depth = None
        if self.want_depth and self._kin.has_new_depth_frame():
            depth = self._kin.get_last_depth_frame().reshape((424, 512)).copy()
        return (color, depth)

    def close(self) -> None:
        if self.backend == "freenect2":
            try:
                self._dev.stop()
                self._dev.close()
            except Exception:
                pass
        elif self.backend == "pykinect2":
            try:
                self._kin.close()
            except Exception:
                pass


def open_source(spec: str, **kw) -> FrameSource:
    """Open a source from a string: "auto", "kinect", "cam:0", "video:path",
    "image:path".

    "auto" prefers a Kinect v2 when a working backend is installed and falls
    back to the first webcam that opens, so a user who just plugs the sensor
    in does not have to know what to type.
    """
    if spec == "auto":
        try:
            return KinectV2Source(**kw)
        except Exception:
            pass
        for index in range(3):
            try:
                return WebcamSource(index, **kw)
            except Exception:
                continue
        raise RuntimeError(
            "no camera found. Check the Kinect is on a USB 3 port with its "
            "power supply and that its driver is installed; see docs/HARDWARE.md"
        )
    if spec in ("kinect", "kinect2"):
        return KinectV2Source(**kw)
    if spec.startswith("cam"):
        _, _, idx = spec.partition(":")
        return WebcamSource(int(idx or 0), **kw)
    if spec.startswith("video:"):
        return VideoFileSource(spec.split(":", 1)[1], **kw)
    if spec.startswith("image:"):
        return ImageSource(spec.split(":", 1)[1], **kw)
    raise ValueError(f"unknown source {spec!r}")
