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
  // The intro loop asks to start long before anyone touches this screen, so
  // the first gesture is where it actually gets to.
  if (musicBlocked && musicWanted && music) {
    music.play().then(() => { musicBlocked = false; }).catch(() => {});
  }
}

export function setEnabled(on) {
  enabled = !!on;
  // The tune is not a separate switch. One 's' quiets the whole table.
  if (!enabled && musicWanted) setMusic(false);
}
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

// --- the intro tune -------------------------------------------------------
// Everything above is synthesised. This is the one actual file, because a
// tune is not something you build out of oscillators as it plays.
//
// It is an arcade attract jingle, not background music: it plays once, waits
// ten minutes, and plays again, for as long as the table sits with no game
// on it. Looping nineteen seconds forever would be authentic to a cabinet
// and unbearable in a room people are trying to talk in.
//
// The first one comes half a minute after the table goes quiet. Not instant,
// because a game has usually just ended and somebody is racking up; not ten
// minutes, because then you would never know it worked.
const MUSIC_SRC = '/audio/intro.mp3';
const MUSIC_VOLUME = 0.30;
const FADE_MS = 1200;
const FIRST_AFTER_MS = 30_000;
const THEN_EVERY_MS = 10 * 60_000;

let music = null;
let musicWanted = false;
let fadeTimer = null;
let nextTimer = null;
/** Set when the browser refused to start it, so a later gesture can retry. */
let musicBlocked = false;

function musicEl() {
  if (music) return music;
  music = new Audio(MUSIC_SRC);
  music.preload = 'auto';
  music.volume = 0;
  // A missing or unplayable file must not take the projector down with it.
  music.addEventListener('error', () => { musicWanted = false; disarm(); });
  music.addEventListener('ended', () => { if (musicWanted) arm(THEN_EVERY_MS); });
  return music;
}

function fadeTo(target, done) {
  const el = musicEl();
  clearInterval(fadeTimer);
  const from = el.volume;
  const started = performance.now();
  fadeTimer = setInterval(() => {
    const k = Math.min(1, (performance.now() - started) / FADE_MS);
    el.volume = Math.max(0, Math.min(1, from + (target - from) * k));
    if (k >= 1) { clearInterval(fadeTimer); fadeTimer = null; if (done) done(); }
  }, 40);
}

function disarm() {
  clearTimeout(nextTimer);
  nextTimer = null;
}

function arm(delay) {
  disarm();
  nextTimer = setTimeout(playOnce, delay);
}

function playOnce() {
  if (!musicWanted || !enabled) return;
  const el = musicEl();
  el.currentTime = 0;
  const started = el.play();
  if (started && typeof started.catch === 'function') {
    started
      .then(() => { musicBlocked = false; })
      // play() is refused until the page has been interacted with, which is
      // most of the time for a screen nobody touches. Remember it, and let
      // unlock() pick it up on the first keypress.
      .catch(() => { musicBlocked = true; arm(THEN_EVERY_MS); });
  }
  fadeTo(MUSIC_VOLUME);
}

/**
 * Say whether the table is idle. Safe to call every frame — it only acts on
 * a change, so the render loop can just report what the table is doing.
 */
export function setMusic(on) {
  const want = !!on && enabled;
  if (want === musicWanted) return;
  musicWanted = want;
  if (want) {
    arm(FIRST_AFTER_MS);
  } else {
    disarm();
    if (music && !music.paused) {
      fadeTo(0, () => { music.pause(); music.currentTime = 0; });
    }
  }
}

export function isMusicPlaying() {
  return !!music && !music.paused && music.volume > 0;
}

/** For the tests, and for anyone wondering why it has gone quiet. */
export function musicState() {
  return { wanted: musicWanted, playing: isMusicPlaying(), blocked: musicBlocked,
           armed: nextTimer !== null };
}
