"""Calibration from printed markers, instead of by hand.

Clicking four corners is the largest single source of position error in this
system: one pixel of click error costs about 1.6 mm on the cloth, three
pixels about 5.4 mm, eight pixels about 11.5 mm with outliers past 40 mm.
A magnifier helps a person be careful, but careful is still manual, still
subjective, and still has to be redone the moment the camera is nudged.

Four printed ArUco markers remove the problem instead of mitigating it. Tape
one near each pocket, and the corners are found to sub-pixel accuracy, in the
same place every time, by a detector that does not get bored. Two
consequences matter more than the accuracy:

  * **it re-calibrates itself.** Leave the markers up and a knocked camera
    heals on the next frame rather than quietly scoring the rest of the night
    from a stale homography;
  * **anybody can do it.** No judgement about where the cloth meets the rail.

Markers can be taken down after calibrating if they are in the way; the
homography is saved either way. Leaving them up is better.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..geometry import Calibration, Table

#: 4x4 patterns are the most forgiving at low resolution, and 50 of them is
#: far more than four corners need.
DICT = "DICT_4X4_50"

#: Which printed marker goes where. Keep the ids small and memorable: the
#: person taping them up is reading a number off a sheet of paper.
CORNER_IDS = (0, 1, 2, 3)          # top-left, top-right, bottom-right, bottom-left
CORNER_NAMES = ("top-left", "top-right", "bottom-right", "bottom-left")


def _detector():
    import cv2
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICT))
    params = cv2.aruco.DetectorParameters()
    # Pool rooms are dim and markers sit at an angle; both help there.
    params.adaptiveThreshWinSizeMax = 43
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(d, params)


def sheet(path: str | Path, px: int = 420, margin: int = 60) -> Path:
    """Write a printable sheet of the four corner markers.

    One page, four markers, each labelled with where it goes. Print it at any
    size — the detector does not care, though bigger is easier to see from
    the ceiling.
    """
    import cv2
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICT))
    cols, rows = 2, 2
    cell = px + margin * 2
    page = np.full((rows * cell + 80, cols * cell, 3), 255, np.uint8)
    for i, mid in enumerate(CORNER_IDS):
        img = cv2.aruco.generateImageMarker(d, mid, px)
        r, c = divmod(i, cols)
        y, x = r * cell + margin, c * cell + margin
        page[y:y + px, x:x + px] = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        cv2.putText(page, f"{mid}: {CORNER_NAMES[i]}", (x, y + px + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(page, "Tape each marker FLAT ON THE CLOTH just inside the corner"
                      " it names, its OUTER corner on the cushion corner.",
                (30, rows * cell + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.72,
                (0, 0, 0), 2, cv2.LINE_AA)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), page)
    return out


@dataclass
class MarkerResult:
    found: dict[int, tuple[float, float]]
    missing: list[int]

    @property
    def complete(self) -> bool:
        return not self.missing

    def to_json(self) -> dict[str, Any]:
        return {
            "found": {str(k): [round(v[0], 2), round(v[1], 2)]
                      for k, v in self.found.items()},
            "missing": self.missing,
            "missing_names": [CORNER_NAMES[CORNER_IDS.index(m)] for m in self.missing],
            "complete": self.complete,
        }


def find_markers(frame) -> MarkerResult:
    """Locate the four corner markers, returning the table corner each marks.

    A marker's centre is not a useful landmark — it depends on how big the
    printout is. What a person can physically line up is one corner of the
    square. The markers lie inside the cloth, so the corner that touches the
    cushion corner is the one furthest from the middle of the table, and
    that is the point returned.
    """
    import cv2
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    corners, ids, _ = _detector().detectMarkers(gray)
    found: dict[int, tuple[float, float]] = {}
    if ids is not None:
        centre = np.array([gray.shape[1] / 2, gray.shape[0] / 2], np.float32)
        for quad, mid in zip(corners, ids.flatten()):
            if int(mid) not in CORNER_IDS:
                continue
            pts = quad.reshape(4, 2)
            outer = max(pts, key=lambda p: float(np.linalg.norm(p - centre)))
            found[int(mid)] = (float(outer[0]), float(outer[1]))
    return MarkerResult(found=found,
                        missing=[m for m in CORNER_IDS if m not in found])


def calibrate(frame, table: Table) -> tuple[Calibration | None, MarkerResult]:
    """A full calibration from one frame, or a clear account of what is missing."""
    res = find_markers(frame)
    if not res.complete:
        return None, res
    pts = [res.found[m] for m in CORNER_IDS]
    return Calibration.from_corners(pts, table), res


class MarkerWatch:
    """Keeps a calibration honest while the markers stay up.

    A camera that gets knocked is the quiet failure mode of this whole
    project: nothing breaks, the scores just drift. If the markers are still
    on the cloth, a shift is visible and correctable, so this re-solves when
    the corners have moved by more than a tolerance and leaves it alone
    otherwise.
    """

    def __init__(self, table: Table, tolerance_px: float = 3.0,
                 every: int = 60) -> None:
        self.table = table
        self.tolerance = tolerance_px
        self.every = every
        self.last: dict[int, tuple[float, float]] = {}
        self.updates = 0
        self._n = 0

    def check(self, frame) -> Calibration | None:
        """Returns a fresh Calibration when the camera has moved."""
        self._n += 1
        if self._n % self.every:
            return None
        res = find_markers(frame)
        if not res.complete:
            return None
        if self.last:
            moved = max(float(np.hypot(res.found[m][0] - self.last[m][0],
                                       res.found[m][1] - self.last[m][1]))
                        for m in CORNER_IDS)
            if moved <= self.tolerance:
                return None
        self.last = dict(res.found)
        self.updates += 1
        return Calibration.from_corners([res.found[m] for m in CORNER_IDS], self.table)
