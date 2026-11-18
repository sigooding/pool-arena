# Calibration

Two separate mappings, done once each, in this order.

## 1. Camera → table (millimetres)

```bash
python -m poolarena calibrate --source kinect --size 8ft
```

Click the four **inside corners of the cushions** — where the cloth meets the
rail, not the outer edge of the wood — in order: top-left, top-right,
bottom-right, bottom-left. Backspace undoes, enter accepts, escape cancels.

It writes `config/calibration.json` and prints an RMS error:

| RMS | Verdict |
|---|---|
| < 5 mm | good |
| 5–15 mm | usable; pocket decisions near the jaws may wobble |
| > 15 mm | re-click; check the camera is rigidly mounted |

Four corners pin the plane but leave lens distortion uncorrected in the middle
of the table. If your lens is wide and barrel-distorted, add the rail diamonds
with `refine_with_diamonds()` for a better fit.

**The camera must not move afterwards.** A knock means recalibrating. Mount it
to a joist, not to a lamp.

### Checking it

Run `python -m poolarena run ...`, open the overlay, and press `b`. The
projector draws where the system *thinks* each ball is. On a calibrated table
those discs land exactly on the real balls. This is the fastest honest check
there is — if the discs sit 2 cm off at one end of the table, your homography
is wrong, not your detector.

## 2. Table → projector (keystone)

Open the overlay on the projector output, fullscreen it with `f`, and press
`c`.

A cyan grid appears with four draggable handles. Drag each one onto the
matching cushion corner of the real table. Pink dots mark where the software
thinks the six pockets are — line those up with the real pockets and you are
done.

- `1`–`4` select a corner (TL, TR, BR, BL)
- arrow keys nudge the selected corner by 1 px, shift+arrow by 10 px
- `r` resets to a default rectangle
- `c` leaves calibration mode

### Calibrating from the tablet

Those hotkeys need a keyboard, and the PC is usually across the room from the
table — which is the one place you cannot judge the alignment from. So the
same controls are on the scoreboard page: **Setup → Calibrate projector**.

Pick a corner, nudge it with the arrow pad (1 px, or 10 px with the toggle),
and watch the projection while you do it. The tablet never draws anything
itself; it relays the nudges to the overlay over the same socket, so what you
see on the cloth is the real mapping, not a preview of one.

It saves to the browser's local storage immediately and also pushes the corners
to the server, so a second screen picks up the same mapping.

**Use the grid, not just the corners.** Getting the four corners right while
the middle of the grid bows is the signature of projector keystone correction
being switched on. Turn it off in the projector's own menu and redo this.

## Why two mappings

The camera and the projector see the table from different places and neither is
square to it. Keeping the two transforms separate means you can move or replace
either one without touching the other, and everything in between — scoring,
zones, games — works purely in table millimetres and never thinks about pixels
at all.

## Optional: learn the cloth

```bash
python -m poolarena run --source kinect --learn-cloth
```

Treats the first frame as an empty table and models the cloth colour from it.
Detection gets noticeably steadier. Clear the table first, obviously.
