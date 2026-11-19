# Pool Arena

Camera scoring and projected games for a real pool table.

One overhead camera watches the table, works out what happened on each shot,
and a projector draws the consequences back onto the cloth — pockets flare
when a ball drops, aiming lines appear for practice modes, and whole game modes
exist that could not work without light on the table.

**It runs with no hardware.** A built-in simulator drives the entire stack, so
you can see every animation and play every game mode before you mount anything.

```bash
git clone <your-remote> pool-arena && cd pool-arena
pip install numpy
python -m poolarena demo
```

Then open <http://localhost:8777/> for the projector view and
<http://localhost:8777/scoreboard.html> for the tablet.

![The projector overlay: aiming line with ghost ball and tangent line, lit pocket, particles](docs/overlay.png)

Leave it alone and it plays a ghost game of pool with itself until someone
racks up:

![Attract mode: ghost balls with comet tails and a caption reading RACK UP](docs/attract.png)

The tablet on the rail shows the live table, the roster as actual balls, and a
colour-coded shot feed:

![The scoreboard: live top-down table, player cards, shot feed](docs/scoreboard.png)

## What works today

- **Scoring** for 8-ball, 9-ball, cut-throat, killer and both UK codes —
  English 8-Ball (two shots after a foul) and Blackball (free shot) — with
  fouls: wrong ball first, scratch, no rail after contact, black early,
  potting the opponent's ball, illegal break.
- **Four party and practice modes** — Hotspots, Pocket Roulette, a graded
  Position Drill and Time Bomb — built around the projector rather than
  bolted onto a normal frame.
- **Time Bomb**: thirty seconds on the clock, every ball you pot buys you
  more, and the rack goes up when it runs out. The clock stops at the moment
  the cue was struck, not when the balls stopped rolling, so a long pot
  played in time still counts. Plays with reds and yellows.
- **27 projected effects**: pocket flares, explosions, ball trails, ghost-ball
  aiming lines with the tangent line and cut angle, glowing zones, a
  countdown clock, fireworks, lightning, on-cloth banners.
- **Both calibrations in the UI, no terminal.** Setup → Camera finds the
  camera, takes a picture and takes four taps to learn where the table is;
  Setup → Projector nudges the projected outline onto the cushions. Works on
  a PC touchscreen, a tablet or a phone.
- **A tablet scoreboard** with a live top-down table view, drawn from the same
  state stream, that works from a phone up to a wall display — including a
  calibration pad that drives the projector, so you align it standing at the
  table rather than at the PC.
- **Both ball sets**: American numbered 1-15, or English reds and yellows
  (`--ball-set english`). Games that genuinely need numbered balls are refused
  on an English set rather than scored by guesswork.
- **A simulator** good enough to develop and demo the whole system without a
  camera, a projector or a table.
- **Undo, redo and manual score correction.** Undo is in the top bar, not
  buried in settings — it rewinds whose turn it is, group assignment, UK
  visits and a frame the table wrongly called as won. Per-player +/- buttons
  cover the other half: undo restores the old score, but only you know the
  right one.
- **A palette computed for your cloth.** A projector's light is multiplied by
  what the cloth reflects, so red is nearly invisible on green and fine on
  pale blue. Set `cloth` in `config/table.json` (or `--cloth "#8FB7D9"`) and
  the overlay picks a palette measured against that surface.
- **An attract mode.** Leave the table alone and it starts playing a ghost
  game of pool with itself, captioned with how to begin and what games it
  knows. A ball moving — or an arm over the cloth — clears it instantly.
- **A detector installer in the UI.** Setup → Detector installs YOLO support
  and takes a trained model from a link or a file, then tests it on a real
  camera frame. You do not need a GPU: detection runs once per shot on a
  still table. It says plainly that a `.pt` file runs code when loaded.
- **One camera or several.** A second camera is an option, not a rewrite:
  each keeps its own calibration and the views are fused in table
  millimetres. It buys seeing past a player leaning over the cloth, not
  better numbers — see [docs/HARDWARE.md](docs/HARDWARE.md) for which
  combination is worth buying and which to avoid.
- **Scoring without a projector.** `--no-projector` and the guides that
  would have been on the cloth — live zones, the nominated pocket, aiming
  lines — are drawn on the scoreboard's table view instead, so the
  projection-native games stay playable.
- **Depth-based ball finding** (`--depth-balls`). A Kinect's depth stream
  has no illumination term at all, so shadows, glare and cloth colour cannot
  affect it: depth says where the balls are, colour says which ball each one
  is. Found every ball on synthetic frames at noise several times worse than
  the real sensor.
- **Calibration from printed markers.** Four ArUco markers taped to the
  cloth calibrate the camera to about 1 mm — better than a careful human
  click and far better than a typical one — and if you leave them up, a
  camera that gets knocked re-calibrates itself.
- **Every game recorded, and playable back.** The Review page replays a
  session shot by shot, animating the path each ball actually took, with the
  figures that tell you where frames are going: pot rate, which foul you
  commit most, how far you move the cue ball, best run.
- **A manual built into the app**, at `/manual.html`, so it is there at the
  table without a phone or a network.
- **Ball-in-hand checking.** After a foul the legal area is marked on the
  cloth, and where the cue ball is actually put back is judged — on the
  table, not touching anything, and in the right half if your rules say so,
  with the nearest legal spot offered when it is wrong.
- **Sound**, synthesised in the browser: no files to ship or license.
- **Cue tracking** (`--cue-line`, experimental): the line the player is
  actually on, projected live, with what it will hit.
- **Nothing lost on a restart.** `--resume` picks up a frame that was
  interrupted, and career totals span every recording.
- **373 tests** covering geometry, shot detection, every rule set, the full
  pipeline end to end, and the overlay's own effect timings (those run the
  JavaScript under node, and skip if node isn't installed).

## Windows: double-click to run

```
windows\setup.bat       once, to install what it needs
windows\demo.bat        no camera needed
windows\calibrate.bat   teach it where the table is
windows\check.bat       is the camera good enough?
windows\start.bat       the real thing
```

No terminal and no typing; the window stays open and explains itself if
something goes wrong. See [windows/README.md](windows/README.md) — including
a note on what has and has not been tested there.

## Before your first game

```bash
python -m poolarena doctor
```

Walks the chain from the lens to a list of balls and puts a number on every
link — frame rate, calibration error in millimetres, how much of the table
reads as cloth, how many balls are found, how far a *still* ball wanders
between frames, whether the colours can be told apart. It changes nothing and
starts no game, so it is safe to run mid-setup and safe to run twice:

```bash
python -m poolarena doctor --source cam:0
python -m poolarena doctor --source kinect --depth-balls
```

Two reports, same numbers, and the better camera is the one with the better
numbers rather than the one that felt better. The check that matters most is
**stability**: a still ball that wanders more than a few millimetres means
the table never reads as settled, and shots never resolve.

## What doesn't, yet

- The colour detector is written and reasonable but **has not been tuned
  against a real table** — that needs your cloth, your lights and your camera.
  This is the one part of the system that has never met real hardware, and
  everything downstream depends on it. Run `python -m poolarena doctor`
  before your first game; expect to spend an evening on
  `config/detector.json`.
- **Live cue-stick tracking is experimental.** It is built and switched on
  with `run --cue-line`, and it recovers the cue's angle to a twentieth of a
  degree on synthetic frames — but it has never seen a real cue, and a real
  cue has a hand and a forearm next to it. Treat it as a thing to try, not a
  thing to rely on.
- **Parallax correction is off by default.** The maths is right and unit
  tested, but it could not be validated end to end here, so it stays off
  until a real table can show it helps. See `docs/VISION.md`.
- **UK rules vary by league.** The two published codes are implemented and
  their differences are options, but your pub may play something else; see
  [docs/GAMES.md](docs/GAMES.md).

## When the table gets a shot wrong

It will, especially before the detector is tuned. Two controls, both in the
scoreboard page:

- **Undo** (top bar) takes back the last judged shot. It rewinds the whole
  game state — the score, whose turn it is, which group each player owns, UK
  two-visit state, and a frame that was wrongly called as won. Press it
  repeatedly to go further back. **Redo** appears if you overshoot.
- **+ / −** on each player card sets a score by hand. Undo puts the old score
  back but cannot know what the right one was; this is the override for when
  the camera called it and the answer is simply a different number.

Undo rewinds the *score*, not the table. The balls stay where they physically
are, so the next real shot is judged from the current layout — which is what
you want when the system got one wrong and play has moved on.

## Commands

```bash
python -m poolarena demo                        # simulated table, no hardware
python -m poolarena demo --game hotspots --players "Sam, Alex"
python -m poolarena calibrate --source kinect   # click the four cushion corners
python -m poolarena run --source kinect --game 8ball
python -m poolarena run --source cam:0 --learn-cloth
python -m poolarena games                       # list game modes
python -m poolarena effects                     # list projector effects
python -m poolarena replay shots.jsonl          # re-run a logged session
```

Overlay keys: `c` calibration, `b` draw tracked balls, `f` fullscreen,
`t` trails, `o` clipping, `x`/`g` test effects, `h` help.

## Hardware

**If a light hangs over your table, read
[docs/HARDWARE.md](docs/HARDWARE.md) before buying anything.** A traditional
pool light shadows about 84% of the table's length from a ceiling camera, so
a single overhead camera is not viable while it is there, and it blocks the
projector too.


An overhead camera, a PC, a short-throw projector on the ceiling. A Kinect v2
works well: its 1080p colour stream is plenty, and its depth stream — useless
for resolving balls — is ideal for spotting an arm over the cloth.

Scoring reads the table when it is **still**, so 30 fps is plenty and nothing
needs to be fast. See [docs/HARDWARE.md](docs/HARDWARE.md) for mounting, USB
pitfalls, lighting, and why the projector's own keystone correction should stay
off.

## How it fits together

```
  camera ──► vision ──────► events ──────► rules ──────► overlay
             (pixels)       (shots)       (verdicts)     (light)
                 │              │             │              ▲
                 └──────────────┴─────────────┴──────────────┘
                        everything speaks table millimetres
```

Vision is the only layer that imports OpenCV. Everything above it — shot
detection, every game, every animation — runs and is tested without a camera
installed. A new game is one file and one method; it never sees a pixel.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the reasoning, including
why first contact is inferred from motion onset rather than proximity (at 30 fps
a ball moves 100 mm between frames, so a "were they touching?" test simply
misses collisions).

## Docs

- **[Setting it up](docs/SETUP.md)** — start here: requirements, camera
  options, and the five things that actually affect accuracy

- [Architecture](docs/ARCHITECTURE.md) — the layers and the decisions behind them
- [Hardware](docs/HARDWARE.md) — cameras, the Kinect, PC specs, projector, lighting
- [Calibration](docs/CALIBRATION.md) — the two homographies, and how to check them
- [Games](docs/GAMES.md) — the rule sets, their options, and how to write one
- [Projection ideas](docs/PROJECTION_IDEAS.md) — the backlog of things worth projecting

## Prior art

- [pooltool](https://github.com/ekiefl/pooltool) — proper billiards physics.
  Use it if you need real simulation; `poolarena/sim` is deliberately crude.
- [Fergus-Gault/Pool-Ball-Tracker](https://github.com/Fergus-Gault/Pool-Ball-Tracker)
  — YOLO tracking with obstruction handling.
- [Rainbowman0/YOLOv5-BilliardsDetection](https://github.com/Rainbowman0/YOLOv5-BilliardsDetection)
  — training data for American pool balls, which would save labelling work if
  you switch the detector to YOLO.

## Tests

```bash
python -m pytest tests/ -q
```

## Licence

MIT.
