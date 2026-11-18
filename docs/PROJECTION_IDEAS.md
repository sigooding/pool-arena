# Projection ideas

Things worth projecting onto a pool table, roughly in the order I'd build them.
Each is tagged with what it needs, because the hard part is almost never the
animation — it is knowing *when* to play it.

Built ones are marked ✅ and live in `overlay/src/effects.js`.

## Feedback: reacting to what just happened

These need only the event detector, which already works.

- ✅ **Pocket flare.** The pocket that just ate a ball lights up and throws a
  burst back onto the cloth. Scale the intensity with how many balls dropped,
  so a two-ball shot genuinely looks better than a one-ball shot.
- ✅ **Ball trails.** A comet tail behind every moving ball. Cheap, constant,
  and the single thing that most makes the table feel alive — it is on by
  default rather than saved for big moments.
- ✅ **Foul flash.** A short red wash across the whole cloth, plus the reason
  in text. Players stop arguing about fouls when the table says why.
- ✅ **Win fireworks.** Random bursts over the whole table for four seconds.
- **Break meter.** Measure cue-ball speed from the first two frames after the
  strike and throw a number on the cloth: "11.2 mph". Costs nothing, and
  everyone will want a go. Needs: frame timing you already collect in the trace.
- **Shot replay on the cloth.** After a good shot, re-draw the actual ball
  paths as glowing lines, one after another, so the table replays itself.
  Needs: the trace, which `ShotEvents.trace` already carries.
- **Heat map at end of game.** Where did the cue ball spend the night? Fade a
  warm blob map over the cloth during the rack-up. Needs: logged traces.

## Guides: showing where to aim

The legality question matters here — most leagues ban aiming aids in matches.
Keep these on practice and party modes, which is why they live in the game
classes rather than being always-on.

- ✅ **Ghost ball + aim line.** A dashed line from cue to the contact point, a
  white ring where the cue ball must arrive, a solid line from object ball to
  pocket, and the cut angle in degrees.
- ✅ **Tangent line.** The grey perpendicular showing where the cue ball goes
  *after* contact. More useful to an improving player than the aiming line,
  and much less often shown.
- **Rail bank preview.** Reflect the aiming line off cushions for one, two or
  three rails. Needs: nothing new, just mirrored geometry.
- **Cue-direction live line.** Track the cue stick itself, not just the balls,
  and draw the line the player is actually on, live, as they move. This is the
  killer feature and the hardest one — the cue is thin, fast, and held over the
  table where your obstruction detector is busy saying "ignore this frame".
  Needs: a dedicated cue detector (a Hough line over the obstruction mask is
  the cheap first attempt) and lighting that does not throw a cue shadow.
- **Safety suggestion.** Highlight the ball to hide behind. Needs: a shot
  evaluator; `shot_candidates()` is the start of one.

## Games that only exist because of the projector

This is the part no app on a phone can do, and where I'd spend the time.

- ✅ **Hotspots.** Glowing zones on the cloth; route an object ball through one
  on the way to a pocket and the zone's value is added. Zones re-light every
  shot, so position play is the whole game. Works with any number of players
  and does not care about ball numbers, which matters when detection is shaky.
- ✅ **Pocket Roulette.** A wheel spins across the pockets and names the one you
  must use this shot. Destroys good players' habits, which is exactly the point
  at a party.
- ✅ **Position Drill.** Pot a ball, then stop the cue ball inside the projected
  ring. Graded in millimetres, scored out of ten, ten shots a round. This is the
  one that will actually make someone better.
- **Territory.** The table is divided into glowing regions. Pot from inside a
  region and you claim it; claimed regions change colour. Last region standing
  wins. Needs: a region map and the cue ball's resting position, both of which
  exist.
- **Ghost opponent.** Project the path of a recorded shot — your own best run
  from last week, or a pro clearance — and race it. Needs: stored traces and a
  way to re-spot balls to match, which means telling players where to place
  them, which the projector is good at.
- **Pandemic / spreading stain.** A patch of "infection" grows across the cloth
  every shot. Potting burns it back. Lose when it covers the table. Purely
  cosmetic state, so it is easy, and it is the kind of thing people photograph.
- **Timed pressure.** A shrinking ring around the cue ball counts down the shot
  clock. Visible to everyone, no arguments.
- **Darts-style 501 on a pool table.** Each pocket is worth a different,
  projected, re-rolling score. Hit exactly zero to win. Needs nothing new.

## Ambience

- **Idle attract mode.** Slow drifting light on an unused table, pulled into a
  sharp "ready" state when a ball moves. Good for a bar.
- **Player colours.** Each player owns a hue; their turn washes the rails in it.
  Already half-built via `spotlight`.
- **Re-rack guide.** Project the triangle outline on the foot spot, with each
  ball's position numbered, so anyone can rack correctly. Trivially easy and
  genuinely useful.
- **Call-pocket by hand.** ✅ The pockets are labelled on the cloth; the shooter
  taps one on the tablet. Tracking a pointing hand would be better and is a
  Kinect depth job, not a colour job.

## What to be careful about

- **Light on a ball is light the camera sees.** Anything projected onto a ball
  changes its colour, and your detector classifies by colour. Either keep
  effects off ball positions (what the guide layer does), or run detection on a
  frame where the projector is dark. If it becomes a real problem, the clean
  fix is to sync: blank the projector for one frame in every six and detect only
  on those. It costs nothing visually and solves the problem permanently.
- **Black is your only "off".** A projector cannot subtract light. Every pixel
  that is not an effect must be pure black, which is why the overlay clips
  everything to the table quad.
- **Mount it where a cue cannot reach it.** Short-throw unit on the ceiling,
  not on a shelf at the end of the table, or the first break of the night with
  a tall player will find it.
- **Shadows.** A single projector over a table means the player's own body
  casts a shadow over the shot they are lining up. You cannot fix this with
  software. Two projectors from opposite corners mostly cancel it, at the cost
  of a second calibration.
