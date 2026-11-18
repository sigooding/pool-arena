"""Ball detection and number classification.

Two detectors share one interface:

  ColorBallDetector  no training, no GPU. Works on a warped top-down view by
                     subtracting the empty cloth, then classifying each blob by
                     hue and by how much white it carries (stripe vs solid).
  YoloDetector       an ultralytics model, when you want robustness in a tight
                     rack. Same output, so it is a drop-in swap.

Both return detections in *warped pixel* space; the pipeline converts to mm.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..types import Kind

# Hue centres (OpenCV H, 0-179) for balls 1-7; 9-15 repeat them as stripes.
HUES = {1: 28, 2: 110, 3: 175, 4: 145, 5: 12, 6: 65, 7: 170}
SOLID_FOR_HUE = {v: k for k, v in HUES.items()}


@dataclass
class Detection:
    x: float                 # warped pixel coords
    y: float
    radius: float
    kind: Kind = Kind.UNKNOWN
    number: int | None = None
    confidence: float = 1.0
    white_frac: float = 0.0
    hue: float = 0.0
    value: float = 0.0


class BallDetector(ABC):
    @abstractmethod
    def detect(self, warped: np.ndarray) -> list[Detection]:
        ...

    def learn_background(self, warped: np.ndarray) -> None:
        """Optional: record the empty cloth."""


class ColorBallDetector(BallDetector):
    """Classic CV. Fast, explainable, and tunable from a config file."""

    def __init__(self, ball_px: float = 36.0, cloth_tolerance: int = 34,
                 min_fill: float = 0.45, white_v: int = 165, white_s: int = 70) -> None:
        import cv2
        self.cv2 = cv2
        self.ball_px = ball_px
        self.cloth_tolerance = cloth_tolerance
        self.min_fill = min_fill
        self.white_v = white_v
        self.white_s = white_s
        self.cloth_hsv: np.ndarray | None = None
        self.background: np.ndarray | None = None

    # --- cloth model -------------------------------------------------------
    def learn_background(self, warped: np.ndarray) -> None:
        """Call once with an empty table. Everything else is 'not cloth'."""
        cv2 = self.cv2
        hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
        self.background = cv2.GaussianBlur(warped, (9, 9), 0)
        h, s, v = (hsv[:, :, i] for i in range(3))
        self.cloth_hsv = np.array([np.median(h), np.median(s), np.median(v)], float)

    def cloth_mask(self, warped: np.ndarray) -> np.ndarray:
        cv2 = self.cv2
        hsv = cv2.cvtColor(cv2.GaussianBlur(warped, (5, 5), 0), cv2.COLOR_BGR2HSV)
        if self.cloth_hsv is None:
            # Fall back to the dominant hue in the frame, which on a pool table
            # is always the cloth.
            hist = cv2.calcHist([hsv], [0], None, [180], [0, 180])
            self.cloth_hsv = np.array([float(np.argmax(hist)),
                                       float(np.median(hsv[:, :, 1])),
                                       float(np.median(hsv[:, :, 2]))])
        ch, cs, cv_ = self.cloth_hsv
        dh = np.minimum(np.abs(hsv[:, :, 0].astype(int) - ch),
                        180 - np.abs(hsv[:, :, 0].astype(int) - ch))
        is_cloth = (dh < self.cloth_tolerance * 0.5) & \
                   (np.abs(hsv[:, :, 1].astype(int) - cs) < self.cloth_tolerance * 2.2)
        mask = np.where(is_cloth, 0, 255).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)

    # --- detection ---------------------------------------------------------
    def detect(self, warped: np.ndarray) -> list[Detection]:
        cv2 = self.cv2
        mask = self.cloth_mask(warped)
        r = self.ball_px / 2
        area = np.pi * r * r
        out: list[Detection] = []

        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        for i in range(1, n):
            a = stats[i, cv2.CC_STAT_AREA]
            if a < area * self.min_fill:
                continue
            w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            # A blob much bigger than one ball is a cluster: split it with
            # Hough inside the blob rather than reporting one fat ball.
            if a > area * 1.9 or max(w, h) > self.ball_px * 1.6:
                out.extend(self._split_cluster(warped, labels == i))
                continue
            cx, cy = cents[i]
            out.append(self._classify(warped, cx, cy, r))

        if not out:
            out = self._hough(warped, mask)
        return [d for d in out if d.radius > 1]

    def _split_cluster(self, warped: np.ndarray, blob: np.ndarray) -> list[Detection]:
        cv2 = self.cv2
        r = self.ball_px / 2
        sub = (blob.astype(np.uint8) * 255)
        circles = cv2.HoughCircles(sub, cv2.HOUGH_GRADIENT, dp=1.1,
                                   minDist=self.ball_px * 0.75,
                                   param1=90, param2=9,
                                   minRadius=int(r * 0.7), maxRadius=int(r * 1.3))
        if circles is None:
            ys, xs = np.nonzero(blob)
            return [self._classify(warped, float(xs.mean()), float(ys.mean()), r)]
        return [self._classify(warped, float(c[0]), float(c[1]), float(c[2]))
                for c in circles[0]]

    def _hough(self, warped: np.ndarray, mask: np.ndarray) -> list[Detection]:
        cv2 = self.cv2
        r = self.ball_px / 2
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        gray = cv2.bitwise_and(gray, gray, mask=mask)
        circles = cv2.HoughCircles(cv2.medianBlur(gray, 5), cv2.HOUGH_GRADIENT,
                                   dp=1.2, minDist=self.ball_px * 0.8,
                                   param1=100, param2=14,
                                   minRadius=int(r * 0.7), maxRadius=int(r * 1.35))
        if circles is None:
            return []
        return [self._classify(warped, float(c[0]), float(c[1]), float(c[2]))
                for c in circles[0]]

    # --- classification ----------------------------------------------------
    def _patch(self, img: np.ndarray, cx: float, cy: float, r: float) -> np.ndarray:
        h, w = img.shape[:2]
        x0, x1 = int(max(0, cx - r * 0.72)), int(min(w, cx + r * 0.72))
        y0, y1 = int(max(0, cy - r * 0.72)), int(min(h, cy + r * 0.72))
        return img[y0:y1, x0:x1]

    def _classify(self, warped: np.ndarray, cx: float, cy: float, r: float) -> Detection:
        cv2 = self.cv2
        patch = self._patch(warped, cx, cy, r)
        if patch.size == 0:
            return Detection(cx, cy, r, confidence=0.1)
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        white = (v > self.white_v) & (s < self.white_s)
        wfrac = float(white.mean())
        dark = float(((v < 70)).mean())
        colored = ~white
        hue = float(np.median(h[colored])) if colored.any() else 0.0
        val = float(np.median(v))

        d = Detection(cx, cy, r, white_frac=wfrac, hue=hue, value=val)

        if wfrac > 0.72:
            d.kind, d.number, d.confidence = Kind.CUE, 0, 0.9
            return d
        if dark > 0.6 and wfrac < 0.3:
            d.kind, d.number, d.confidence = Kind.EIGHT, 8, 0.8
            return d

        # Nearest named hue, then stripe-vs-solid by how much white is showing.
        best, best_d = None, 999.0
        for num, hc in HUES.items():
            dist = min(abs(hue - hc), 180 - abs(hue - hc))
            if dist < best_d:
                best, best_d = num, dist
        striped = wfrac > 0.22
        d.kind = Kind.STRIPE if striped else Kind.SOLID
        if best is not None:
            d.number = best + 8 if striped else best
            d.confidence = max(0.25, 1.0 - best_d / 45.0)
        return d


class YoloDetector(BallDetector):
    """ultralytics YOLO wrapper. Expects classes named "0".."15" or "cue"/"8"."""

    def __init__(self, weights: str | Path, conf: float = 0.4, device: str | None = None) -> None:
        from ultralytics import YOLO
        self.model = YOLO(str(weights))
        self.conf = conf
        self.device = device

    def detect(self, warped: np.ndarray) -> list[Detection]:
        res = self.model.predict(warped, conf=self.conf, verbose=False,
                                 device=self.device)[0]
        names = res.names
        out: list[Detection] = []
        for box, cls, cf in zip(res.boxes.xywh.tolist(), res.boxes.cls.tolist(),
                                res.boxes.conf.tolist()):
            x, y, w, h = box
            label = str(names[int(cls)]).lower()
            number: int | None = None
            if label in ("cue", "white", "cueball"):
                number = 0
            else:
                digits = "".join(c for c in label if c.isdigit())
                number = int(digits) if digits else None
            kind = Kind.UNKNOWN
            if number is not None:
                from ..types import kind_of
                kind = kind_of(number)
            out.append(Detection(x, y, max(w, h) / 2, kind=kind, number=number,
                                 confidence=float(cf)))
        return out


def build_detector(cfg: dict[str, Any]) -> BallDetector:
    kind = (cfg or {}).get("detector", "color")
    if kind == "yolo":
        return YoloDetector(cfg["weights"], conf=cfg.get("conf", 0.4),
                            device=cfg.get("device"))
    return ColorBallDetector(
        ball_px=cfg.get("ball_px", 36.0),
        cloth_tolerance=cfg.get("cloth_tolerance", 34),
        min_fill=cfg.get("min_fill", 0.45),
    )
