// Table-millimetres -> projector-pixels, through a 4-corner homography.
//
// A projector is never square to the table and never will be, so rather than
// fighting it with physical alignment we solve the mapping once by dragging
// four corners onto the cushion corners. Everything else in the overlay draws
// in millimetres and never thinks about the projector again.

function solve(A, b) {
  // Gaussian elimination with partial pivoting. n is 8, so this is free.
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let piv = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
    [M[col], M[piv]] = [M[piv], M[col]];
    const d = M[col][col] || 1e-12;
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = M[r][col] / d;
      if (!f) continue;
      for (let c = col; c <= n; c++) M[r][c] -= f * M[col][c];
    }
  }
  return M.map((row, i) => row[n] / (row[i] || 1e-12));
}

export function homography(src, dst) {
  const A = [], b = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i], [u, v] = dst[i];
    A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
    A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
  }
  const h = solve(A, b);
  return [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], 1];
}

export class View {
  constructor(table) {
    this.setTable(table);
    this.corners = null;          // projector-pixel corners, TL TR BR BL
    this.H = null;
    this.calibrating = false;
    this.dragging = -1;
  }

  setTable(table) {
    this.table = table || { length: 2235, width: 1118 };
    this.L = this.table.length;
    this.W = this.table.width;
  }

  // Default corners: the table centred in the window with a small margin, so
  // something sensible appears before anyone calibrates.
  defaultCorners(w, h) {
    const pad = 0.04;
    const aspect = this.L / this.W;
    let tw = w * (1 - pad * 2), th = tw / aspect;
    if (th > h * (1 - pad * 2)) { th = h * (1 - pad * 2); tw = th * aspect; }
    const x0 = (w - tw) / 2, y0 = (h - th) / 2;
    return [[x0, y0], [x0 + tw, y0], [x0 + tw, y0 + th], [x0, y0 + th]];
  }

  resize(w, h) {
    this.w = w; this.h = h;
    if (!this.corners) this.corners = this.defaultCorners(w, h);
    this.solve();
  }

  setCorners(corners) {
    if (!corners || corners.length !== 4) return;
    this.corners = corners.map((c) => [c[0], c[1]]);
    this.solve();
  }

  solve() {
    const src = [[0, 0], [this.L, 0], [this.L, this.W], [0, this.W]];
    this.H = homography(src, this.corners);
    // Average projected length of a 100 mm segment, for line widths and radii.
    const a = this.project(0, this.W / 2), b = this.project(100, this.W / 2);
    const c = this.project(this.L / 2, 0), d = this.project(this.L / 2, 100);
    this.pxPerMm = (Math.hypot(b[0] - a[0], b[1] - a[1]) +
                    Math.hypot(d[0] - c[0], d[1] - c[1])) / 200;
  }

  project(x, y) {
    const H = this.H;
    const wz = H[6] * x + H[7] * y + H[8] || 1e-12;
    return [(H[0] * x + H[1] * y + H[2]) / wz, (H[3] * x + H[4] * y + H[5]) / wz];
  }

  // Trace a path given in mm. Circles become polygons because a homography
  // turns a circle into a conic, and 48 segments is visually exact.
  pathPoly(ctx, pts, close = true) {
    ctx.beginPath();
    pts.forEach(([x, y], i) => {
      const p = this.project(x, y);
      if (i === 0) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
    });
    if (close) ctx.closePath();
  }

  circlePoly(ctx, cx, cy, r, segments = 48) {
    const pts = [];
    for (let i = 0; i < segments; i++) {
      const a = (i / segments) * Math.PI * 2;
      pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
    }
    this.pathPoly(ctx, pts, true);
  }

  mm(v) { return v * this.pxPerMm; }

  // --- calibration -----------------------------------------------------
  cornerAt(px, py, tol = 28) {
    for (let i = 0; i < 4; i++) {
      const [x, y] = this.corners[i];
      if (Math.hypot(px - x, py - y) < tol) return i;
    }
    return -1;
  }

  nudge(i, dx, dy) {
    this.corners[i][0] += dx;
    this.corners[i][1] += dy;
    this.solve();
  }

  save() {
    localStorage.setItem('poolarena.corners', JSON.stringify(this.corners));
  }

  load() {
    try {
      const raw = localStorage.getItem('poolarena.corners');
      if (raw) { this.setCorners(JSON.parse(raw)); return true; }
    } catch (e) { /* ignore a corrupt entry and fall back to defaults */ }
    return false;
  }

  drawCalibration(ctx) {
    const labels = ['TL', 'TR', 'BR', 'BL'];
    ctx.save();
    // Table outline plus a grid, so you can see keystone error in the middle
    // rather than only at the corners.
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 2;
    this.pathPoly(ctx, [[0, 0], [this.L, 0], [this.L, this.W], [0, this.W]]);
    ctx.stroke();
    ctx.strokeStyle = 'rgba(34,211,238,0.35)';
    ctx.lineWidth = 1;
    for (let i = 1; i < 8; i++) {
      this.pathPoly(ctx, [[this.L * i / 8, 0], [this.L * i / 8, this.W]], false);
      ctx.stroke();
    }
    for (let i = 1; i < 4; i++) {
      this.pathPoly(ctx, [[0, this.W * i / 4], [this.L, this.W * i / 4]], false);
      ctx.stroke();
    }
    // Pocket markers: the real test of a good calibration.
    ctx.fillStyle = 'rgba(244,114,182,0.9)';
    [[0, 0], [this.L / 2, 0], [this.L, 0], [0, this.W], [this.L / 2, this.W], [this.L, this.W]]
      .forEach(([x, y]) => {
        const p = this.project(x, y);
        ctx.beginPath(); ctx.arc(p[0], p[1], 8, 0, Math.PI * 2); ctx.fill();
      });
    this.corners.forEach(([x, y], i) => {
      ctx.fillStyle = this.dragging === i ? '#fde047' : '#22d3ee';
      ctx.beginPath(); ctx.arc(x, y, 12, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#000';
      ctx.font = 'bold 11px system-ui';
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(labels[i], x, y);
    });
    ctx.restore();
  }
}
