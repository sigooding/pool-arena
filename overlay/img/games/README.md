# Game card artwork

Drop a file in here named after the game and the picker uses it. Nothing
else to change — the server lists what is here and the card picks it up.

| file | game |
|---|---|
| `8ball.webp` | 8-Ball |
| `9ball.webp` | 9-Ball |
| `uk8.webp` | English 8-Ball |
| `blackball.webp` | Blackball |
| `cutthroat.webp` | Cut-Throat |
| `hotspots.webp` | Hotspots |
| `killer.webp` | Killer |
| `roulette.webp` | Pocket Roulette |
| `position.webp` | Position Drill |
| `timebomb.webp` | Time Bomb |

**The picture is the whole card.** A title baked into the artwork is fine —
titles never change — so where a file exists the card does not draw its own,
and the picture fills it edge to edge.

What the picture cannot carry is anything that changes, and two things do: a
game goes unplayable when the table is set to reds and yellows, and a
projector-only game has to say where its guides went. Those appear as a badge
over the bottom of the artwork, and only when there is something to say.

**5:3, around 900 px wide.** The card is about 250 px across on a tablet, so
900 is sharp on a retina screen with room to spare; bigger is just a slower
page. The badge sits over the bottom eighth, so keep anything important out
of that strip.

A game with no file here is not broken: it gets an accent-coloured glow
drawn in CSS instead, in that game's colour, which stays sharp at any size.
So the picker never has a hole in it while artwork is being made, and you
can add them one at a time.
