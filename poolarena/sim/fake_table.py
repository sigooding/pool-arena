"""A small billiards simulator, good enough to drive the whole stack.

This is not a physics project — pooltool exists for that. It is deliberately
crude (no spin, no throw, no cushion compression) because its only job is to
emit believable TableState streams so the event detector, the rules engines and
every projector effect can be built and demoed with no camera in the room.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..geometry import Table, shot_candidates
from ..types import Ball, TableState, kind_of

DT = 1.0 / 240.0          # physics step
FRICTION = 0.48           # m/s^2-ish, tuned by eye against real roll-out
CUSHION_LOSS = 0.82
BALL_LOSS = 0.96
STOP_SPEED = 12.0         # mm/s below which a ball is parked


@dataclass
class _B:
    number: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    live: bool = True


@dataclass
class FakeTable:
    table: Table = field(default_factory=Table)
    rng: random.Random = field(default_factory=random.Random)
    balls: list[_B] = field(default_factory=list)
    t: float = 0.0
    fps: float = 30.0
    obstruct_until: float = -1.0

    # --- setup -------------------------------------------------------------
    def rack(self, game: str = "8ball") -> None:
        """Triangle rack on the foot spot, cue ball on the head spot."""
        self.balls = []
        r = self.table.ball_radius
        fx, fy = self.table.foot_spot
        if game == "9ball":
            order = [1, 2, 3, 9, 4, 5, 6, 7, 8]
            rows = [1, 2, 3, 2, 1]
        else:
            order = [1, 9, 2, 8, 10, 3, 11, 7, 14, 4, 5, 13, 15, 6, 12]
            rows = [1, 2, 3, 4, 5]
        i = 0
        for row, count in enumerate(rows):
            for k in range(count):
                if i >= len(order):
                    break
                x = fx + row * r * 1.75
                y = fy + (k - (count - 1) / 2) * r * 2.05
                self.balls.append(_B(order[i], x, y))
                i += 1
        hx, hy = self.table.head_spot
        self.balls.insert(0, _B(0, hx, hy))
        self.t = 0.0

    def place(self, number: int, x: float, y: float) -> None:
        for b in self.balls:
            if b.number == number:
                b.x, b.y, b.vx, b.vy, b.live = x, y, 0.0, 0.0, True
                return
        self.balls.append(_B(number, x, y))

    def set_balls(self, positions: dict[int, tuple[float, float]]) -> None:
        self.balls = [_B(n, x, y) for n, (x, y) in positions.items()]

    # --- state -------------------------------------------------------------
    def state(self) -> TableState:
        return TableState(
            balls=[Ball(b.number, b.x, b.y, kind_of(b.number), self.table.ball_radius)
                   for b in self.balls if b.live],
            ts=self.t,
            settled=not self.moving(),
            obstructed=self.t < self.obstruct_until,
        )

    def moving(self) -> bool:
        return any(b.live and (b.vx or b.vy) for b in self.balls)

    def cue(self) -> _B | None:
        return next((b for b in self.balls if b.number == 0 and b.live), None)

    # --- striking ----------------------------------------------------------
    def strike(self, speed: float, angle_deg: float) -> None:
        """Hit the cue ball. speed in mm/s (1500-5000 is a normal range)."""
        cue = self.cue()
        if cue is None:
            return
        a = math.radians(angle_deg)
        cue.vx = speed * math.cos(a)
        cue.vy = speed * math.sin(a)

    def aim_at(self, x: float, y: float, speed: float = 2600.0, error_deg: float = 0.0) -> None:
        cue = self.cue()
        if cue is None:
            return
        ang = math.degrees(math.atan2(y - cue.y, x - cue.x))
        if error_deg:
            ang += self.rng.gauss(0, error_deg)
        self.strike(speed, ang)

    def spot_cue(self, x: float | None = None, y: float | None = None) -> None:
        hx, hy = self.table.head_spot
        self.place(0, x if x is not None else hx, y if y is not None else hy)

    def obstruct(self, seconds: float = 0.4) -> None:
        """Simulate an arm over the table, so the pipeline's handling gets exercised."""
        self.obstruct_until = self.t + seconds

    # --- stepping ----------------------------------------------------------
    def step_frame(self) -> TableState:
        """Advance one camera frame and return the state the camera would see."""
        steps = max(1, int((1.0 / self.fps) / DT))
        for _ in range(steps):
            self._physics(DT)
        self.t += 1.0 / self.fps
        return self.state()

    def run_shot(self, max_seconds: float = 20.0) -> list[TableState]:
        """Step until everything is at rest; return every frame."""
        frames = [self.state()]
        guard = int(max_seconds * self.fps)
        while self.moving() and guard > 0:
            frames.append(self.step_frame())
            guard -= 1
        for _ in range(6):                    # trailing still frames to settle
            frames.append(self.step_frame())
        return frames

    def _physics(self, dt: float) -> None:
        t = self.table
        r = t.ball_radius
        for b in self.balls:
            if not b.live:
                continue
            sp = math.hypot(b.vx, b.vy)
            if sp < STOP_SPEED:
                b.vx = b.vy = 0.0
                continue
            decel = FRICTION * 1000.0 * dt
            ns = max(0.0, sp - decel)
            b.vx *= ns / sp
            b.vy *= ns / sp
            b.x += b.vx * dt
            b.y += b.vy * dt

            pid = t.in_pocket(b.x, b.y)
            if pid:
                b.live = False
                b.vx = b.vy = 0.0
                continue
            if b.x < r:
                b.x, b.vx = r, abs(b.vx) * CUSHION_LOSS
            elif b.x > t.length - r:
                b.x, b.vx = t.length - r, -abs(b.vx) * CUSHION_LOSS
            if b.y < r:
                b.y, b.vy = r, abs(b.vy) * CUSHION_LOSS
            elif b.y > t.width - r:
                b.y, b.vy = t.width - r, -abs(b.vy) * CUSHION_LOSS

        live = [b for b in self.balls if b.live]
        for i, a in enumerate(live):
            for c in live[i + 1:]:
                dx, dy = c.x - a.x, c.y - a.y
                d = math.hypot(dx, dy)
                if d >= 2 * r or d == 0:
                    continue
                nx, ny = dx / d, dy / d
                overlap = 2 * r - d
                a.x -= nx * overlap / 2
                a.y -= ny * overlap / 2
                c.x += nx * overlap / 2
                c.y += ny * overlap / 2
                rel = (a.vx - c.vx) * nx + (a.vy - c.vy) * ny
                if rel <= 0:
                    continue
                imp = rel * BALL_LOSS
                a.vx -= imp * nx
                a.vy -= imp * ny
                c.vx += imp * nx
                c.vy += imp * ny


def auto_shot(sim: FakeTable, skill: float = 0.7, prefer: list[int] | None = None) -> dict:
    """Pick and play a plausible shot. Drives the demo without a human.

    skill 0..1 scales aiming error, so you can watch a game of misses and
    fouls or a game of run-outs, which is handy for exercising foul effects.
    """
    st = sim.state()
    cue = st.cue()
    if cue is None:
        sim.spot_cue()
        st = sim.state()
        cue = st.cue()
        if cue is None:
            return {"shot": "none"}

    objs = [b for b in st.balls if not b.is_cue]
    if prefer:
        pick = [b for b in objs if b.number in prefer] or objs
    else:
        pick = objs
    if not pick:
        return {"shot": "none"}

    blockers = [(b.x, b.y) for b in st.balls]
    best = None
    for o in pick:
        for c in shot_candidates((cue.x, cue.y), (o.x, o.y), sim.table, blockers):
            if c["blocked"]:
                continue
            if best is None or c["difficulty"] < best[0]["difficulty"]:
                best = (c, o)
            break
    if best is None:
        o = sim.rng.choice(pick)
        sim.aim_at(o.x, o.y, speed=2400, error_deg=9 * (1 - skill))
        return {"shot": "desperate", "target": o.number}

    c, o = best
    gx, gy = c["ghost"]
    err = (1.0 - skill) * (3.0 + c["cut_angle"] / 12.0)
    speed = 2200 + c["distance"] * 0.5 + sim.rng.uniform(-200, 400)
    sim.aim_at(gx, gy, speed=speed, error_deg=err)
    return {"shot": "aimed", "target": o.number, "pocket": c["pocket"],
            "cut_angle": c["cut_angle"], "error_deg": round(err, 2)}
