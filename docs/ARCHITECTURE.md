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

Sticky messages are replayed to a client when it connects, so opening the
overlay mid-game shows the right thing immediately.

Client to server: `start_game`, `next_turn`, `call_pocket`, `games`,
`test_effect`, `projector_calibration`, `ping`.
