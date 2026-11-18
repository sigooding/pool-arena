// A live top-down table for the tablet.
//
// The state stream is already being broadcast to every client, so showing the
// real table costs one canvas and makes the scoreboard worth looking at: you
// can see the layout, whose turn it is, and what just dropped, from the rail.

import { CLOTH, CLOTH_DARK, RAIL, ballStyle, drawBall } from './balls.js';

/** Darken or lighten a hex colour, for the cloth's vignette. */
function shade(hex, amount) {
  const n = hex.replace('#', '');
  const v = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16));
  return '#' + v.map((c) => Math.max(0, Math.min(255, Math.round(c * (1 + amount))))
    .toString(16).padStart(2, '0')).join('');
}

export class MiniTable {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.table = { length: 2235, width: 1118 };
    this.balls = [];
    this.pockets = null;
    this.highlight = new Set();     // ball numbers to ring
    this.accent = '#F2B705';
    // Guides mirrored from the projector stream. With no projector these are
    // the only place a player can see which pocket they have been given or
    // which zones are live, so the games that depend on them stay playable.
    this.guides = { zones: [], pockets: [], marked: [], aim: null };
    //: paths drawn behind the balls during a replay, as {n, points, upto}
    this.traces = [];
    this.ghosts = [];               // recently pocketed, fading out
    this._raf = null;
    // Measure whenever the box actually changes rather than once at startup:
    // the grid, the media queries and the collapsible setup drawer all settle
    // after this constructor runs, and a single early measurement locks the
    // table to whatever size the page happened to have mid-layout.
    const box = canvas.parentElement;
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(box);
    }
    window.addEventListener('resize', () => this.resize());
    this.resize();
  }

  setTable(t) {
    this.table = { ...this.table, ...t };
    if (t && t.cloth) this.cloth = t.cloth;
    if (t && t.pockets) this.pockets = t.pockets;
    this.resize();
  }

  setBalls(balls) {
    const had = new Set(this.balls.map((b) => b.number));
    const now = new Set(balls.map((b) => b.number));
    for (const b of this.balls) {
      if (!now.has(b.number) && had.has(b.number)) {
        this.ghosts.push({ ...b, t: performance.now() });
      }
    }
    this.balls = balls;
    this.draw();
  }

  resize() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const aspect = this.table.width / this.table.length;
    // Fit the table into the box the layout gives us, constrained by whichever
    // of width or height runs out first, and keep it exactly proportional —
    // a stretched table would misrepresent every angle on it.
    const parent = this.canvas.parentElement;
    const cs = getComputedStyle(parent);
    const padX = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
    const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    // clientWidth excludes the scrollbar; the canvas's own size must not feed
    // back into the measurement, so read the parent's content box directly.
    let w = Math.max(220, parent.clientWidth - padX);
    let h = w * aspect;
    // Height budget measured against the viewport, not the parent. When the
    // layout stacks into one column the parent's height comes *from* the
    // canvas, so constraining the canvas by it is circular and collapses the
    // table to its minimum. The distance from the wrapper's top to the bottom
    // of the window does not depend on the canvas at all.
    const top = parent.getBoundingClientRect().top;
    const maxH = Math.max(140, window.innerHeight - top - padY - 16);
    if (h > maxH) { h = maxH; w = h / aspect; }
    if (Math.abs(w - (this._lastW || 0)) < 0.5 && Math.abs(h - (this._lastH || 0)) < 0.5) {
      return;                     // nothing changed; do not thrash the observer
    }
    this._lastW = w; this._lastH = h;
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w;
    this.h = h;
    this.scale = w / this.table.length;
    this.draw();
  }

  pos(x, y) { return [x * this.scale, y * this.scale]; }

  setTraces(traces) {
    this.traces = traces || [];
    this.draw();
  }

  /** The path each ball actually took, revealed as the replay advances. */
  drawTraces(ctx) {
    for (const t of this.traces) {
      const pts = t.points || [];
      const upto = Math.max(2, Math.min(pts.length, t.upto ?? pts.length));
      if (upto < 2) continue;
      const { fill } = ballStyle(t.n);
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      for (let i = 1; i < upto; i++) {
        const age = 1 - i / upto;
        ctx.globalAlpha = 0.25 + 0.55 * (1 - age);
        ctx.strokeStyle = fill;
        ctx.lineWidth = Math.max(1.5, this.scale * 22);
        const a = this.pos(pts[i - 1][0], pts[i - 1][1]);
        const b = this.pos(pts[i][0], pts[i][1]);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
      ctx.restore();
    }
  }

  setGuides(g) {
    this.guides = { zones: [], pockets: [], marked: [], aim: null, ...g };
    this.draw();
  }

  drawGuides(ctx) {
    const g = this.guides;
    const P = this.pockets || {};
    const t = performance.now() / 1000;

    for (const z of g.zones || []) {
      const [zx, zy] = this.pos(z.x, z.y);
      const r = Math.max(6, this.scale * (z.r || 150));
      const spent = z.state && z.state !== 'active';
      ctx.save();
      ctx.globalAlpha = spent ? 0.2 : 0.55;
      const grad = ctx.createRadialGradient(zx, zy, r * 0.2, zx, zy, r);
      grad.addColorStop(0, (z.color || '#38bdf8') + 'cc');
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(zx, zy, r, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = spent ? 0.3 : 1;
      ctx.strokeStyle = z.color || '#38bdf8';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(zx, zy, r, 0, Math.PI * 2); ctx.stroke();
      if (z.label) {
        ctx.fillStyle = '#fff';
        ctx.font = `700 ${Math.max(10, Math.round(r * 0.8))}px system-ui`;
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(z.label, zx, zy);
      }
      ctx.restore();
    }

    // The nominated pocket, pulsing so it is unmissable from the rail.
    for (const p of g.pockets || []) {
      const pos = P[p.pocket];
      if (!pos) continue;
      const [px, py] = this.pos(pos[0], pos[1]);
      const beat = 0.6 + 0.4 * Math.sin(t * 4);
      ctx.save();
      ctx.globalAlpha = beat;
      ctx.strokeStyle = p.color || '#22d3ee';
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(px, py, Math.max(10, this.scale * 150), 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }

    if (g.aim && g.aim.cue && g.aim.target) {
      const a = this.pos(g.aim.cue[0], g.aim.cue[1]);
      const b = this.pos(g.aim.target[0], g.aim.target[1]);
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = 'rgba(255,255,255,0.75)';
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.restore();
      if (g.aim.pocket && P[g.aim.pocket]) {
        const c = this.pos(P[g.aim.pocket][0], P[g.aim.pocket][1]);
        ctx.save();
        ctx.strokeStyle = '#ffd166';
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(b[0], b[1]); ctx.lineTo(c[0], c[1]); ctx.stroke();
        ctx.restore();
      }
    }
    if ((g.zones || []).length || (g.pockets || []).length) {
      // Keep the pulse alive without a render loop when nothing else moves.
      if (!this._pulse) {
        this._pulse = setInterval(() => this.draw(), 90);
      }
    } else if (this._pulse) {
      clearInterval(this._pulse);
      this._pulse = null;
    }
  }

  draw() {
    const ctx = this.ctx;
    const { w, h } = this;
    if (!w) return;
    ctx.clearRect(0, 0, w, h);

    // cloth, with a little vignette so the balls sit on something
    // Show the real cloth, so the tablet looks like the table in front of you.
    const base = this.cloth || CLOTH;
    const g = ctx.createRadialGradient(w / 2, h / 2, h * 0.1, w / 2, h / 2, w * 0.72);
    g.addColorStop(0, base);
    g.addColorStop(1, this.cloth ? shade(base, -0.22) : CLOTH_DARK);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // head string and spots, the markings a player actually reads
    ctx.strokeStyle = 'rgba(255,255,255,0.10)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(w * 0.25, 0); ctx.lineTo(w * 0.25, h);
    ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.18)';
    for (const fx of [0.25, 0.5, 0.75]) {
      ctx.beginPath(); ctx.arc(w * fx, h / 2, 2, 0, Math.PI * 2); ctx.fill();
    }

    // diamonds
    ctx.fillStyle = 'rgba(255,255,255,0.22)';
    for (let i = 1; i < 8; i++) {
      if (i === 4) continue;
      for (const y of [1.5, h - 1.5]) {
        ctx.beginPath(); ctx.arc((w * i) / 8, y, 1.6, 0, Math.PI * 2); ctx.fill();
      }
    }

    // Pockets at their real mouth size (a corner mouth is about two ball
    // widths), not an arbitrary blob — the point of this view is that it
    // matches the table.
    const corner = (this.table.corner_mouth || 115) / 2;
    const side = (this.table.side_mouth || 130) / 2;
    const P = this.pockets || {
      TL: [0, 0], TM: [this.table.length / 2, 0], TR: [this.table.length, 0],
      BL: [0, this.table.width], BM: [this.table.length / 2, this.table.width],
      BR: [this.table.length, this.table.width],
    };
    for (const id of Object.keys(P)) {
      const [px, py] = this.pos(P[id][0], P[id][1]);
      const pr = Math.max(5, this.scale * (id === 'TM' || id === 'BM' ? side : corner));
      ctx.beginPath();
      ctx.arc(px, py, pr, 0, Math.PI * 2);
      ctx.fillStyle = '#080A0C';
      ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,0.6)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    this.drawGuides(ctx);
    this.drawTraces(ctx);

    // balls that just dropped, fading
    const now = performance.now();
    this.ghosts = this.ghosts.filter((g2) => now - g2.t < 900);
    for (const gh of this.ghosts) {
      const k = 1 - (now - gh.t) / 900;
      ctx.save();
      ctx.globalAlpha = k * 0.5;
      const [bx, by] = this.pos(gh.x, gh.y);
      drawBall(ctx, bx, by, Math.max(3, this.scale * (gh.r || 28.6)) * (0.6 + k * 0.4),
               gh.number, { shadow: false, number: false });
      ctx.restore();
    }

    for (const b of this.balls) {
      const [bx, by] = this.pos(b.x, b.y);
      const r = Math.max(3, this.scale * (b.r || 28.6));
      if (this.highlight.has(b.number)) {
        // A soft pool of light under the ball reads better in a cluster than
        // a hard ring, which just adds edges to an already busy rack.
        const halo = ctx.createRadialGradient(bx, by, r * 0.8, bx, by, r * 2.1);
        halo.addColorStop(0, this.accent + '66');
        halo.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = halo;
        ctx.beginPath();
        ctx.arc(bx, by, r * 2.1, 0, Math.PI * 2);
        ctx.fill();
      }
      drawBall(ctx, bx, by, r, b.number);
      if ((b.confidence ?? 1) < 0.5) {
        ctx.beginPath();
        ctx.arc(bx, by, r * 1.4, 0, Math.PI * 2);
        ctx.strokeStyle = '#F59E0B';
        ctx.setLineDash([3, 3]);
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    if (this.ghosts.length) requestAnimationFrame(() => this.draw());
  }
}
