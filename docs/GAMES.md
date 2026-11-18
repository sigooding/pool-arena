# Games

```bash
python -m poolarena games
```

| name | title | players | what it is |
|---|---|---|---|
| `8ball` | 8-Ball | 2 | American rules: open table, group on the first legal pot, called pocket on the 8 |
| `uk8` | English 8-Ball | 2 | UK World Rules: **two shots** after a foul, no called pocket |
| `blackball` | Blackball | 2 | International code: one shot with a **free shot** after a foul |
| `9ball` | 9-Ball | 2–4 | Lowest ball first, pot the 9 to win, combos count |
| `cutthroat` | Cut-Throat | 3 | Own five balls, pot everyone else's, last one with balls wins |
| `killer` | Killer | 2–8 | Pot on your turn or lose a life |
| `hotspots` | Hotspots | 1–6 | **Projector-native.** Route object balls through glowing zones |
| `roulette` | Pocket Roulette | 1–6 | **Projector-native.** The table picks which pocket you must use |
| `position` | Position Drill | 1–4 | **Projector-native.** Pot, then stop the cue ball in the ring |

## UK rules

`uk8` and `blackball` are not the American game with different coloured balls.
What actually differs in play:

- **no called pocket on the black** — American 8-ball nominates one;
- **potting an opponent's ball is a foul**, not just a wasted shot;
- **the foul penalty is not simply ball in hand.** English 8-ball gives the
  incoming player *two visits*: miss with the first and you are still at the
  table. Blackball gives one visit with a *free shot*, on which any ball may
  be struck first — which is why a snooker is worth much less in Blackball.

**A warning before anyone argues over a frame.** UK pub and league rules
genuinely vary, by league, by county and by pub. What is implemented is the
two common published codes, and the points they disagree on are options, not
assumptions baked into the code:

| option | `uk8` | `blackball` | meaning |
|---|---|---|---|
| `foul_visits` | 2 | 1 | shots the incoming player gets after a foul |
| `free_shot` | false | true | may the first ball struck be anything? |
| `break_balls_to_rail` | 2 | 2 | balls that must reach a cushion on a dry break |

Set them like any other option:

```json
{"type": "start_game", "game": "uk8",
 "players": ["Sam", "Alex"], "options": {"foul_visits": 1}}
```

If your league plays something these cannot express, the rule set is one file
— see "Writing one" below.

## Ball sets

Two worlds, and they are not interchangeable:

| | American | English (blackball) |
|---|---|---|
| balls | 15 numbered, 1-7 solid, 9-15 striped | 7 reds, 7 yellows, 1 black |
| identity | every ball is distinguishable | balls within a colour are identical |
| groups called | solids / stripes | reds / yellows |

Set it in `config/table.json` or with `--ball-set english`.

Internally the numbering is the same either way — reds take 1-7, yellows
9-15, black is 8 — so the rule sets, the event detector and every projected
effect work unchanged. Only the labels and the detector's colour model differ.

What that cannot paper over is identity. In an English set those numbers are
labels the tracker hands out, not something a camera (or a player) could read
off the ball. Any game that needs real identity is therefore **refused rather
than quietly scored wrong**:

| game | American | English |
|---|---|---|
| 8-ball, killer, hotspots, roulette, position | yes | yes |
| 9-ball, cut-throat | yes | **no** — needs numbered balls |

If you write a game that only cares about colour or count, set
`needs_numbered_balls = False` on the class and it becomes available to both.

## Options

Passed as a dict to the game, or over the websocket:

```json
{"type": "start_game", "game": "hotspots",
 "players": ["Sam", "Alex"], "options": {"target": 40, "zones": 4}}
```

| game | option | default | meaning |
|---|---|---|---|
| `8ball` | `call_pocket` | `true` | must call the pocket for the 8 |
| `9ball` | `show_aim` | `false` | project the aiming line |
| `killer` | `lives` | `3` | starting lives |
| `hotspots` | `target` | `25` | points to win |
| `hotspots` | `zones` | `3` | zones lit at once |
| `hotspots` | `radius` | `150` | zone radius in mm |
| `roulette` | `target` | `10` | points to win |
| `position` | `shots` | `10` | shots in a round |
| `position` | `radius` | `170` | target ring radius in mm |
| `position` | `show_aim` | `true` | project the aiming line |

## Writing one

A game is one file in `poolarena/rules/`. It gets two resting table states and
what happened between them, and returns a verdict plus effects.

```python
from ..types import Effect, ShotResult
from .base import Game, ShotContext, register


@register
class LastPocket(Game):
    """Pot in the same pocket as your previous ball, or the turn passes."""

    name = "lastpocket"
    title = "Last Pocket"
    description = "Keep using the same pocket"
    min_players = 2
    max_players = 4

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.locked = {}          # player index -> pocket id

    def on_turn_start(self, state):
        pid = self.locked.get(self.turn)
        if not pid:
            return []
        return [Effect("pocket_glow",
                       {"pocket": pid, "persist": True, "label": "YOURS"},
                       layer="guide")]

    def on_shot(self, ctx: ShotContext) -> ShotResult:
        ev = ctx.events
        if ev.cue_scratched:
            return ShotResult(foul="scratch", turn_passes=True,
                              ball_in_hand=True,
                              effects=self.foul_effects("scratch"))
        if not ev.pocketed:
            return ShotResult(turn_passes=True, message="miss")

        want = self.locked.get(self.turn)
        used = ev.pocketed_in.get(ev.pocketed[0])
        if want and used != want:
            return ShotResult(turn_passes=True, message=f"wrong pocket ({used})",
                              effects=[Effect("pocket_reject", {"pocket": used})])

        self.locked[self.turn] = used
        self.shooter.score += len(ev.pocketed)
        return ShotResult(message=f"+{len(ev.pocketed)} in {used}",
                          effects=self.celebrate(ctx))
```

Import it in `rules/__init__.py` and it shows up everywhere.

### What you get for free

From `Game`:

- `self.players`, `self.turn`, `self.shooter`, `self.next_turn()`
- `self.celebrate(ctx)` — pocket glow and burst for everything just potted
- `self.foul_effects(reason)` — red flash plus a reason banner
- `self.win_effects(winner)` — fireworks
- `self.pocket_pos(pocket_id)` — table coordinates of a pocket
- `self.scoreboard()` — the dict the tablet renders

From `ctx.events`:

- `pocketed`, `pocketed_in` (ball → pocket id), `cue_scratched`
- `first_contact`, `rails_after_contact`, `cue_struck`
- `trace` — per-ball paths, which is how zone games know what rolled where

### Testing it

No hardware needed. `tests/helpers.py` builds states and events by hand:

```python
def test_wrong_pocket_passes_the_turn():
    g = get_game("lastpocket")(players=["A", "B"], table=TABLE)
    g.locked[0] = "TR"
    before = state(b0=(400, 600), b3=(1800, 300))
    after = state(b0=(1600, 350))
    res = play(g, before, after,
               events(pocketed=[3], pockets={3: "BL"}, first=3))
    assert res.turn_passes
```

### Designing for the projector

The games worth building here are the ones that cannot exist without light on
the cloth. Three patterns that work:

1. **Make the table set the task.** Roulette names your pocket; nothing on a
   scoresheet can do that.
2. **Score the journey, not just the result.** Hotspots cares where the ball
   *rolled*, which only a tracked table can know.
3. **Grade in millimetres.** Position Drill tells you that you were 84 mm long.
   A coach cannot measure that; a camera can.

See `docs/PROJECTION_IDEAS.md` for the longer list.
