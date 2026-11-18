// Projected effects. Every effect draws in table millimetres and is handed the
// live scene, so an effect attached to a ball follows that ball as it rolls.
//
// Palettes are warm/saturated on purpose: cloth eats light, and anything
// pastel disappears on green. Black is the only "off" colour a projector has,
// so effects are drawn additively on a black canvas.

import { adapt, palette as clothPalette } from './cloth.js';

// Fallback palettes, used before the server has said what the cloth is.
// Once it has, cloth.js supplies a set computed for that surface.
export const PALETTES = {
  fire:     ['#fff3b0', '#ffb703', '#fb8500', '#e63946'],
  gold:     ['#fffbe6', '#ffe066', '#ffc300', '#ff8f00'],
  electric: ['#e0fbfc', '#90e0ef', '#00b4d8', '#0077b6'],
  neon:     ['#f72585', '#b5179e', '#7209b7', '#4361ee'],
  mint:     ['#d8f3dc', '#95d5b2', '#52b788', '#2d6a4f'],
  rainbow:  ['#ff006e', '#fb5607', '#ffbe0b', '#8338ec', '#3a86ff', '#06d6a0'],
  ash:      ['#adb5bd', '#6c757d', '#495057'],
};

const pick = (arr, i) => arr[(i | 0) % arr.length];
const paletteFor = (name) => clothPalette(name) || PALETTES[name] || PALETTES.fire;
const rand = (a, b) => a + Math.random() * (b - a);
const ease = (t) => 1 - Math.pow(1 - t, 3);
const clamp01 = (t) => Math.max(0, Math.min(1, t));

export class Effect {
  constructor(args = {}) {
    this.args = args;
    this.t = 0;
    this.dur = (args.duration ?? this.defaultDuration ?? 1000) / 1000;
    this.persist = !!args.persist || args.duration === 0;
    this.done = false;
    this.layer = 'fx';
  }
  get p() { return this.persist ? 1 : clamp01(this.t / this.dur); }
  update(dt) {
    this.t += dt;
    if (!this.persist && this.t >= this.dur) this.done = true;
  }
  draw() {}
}

// --- particles -------------------------------------------------------------
class Particles {
  constructor() { this.list = []; }
  burst(x, y, n, opts = {}) {
    const palette = paletteFor(opts.palette);
    for (let i = 0; i < n; i++) {
      const a = opts.angle !== undefined ? opts.angle + rand(-opts.spread, opts.spread)
                                         : rand(0, Math.PI * 2);
      const sp = rand(opts.minSpeed ?? 400, opts.maxSpeed ?? 2200);
      this.list.push({
        x, y,
        vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
        life: rand(opts.minLife ?? 0.35, opts.maxLife ?? 1.1),
        age: 0,
        r: rand(opts.minSize ?? 6, opts.maxSize ?? 22),
        color: pick(palette, Math.random() * palette.length),
        drag: opts.drag ?? 2.6,
        gravity: opts.gravity ?? 0,
      });
    }
  }
  update(dt) {
    for (const p of this.list) {
      p.age += dt;
      const k = Math.exp(-p.drag * dt);
      p.vx *= k; p.vy *= k;
      p.vy += p.gravity * dt;
      p.x += p.vx * dt; p.y += p.vy * dt;
    }
    this.list = this.list.filter((p) => p.age < p.life);
  }
  draw(ctx, view) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const p of this.list) {
      const k = 1 - p.age / p.life;
      const [sx, sy] = view.project(p.x, p.y);
      const r = Math.max(1, view.mm(p.r * k));
      const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, r);
      g.addColorStop(0, p.color);
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.globalAlpha = k;
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(sx, sy, r, 0, Math.PI * 2); ctx.fill();
    }
    ctx.restore();
  }
  get empty() { return this.list.length === 0; }
}

// --- pocket --------------------------------------------------------------
export class PocketGlow extends Effect {
  defaultDuration = 900;
  constructor(args, scene) {
    super(args);
    this.layer = args.layer || 'guide';
    const pockets = scene.pockets();
    this.pos = args.pocket ? pockets[args.pocket] : [args.x, args.y];
    this.color = adapt(args.color || '#ffc24a');
    this.intensity = args.intensity ?? 1;
  }
  draw(ctx, view) {
    if (!this.pos) return;
    const [x, y] = this.pos;
    const beat = this.persist ? 0.72 + 0.28 * Math.sin(this.t * 4.2)
                              : 1 - ease(this.p);
    const r = 150 * this.intensity * (this.persist ? 1 : 1 + this.p * 1.4);
    const [sx, sy] = view.project(x, y);
    const R = view.mm(r);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, R);
    g.addColorStop(0, this.color);
    g.addColorStop(0.45, this.color + 'aa');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.globalAlpha = 0.9 * beat;
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(sx, sy, R, 0, Math.PI * 2); ctx.fill();
    // Rim on the cloth so the mouth of the pocket is unmistakable.
    ctx.globalAlpha = beat;
    ctx.strokeStyle = this.color;
    ctx.lineWidth = Math.max(2, view.mm(9));
    view.circlePoly(ctx, x, y, 115);
    ctx.stroke();
    if (this.args.label) {
      ctx.globalAlpha = beat;
      ctx.fillStyle = this.color;
      ctx.font = `bold ${Math.round(view.mm(60))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      // Push the label towards the middle of the table on both axes, or a
      // corner-pocket label runs off the cloth and onto the wall.
      const [lx, ly] = view.project(x + (x < view.L / 2 ? 260 : -260),
                                    y + (y < view.W / 2 ? 230 : -230));
      ctx.fillText(this.args.label, lx, ly);
    }
    ctx.restore();
  }
}

export class PocketArrows extends Effect {
  defaultDuration = 0;
  constructor(args, scene) {
    super(args);
    this.layer = 'guide';
    this.pos = scene.pockets()[args.pocket] || [args.x, args.y];
    this.persist = true;
  }
  draw(ctx, view) {
    const [px, py] = this.pos;
    const toCentre = Math.atan2(view.W / 2 - py, view.L / 2 - px);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (let i = 0; i < 3; i++) {
      const phase = (this.t * 1.5 + i * 0.33) % 1;
      const d = 520 - phase * 360;
      const a = 1 - Math.abs(phase - 0.5) * 2;
      const cx = px + Math.cos(toCentre) * d;
      const cy = py + Math.sin(toCentre) * d;
      const s = 70;
      const pts = [
        [cx + Math.cos(toCentre) * s, cy + Math.sin(toCentre) * s],
        [cx + Math.cos(toCentre + 2.4) * s, cy + Math.sin(toCentre + 2.4) * s],
        [cx + Math.cos(toCentre - 2.4) * s, cy + Math.sin(toCentre - 2.4) * s],
      ];
      ctx.globalAlpha = 0.85 * a;
      ctx.fillStyle = '#22d3ee';
      view.pathPoly(ctx, pts);
      ctx.fill();
    }
    ctx.restore();
  }
}

export class PocketReject extends Effect {
  defaultDuration = 700;
  constructor(args, scene) {
    super(args);
    this.pos = scene.pockets()[args.pocket] || [0, 0];
  }
  draw(ctx, view) {
    const [x, y] = this.pos;
    const k = 1 - this.p;
    ctx.save();
    ctx.globalAlpha = k;
    ctx.strokeStyle = '#94a3b8';
    ctx.lineWidth = Math.max(2, view.mm(14));
    const r = 110;
    view.pathPoly(ctx, [[x - r, y - r], [x + r, y + r]], false); ctx.stroke();
    view.pathPoly(ctx, [[x - r, y + r], [x + r, y - r]], false); ctx.stroke();
    ctx.restore();
  }
}

// --- bangs ---------------------------------------------------------------
export class Explosion extends Effect {
  defaultDuration = 1400;
  constructor(args) {
    super(args);
    this.parts = new Particles();
    const n = Math.round(90 * (args.intensity ?? 1));
    this.parts.burst(args.x, args.y, n, {
      palette: args.palette || 'fire',
      maxSpeed: 1500 + 900 * (args.intensity ?? 1),
      maxSize: 18 + 10 * (args.intensity ?? 1),
    });
  }
  update(dt) { super.update(dt); this.parts.update(dt); }
  draw(ctx, view) {
    const { x, y } = this.args;
    const k = 1 - this.p;
    // Shockwave ring, then the particles over the top.
    if (this.p < 0.5) {
      // Capped: a shockwave wider than the table reads as a bug, not a bang.
      const r = Math.min(620, 60 + ease(this.p * 2) * 420 * (this.args.intensity ?? 1));
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = (1 - this.p * 2) * 0.8;
      ctx.strokeStyle = pick(paletteFor(this.args.palette), 1);
      ctx.lineWidth = Math.max(1, view.mm(26 * (1 - this.p * 2)));
      view.circlePoly(ctx, x, y, r);
      ctx.stroke();
      ctx.restore();
    }
    this.parts.draw(ctx, view);
    void k;
  }
}

export class Fireworks extends Effect {
  defaultDuration = 4000;
  constructor(args, scene) {
    super(args);
    this.parts = new Particles();
    this.next = 0;
    this.scene = scene;
  }
  update(dt) {
    super.update(dt);
    this.next -= dt;
    if (this.next <= 0 && this.p < 0.85) {
      this.next = rand(0.12, 0.3);
      this.parts.burst(rand(200, this.scene.table.length - 200),
                       rand(150, this.scene.table.width - 150),
                       70, { palette: this.args.palette || 'rainbow', maxSpeed: 1800 });
    }
    this.parts.update(dt);
  }
  draw(ctx, view) { this.parts.draw(ctx, view); }
}

export class Lightning extends Effect {
  defaultDuration = 600;
  constructor(args, scene) {
    super(args);
    this.from = scene.pockets()[args.pocket] || [0, 0];
    this.bolts = [];
    const pockets = scene.pockets();
    for (const id of Object.keys(pockets)) {
      if (id === args.pocket) continue;
      this.bolts.push(this.makeBolt(pockets[id], this.from));
    }
  }
  makeBolt(a, b) {
    const pts = [a];
    const n = 7;
    for (let i = 1; i < n; i++) {
      const t = i / n;
      pts.push([a[0] + (b[0] - a[0]) * t + rand(-90, 90),
                a[1] + (b[1] - a[1]) * t + rand(-60, 60)]);
    }
    pts.push(b);
    return pts;
  }
  draw(ctx, view) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = (1 - this.p) * (0.5 + 0.5 * Math.random());
    ctx.strokeStyle = '#a5f3fc';
    ctx.lineWidth = Math.max(1, view.mm(10));
    for (const bolt of this.bolts) { view.pathPoly(ctx, bolt, false); ctx.stroke(); }
    ctx.restore();
  }
}

export class TableFlash extends Effect {
  defaultDuration = 400;
  constructor(args) { super(args); this.pulses = args.pulses || 1; }
  draw(ctx, view) {
    const k = Math.abs(Math.sin(this.p * Math.PI * this.pulses)) * (1 - this.p * 0.4);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.5 * k;
    ctx.fillStyle = adapt(this.args.color || '#ff2d55');
    view.pathPoly(ctx, [[0, 0], [view.L, 0], [view.L, view.W], [0, view.W]]);
    ctx.fill();
    ctx.restore();
  }
}

export class Shatter extends Effect {
  defaultDuration = 1200;
  constructor(args, scene) {
    super(args);
    this.parts = new Particles();
    const [cx, cy] = [scene.table.length / 2, scene.table.width / 2];
    this.parts.burst(cx, cy, 160, { palette: 'ash', maxSpeed: 2600, maxLife: 1.2 });
  }
  update(dt) { super.update(dt); this.parts.update(dt); }
  draw(ctx, view) { this.parts.draw(ctx, view); }
}

// --- guides --------------------------------------------------------------
export class HighlightBalls extends Effect {
  defaultDuration = 0;
  constructor(args) {
    super(args);
    this.layer = 'guide';
    this.persist = true;
    this.numbers = args.balls || [];
    this.color = adapt(args.color || '#4ade80');
    this.style = args.style || 'ring';
  }
  draw(ctx, view, scene) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const n of this.numbers) {
      const b = scene.ball(n);
      if (!b) continue;
      const pulse = this.style === 'pulse-ring' ? 0.6 + 0.4 * Math.sin(this.t * 5) : 1;
      ctx.globalAlpha = 0.9 * pulse;
      ctx.strokeStyle = this.color;
      ctx.lineWidth = Math.max(2, view.mm(10));
      if (this.style === 'crosshair') {
        const r = 58;
        for (const [a0, a1] of [[0.2, 1.37], [1.77, 2.94], [3.34, 4.51], [4.91, 6.08]]) {
          const pts = [];
          for (let i = 0; i <= 8; i++) {
            const a = a0 + (a1 - a0) * (i / 8);
            pts.push([b.x + Math.cos(a) * r, b.y + Math.sin(a) * r]);
          }
          view.pathPoly(ctx, pts, false); ctx.stroke();
        }
      } else {
        view.circlePoly(ctx, b.x, b.y, 48 + (this.style === 'pulse-ring' ? pulse * 14 : 0));
        ctx.stroke();
      }
      if (this.args.label && n === this.numbers[0]) {
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = this.color;
        ctx.font = `bold ${Math.round(view.mm(52))}px system-ui, sans-serif`;
        ctx.textAlign = 'center';
        const [lx, ly] = view.project(b.x, b.y - 110);
        ctx.fillText(this.args.label, lx, ly);
      }
    }
    ctx.restore();
  }
}

export class AimLine extends Effect {
  defaultDuration = 0;
  constructor(args, scene) {
    super(args);
    this.layer = 'guide';
    this.persist = true;
    this.scene = scene;
  }
  draw(ctx, view, scene) {
    const a = this.args;
    const cue = a.cue, target = a.target;
    const ghost = a.ghost;
    const pocket = a.pocket ? scene.pockets()[a.pocket] : a.pocketPos;
    if (!cue || !target) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const dash = (this.t * 240) % 120;

    // cue ball -> ghost ball
    if (ghost) {
      ctx.setLineDash([view.mm(60), view.mm(40)]);
      ctx.lineDashOffset = -view.mm(dash);
      ctx.globalAlpha = 0.85;
      ctx.strokeStyle = '#e0fbfc';
      ctx.lineWidth = Math.max(2, view.mm(12));
      view.pathPoly(ctx, [cue, ghost], false);
      ctx.stroke();
      ctx.setLineDash([]);
      // the ghost ball itself
      ctx.globalAlpha = 0.5 + 0.2 * Math.sin(this.t * 4);
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = Math.max(1, view.mm(7));
      view.circlePoly(ctx, ghost[0], ghost[1], 28.6);
      ctx.stroke();
    }
    // object ball -> pocket
    if (pocket) {
      ctx.globalAlpha = 0.9;
      ctx.strokeStyle = '#ffd166';
      ctx.lineWidth = Math.max(2, view.mm(12));
      view.pathPoly(ctx, [target, pocket], false);
      ctx.stroke();
      // tangent line: where the cue ball goes after contact, the thing most
      // players actually need to see.
      const ang = Math.atan2(pocket[1] - target[1], pocket[0] - target[0]);
      const tan = ang + Math.PI / 2;
      ctx.globalAlpha = 0.4;
      ctx.strokeStyle = '#94a3b8';
      ctx.lineWidth = Math.max(1, view.mm(6));
      view.pathPoly(ctx, [
        [target[0] + Math.cos(tan) * 420, target[1] + Math.sin(tan) * 420],
        [target[0] - Math.cos(tan) * 420, target[1] - Math.sin(tan) * 420],
      ], false);
      ctx.stroke();
    }
    if (a.cut_angle !== undefined) {
      ctx.globalAlpha = 0.9;
      ctx.fillStyle = '#ffd166';
      ctx.font = `bold ${Math.round(view.mm(46))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      const [lx, ly] = view.project(target[0], target[1] + 130);
      ctx.fillText(`${a.cut_angle}°`, lx, ly);
    }
    ctx.restore();
  }
}

export class Trajectory extends Effect {
  defaultDuration = 1800;
  constructor(args) { super(args); this.layer = args.layer || 'fx'; }
  draw(ctx, view) {
    const pts = this.args.points || this.args.path || [];
    if (pts.length < 2) return;
    const shown = Math.max(2, Math.floor(pts.length * ease(Math.min(1, this.p * 1.6))));
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.85 * (1 - Math.max(0, this.p - 0.6) / 0.4);
    ctx.strokeStyle = adapt(this.args.color || '#22d3ee');
    ctx.lineWidth = Math.max(2, view.mm(this.args.width || 16));
    ctx.lineJoin = 'round';
    if (this.args.style === 'dashed') {
      ctx.setLineDash([view.mm(70), view.mm(50)]);
      ctx.lineDashOffset = -view.mm((this.t * 200) % 120);
    }
    view.pathPoly(ctx, pts.slice(0, shown), false);
    ctx.stroke();
    ctx.restore();
  }
}

// --- zones ---------------------------------------------------------------
function drawZone(ctx, view, z, t, alphaScale = 1) {
  const pulse = 0.65 + 0.35 * Math.sin(t * 3 + (z.x + z.y) * 0.01);
  const spent = z.state !== 'active';
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const [sx, sy] = view.project(z.x, z.y);
  const R = view.mm(z.r || 150);
  const g = ctx.createRadialGradient(sx, sy, R * 0.15, sx, sy, R);
  const zc = adapt(z.color || '#38bdf8');
  g.addColorStop(0, zc + 'cc');
  g.addColorStop(0.7, zc + '33');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.globalAlpha = (spent ? 0.12 : 0.55 * pulse) * alphaScale;
  ctx.fillStyle = g;
  ctx.beginPath(); ctx.arc(sx, sy, R, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = (spent ? 0.2 : 0.95) * alphaScale;
  ctx.strokeStyle = zc;
  ctx.lineWidth = Math.max(2, view.mm(10));
  if (z.shape === 'rect') {
    view.pathPoly(ctx, [
      [z.x - z.w / 2, z.y - z.h / 2], [z.x + z.w / 2, z.y - z.h / 2],
      [z.x + z.w / 2, z.y + z.h / 2], [z.x - z.w / 2, z.y + z.h / 2]]);
  } else {
    view.circlePoly(ctx, z.x, z.y, z.r || 150);
  }
  ctx.stroke();
  if (z.label) {
    ctx.globalAlpha = (spent ? 0.2 : 1) * alphaScale;
    ctx.fillStyle = zc;
    ctx.font = `bold ${Math.round(view.mm(z.label.length > 3 ? 46 : 92))}px system-ui, sans-serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(z.label, sx, sy);
  }
  ctx.restore();
}

export class Zones extends Effect {
  defaultDuration = 0;
  constructor(args) {
    super(args);
    this.layer = 'guide';
    this.persist = true;
    this.zones = args.zones || [];
    this.intro = args.transition ? 0 : 1;
  }
  update(dt) { super.update(dt); this.intro = Math.min(1, this.intro + dt * 2.5); }
  draw(ctx, view) {
    for (const z of this.zones) drawZone(ctx, view, z, this.t, ease(this.intro));
  }
}

export class TargetZone extends Zones {
  constructor(args) {
    super({ ...args, zones: [args.zone] });
  }
}

export class ZoneHit extends Effect {
  defaultDuration = 1600;
  constructor(args) {
    super(args);
    this.parts = new Particles();
    const z = args.zone || {};
    this.parts.burst(z.x, z.y, 70, { palette: 'electric', maxSpeed: 1600 });
  }
  update(dt) { super.update(dt); this.parts.update(dt); }
  draw(ctx, view) {
    const z = this.args.zone || {};
    const path = this.args.path || [];
    if (path.length > 1) {
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = 0.8 * (1 - this.p);
      ctx.strokeStyle = z.color || '#38bdf8';
      ctx.lineWidth = Math.max(2, view.mm(18));
      view.pathPoly(ctx, path, false);
      ctx.stroke();
      ctx.restore();
    }
    const r = (z.r || 150) * (1 + ease(this.p) * 1.2);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 1 - this.p;
    ctx.strokeStyle = z.color || '#38bdf8';
    ctx.lineWidth = Math.max(1, view.mm(20 * (1 - this.p)));
    view.circlePoly(ctx, z.x, z.y, r);
    ctx.stroke();
    if (z.points) {
      ctx.fillStyle = '#ffffff';
      ctx.font = `bold ${Math.round(view.mm(90))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      const [lx, ly] = view.project(z.x, z.y - 60 - ease(this.p) * 180);
      ctx.fillText(`+${z.points}`, lx, ly);
    }
    ctx.restore();
    this.parts.draw(ctx, view);
  }
}

export class ZonePark extends ZoneHit {
  defaultDuration = 1800;
}

export class ZoneGrade extends Effect {
  defaultDuration = 2200;
  draw(ctx, view) {
    const a = this.args;
    const z = a.zone || {};
    const cue = a.cue;
    drawZone(ctx, view, { ...z, color: a.inside ? '#34d399' : '#f59e0b' }, this.t, 1 - this.p * 0.5);
    if (cue) {
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = 1 - this.p;
      ctx.strokeStyle = a.inside ? '#34d399' : '#f59e0b';
      ctx.lineWidth = Math.max(2, view.mm(10));
      ctx.setLineDash([view.mm(40), view.mm(30)]);
      view.pathPoly(ctx, [[z.x, z.y], cue], false);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = '#fff';
      ctx.font = `bold ${Math.round(view.mm(58))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      const mid = [(z.x + cue[0]) / 2, (z.y + cue[1]) / 2 - 90];
      const [lx, ly] = view.project(mid[0], mid[1]);
      ctx.fillText(a.inside ? `+${a.points}` : `${Math.round(a.distance)} mm  +${a.points}`, lx, ly);
      ctx.restore();
    }
  }
}

// --- roulette ------------------------------------------------------------
export class RouletteSpin extends Effect {
  defaultDuration = 2200;
  constructor(args, scene) {
    super(args);
    this.order = args.pockets || ['TL', 'TM', 'TR', 'BR', 'BM', 'BL'];
    this.landedIndex = Math.max(0, this.order.indexOf(args.landed));
    this.scene = scene;
  }
  draw(ctx, view, scene) {
    const pockets = scene.pockets();
    // Decelerating sweep around the six pockets, settling on the winner.
    const k = ease(this.p);
    const total = 3 * this.order.length + this.landedIndex;
    const at = Math.floor(k * total) % this.order.length;
    const settled = this.p > 0.96;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    this.order.forEach((id, i) => {
      const pos = pockets[id];
      if (!pos) return;
      const on = settled ? i === this.landedIndex : i === at;
      ctx.globalAlpha = on ? 0.95 : 0.14;
      ctx.strokeStyle = on ? '#22d3ee' : '#334155';
      ctx.lineWidth = Math.max(2, view.mm(on ? 22 : 8));
      view.circlePoly(ctx, pos[0], pos[1], on ? 150 : 110);
      ctx.stroke();
    });
    ctx.restore();
  }
}

// --- HUD-on-cloth --------------------------------------------------------
export class Banner extends Effect {
  defaultDuration = 2400;
  constructor(args) { super(args); this.layer = 'hud'; }
  draw(ctx, view, scene) {
    const a = this.args;
    const tone = adapt(a.tone === 'bad' ? '#ff4d6d'
      : a.tone === 'good' ? '#4ade80' : '#e0fbfc');
    const k = this.p < 0.15 ? this.p / 0.15 : this.p > 0.82 ? (1 - this.p) / 0.18 : 1;
    const cx = scene.table.length / 2;
    const cy = scene.table.width / 2;
    ctx.save();
    ctx.globalAlpha = clamp01(k);
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    const [sx, sy] = view.project(cx, cy);
    const size = view.mm(a.text && a.text.length > 14 ? 90 : 150);
    ctx.font = `900 ${Math.round(size)}px system-ui, sans-serif`;
    ctx.lineWidth = Math.max(2, view.mm(8));
    ctx.strokeStyle = 'rgba(0,0,0,0.85)';
    ctx.fillStyle = tone;
    ctx.strokeText(a.text || '', sx, sy);
    ctx.fillText(a.text || '', sx, sy);
    if (a.subtitle) {
      const [bx, by] = view.project(cx, cy + 190);
      ctx.font = `600 ${Math.round(view.mm(62))}px system-ui, sans-serif`;
      ctx.fillStyle = '#cbd5e1';
      ctx.strokeText(a.subtitle, bx, by);
      ctx.fillText(a.subtitle, bx, by);
    }
    ctx.restore();
  }
}

export class Spotlight extends Effect {
  defaultDuration = 2600;
  constructor(args) { super(args); this.layer = 'hud'; }
  draw(ctx, view, scene) {
    const k = this.p < 0.1 ? this.p / 0.1 : this.p > 0.8 ? (1 - this.p) / 0.2 : 1;
    const y = scene.table.width - 150;
    const [sx, sy] = view.project(scene.table.length / 2, y);
    ctx.save();
    ctx.globalAlpha = clamp01(k) * 0.95;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `800 ${Math.round(view.mm(74))}px system-ui, sans-serif`;
    ctx.lineWidth = Math.max(2, view.mm(7));
    ctx.strokeStyle = 'rgba(0,0,0,0.8)';
    ctx.fillStyle = adapt(this.args.color || '#f59e0b');
    ctx.strokeText(this.args.text || '', sx, sy);
    ctx.fillText(this.args.text || '', sx, sy);
    ctx.restore();
  }
}

export class ScorePop extends Effect {
  defaultDuration = 1500;
  constructor(args) { super(args); this.layer = 'hud'; }
  draw(ctx, view, scene) {
    const a = this.args;
    const txt = a.delta ? (a.delta > 0 ? `+${a.delta}` : `${a.delta}`) : `${a.total ?? ''}`;
    if (!txt) return;
    const rise = ease(this.p) * 220;
    const [sx, sy] = view.project(scene.table.length / 2, scene.table.width / 2 - 320 - rise);
    ctx.save();
    ctx.globalAlpha = 1 - this.p;
    ctx.textAlign = 'center';
    ctx.font = `900 ${Math.round(view.mm(110))}px system-ui, sans-serif`;
    ctx.fillStyle = (a.delta ?? 1) >= 0 ? '#4ade80' : '#ff4d6d';
    ctx.strokeStyle = 'rgba(0,0,0,0.8)';
    ctx.lineWidth = Math.max(2, view.mm(8));
    ctx.strokeText(txt, sx, sy); ctx.fillText(txt, sx, sy);
    ctx.restore();
  }
}

export class PlayerHit extends ScorePop {
  defaultDuration = 1600;
  draw(ctx, view, scene) {
    const a = this.args;
    const [sx, sy] = view.project(scene.table.length / 2,
                                  scene.table.width / 2 - 260 - ease(this.p) * 160);
    ctx.save();
    ctx.globalAlpha = 1 - this.p;
    ctx.textAlign = 'center';
    ctx.font = `800 ${Math.round(view.mm(70))}px system-ui, sans-serif`;
    ctx.fillStyle = a.color || '#f87171';
    ctx.strokeStyle = 'rgba(0,0,0,0.8)';
    ctx.lineWidth = Math.max(2, view.mm(6));
    const txt = `${a.name}: ${a.remaining} left`;
    ctx.strokeText(txt, sx, sy); ctx.fillText(txt, sx, sy);
    ctx.restore();
  }
}

export class LifeLost extends Effect {
  defaultDuration = 1800;
  constructor(args) { super(args); this.layer = 'hud'; }
  draw(ctx, view, scene) {
    const a = this.args;
    const [sx, sy] = view.project(scene.table.length / 2, scene.table.width / 2);
    ctx.save();
    ctx.globalAlpha = (1 - this.p) * 0.95;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `900 ${Math.round(view.mm(120))}px system-ui, sans-serif`;
    ctx.fillStyle = '#ff4d6d';
    ctx.strokeStyle = 'rgba(0,0,0,0.85)';
    ctx.lineWidth = Math.max(2, view.mm(8));
    const hearts = '♥'.repeat(Math.max(0, a.lives)) + '♡';
    ctx.strokeText(hearts, sx, sy); ctx.fillText(hearts, sx, sy);
    ctx.restore();
  }
}

export class LivesBar extends Effect {
  defaultDuration = 0;
  constructor(args) { super(args); this.layer = 'hud'; this.persist = true; }
  draw(ctx, view, scene) {
    const players = this.args.players || [];
    if (!players.length) return;
    ctx.save();
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    players.forEach((p, i) => {
      const x = scene.table.length * ((i + 0.5) / players.length);
      const [sx, sy] = view.project(x, 110);
      ctx.globalAlpha = p.out ? 0.3 : 1;
      ctx.font = `700 ${Math.round(view.mm(46))}px system-ui, sans-serif`;
      ctx.fillStyle = i === this.args.turn ? '#fde047' : '#94a3b8';
      ctx.strokeStyle = 'rgba(0,0,0,0.8)';
      ctx.lineWidth = Math.max(1, view.mm(5));
      const txt = `${p.name} ${'♥'.repeat(Math.max(0, p.lives))}`;
      ctx.strokeText(txt, sx, sy); ctx.fillText(txt, sx, sy);
    });
    ctx.restore();
  }
}

export class CallPocketPrompt extends Effect {
  defaultDuration = 0;
  constructor(args) { super(args); this.layer = 'guide'; this.persist = true; }
  draw(ctx, view, scene) {
    const pockets = scene.pockets();
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const pulse = 0.5 + 0.5 * Math.sin(this.t * 3);
    for (const id of Object.keys(pockets)) {
      const [x, y] = pockets[id];
      ctx.globalAlpha = 0.35 * pulse;
      ctx.strokeStyle = '#f472b6';
      ctx.lineWidth = Math.max(1, view.mm(8));
      view.circlePoly(ctx, x, y, 120);
      ctx.stroke();
      ctx.globalAlpha = 0.8;
      ctx.fillStyle = '#f472b6';
      ctx.font = `bold ${Math.round(view.mm(44))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      const [lx, ly] = view.project(x + (x < view.L / 2 ? 180 : -180),
                                    y + (y < view.W / 2 ? 190 : -190));
      ctx.fillText(id, lx, ly);
    }
    ctx.restore();
  }
}

export class AssignGroup extends Banner {
  constructor(args) {
    super({ text: (args.group || '').toUpperCase(),
            subtitle: `balls ${(args.balls || []).join(' ')}`, tone: 'good', duration: 2600 });
  }
}

export class AimAssist extends AimLine {}

export class PlacementArea extends Effect {
  defaultDuration = 0;
  constructor(args) { super(args); this.layer = 'guide'; this.persist = true; }
  draw(ctx, view) {
    const sh = this.args.shape || { kind: 'table' };
    const pulse = 0.5 + 0.5 * Math.sin(this.t * 2.6);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.35 + 0.25 * pulse;
    ctx.strokeStyle = adapt('#38bdf8');
    ctx.lineWidth = Math.max(2, view.mm(12));
    ctx.setLineDash([view.mm(70), view.mm(45)]);
    if (sh.kind === 'rect') {
      view.pathPoly(ctx, [[sh.x - sh.w / 2, sh.y - sh.h / 2],
                          [sh.x + sh.w / 2, sh.y - sh.h / 2],
                          [sh.x + sh.w / 2, sh.y + sh.h / 2],
                          [sh.x - sh.w / 2, sh.y + sh.h / 2]]);
    } else if (sh.kind === 'halfcircle') {
      const pts = [];
      for (let i = 0; i <= 24; i++) {
        const a = Math.PI / 2 + (i / 24) * Math.PI;
        pts.push([sh.x + Math.cos(a) * sh.r, sh.y + Math.sin(a) * sh.r]);
      }
      view.pathPoly(ctx, pts);
    } else {
      view.pathPoly(ctx, [[0, 0], [view.L, 0], [view.L, view.W], [0, view.W]]);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    if (this.args.label) {
      ctx.globalAlpha = 0.9;
      ctx.fillStyle = adapt('#38bdf8');
      ctx.font = `700 ${Math.round(view.mm(56))}px system-ui, sans-serif`;
      ctx.textAlign = 'center';
      const [lx, ly] = view.project(view.L / 2, view.W - 120);
      ctx.fillText(this.args.label, lx, ly);
    }
    ctx.restore();
  }
}

export class PlacementOk extends Effect {
  defaultDuration = 700;
  draw(ctx, view) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 1 - this.p;
    ctx.strokeStyle = adapt('#4ade80');
    ctx.lineWidth = Math.max(2, view.mm(14));
    view.circlePoly(ctx, this.args.x, this.args.y, 40 + ease(this.p) * 90);
    ctx.stroke();
    ctx.restore();
  }
}

export class PlacementBad extends Effect {
  defaultDuration = 1800;
  draw(ctx, view) {
    const k = 0.5 + 0.5 * Math.sin(this.t * 10);
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = (1 - this.p) * k;
    ctx.strokeStyle = adapt('#ff2d55');
    ctx.lineWidth = Math.max(2, view.mm(14));
    const r = 70;
    view.pathPoly(ctx, [[this.args.x - r, this.args.y - r],
                        [this.args.x + r, this.args.y + r]], false); ctx.stroke();
    view.pathPoly(ctx, [[this.args.x - r, this.args.y + r],
                        [this.args.x + r, this.args.y - r]], false); ctx.stroke();
    ctx.restore();
  }
}

export class PlacementSuggest extends Effect {
  defaultDuration = 0;
  constructor(args) { super(args); this.layer = 'guide'; this.persist = true; }
  draw(ctx, view) {
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.45 + 0.35 * Math.sin(this.t * 3);
    ctx.strokeStyle = adapt('#4ade80');
    ctx.lineWidth = Math.max(1, view.mm(8));
    ctx.setLineDash([view.mm(30), view.mm(22)]);
    view.circlePoly(ctx, this.args.x, this.args.y, 28.6);
    ctx.stroke();
    ctx.restore();
  }
}

/** The line the player is actually on, from the tracked cue. */
export class CueLineFx extends Effect {
  defaultDuration = 0;
  constructor(args) { super(args); this.layer = 'guide'; this.persist = true; }
  draw(ctx, view) {
    const a = this.args;
    if (!a.tip || !a.to) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.35 + 0.5 * (a.confidence ?? 0.5);
    ctx.strokeStyle = adapt('#e0fbfc');
    ctx.lineWidth = Math.max(2, view.mm(10));
    view.pathPoly(ctx, [a.tip, a.to], false);
    ctx.stroke();
    ctx.restore();
  }
}

export class CueContact extends Effect {
  defaultDuration = 0;
  constructor(args) { super(args); this.layer = 'guide'; this.persist = true; }
  draw(ctx, view) {
    const a = this.args;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.8;
    ctx.strokeStyle = adapt('#ffd166');
    ctx.lineWidth = Math.max(2, view.mm(10));
    if (a.object_path) { view.pathPoly(ctx, a.object_path, false); ctx.stroke(); }
    if (a.contact) {
      ctx.strokeStyle = adapt('#ffffff');
      ctx.lineWidth = Math.max(1, view.mm(6));
      view.circlePoly(ctx, a.contact[0], a.contact[1], 28.6);
      ctx.stroke();
    }
    ctx.restore();
  }
}

export const EFFECTS = {
  placement_area: PlacementArea,
  placement_ok: PlacementOk,
  placement_bad: PlacementBad,
  placement_suggest: PlacementSuggest,
  cue_line: CueLineFx,
  cue_contact: CueContact,
  pocket_glow: PocketGlow,
  pocket_arrows: PocketArrows,
  pocket_reject: PocketReject,
  explosion: Explosion,
  fireworks: Fireworks,
  lightning: Lightning,
  table_flash: TableFlash,
  shatter: Shatter,
  highlight_balls: HighlightBalls,
  aim_line: AimLine,
  aim_assist: AimAssist,
  trajectory: Trajectory,
  zones: Zones,
  target_zone: TargetZone,
  zone_hit: ZoneHit,
  zone_park: ZonePark,
  zone_grade: ZoneGrade,
  roulette_spin: RouletteSpin,
  banner: Banner,
  spotlight: Spotlight,
  score_pop: ScorePop,
  player_hit: PlayerHit,
  life_lost: LifeLost,
  lives_bar: LivesBar,
  call_pocket_prompt: CallPocketPrompt,
  assign_group: AssignGroup,
};

export function makeEffect(name, args, scene) {
  const Cls = EFFECTS[name];
  if (!Cls) return null;
  const fx = new Cls(args || {}, scene);
  if (args && args.layer) fx.layer = args.layer;
  return fx;
}
