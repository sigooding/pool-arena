# Hardware

## The short version

An overhead colour camera, a PC that can run Python, and a short-throw
projector on the ceiling. Nothing exotic, and nothing that has to be fast:
scoring reads the table when it is *still*, so 30 fps is plenty.

## Camera

Pool is an easier vision problem than darts. A dart tip is small, occluded and
needs depth, which is why Autodarts uses three cameras 120° apart. A pool table
is a flat, fixed, high-contrast plane, so one overhead camera does the job.

| | Minimum | Comfortable |
|---|---|---|
| Resolution | 1080p | 1080p–4K |
| Frame rate | 30 fps | 60 fps+ (needed only for live cue tracking) |
| Shutter | rolling | global, if you want clean mid-shot frames |
| Mount height | 2.0 m above the cloth | 2.2–2.5 m |
| Lens | wide enough to see all four corners | same, with a little margin |

Mount it over the **centre** of the table, looking straight down if you can.
Off-centre is fine — the homography handles it — but the further off-axis, the
more the far corner's balls occlude each other.

### Kinect v2 (Xbox One sensor)

What you have, and it works:

- **Colour:** 1920×1080 at 30 fps, wide field of view. At ~2 m over an 8 ft
  table a ball is about 35 px across, which is comfortable.
- **Depth:** 512×424. Far too coarse to resolve balls (a ball is ~7 px), so
  this code never tries. Depth is used for one thing only, and it is a good
  thing: telling whether an arm, a cue or a body is over the cloth, which is
  exactly when colour detection should be ignored. See
  `VisionPipeline._depth_obstructed`.
- **Frame rate warning:** the Kinect's auto-exposure drops the colour stream to
  ~15 fps in dim light. Light the table properly or you will lose shots.

**USB is the fussy part.** Kinect v2 needs:

- a genuine USB 3.0 port, no hub;
- an Intel or Renesas controller. ASMedia controllers are a known source of
  dropouts. If your motherboard has one, a £15 PCIe card with a Renesas chip
  fixes it;
- its own power brick and the official USB adapter;
- a short cable run. Most powered USB 3 extenders do *not* work with it. If the
  sensor is on the ceiling and the PC is not, test the extender before you
  mount anything.

**Drivers:**

- Windows: Kinect for Windows SDK 2.0, then `pip install pykinect2`.
- Linux/macOS: build [libfreenect2](https://github.com/OpenKinect/libfreenect2)
  with OpenCL or CUDA support, then `pip install pylibfreenect2`.

`KinectV2Source` picks whichever it finds.

**Does it find the Kinect on its own?** Yes, once a driver is installed.
`--source auto` (the default for `run` and `calibrate`) tries a Kinect v2
first and falls back to the first webcam that opens, and **Setup → Camera →
Connect camera** does the same from the UI. What it cannot do is install the
driver for you: with no `pykinect2` or `pylibfreenect2` present, the sensor is
invisible to Python no matter how it is plugged in. The Camera tab says so
explicitly rather than just reporting "no camera".

**Kinect v1 (Xbox 360): don't.** At 640×480 a ball is about 14 px across.

### Reds and yellows are easier to see than a numbered set

If you have a UK blackball set, the vision problem gets markedly simpler: two
well-separated hues plus a black and a white, instead of seven hues that have
to be told apart *and* a stripe-versus-glare judgement on every ball. Run with
`--ball-set english` and the detector switches models.

The trade is that no camera can tell one red from another — so 9-ball and
cut-throat are unavailable, by design, rather than being scored by guesswork.

### A plain webcam instead

A 1080p UVC webcam works and is simpler. You lose depth-based obstruction
detection and fall back to the frame-difference method, which is less reliable
but fine. A common setup is a cheap webcam for colour *and* the Kinect for
depth, which this code supports because colour and depth travel separately
through the pipeline.

## PC

| | Minimum | Comfortable |
|---|---|---|
| CPU | 4-core i5 / Ryzen 5 | 6+ cores |
| RAM | 8 GB | 16 GB |
| GPU | integrated | RTX 3050 / 4060 class |
| OS | Windows 10/11, or Linux | either |

Without a GPU, the colour detector runs on a still frame of a resting table in
well under a second. That is all scoring needs.

A GPU buys you two things: faster Kinect depth decoding, and the headroom to
run a YOLO model per-frame if you want live mid-shot tracking (trajectories,
speed, first-contact by proximity rather than by motion onset).

The projector output wants to be a second display, set to **extend**, not
mirror. Drag the overlay window onto it and press `f` for fullscreen.

## Projector

- **Short throw** matters more than brightness. A 0.5:1 lens at 2.2 m gives you
  roughly a 2.4 m wide image, which covers an 8 ft table.
- **2500+ ANSI lumens.** Cloth is dark and eats light. Green cloth eats red.
- **Ceiling mount, well clear of a raised cue.** Centre it over the table.
- Keystone correction in the projector's own menu is the enemy of sharpness —
  leave it off and let the software homography do the work. That is what the
  four-corner calibration in the overlay is for.
- Turn off every "eco", "dynamic contrast" and "auto brightness" mode. They
  change the picture mid-animation.

## Cloth colour and the projected palette

A projector adds light to a surface that reflects it selectively, so what a
player sees is the projected colour **multiplied** by the cloth's reflectance.
A palette that works on one table can be unreadable on another, which is why
the cloth colour is a setting (`cloth` in `config/table.json`, or `--cloth`)
and the overlay picks its palette from it.

Measured as the CIE76 distance between a lit patch and the unlit cloth beside
it, with each palette also required to be separable from the others:

| cloth | unlit L* | best projected colours | avoid |
|---|---|---|---|
| pale blue `#8FB7D9` | 34 | pure green, magenta, spring `#00FFCC`, amber, rose | pale pastels, mid-blue (reads as the cloth) |
| powder blue `#6E9BC5` | 28 | magenta, green, azure, amber | red, orange, hot pink |
| tournament green `#1B6E54` | 16 | lime, yellow, white, amber | **red (nearly invisible)**, orange, pink |

![The same scene composited onto each cloth with that model](cloth-palette.png)

Two things follow that are worth knowing before you buy a projector.

**Pale cloth renders colour better than green.** A desaturated surface
reflects broadly, so hues come back faithfully: the best colours on pale blue
separate by ~80 ΔE against ~50 on tournament green. Every semantic colour the
games use clears the visibility floor on pale blue unchanged; on green, half
of them have to be substituted.

**Pale cloth has a much worse black level.** Unlit pale blue sits around
L* 34 against green's 16, and a projector cannot subtract light. "Off" is
never dark, so the dynamic range you have to play with is smaller than the
colour figures suggest, and **controlling ambient light matters more than
anything else you can do in software**. Dim the room lights and the same
effects go from washed out to vivid.

A consequence on green cloth specifically: green reflects almost no red, so
**no hue can read as an alarm there** — a magenta foul flash comes back navy.
The overlay therefore uses a near-white strobe for fouls on green and carries
the meaning in the flash pattern. On blue cloth red and rose work properly and
are used as they were intended.

## Lighting

The one thing that will cost you a weekend if you get it wrong.

- Diffuse, even, and from the sides rather than straight down.
- No bare bulbs in the camera's view, and nothing that puts a specular
  highlight on top of every ball — that white dot looks exactly like a cue ball
  to a colour detector.
- A traditional low-hanging pool light is bad for this: it puts a hot spot in
  the middle and leaves the corners dark. Two diffused strips along the long
  rails are much better.
- Whatever you choose, keep it constant. Auto-exposure chasing a changing room
  is worse than slightly bad light.

The detector compensates for uneven light by dividing out the slow brightness
gradient before thresholding (`normalise_light`, on by default). On a test
frame lit like a traditional pool table — ten times brighter in the middle
than in the corners — that is the difference between finding seven of eight
balls and finding all eight. It is a safety net, not a substitute for lighting
the table properly.
