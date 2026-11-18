# Architecture

Four layers. Each one only knows about the layer below it, and the boundary
between vision and everything else is the whole point of the design.

```
  camera ──► vision ──────► events ──────► rules ──────► overlay
             (pixels)       (shots)       (verdicts)     (light)
                 │              │             │              ▲
                 └──────────────┴─────────────┴──────────────┘
                        everything speaks table millimetres
```

## 1. Vision — `poolarena/vision/`

Frames in, `TableState` out.

- `source.py` — one interface over a Kinect v2, a webcam, a video file or a
  still. Swapping cameras touches nothing else.
- `calibrate.py` — click four cushion corners once, get a homography.
- `detect.py` — find balls and name them. Either classic colour CV (no
  training, no GPU) or a YOLO model, behind the same interface.
- `pipeline.py` — warp to top-down, detect, carry identities between frames,
  decide whether the view is obstructed.

This is the only layer that imports OpenCV. Everything above it runs, and is
tested, with no camera installed.

**Why warp first.** In the warped top-down view a ball is the same size
everywhere and one pixel is a fixed number of millimetres. Detection thresholds
and tracking gates become constants instead of functions of position.

## 2. Events — `poolarena/events/detector.py`

A stream of `TableState` in, one `ShotEvents` per shot out.

Rest-state driven: snapshot the table when still, watch the motion, read the
result when still again. This is what makes 30 fps hardware viable — we never
need to see a collision happen, only its consequences.

Two decisions worth knowing about:

- **First contact comes from motion onset, not proximity.** At 30 fps a ball
  at 3 m/s moves 100 mm between frames, so a "were they touching?" test misses
  collisions outright. "Which object ball twitched first" survives a low frame
  rate and is right nearly always.
- **Obstruction suspends, it does not reset.** An arm over the table does not
  end the shot; it just means those frames are not trusted.

## 3. Rules — `poolarena/rules/`

`ShotContext` (two resting states + the events) in, `ShotResult` out: a foul or
not, whose turn it is, who won, and **a list of projector effects**.

A game is one file and one method. It never sees a pixel, a camera or a
websocket, which is why `tests/test_games.py` can test the 8-ball rule set with
hand-written positions and no hardware at all.

```python
@register
class MyGame(Game):
    name = "mygame"
    title = "My Game"

    def on_turn_start(self, state):
        return [Effect("highlight_balls", {"balls": [1], "color": "#4ade80"},
                       layer="guide")]

    def on_shot(self, ctx):
        if ctx.events.cue_scratched:
            return ShotResult(foul="scratch", turn_passes=True,
                              effects=self.foul_effects("scratch"))
        return ShotResult(effects=self.celebrate(ctx))
```

Add it to the imports in `rules/__init__.py` and it appears in the CLI, the API
and the scoreboard dropdown.

## 4. Overlay — `overlay/`

A browser page, fullscreen on the projector output.

- `view.js` — the second homography: table millimetres to projector pixels,
  set by dragging four corners. Also the on-screen calibration grid.
- `effects.js` — every animation, keyed by name. Effects draw in millimetres
  and are handed the live scene, so an effect attached to a ball follows it.
- `main.js` — websocket, render loop, layer order, ball trails, debug view.
- `board.js` + `board.css` — the tablet scoreboard, a separate page with its
  own stylesheet. The projector needs pure black and no chrome; a tablet needs
  the opposite, and sharing one sheet made both worse.
- `balls.js` — the design system. Every colour in the interface is a real ball
  colour, and both the tablet's live table and the projector's alignment view
  draw balls through the same function, so a 9-ball looks like a 9-ball in
  both places.
- `minitable.js` — the live top-down table on the tablet, fed by the same
  state stream the projector uses.

**Layer order is physical, not cosmetic.** `guide` draws under the balls
(aiming lines, pocket rings, zones) so it reads as markings on the cloth; `fx`
draws over (sparks, explosions); `hud` sits on top in the dead space. Everything
is clipped to the table quad, because light that misses the table lands on the
players.

**Batch semantics.** Effects arrive in batches — one per turn start, per shot,
per game start. A batch carrying persistent effects on a layer replaces the
persistent effects already on that layer, so last turn's aiming line does not
survive into this turn, while a game that lights two things at once (cut-throat
marks your balls *and* your targets) sends them together and both stay up.

## The glue — `engine.py` and `server/ws.py`

`Engine.feed(state)` is the single entry point: it pushes state to the detector,
hands completed shots to the game, and broadcasts state, effects and the
scoreboard to every connected client.

The server is a hand-rolled HTTP + WebSocket implementation in the standard
library — about 200 lines — so the pool-room PC needs nothing but CPython and
numpy. No pip install to go wrong on a machine you touch twice a year.

## The simulator — `poolarena/sim/`

A crude billiards model: no spin, no throw, no cushion compression. It exists
so the entire stack can be developed and demoed with no camera, no projector
and no table, and so the integration tests can play whole games in 0.3 s.

For real physics, use [pooltool](https://github.com/ekiefl/pooltool).

## Message protocol

Server to client:

| type | payload | sticky |
|---|---|---|
| `table` | dimensions and pocket positions | yes |
| `state` | balls, settled, obstructed | yes |
| `effects` | a batch of `{name, args, layer}` | no |
| `scoreboard` | players, turn, log | yes |
| `shot` | the full record: events + verdict | no |
| `history` | the last 25 shots | yes |
| `undo_result` | whether an undo or redo took | no |
| `attract` | a frame of the ghost game, or `active: false` | no |

Sticky messages are replayed to a client when it connects, so opening the
overlay mid-game shows the right thing immediately.

Client to server: `start_game`, `next_turn`, `call_pocket`, `games`,
`test_effect`, `projector_calibration`, `calibrate`, `projector_nudge`,
`undo`, `redo`, `adjust_score`, `attract`, `ping`.

The scoreboard's shot feed is built from the sticky `history` message rather
than from live `shot` messages. That is what makes a page opened in the middle
of a frame show what has happened, and it means undo needs no special case in
the client: the list simply comes back shorter.

## Several cameras

`poolarena/vision/multi.py` fuses any number of cameras. Each keeps its own
`VisionPipeline` and calibration and reports table millimetres, so fusion
happens in physical units and the cameras need not match, be aligned, or be
the same kind of device.

Two rules carry most of the value. Detections from *different* cameras within
45 mm are the same ball and are merged, weighted by how near each camera is
to it — the merge radius stays below a ball diameter so a rack never
collapses into one ball, and two detections from the *same* camera are never
merged with each other. And the table is obstructed only when every camera is
obstructed, which is the main reason to hang a second one.

A rig where every camera has failed reports `obstructed`, never an empty
table: an empty table and a broken rig must not look alike, or every ball
scores as potted.

## Swapping the detector

`poolarena/models.py` installs and selects detector models. The colour
detector is the default and needs nothing; a YOLO model is an opt-in that
pulls in torch and runs a third-party checkpoint.

That second part is the reason this module is cautious rather than
convenient. A `.pt` file is a pickle, so loading one executes code from the
file: an installer that quietly fetched and ran one would be a supply-chain
hole with a friendly button on it. So downloads are restricted to an
allowlist of hosts, the URL is shown before anything is fetched, a local
path is always offered as an alternative, filenames are flattened so a
crafted name cannot escape `weights/`, and the UI states in plain words what
loading a checkpoint does. None of that makes an untrusted model safe; it
makes the decision visible, which is as far as software can honestly go.

## Attract mode

`poolarena/attract.py` runs a second simulator on a daemon thread and streams
ghost-ball frames to the overlay. It never touches the real game, so a match
paused mid-frame is safe.

Idle is judged two ways, because neither alone is enough. `Engine.feed()`
notices movement and kills the attract loop at once; a one-second heartbeat
starts it. The heartbeat is what covers a camera that has stalled or a run
loop sleeping between shots — no frames at all is about as idle as a table
gets, and an engine that only asked the question when a frame arrived would
never ask it.

## Undo

Rewinding a score cannot be computed backwards. A single shot may have
assigned ball groups, changed whose turn it is, handed out two visits, lit a
new set of zones and ended the frame — so the engine keeps a deep copy of the
game taken immediately before each shot is judged, and undo puts it back. The
copy shares the `Table`, which is geometry and never changes.

Undo rewinds the game, not the detector: the balls are wherever they
physically are, so the next real shot is judged from the current layout.
