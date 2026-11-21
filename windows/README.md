# Windows: double-click to run

## On a brand new PC

`setup.bat` installs **numpy and OpenCV**, into a private `.venv` folder.
About 60 MB, a few minutes, and nothing it does touches the rest of the
machine — delete `.venv` and it is all undone.

It does **not** install these, so do them first:

1. **Python**, from <https://www.python.org/downloads/>. Tick **Add
   python.exe to PATH** on the installer's first screen — it is off by
   default and everything else depends on it. Any current version is fine;
   `setup.bat` checks and will tell you if it is too old.
2. **This code.** Either `git clone`, or the green **Code** button on GitHub
   → **Download ZIP**, then unzip it somewhere permanent. Not inside the zip
   viewer: Windows will let scripts run from there and then lose the files.
3. **Kinect for Windows SDK 2.0**, from Microsoft — only if you are using the
   Kinect, and it wants a USB 3 port. Then run `kinect.bat`.

Then `setup.bat`, then `demo.bat` to confirm it all works before the table is
involved.

Worth knowing: the first time it runs, Windows will ask whether to allow
network access. Say yes for private networks. That is the local web server
the projector and the tablet talk to; nothing leaves the machine.

## The scripts

In the order you will want them. Double-click; no terminal, no typing.

| | |
|---|---|
| **cameras.bat** | Lists every camera the machine can see. Run this first if the wrong one opens, or the right one will not. |
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

**"no camera at index N"** — nothing is on that index. Run `cameras.bat` to
see what is actually there; it lists each one with its resolution, which is
how you tell a phone from a laptop lid. If something else has the camera
open (Teams, Zoom, the Camera app), close it first.

**Three cameras listed but only one opens?** That was OpenCV reaching for
its FFmpeg backend, which cannot see a Windows virtual camera. It now asks
for DirectShow first. If you are on a build from before 21 November, pull.

**Using a phone as the camera?** Camo, Continuity and OBS create the camera
when the app connects, not when the phone is plugged in. Start the app, get
the phone streaming, *then* run `cameras.bat`.

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
