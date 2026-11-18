// Watching a game back.
//
// The engine samples ball positions while the balls are rolling, so a
// recording contains the path each ball actually took — not just where they
// ended up. Replaying those paths is the difference between a scoresheet and
// something you can learn from: you see the shot you played, where the cue
// ball went afterwards, and which of those two lost you the frame.

import { setBallSet } from './balls.js';
import { setCloth } from './cloth.js';
import { MiniTable } from './minitable.js';

const el = (id) => document.getElementById(id);
const api = async (path, body) => (await fetch(path, body
  ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body) }
  : undefined)).json();

let mini = null;
let session = null;
let shotIndex = 0;
let playing = false;
let raf = null;

// --- the list -------------------------------------------------------------
const when = (t) => {
  if (!t) return '';
  const d = new Date(t * 1000);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
    + ' ' + d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
};

async function loadSessions() {
  const { sessions } = await api('/api/sessions');
  const list = el('sessions');
  list.textContent = '';
  if (!sessions.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No recordings yet. Play a game and it will appear here.';
    list.appendChild(li);
    el('sub').textContent = 'nothing recorded yet';
    return;
  }
  el('sub').textContent = `${sessions.length} recorded`;
  for (const s of sessions) {
    const li = document.createElement('li');
    li.innerHTML = '<div class="who"></div><div class="when"></div>';
    li.querySelector('.who').textContent =
      `${s.title} — ${(s.players || []).join(' v ')}`;
    const won = s.winner !== null && s.winner !== undefined && s.players[s.winner]
      ? `, ${s.players[s.winner]} won` : '';
    li.querySelector('.when').textContent = `${when(s.started)} · ${s.shots} shots${won}`;
    li.onclick = () => open(s.id, li);
    list.appendChild(li);
  }
}

async function open(id, li) {
  [...el('sessions').children].forEach((c) =>
    c.setAttribute('aria-selected', String(c === li)));
  const d = await api('/api/session', { id });
  if (d.ok === false) { el('sub').textContent = d.error; return; }
  session = d;
  setBallSet({ name: d.ball_set, has_numbers: d.ball_set !== 'english' });
  if (d.table) { setCloth(d.table.cloth); mini.setTable(d.table); }
  el('title').textContent = d.title || d.game;
  el('sub').textContent = `${(d.players || []).join(' v ')} · ${d.shots.length} shots`;
  shotIndex = 0;
  renderShots();
  renderStats(d.stats);
  show(0);
}

// --- shots ----------------------------------------------------------------
function kindOf(shot) {
  const r = shot.result || {};
  const ev = shot.events || {};
  if (r.winner !== null && r.winner !== undefined) return 'win';
  if (r.foul) return 'foul';
  if ((ev.pocketed || []).length) return 'pot';
  return 'safe';
}

function renderShots() {
  const ol = el('shots');
  ol.textContent = '';
  session.shots.forEach((shot, i) => {
    const li = document.createElement('li');
    li.className = kindOf(shot);
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = session.players[shot.shooter] ?? `P${shot.shooter + 1}`;
    const what = document.createElement('span');
    what.className = 'what';
    what.textContent = (shot.result || {}).message || (shot.result || {}).foul || 'shot';
    li.append(who, what);
    li.onclick = () => { stop(); shotIndex = i; show(i); };
    ol.appendChild(li);
  });
}

function highlightShot() {
  [...el('shots').children].forEach((c, i) =>
    c.style.outline = i === shotIndex ? '2px solid var(--gold)' : '');
  const li = el('shots').children[shotIndex];
  if (li) li.scrollIntoView({ block: 'nearest' });
}

/** Draw one shot, either its final state or a moment part-way through. */
function show(i, progress = 1) {
  const shot = session.shots[i];
  if (!shot) return;
  const traces = Object.entries(shot.trace || {}).map(([n, points]) => ({
    n: Number(n), points, upto: Math.max(2, Math.round(points.length * progress)),
  }));

  // Positions come from the traces while the shot is running and from the
  // recorded resting state once it has finished, so the end is exact.
  let balls;
  if (progress >= 1 || !traces.length) {
    balls = (shot.after || {}).balls || [];
  } else {
    const start = new Map(((shot.before || {}).balls || []).map((b) => [b.number, b]));
    balls = [];
    for (const [num, b] of start) {
      const t = traces.find((x) => x.n === num);
      if (t) {
        const p = t.points[Math.min(t.points.length - 1, t.upto - 1)];
        balls.push({ ...b, x: p[0], y: p[1] });
      } else {
        balls.push(b);
      }
    }
  }
  mini.setBalls(balls);
  mini.setTraces(traces);

  const r = shot.result || {};
  const ev = shot.events || {};
  const bits = [`Shot ${i + 1} of ${session.shots.length}`,
                session.players[shot.shooter] ?? ''];
  if (r.foul) bits.push(`foul: ${r.foul}`);
  else if ((ev.pocketed || []).length) bits.push(`potted ${ev.pocketed.join(', ')}`);
  else bits.push(r.message || 'safe');
  if (ev.pocketed_in && Object.keys(ev.pocketed_in).length) {
    bits.push(`into ${Object.values(ev.pocketed_in).join(', ')}`);
  }
  el('caption').textContent = bits.filter(Boolean).join(' · ');
  el('felt-tag').textContent = `shot ${i + 1}`;
  highlightShot();
}

// --- playback -------------------------------------------------------------
function speed() { return Number(el('speed').value) / 100; }

function play() {
  if (!session || !session.shots.length) return;
  playing = true;
  el('play').textContent = 'Pause';
  let started = performance.now();
  const step = (now) => {
    if (!playing) return;
    // A real shot takes a second or two; replay it over that, scaled.
    const span = 1400 / speed();
    const p = Math.min(1, (now - started) / span);
    show(shotIndex, p);
    if (p >= 1) {
      if (shotIndex >= session.shots.length - 1) { stop(); return; }
      shotIndex += 1;
      started = now + 450 / speed();     // a beat between shots
    }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}

function stop() {
  playing = false;
  el('play').textContent = 'Play';
  if (raf) cancelAnimationFrame(raf);
}

el('play').onclick = () => (playing ? stop() : play());
el('prev').onclick = () => { stop(); shotIndex = Math.max(0, shotIndex - 1); show(shotIndex); };
el('next').onclick = () => {
  stop();
  shotIndex = Math.min((session?.shots.length ?? 1) - 1, shotIndex + 1);
  show(shotIndex);
};
el('speed').oninput = () => { el('speed-label').textContent = speed().toFixed(1) + 'x'; };
window.addEventListener('keydown', (e) => {
  if (e.key === ' ') { e.preventDefault(); playing ? stop() : play(); }
  if (e.key === 'ArrowLeft') el('prev').click();
  if (e.key === 'ArrowRight') el('next').click();
});

// --- stats ----------------------------------------------------------------
function renderStats(stats) {
  const box = el('stats');
  box.hidden = !stats;
  if (!stats) return;
  box.textContent = '';
  if (stats.insight) {
    const p = document.createElement('div');
    p.className = 'insight';
    p.textContent = stats.insight;
    box.appendChild(p);
  }
  const grid = document.createElement('div');
  grid.className = 'stat-grid';
  for (const p of stats.players || []) {
    const card = document.createElement('div');
    card.className = 'stat-card';
    const h = document.createElement('h3');
    h.textContent = p.name;
    card.appendChild(h);
    const rows = [
      ['Shots', p.shots],
      ['Pot rate', p.pot_rate === null ? '—' : `${Math.round(p.pot_rate * 100)}%`],
      ['Balls potted', p.balls_potted],
      ['Best run', p.best_run],
      ['Fouls', `${p.fouls}${p.worst_foul ? ` (mostly ${p.worst_foul})` : ''}`],
      ['Cue ball moved', p.avg_cue_travel_mm ? `${p.avg_cue_travel_mm} mm a shot` : '—'],
    ];
    for (const [k, v] of rows) {
      const r = document.createElement('div');
      r.className = 'stat-row';
      const a = document.createElement('span'); a.textContent = k;
      const b = document.createElement('b'); b.textContent = v;
      r.append(a, b);
      card.appendChild(r);
    }
    grid.appendChild(card);
  }
  box.appendChild(grid);
}

mini = new MiniTable(el('mini'));
el('speed-label').textContent = '1.0x';
loadSessions();
