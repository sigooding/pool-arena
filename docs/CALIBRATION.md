# Calibration

**There are two calibrations and they do completely different jobs.** Mixing
them up is the easiest mistake to make here:

| | what it does | where |
|---|---|---|
| **Camera** | teaches the system where the *table* is in the camera picture | Setup → Camera |
| **Projector** | lines the *projected image* up with the table | Setup → Projector |

Doing one does nothing for the other. You need both, once each, in that order.

Neither needs the command line: both are in the scoreboard page under
**Setup**, which works on a PC touchscreen, a tablet or a phone.

## The short version

1. Mount the camera, open Setup → Camera, press **Connect camera**, then tap
   the four corners of the cushion in the picture and save.
2. Turn the projector on, open Setup → Projector, and nudge the four corners
   of the projected outline onto the corners of the real table.

The rest of this page is detail and troubleshooting.

## 1. Camera → table (millimetres)

### From the UI (no terminal)

Open the scoreboard page, press **Setup**, then the **Camera** tab.

- **Connect camera** finds a Kinect v2 if its driver is installed, and falls
  back to the first webcam that opens. The status line tells you what it
  found, or why it found nothing.
- **Take picture** grabs a still. It pulls a dozen frames first and keeps the
  last, because auto-exposure needs a moment to settle and calibrating
  against a dark first frame is how you end up clicking the wrong corners.
- Tap the four corners in order: top-left, top-right, bottom-right,
  bottom-left. **Undo corner** steps back.
- **Save calibration** writes `config/calibration.json` and reports the
  average error in millimetres.

### From the command line

```bash
python -m poolarena calibrate --source auto --size 8ft
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

### From the UI

Setup → **Projector**. Opening that tab puts the grid on the cloth
automatically. Pick a corner, nudge it with the arrow pad (1 px, or 10 px with
the toggle), and watch the table while you do it — the tablet relays the
nudges to the projector, so what you see on the cloth is the real mapping.

### From the overlay itself

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
