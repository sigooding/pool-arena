# Setting it up

Everything on one page, in the order you would actually do it. Figures come
from measurements in this repository's own tests, not from guesses; where
something is unverified it says so.

## What you need

| | Minimum | What I would actually get |
|---|---|---|
| Camera | one 1080p webcam overhead | **Kinect v2 + one 1080p/4K webcam** |
| PC | 4-core i5/Ryzen 5, 8 GB | the same; no GPU needed |
| Display | anything with a browser | a touchscreen or tablet on the rail |
| Projector | none — it is optional | short-throw, 2500+ lumens, ceiling |
| Paper | — | four printed markers (free, see below) |
| Software | Python 3.10+ and numpy | plus `opencv-python` for the camera |

```bash
pip install numpy opencv-python
```

Ultralytics/PyTorch is only needed if you later switch to a YOLO detector,
and is a few gigabytes. Start without it.

## The five things that actually matter

In descending order of how much they affect accuracy, measured:

1. **How the camera is calibrated.** Clicking corners by hand: 1 px of error
   costs 1.6 mm on the cloth, 3 px costs 5.4 mm, 8 px costs 11.5 mm with
   outliers past 40 mm. Four printed markers cost about **1 mm, every time**.
   This is the single biggest lever and it is free.
2. **Where the camera is.** High and central if you can. Parallax at the far
   corner is 20 mm at 1.8 m and 12 mm at 3 m; a corner mount roughly doubles
   it.
3. **Lighting.** Diffuse and from the sides. A hanging pool lamp is the worst
   case for all three of camera, projector and detector.
4. **Rigidity.** A knocked camera silently invalidates everything — unless
   you leave the markers up, in which case it heals itself.
5. **Which detector.** Colour is fine on a well-lit table; depth ignores
   light entirely; YOLO is the heavyweight option.

## Step by step

### 1. Mount the camera

Over the middle of the table if nothing is in the way, as high as the
ceiling allows. **If a light hangs over the table**, read
[HARDWARE.md](HARDWARE.md) first: a typical fixture shadows 84% of the
table's length from a camera at 2.2 m, so the camera has to go off to one
side and you will want two.

Fix it to a joist, not a lamp.

### 2. Print the markers

```bash
python -m poolarena markers
```

Print the sheet, cut out the four markers, and tape each one flat on the
cloth just inside the corner it names, with its **outer** corner on the
cushion corner. 60 mm markers are enough; bigger is easier.

Leave them taped down. They cost nothing and they let the camera notice when
it has been nudged.

### 3. Calibrate the camera

```bash
python -m poolarena calibrate --markers
```

Or in the UI: **Setup → Camera → Calibrate from markers**.

No markers? The same tab does it by hand, with a magnifier and arrow-key
nudge, and tells you the error afterwards. Under 5 mm is good; over 15 mm,
do it again.

### 4. Check it, which takes ten seconds

```bash
python -m poolarena run --source auto
```

Open the overlay and press `b`. The system draws where it thinks each ball
is. On a good calibration those land exactly on the real balls. **This is
the only ground truth that matters** — if they sit 2 cm off at one end, the
calibration is wrong, not the detector.

### 5. Tell it about your table

`config/table.json`: size, `cloth` colour (the projected palette is chosen
from it), and `ball_set` — `english` for reds and yellows, `american` for
numbered. Measure the playing surface rather than trusting the nominal size.

### 6. Play

```bash
python -m poolarena run --source auto --game uk8 --no-projector
```

The scoreboard is at `/scoreboard.html`. Without a projector the guides are
drawn there instead of on the cloth, so every game still works.

## Camera options, ranked

| Setup | Verdict |
|---|---|
| **Kinect v2 + 1080p/4K webcam** | Best for a lit, shadowed room. Depth finds balls regardless of light; colour names them; depth also answers "is someone leaning over the table?" |
| **2 × HD webcams** | Best value, and the right answer if a light forces both cameras off-axis. |
| **1 × 4K webcam** | Simplest, and the most pixels per ball. Fine on an evenly lit table. |
| **1 × Kinect v2** | Workable. 1080p colour plus depth, in one device you may already own. |
| **2 × Kinect v2** | **Avoid.** Each needs its own USB 3 controller and their infrared interferes. |

Add a second camera to see past people and around glare — not for accuracy.
Parallax, the accuracy argument usually given for two, is cheaper to fix in
software with one.

## Detector options

| | Needs | Good at | Bad at |
|---|---|---|---|
| **Colour** (default) | nothing | a lit table; reds and yellows especially | deep shadow, glare |
| **Depth** (`--depth-balls`) | a Kinect | *where* balls are, under any light | saying which ball |
| **YOLO** (`--weights`) | ~1 GB of PyTorch | tight racks, poor light | needs a trained model |

Depth and colour together is the strong combination: depth says where, colour
says which. Balls that colour loses to a shadow still appear, marked
located-but-unidentified, so they are not scored as potted.

## Watching games back

Every game is recorded to `recordings/` as it is played — one JSON file per
frame, written shot by shot so a session that ends unexpectedly is still
usable. `--no-record` turns it off.

Open **Review** from the scoreboard. Pick a game and it replays shot by
shot, animating the path each ball actually took, because the detector
samples positions while the balls are rolling. Space plays and pauses, the
arrow keys step a shot at a time.

The figures are chosen to answer "where am I losing frames" rather than to
fill a page:

| | why it is there |
|---|---|
| Pot rate | shots that potted something, not balls potted — two on one shot is one shot |
| Fouls, and which kind | how you hand the table over, and the habit to fix first |
| Cue ball moved | the closest single number to position play; good position means moving it less and still having a shot |
| Best run | the one everybody wants to know |

## The manual

There is a manual inside the app at `/manual.html`, linked from the
scoreboard. It covers the same ground as these docs in the order you need it
at the table, and it works with no network.

## If something is wrong

| Symptom | Likely cause |
|---|---|
| Discs (`b`) are offset at one end | calibration — redo it with markers |
| Balls missing in the corners | lighting gradient, or the camera cannot see them |
| A ball vanishes and "pots" itself | glare, or a shadow edge; try `--depth-balls` |
| Everything drifts after a knock | recalibrate; leave the markers up next time |
| Scores wrong after a misread | **Undo** in the top bar, then the +/- on the player card |
| Nothing is detected at all | the cloth colour model — run with `--learn-cloth` on an empty table |
