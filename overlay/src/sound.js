// Sound, synthesised rather than sampled.
//
// No audio files: nothing to license, nothing to download, nothing to go
// missing. Every noise here is built from oscillators and filtered noise at
// the moment it plays, which also means they can be varied — a two-ball pot
// is not the same sound twice.
//
// The rules of the thing, learned from arcade machines: short, dry, and
// mixed well below the room. A pool hall is already noisy and the table
// should punctuate it, not compete.

let ctx = null;
let master = null;
let enabled = true;

function audio() {
  if (ctx) return ctx;
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  ctx = new AC();
  master = ctx.createGain();
  master.gain.value = 0.35;
  master.connect(ctx.destination);
  return ctx;
}

/** Browsers refuse to make noise until the user has interacted. */
export function unlock() {
  const c = audio();
  if (c && c.state === 'suspended') c.resume();
}

export function setEnabled(on) { enabled = !!on; }
export function isEnabled() { return enabled; }
export function setVolume(v) { if (master) master.gain.value = Math.max(0, Math.min(1, v)); }

function env(node, { attack = 0.004, decay = 0.18, peak = 1.0, at = 0 } = {}) {
  const c = audio();
  const g = c.createGain();
  const t = c.currentTime + at;
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(Math.max(0.0001, peak), t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
  node.connect(g);
  g.connect(master);
  return g;
}

function tone(freq, opts = {}) {
  const c = audio();
  if (!c) return;
  const o = c.createOscillator();
  o.type = opts.type || 'sine';
  const t = c.currentTime + (opts.at || 0);
  o.frequency.setValueAtTime(freq, t);
  if (opts.to) o.frequency.exponentialRampToValueAtTime(opts.to, t + (opts.decay || 0.2));
  env(o, opts);
  o.start(t);
  o.stop(t + (opts.attack || 0.004) + (opts.decay || 0.2) + 0.05);
}

function noise({ at = 0, decay = 0.12, peak = 0.5, bandpass = 1200, q = 1 } = {}) {
  const c = audio();
  if (!c) return;
  const len = Math.max(1, Math.floor(c.sampleRate * (decay + 0.05)));
  const buf = c.createBuffer(1, len, c.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  const src = c.createBufferSource();
  src.buffer = buf;
  const f = c.createBiquadFilter();
  f.type = 'bandpass';
  f.frequency.value = bandpass;
  f.Q.value = q;
  src.connect(f);
  env(f, { attack: 0.002, decay, peak, at });
  src.start(c.currentTime + at);
}

// --- the sounds -----------------------------------------------------------
// A pot is the one that has to feel right: a short woody knock and the drop
// into the pocket underneath it.
const SOUNDS = {
  pot(n = 1) {
    noise({ bandpass: 2200, q: 1.4, decay: 0.05, peak: 0.5 });
    tone(190, { type: 'triangle', to: 90, decay: 0.22, peak: 0.5 });
    tone(95, { type: 'sine', to: 55, decay: 0.34, peak: 0.35, at: 0.05 });
    for (let i = 1; i < Math.min(n, 4); i++) {
      tone(210 + i * 30, { type: 'triangle', to: 100, decay: 0.2,
                           peak: 0.35, at: 0.09 * i });
    }
  },
  foul() {
    tone(150, { type: 'square', to: 80, decay: 0.42, peak: 0.28 });
    tone(151.5, { type: 'square', to: 78, decay: 0.42, peak: 0.26, at: 0.01 });
  },
  win() {
    [523.25, 659.25, 783.99, 1046.5].forEach((f, i) =>
      tone(f, { type: 'triangle', decay: 0.5, peak: 0.42, at: i * 0.1 }));
    noise({ bandpass: 4000, q: 0.7, decay: 0.7, peak: 0.16, at: 0.3 });
  },
  zone() {
    tone(880, { type: 'sine', decay: 0.16, peak: 0.3 });
    tone(1320, { type: 'sine', decay: 0.22, peak: 0.22, at: 0.06 });
  },
  tick() { tone(1400, { type: 'square', decay: 0.04, peak: 0.12 }); },
  spin() {
    for (let i = 0; i < 10; i++) {
      tone(700 + i * 60, { type: 'square', decay: 0.03, peak: 0.1, at: i * 0.11 });
    }
  },
  lost() { tone(330, { type: 'triangle', to: 160, decay: 0.3, peak: 0.3 }); },
};

/** Map an effect from the engine to a noise, or to nothing. */
export function play(name, args = {}) {
  if (!enabled || !audio()) return;
  switch (name) {
    case 'explosion':   return SOUNDS.pot(Math.round(args.intensity || 1));
    case 'pocket_glow': return args.persist ? undefined : SOUNDS.tick();
    case 'table_flash': return SOUNDS.foul();
    case 'fireworks':   return SOUNDS.win();
    case 'zone_hit':
    case 'zone_park':   return SOUNDS.zone();
    case 'roulette_spin': return SOUNDS.spin();
    case 'life_lost':
    case 'shatter':     return SOUNDS.lost();
    case 'score_pop':   return (args.delta ?? 0) > 0 ? SOUNDS.zone() : undefined;
    default:            return undefined;
  }
}

export function test() { unlock(); SOUNDS.pot(2); }
