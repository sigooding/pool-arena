// What the table shows when nobody is playing.
//
// Drawn as light rather than as objects: the ghost balls are glows with long
// comet tails, so an empty table reads as "something is happening here" from
// across a room, and nobody mistakes a projected ball for a real one.

import { ballStyle } from './balls.js';
import { adapt, semantic } from './cloth.js';

const TRAIL = 900;        // ms of tail behind each ghost ball

export class Attract {
  constructor() {
    this.balls = [];
    this.caption = null;
    this.trails = new Map();
    this.t = 0;
    this.fade = 0;         // 0..1, eases the whole thing in and out
    this.on = false;
  }

  update(msg) {
    if (!msg.active) { this.on = false; return; }
    this.on = true;
    if (msg.balls) {
      this.balls = msg.balls;
      const now = performance.now();
      for (const b of msg.balls) {
        let tr = this.trails.get(b.n);
        if (!tr) { tr = []; this.trails.set(b.n, tr); }
        const last = tr[tr.length - 1];
        if (!last || Math.hypot(b.x - last[0], b.y - last[1]) > 6) {
          tr.push([b.x, b.y, now]);
          if (tr.length > 40) tr.shift();
        }
      }
      // A ball that has gone (potted) should not keep a tail forever.
      const live = new Set(msg.balls.map((b) => b.n));
      for (const n of [...this.trails.keys()]) if (!live.has(n)) this.trails.delete(n);
    }
    if (msg.caption) this.caption = msg.caption;
    if (msg.event === 'rack') this.trails.clear();
  }

  tick(dt) {
    this.t += dt;
    const target = this.on ? 1 : 0;
    // Fade out faster than in: getting out of a player's way should feel
    // immediate, arriving should not be startling.
    const rate = this.on ? 1.1 : 4.0;
    this.fade += Math.sign(target - this.fade) * Math.min(Math.abs(target - this.fade), rate * dt);
    return this.fade > 0.001;
  }

  draw(ctx, view) {
    const k = this.fade;
    if (k <= 0.001) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';

    this.drawSweep(ctx, view, k);
    this.drawTrails(ctx, view, k);
    this.drawBalls(ctx, view, k);
    ctx.restore();
    this.drawCaption(ctx, view, k);
  }

  // A slow band of light crossing the cloth: the thing that catches an eye
  // from the bar without being mistaken for part of a game.
  drawSweep(ctx, view, k) {
    const L = view.L, W = view.W;
    const x = ((this.t * 0.11) % 1.6 - 0.3) * L;
    const band = L * 0.22;
    const g = ctx.createLinearGradient(...view.project(x - band, W / 2),
                                       ...view.project(x + band, W / 2));
    const tint = adapt(semantic('key') || '#A3E635');
    g.addColorStop(0, 'rgba(0,0,0,0)');
    g.addColorStop(0.5, tint + '22');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.globalAlpha = 0.5 * k;
    ctx.fillStyle = g;
    view.pathPoly(ctx, [[0, 0], [L, 0], [L, W], [0, W]]);
    ctx.fill();
  }

  drawTrails(ctx, view, k) {
    const now = performance.now();
    for (const [n, tr] of this.trails) {
      while (tr.length && now - tr[0][2] > TRAIL) tr.shift();
      if (tr.length < 2) continue;
      const { fill } = ballStyle(n);
      const col = adapt(fill);
      for (let i = 1; i < tr.length; i++) {
        const age = (now - tr[i][2]) / TRAIL;
        ctx.globalAlpha = Math.max(0, 0.5 * (1 - age) * k);
        ctx.strokeStyle = col;
        ctx.lineWidth = Math.max(1, view.mm(40 * (1 - age)));
        ctx.lineCap = 'round';
        view.pathPoly(ctx, [[tr[i - 1][0], tr[i - 1][1]], [tr[i][0], tr[i][1]]], false);
        ctx.stroke();
      }
    }
  }

  drawBalls(ctx, view, k) {
    for (const b of this.balls) {
      const { fill } = ballStyle(b.n);
      const col = adapt(fill);
      const [sx, sy] = view.project(b.x, b.y);
      const r = view.mm(29);
      const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, r * 2.4);
      g.addColorStop(0, col);
      g.addColorStop(0.35, col + '99');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.globalAlpha = 0.9 * k;
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(sx, sy, r * 2.4, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = k;
      ctx.strokeStyle = col;
      ctx.lineWidth = Math.max(1, view.mm(6));
      view.circlePoly(ctx, b.x, b.y, 28.6);
      ctx.stroke();
    }
  }

  drawCaption(ctx, view, k) {
    if (!this.caption) return;
    const { title, sub } = this.caption;
    // Low on the cloth, clear of the ghost game, and breathing slightly so it
    // never looks like a frozen screen.
    const breathe = 0.86 + 0.14 * Math.sin(this.t * 1.1);
    const cx = view.L / 2;
    ctx.save();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.globalAlpha = k * breathe;
    const [tx, ty] = view.project(cx, view.W * 0.80);
    ctx.font = `900 ${Math.round(view.mm(135))}px system-ui, sans-serif`;
    ctx.lineWidth = Math.max(2, view.mm(9));
    ctx.strokeStyle = 'rgba(0,0,0,0.75)';
    ctx.fillStyle = adapt('#FFFFFF');
    ctx.strokeText(title || '', tx, ty);
    ctx.fillText(title || '', tx, ty);
    if (sub) {
      const [bx, by] = view.project(cx, view.W * 0.80 + 185);
      ctx.font = `600 ${Math.round(view.mm(62))}px system-ui, sans-serif`;
      ctx.globalAlpha = k * 0.85;
      ctx.fillStyle = adapt(semantic('key') || '#A3E635');
      ctx.strokeText(sub, bx, by);
      ctx.fillText(sub, bx, by);
    }
    ctx.restore();
  }
}
