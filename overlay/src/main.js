// The projector client: subscribe to the engine, draw light on the cloth.
//
// Layer order matters physically, not just visually. Guides go under the balls
// (aiming lines, pocket rings, zones) so they read as markings on the cloth;
// effects go over (explosions, sparks); the HUD sits on top in the dead space
// between balls. Nothing is drawn where a ball sits unless it is meant to look
// like it is lighting the ball up.

import { View } from './view.js';
import { makeEffect } from './effects.js';

const canvas = document.getElementById('stage');
const ctx = canvas.getContext('2d');
const statusEl = document.getElementById('status');
const helpEl = document.getElementById('help');

const DEFAULT_TABLE = { length: 2235, width: 1118, ball_radius: 28.6 };

const scene = {
  table: DEFAULT_TABLE,
  pocketMap: null,
  balls: [],
  prevBalls: [],
  settled: true,
  obstructed: false,
  scoreboard: null,
  trails: new Map(),            // ball number -> recent positions
  pockets() {
    if (this.pocketMap) return this.pocketMap;
    const { length: L, width: W } = this.table;
    this.pocketMap = {
      TL: [0, 0], TM: [L / 2, 0], TR: [L, 0],
      BL: [0, W], BM: [L / 2, W], BR: [L, W],
    };
    return this.pocketMap;
  },
  ball(n) { return this.balls.find((b) => b.number === n); },
};

const view = new View(scene.table);
let effects = [];
let showBalls = localStorage.getItem('poolarena.showBalls') === '1';
let showTrails = true;
let clipToTable = localStorage.getItem('poolarena.clip') !== '0';

// --- sizing ---------------------------------------------------------------
function resize() {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.floor(window.innerWidth * dpr);
  canvas.height = Math.floor(window.innerHeight * dpr);
  canvas.style.width = window.innerWidth + 'px';
  canvas.style.height = window.innerHeight + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  view.resize(window.innerWidth, window.innerHeight);
}
window.addEventListener('resize', resize);

// --- websocket ------------------------------------------------------------
let ws = null;
let retry = 500;

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    retry = 500;
    setStatus('connected', true);
    send({ type: 'games' });
  };
  ws.onclose = () => {
    setStatus('reconnecting…', false);
    setTimeout(connect, retry);
    retry = Math.min(5000, retry * 1.6);
  };
  ws.onerror = () => setStatus('socket error', false);
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch (e) { return; }
    handle(msg);
  };
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function setStatus(text, ok) {
  statusEl.textContent = text;
  statusEl.className = ok ? 'ok' : 'bad';
}

function handle(msg) {
  switch (msg.type) {
    case 'table':
      scene.table = { ...DEFAULT_TABLE, ...msg.table };
      scene.pocketMap = null;
      if (msg.table.pockets) scene.pocketMap = msg.table.pockets;
      view.setTable(scene.table);
      view.solve();
      break;
    case 'state': {
      scene.prevBalls = scene.balls;
      scene.balls = msg.state.balls || [];
      scene.settled = msg.state.settled;
      scene.obstructed = msg.state.obstructed;
      updateTrails();
      break;
    }
    case 'effects':
      applyBatch(msg.effects || []);
      break;
    case 'scoreboard':
      scene.scoreboard = msg.scoreboard;
      break;
    case 'projector_calibration':
      if (msg.corners) view.setCorners(msg.corners);
      break;
    default:
      break;
  }
}

// Effects arrive in batches — one batch per turn start, per shot result, per
// game start. A batch that carries persistent effects on a layer replaces the
// persistent effects already on that layer, so last turn's aiming line does
// not survive into this turn. Clearing is per batch, never per effect: a game
// that lights two things at once (cut-throat marks your balls *and* your
// targets) sends them together and both stay up.
function applyBatch(list) {
  const made = [];
  for (const e of list) {
    const fx = makeEffect(e.name, e.args, scene);
    if (!fx) { console.warn('unknown effect', e.name); continue; }
    made.push(fx);
  }
  const replacing = new Set(made.filter((f) => f.persist).map((f) => f.layer));
  if (replacing.size) {
    effects = effects.filter((x) => !(x.persist && replacing.has(x.layer)));
  }
  effects.push(...made);
}

// Single effect, for the console and the test keys. Never clears anything.
function spawn(e) {
  const fx = makeEffect(e.name, e.args, scene);
  if (!fx) { console.warn('unknown effect', e.name); return; }
  effects.push(fx);
}

// --- trails ---------------------------------------------------------------
function updateTrails() {
  const prev = new Map(scene.prevBalls.map((b) => [b.number, b]));
  for (const b of scene.balls) {
    const p = prev.get(b.number);
    const moved = p ? Math.hypot(b.x - p.x, b.y - p.y) : 0;
    let tr = scene.trails.get(b.number);
    if (!tr) { tr = []; scene.trails.set(b.number, tr); }
    if (moved > 4) {
      tr.push([b.x, b.y, performance.now()]);
      if (tr.length > 26) tr.shift();
    }
  }
}

function drawTrails() {
  if (!showTrails) return;
  const now = performance.now();
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  for (const [, tr] of scene.trails) {
    while (tr.length && now - tr[0][2] > 700) tr.shift();
    if (tr.length < 2) continue;
    for (let i = 1; i < tr.length; i++) {
      const age = (now - tr[i][2]) / 700;
      ctx.globalAlpha = Math.max(0, 0.55 * (1 - age));
      ctx.strokeStyle = '#7dd3fc';
      ctx.lineWidth = Math.max(1, view.mm(34 * (1 - age)));
      ctx.lineCap = 'round';
      view.pathPoly(ctx, [[tr[i - 1][0], tr[i - 1][1]], [tr[i][0], tr[i][1]]], false);
      ctx.stroke();
    }
  }
  ctx.restore();
}

// Debug view: draw where the system thinks each ball is. On a real table this
// should land exactly on the balls — it is the fastest calibration check there
// is, and it is the only honest way to see tracking error.
const BALL_COLORS = {
  0: '#ffffff', 1: '#ffd60a', 2: '#0353a4', 3: '#d00000', 4: '#7209b7',
  5: '#f77f00', 6: '#2d6a4f', 7: '#6a040f', 8: '#1b1b1b',
};
function drawBalls() {
  if (!showBalls) return;
  ctx.save();
  for (const b of scene.balls) {
    const base = BALL_COLORS[b.number % 8 === 0 && b.number ? 8 : (b.number > 8 ? b.number - 8 : b.number)]
      || '#cccccc';
    const striped = b.number > 8;
    const [sx, sy] = view.project(b.x, b.y);
    const R = Math.max(3, view.mm(b.r || 28.6));
    ctx.globalAlpha = 0.9;
    ctx.fillStyle = striped ? '#ffffff' : base;
    ctx.beginPath(); ctx.arc(sx, sy, R, 0, Math.PI * 2); ctx.fill();
    if (striped) {
      ctx.fillStyle = base;
      ctx.beginPath();
      ctx.ellipse(sx, sy, R, R * 0.52, 0, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = b.number === 8 || striped || b.number === 0 ? '#111' : '#fff';
    if (b.number !== 0) {
      ctx.font = `bold ${Math.round(R * 0.95)}px system-ui, sans-serif`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillStyle = '#ffffff';
      ctx.strokeStyle = 'rgba(0,0,0,0.7)';
      ctx.lineWidth = 2;
      ctx.strokeText(String(b.number), sx, sy);
      ctx.fillText(String(b.number), sx, sy);
    }
    if ((b.confidence ?? 1) < 0.5) {
      ctx.globalAlpha = 0.8;
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(sx, sy, R * 1.5, 0, Math.PI * 2); ctx.stroke();
    }
  }
  ctx.restore();
}

// --- loop -----------------------------------------------------------------
let last = performance.now();
function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;

  ctx.setTransform(Math.min(2, window.devicePixelRatio || 1), 0, 0,
                   Math.min(2, window.devicePixelRatio || 1), 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  for (const fx of effects) fx.update(dt);
  effects = effects.filter((fx) => !fx.done);

  // Clip to the table quad. Without this an explosion throws sparks onto the
  // players and the floor, which looks like a fault rather than an effect —
  // the cloth is the screen, and nothing should land outside it.
  ctx.save();
  if (clipToTable) {
    view.pathPoly(ctx, [[0, 0], [view.L, 0], [view.L, view.W], [0, view.W]]);
    ctx.clip();
  }
  for (const layer of ['guide']) {
    for (const fx of effects) if (fx.layer === layer) fx.draw(ctx, view, scene);
  }
  drawTrails();
  drawBalls();
  for (const layer of ['fx', 'hud']) {
    for (const fx of effects) if (fx.layer === layer) fx.draw(ctx, view, scene);
  }
  ctx.restore();

  if (scene.obstructed) {
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.fillStyle = '#f59e0b';
    ctx.font = '600 16px system-ui';
    ctx.fillText('view obstructed', 20, window.innerHeight - 20);
    ctx.restore();
  }

  if (view.calibrating) view.drawCalibration(ctx);
  requestAnimationFrame(frame);
}

// --- input ----------------------------------------------------------------
canvas.addEventListener('pointerdown', (e) => {
  if (!view.calibrating) return;
  view.dragging = view.cornerAt(e.clientX, e.clientY);
});
canvas.addEventListener('pointermove', (e) => {
  if (!view.calibrating || view.dragging < 0) return;
  view.corners[view.dragging] = [e.clientX, e.clientY];
  view.solve();
});
canvas.addEventListener('pointerup', () => {
  if (view.dragging >= 0) { view.save(); pushCalibration(); }
  view.dragging = -1;
});

function pushCalibration() {
  send({ type: 'projector_calibration', corners: view.corners });
}

const HELP = [
  ['c', 'corner calibration on/off'],
  ['arrows', 'nudge the selected corner (shift = 10 px)'],
  ['1-4', 'select corner TL TR BR BL'],
  ['b', 'draw tracked balls (alignment check)'],
  ['t', 'trails on/off'],
  ['o', 'clip effects to the table (default on)'],
  ['x', 'test explosion'],
  ['g', 'test pocket glows'],
  ['f', 'fullscreen'],
  ['r', 'reset corners'],
  ['h', 'this help'],
];

function renderHelp() {
  helpEl.innerHTML = HELP.map(([k, v]) => `<div><kbd>${k}</kbd><span>${v}</span></div>`).join('');
}

let selected = 0;
window.addEventListener('keydown', (e) => {
  const k = e.key.toLowerCase();
  if (k === 'c') {
    view.calibrating = !view.calibrating;
    helpEl.classList.toggle('show', view.calibrating);
  } else if (k === 'b') {
    showBalls = !showBalls;
    localStorage.setItem('poolarena.showBalls', showBalls ? '1' : '0');
  } else if (k === 't') {
    showTrails = !showTrails;
  } else if (k === 'o') {
    clipToTable = !clipToTable;
    localStorage.setItem('poolarena.clip', clipToTable ? '1' : '0');
  } else if (k === 'f') {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  } else if (k === 'h') {
    helpEl.classList.toggle('show');
  } else if (k === 'r') {
    view.corners = view.defaultCorners(window.innerWidth, window.innerHeight);
    view.solve(); view.save(); pushCalibration();
  } else if (['1', '2', '3', '4'].includes(k)) {
    selected = Number(k) - 1;
    view.dragging = selected;
  } else if (k === 'x') {
    spawn({ name: 'explosion', args: { x: scene.table.length / 2, y: scene.table.width / 2,
                                       intensity: 1.6, palette: 'fire' } });
  } else if (k === 'g') {
    for (const id of Object.keys(scene.pockets())) {
      spawn({ name: 'pocket_glow', args: { pocket: id, duration: 1500, intensity: 1.2 } });
    }
  } else if (e.key.startsWith('Arrow') && view.calibrating) {
    const step = e.shiftKey ? 10 : 1;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (d) { view.nudge(selected, d[0], d[1]); view.save(); pushCalibration(); }
    e.preventDefault();
  }
});

// --- go -------------------------------------------------------------------
renderHelp();
resize();
view.load();
connect();
requestAnimationFrame(frame);

// Expose a little surface for poking at effects from the browser console,
// which is how you tune an animation without replaying a whole game.
window.poolarena = { scene, view, spawn, applyBatch, effects: () => effects, send };
