// The design system is the rack. Every colour in this interface comes from a
// real ball, which is why it reads as a pool product rather than as a generic
// dark dashboard with a green accent.

export const BALL = {
  0:  { solid: '#F4F1E8', ink: '#15161A', name: 'cue' },
  1:  { solid: '#F2B705', ink: '#15161A' },
  2:  { solid: '#0B5FD8', ink: '#FFFFFF' },
  3:  { solid: '#DC2626', ink: '#FFFFFF' },
  4:  { solid: '#6D28D9', ink: '#FFFFFF' },
  5:  { solid: '#F97316', ink: '#15161A' },
  6:  { solid: '#15803D', ink: '#FFFFFF' },
  7:  { solid: '#7F1D1D', ink: '#FFFFFF' },
  8:  { solid: '#15161A', ink: '#FFFFFF' },
};

export const CLOTH = '#1B6E54';
export const CLOTH_DARK = '#14543F';
export const RAIL = '#3B2416';

/** Colour and stripe flag for any ball number. */
export function ballStyle(n) {
  if (n === 0) return { fill: BALL[0].solid, ink: BALL[0].ink, striped: false };
  const base = BALL[n > 8 ? n - 8 : n] || BALL[8];
  return { fill: base.solid, ink: base.ink, striped: n > 8 };
}

/**
 * Draw a ball into a 2D context, centred, in device pixels.
 * Shared by the tablet's live table and the projector's alignment view, so a
 * 9-ball looks like a 9-ball in both places.
 */
export function drawBall(ctx, x, y, r, n, opts = {}) {
  const { fill, ink, striped } = ballStyle(n);
  ctx.save();
  ctx.translate(x, y);

  if (opts.shadow !== false) {
    ctx.save();
    ctx.globalAlpha = 0.45;
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.ellipse(r * 0.18, r * 0.3, r * 0.98, r * 0.86, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  // White base for a stripe, colour for a solid.
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fillStyle = striped ? '#F4F1E8' : fill;
  ctx.fill();

  if (striped) {
    ctx.save();
    ctx.clip();
    ctx.fillStyle = fill;
    ctx.fillRect(-r, -r * 0.55, r * 2, r * 1.1);
    ctx.restore();
  }

  // A single soft highlight sells the sphere; two makes it look like plastic.
  const g = ctx.createRadialGradient(-r * 0.35, -r * 0.42, r * 0.05, 0, 0, r * 1.15);
  g.addColorStop(0, 'rgba(255,255,255,0.55)');
  g.addColorStop(0.35, 'rgba(255,255,255,0.08)');
  g.addColorStop(1, 'rgba(0,0,0,0.45)');
  ctx.beginPath();
  ctx.arc(0, 0, r, 0, Math.PI * 2);
  ctx.fillStyle = g;
  ctx.fill();

  if (n > 0 && opts.number !== false && r > 7) {
    const nr = r * 0.56;
    ctx.beginPath();
    ctx.arc(0, 0, nr, 0, Math.PI * 2);
    ctx.fillStyle = '#F7F4EC';
    ctx.fill();
    ctx.fillStyle = '#15161A';
    ctx.font = `700 ${Math.round(nr * 1.15)}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(n), 0, nr * 0.06);
  }
  ctx.restore();
}

/** An <span> chip of a ball, for the roster and the shot feed. */
export function ballChip(n, size = 26) {
  const { fill, striped } = ballStyle(n);
  const el = document.createElement('span');
  el.className = 'ball' + (striped ? ' striped' : '');
  el.style.setProperty('--ball', fill);
  el.style.setProperty('--size', size + 'px');
  el.textContent = n === 0 ? '' : String(n);
  el.title = n === 0 ? 'cue ball' : `${striped ? 'stripe' : 'solid'} ${n}`;
  return el;
}

export function ballRow(numbers, size = 26) {
  const wrap = document.createElement('span');
  wrap.className = 'ball-row';
  numbers.forEach((n) => wrap.appendChild(ballChip(n, size)));
  return wrap;
}
