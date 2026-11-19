# Windows: double-click to run

Six scripts, in the order you will want them. Double-click; no terminal, no
typing.

| | |
|---|---|
| **setup.bat** | Run once. Makes a private Python environment in `.venv` and installs what it needs. Nothing it does touches the rest of the PC — delete `.venv` and it is all undone. |
| **demo.bat** | No camera, no table. The games, the projector view and the scoreboard, all against a simulator. Start here. |
| **calibrate.bat** | Teaches it where the table is in the camera picture. Once after the camera is mounted, and again if it moves. |
| **check.bat** | Reads the table and reports what it found, link by link. Run this before a real game. |
| **start.bat** | The real thing. |

And two you only need if you are using them:

| | |
|---|---|
| **kinect.bat** | Adds Kinect v2 support. The Kinect for Windows SDK 2.0 has to be installed first, from Microsoft. |
| **yolo.bat** | Adds the YOLO ball detector — finds balls by shape rather than colour, and copes better with a tight rack and poor light. Large download. |

## Passing options

Anything typed after the script name goes straight through, so from a
Command Prompt in this folder:

```bat
start.bat --source kinect
```

```bat
check.bat --source cam:1 --expect 8
```

```bat
demo.bat --game timebomb --players "Sam, Alex"
```

Nothing has to be edited to try a different camera.

## When something goes wrong

The window stays open and tells you. That is deliberate: a batch file that
fails and closes instantly is the most common way to lose an evening.

**"No Python found"** — install it from
<https://www.python.org/downloads/>, and tick *Add python.exe to PATH* on the
installer's first screen. Then run `setup.bat`.

**"No module named numpy"** — `setup.bat` has not been run, or it did not
finish.

**"cannot open camera"** — something else has the camera open (Teams, Zoom,
the Camera app), or it is on a different index. Try `start.bat --source
cam:1`, then `cam:2`.

**"no calibration"** — run `calibrate.bat`, or do it from the scoreboard:
Setup, then Camera.

**Windows asks whether to allow network access** the first time — say yes for
private networks. That is the local web server the projector and the tablet
connect to; nothing leaves the machine.

## A note on what has been tested

These scripts were written on Linux and have not been run on Windows. The
commands inside them are the same ones used throughout development, and a
test checks that every command they call still exists, that every `goto` has
a label, that the line endings are right and that no failure path can close
the window before it is read — but that is not the same as having run them.
If one misbehaves, the error it prints will say why.
