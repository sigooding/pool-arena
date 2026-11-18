"""Interactive calibration: click the four inside corners of the cushions.

Run once per camera position. The homography it writes is the only thing tying
pixels to millimetres, so everything downstream — scoring, zones, projection —
inherits its accuracy. Check the reported RMS error: under about 5 mm is fine,
over 15 mm and a ball near a pocket will be judged wrongly.
"""
from __future__ import annotations

from pathlib import Path

from ..geometry import Calibration, Table

ORDER = ["top-left", "top-right", "bottom-right", "bottom-left"]


def pick_corners(frame, window: str = "calibrate") -> list[tuple[float, float]]:
    """Click four corners in order; backspace undoes, enter accepts."""
    import cv2

    pts: list[tuple[float, float]] = []

    def draw():
        img = frame.copy()
        for i, (x, y) in enumerate(pts):
            cv2.circle(img, (int(x), int(y)), 7, (0, 255, 0), 2)
            cv2.putText(img, ORDER[i], (int(x) + 10, int(y)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1, cv2.LINE_AA)
        if len(pts) > 1:
            for a, b in zip(pts, pts[1:]):
                cv2.line(img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])),
                         (0, 255, 0), 1)
        if len(pts) == 4:
            cv2.line(img, (int(pts[3][0]), int(pts[3][1])),
                     (int(pts[0][0]), int(pts[0][1])), (0, 255, 0), 1)
        nxt = ORDER[len(pts)] if len(pts) < 4 else "enter to accept"
        cv2.putText(img, f"click: {nxt}", (16, 32), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.imshow(window, img)

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 4:
            pts.append((float(x), float(y)))
            draw()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    draw()
    while True:
        key = cv2.waitKey(30) & 0xFF
        if key in (13, 10) and len(pts) == 4:
            break
        if key == 8 and pts:
            pts.pop()
            draw()
        if key == 27:
            pts.clear()
            break
    cv2.destroyWindow(window)
    return pts


def calibrate_from_frame(frame, table: Table, out_path: str | Path) -> Calibration:
    pts = pick_corners(frame)
    if len(pts) != 4:
        raise RuntimeError("calibration cancelled")
    calib = Calibration.from_corners(pts, table)
    calib.save(out_path)
    return calib


def refine_with_diamonds(calib: Calibration, image_points, table: Table) -> Calibration:
    """Optional second pass: add rail diamonds for a better fit than 4 corners.

    Four corners pin the plane but leave lens distortion in the middle of the
    table uncorrected. Adding diamonds spreads the error out.
    """
    diamonds = table.diamonds()
    if len(image_points) != len(diamonds):
        raise ValueError(f"expected {len(diamonds)} diamond clicks, got {len(image_points)}")
    calib.image_points = list(calib.image_points) + [tuple(p) for p in image_points]
    calib.table_points = list(calib.table_points) + diamonds
    calib.label = "corners+diamonds"
    calib.solve()
    return calib
