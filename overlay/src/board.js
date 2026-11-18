// The tablet: whose turn it is, what the table looks like, what just happened.
//
// It subscribes to the same stream as the projector, so it needs no polling and
// no state of its own beyond what the engine last said.

import { ballRow, setBallSet } from './balls.js';
import { MiniTable } from './minitable.js';

const el = (id) => document.getElementById(id);

let ws = null;
let retry = 400;
let games = [];
let picked = null;
let board = null;
let mini = null;

// --- connection -----------------------------------------------------------
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { retry = 400; setState('waiting for a game', true); send({ type: 'games' }); };
  ws.onclose = () => {
    setState('reconnecting', false);
    setTimeout(connect, retry);
    retry = Math.min(4000, retry * 1.6);
  };
  ws.onmessage = (ev) => {
    let msg; try { msg = JSON.parse(ev.data); } catch { return; }
    route(msg);
  };
}

const send = (o) => ws && ws.readyState === 1 && ws.send(JSON.stringify(o));

function route(msg) {
  switch (msg.type) {
    case 'games':
      games = msg.games;
      if (msg.ball_set) applyBallSet(msg.ball_set);
      renderGames();
      break;
    case 'table':
      if (msg.ball_set) applyBallSet(msg.ball_set);
      mini.setTable(msg.table);
      break;
    case 'state':      mini.setBalls(msg.state.balls || []); break;
    case 'scoreboard': board = msg.scoreboard; render(); break;
    case 'shot':       pushShot(msg.shot); break;
    case 'error':      showAlert(msg.error); break;
    default: break;
  }
}

function setState(text, live) {
  const s = el('game-state');
  s.textContent = text;
  s.className = 'state ' + (live ? 'live' : 'off');
}

function showAlert(text) {
  const box = el('alert');
  box.textContent = text;
  box.hidden = false;
  clearTimeout(showAlert.timer);
  showAlert.timer = setTimeout(() => { box.hidden = true; }, 9000);
}

// --- game picker ----------------------------------------------------------
let ballSetInfo = { name: 'american', title: 'American', has_numbers: true };

function applyBallSet(bs) {
  ballSetInfo = bs;
  setBallSet(bs);
  mini.draw();
}

function renderGames() {
  const wrap = el('games');
  wrap.textContent = '';
  for (const g of games) {
    const b = document.createElement('button');
    b.className = 'chip';
    b.type = 'button';
    b.disabled = g.supported === false;
    b.setAttribute('aria-pressed', String(picked === g.name));
    b.innerHTML = `<b></b><i></i>`;
    b.querySelector('b').textContent = g.title;
    b.querySelector('i').textContent = g.description;
    if (!b.disabled) b.onclick = () => pick(g.name);
    wrap.appendChild(b);
  }
  const hint = el('roster-hint');
  if (hint) hint.dataset.set = ballSetInfo.title || '';
  // Never leave an unplayable game selected.
  const playable = games.filter((g) => g.supported !== false);
  if (playable.length && !playable.some((g) => g.name === picked)) {
    pick(playable[0].name, false);
  }
}

// One field per player, rather than a comma-separated string nobody can see
// the shape of. The list resizes itself to whatever the chosen game accepts.
let roster = ['Player 1', 'Player 2'];

function renderRoster() {
  const g = games.find((x) => x.name === picked);
  const list = el('name-list');
  list.textContent = '';
  roster.forEach((name, i) => {
    const row = document.createElement('div');
    row.className = 'name-row';
    const seat = document.createElement('span');
    seat.className = 'seat';
    seat.textContent = `P${i + 1}`;
    const input = document.createElement('input');
    input.value = name;
    input.placeholder = `Player ${i + 1}`;
    input.autocomplete = 'off';
    input.oninput = () => { roster[i] = input.value; };
    input.onkeydown = (e) => { if (e.key === 'Enter') startGame(); };
    row.append(seat, input);
    list.appendChild(row);
  });
  if (g) {
    const span = g.min_players === g.max_players
      ? `${g.min_players} players` : `${g.min_players}-${g.max_players} players`;
    el('roster-hint').textContent = `${g.title}: ${span}`;
    el('add-player').disabled = roster.length >= g.max_players;
    el('remove-player').disabled = roster.length <= g.min_players;
  }
}

function fitRoster() {
  const g = games.find((x) => x.name === picked);
  if (!g) return;
  while (roster.length < g.min_players) roster.push(`Player ${roster.length + 1}`);
  if (roster.length > g.max_players) roster = roster.slice(0, g.max_players);
  renderRoster();
}

function pick(name, fixRoster = true) {
  picked = name;
  [...el('games').children].forEach((c, i) =>
    c.setAttribute('aria-pressed', String(games[i].name === name)));
  if (fixRoster) fitRoster(); else renderRoster();
}

const rosterNames = () =>
  roster.map((s) => s.trim()).filter(Boolean);

// --- scoreboard -----------------------------------------------------------
function render() {
  if (!board) return;
  el('game-title').textContent = board.title;
  el('shot-no').textContent = board.shot_number + 1;

  if (board.over) {
    const w = board.winner !== null && board.players[board.winner];
    setState(w ? `${w.name} wins` : 'game over', false);
  } else {
    setState(`${board.players[board.turn].name} to play`, true);
  }

  mini.highlight = new Set();
  const list = el('players-list');
  list.textContent = '';

  board.players.forEach((p, i) => {
    const card = document.createElement('div');
    card.className = 'player'
      + (i === board.turn && !board.over ? ' turn' : '')
      + (p.out ? ' out' : '');

    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = p.name;

    const meta = document.createElement('div');
    meta.className = 'meta';
    if (p.group) {
      const t = document.createElement('span');
      t.className = 'tag';
      t.textContent = p.group;
      meta.appendChild(t);
    }
    if (p.balls_left && p.balls_left.length) {
      meta.appendChild(ballRow(p.balls_left, 24));
    }
    if (p.lives) {
      const lv = document.createElement('span');
      lv.className = 'lives';
      const total = Math.max(p.lives, 3);
      for (let k = 0; k < total; k++) {
        const d = document.createElement('span');
        d.className = 'life' + (k < p.lives ? '' : ' spent');
        lv.appendChild(d);
      }
      meta.appendChild(lv);
    }

    const score = document.createElement('div');
    score.className = 'score';
    score.textContent = p.score;

    card.append(name, meta, score);
    list.appendChild(card);

    // ring the current player's remaining balls on the live table
    if (i === board.turn && p.balls_left) {
      p.balls_left.forEach((n) => mini.highlight.add(n));
    }
  });
  mini.draw();
}

// --- shot feed ------------------------------------------------------------
// Built from shot records rather than the engine's text log, so each row can
// be classified and coloured instead of being one more grey line.
const feed = [];

function pushShot(shot) {
  const r = shot.result || {};
  const ev = shot.events || {};
  const who = (board && board.players[shot.shooter] && board.players[shot.shooter].name) || '—';

  let kind = 'safe';
  let text = r.message || 'safe';
  if (r.winner !== null && r.winner !== undefined) kind = 'win';
  else if (r.foul) { kind = 'foul'; text = r.foul; }
  else if ((ev.pocketed || []).length) kind = 'pot';

  feed.unshift({ who, text, kind, balls: ev.pocketed || [], pockets: ev.pocketed_in || {} });
  feed.length = Math.min(feed.length, 40);
  renderFeed();
}

function renderFeed() {
  const ol = el('feed');
  ol.textContent = '';
  if (!feed.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'no shots yet';
    ol.appendChild(li);
    return;
  }
  for (const f of feed) {
    const li = document.createElement('li');
    li.className = f.kind;
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = f.who;
    const what = document.createElement('span');
    what.className = 'what';
    what.textContent = f.text;
    li.append(who, what);
    if (f.balls.length) {
      li.appendChild(ballRow(f.balls, 20));
    }
    ol.appendChild(li);
  }
}

// --- controls -------------------------------------------------------------
el('toggle-setup').onclick = () => {
  const panel = el('setup');
  panel.hidden = !panel.hidden;
  el('toggle-setup').setAttribute('aria-expanded', String(!panel.hidden));
  if (panel.hidden) send({ type: 'calibrate', on: false });
};
function startGame() {
  el('alert').hidden = true;
  send({ type: 'start_game', game: picked, players: rosterNames() });
}
el('start').onclick = startGame;
el('start2').onclick = startGame;
el('add-player').onclick = () => {
  roster.push(`Player ${roster.length + 1}`);
  renderRoster();
};
el('remove-player').onclick = () => { roster.pop(); renderRoster(); };

// --- setup tabs -----------------------------------------------------------
el('tabs').onclick = (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  const want = b.dataset.tab;
  [...el('tabs').children].forEach((t) =>
    t.setAttribute('aria-pressed', String(t.dataset.tab === want)));
  document.querySelectorAll('.tab').forEach((panel) => {
    panel.hidden = panel.dataset.panel !== want;
  });
  // Entering or leaving the projector tab drives the overlay's grid, so the
  // outline is on the cloth exactly while you are looking at these controls.
  send({ type: 'calibrate', on: want === 'projector' });
  if (want === 'camera') refreshCamera();
};
el('pass').onclick = () => send({ type: 'next_turn' });
el('boom').onclick = () => send({
  type: 'test_effect', name: 'fireworks', args: { duration: 2500, palette: 'rainbow' },
});

// --- projector calibration, driven from here --------------------------------
// The overlay's hotkeys only work at the PC. These controls send the same
// nudges over the socket so you can calibrate standing at the table, watching
// the projection rather than the keyboard.
let corner = 0;

function setCorner(c) {
  corner = c;
  [...el('corner-pick').children].forEach((b) =>
    b.setAttribute('aria-pressed', String(Number(b.dataset.c) === c)));
}

el('corner-pick').onclick = (e) => {
  const b = e.target.closest('button');
  if (b) setCorner(Number(b.dataset.c));
};

el('dpad').onclick = (e) => {
  const b = e.target.closest('button');
  if (!b || !b.dataset.dx) return;
  const step = el('big-step').checked ? 10 : 1;
  send({ type: 'projector_nudge', corner,
         dx: Number(b.dataset.dx) * step, dy: Number(b.dataset.dy) * step });
};

el('calib-reset').onclick = () => send({ type: 'projector_nudge', reset: true });
el('calib-done').onclick = () => {
  send({ type: 'calibrate', on: false });
  el('tabs').querySelector('[data-tab="game"]').click();
};

// --- camera calibration ---------------------------------------------------
// Four clicks on a still from the camera. The corners are sent back as
// fractions of the picture, so it does not matter how the browser scaled it.
const CORNERS = ['top-left', 'top-right', 'bottom-right', 'bottom-left'];
let camPoints = [];
let camSize = null;

async function api(path, body) {
  const res = await fetch(path, body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body) }
    : undefined);
  return res.json();
}

async function refreshCamera() {
  const box = el('cam-status');
  box.className = 'cam-status';
  box.textContent = 'checking…';
  let st;
  try { st = await api('/api/camera/status'); }
  catch (e) { box.className = 'cam-status bad'; box.textContent = String(e); return; }

  const lines = [];
  if (st.open) {
    // An open camera beats the probe: the probe only lists devices it can
    // find by scanning, and the one in use may not be one of them.
    box.className = 'cam-status ready';
    lines.push(`Connected: ${st.spec}`);
  } else if (!st.opencv) {
    box.className = 'cam-status bad';
    lines.push(st.hint || 'OpenCV is not installed.');
  } else if (!st.cameras.length) {
    box.className = 'cam-status bad';
    lines.push(st.hint || 'No camera detected.');
  } else {
    box.className = 'cam-status ready';
    lines.push('Found: ' + st.cameras.map((c) => c.label).join(', '));
  }
  if (st.calibrated) {
    lines.push(`Calibrated, ${st.error_mm} mm average error ` +
               `(under 5 mm is good, over 15 mm needs redoing).`);
  } else {
    lines.push('Not calibrated yet.');
  }
  box.textContent = lines.join('  ');
  el('cam-snap').disabled = !st.open;
}

el('cam-connect').onclick = async () => {
  el('cam-status').textContent = 'connecting…';
  const r = await api('/api/camera/open', { spec: 'auto' });
  if (!r.ok) {
    el('cam-status').className = 'cam-status bad';
    el('cam-status').textContent = r.error || 'could not open the camera';
    return;
  }
  await refreshCamera();
  el('cam-snap').disabled = false;
  el('cam-snap').click();
};

el('cam-snap').onclick = async () => {
  el('cam-prompt').textContent = 'taking a picture…';
  el('cam-shot').hidden = false;
  const r = await api('/api/camera/snapshot');
  if (!r.ok) {
    el('cam-prompt').textContent = r.error || 'no picture';
    return;
  }
  camSize = [r.width, r.height];
  const img = el('cam-img');
  img.onload = () => { sizeCamOverlay(); drawCamPoints(); };
  img.src = r.image;
  camPoints = [];
  updateCamPrompt();
};

function sizeCamOverlay() {
  const img = el('cam-img');
  const c = el('cam-overlay');
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  c.width = Math.round(img.clientWidth * dpr);
  c.height = Math.round(img.clientHeight * dpr);
  c.getContext('2d').setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', () => { if (camSize) { sizeCamOverlay(); drawCamPoints(); } });

function updateCamPrompt() {
  el('cam-prompt').textContent = camPoints.length < 4
    ? `Tap the ${CORNERS[camPoints.length]} corner of the cushion ` +
      `(where the cloth meets the rail)`
    : 'Four corners set — save the calibration';
  el('cam-undo').disabled = !camPoints.length;
  el('cam-save').disabled = camPoints.length !== 4;
}

el('cam-overlay').onpointerdown = (e) => {
  if (camPoints.length >= 4) return;
  const r = e.currentTarget.getBoundingClientRect();
  camPoints.push([(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]);
  drawCamPoints();
  updateCamPrompt();
};

el('cam-undo').onclick = () => { camPoints.pop(); drawCamPoints(); updateCamPrompt(); };

function drawCamPoints() {
  const c = el('cam-overlay');
  const ctx = c.getContext('2d');
  const w = el('cam-img').clientWidth, h = el('cam-img').clientHeight;
  ctx.clearRect(0, 0, w, h);
  const pts = camPoints.map(([x, y]) => [x * w, y * h]);
  if (pts.length > 1) {
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    if (pts.length === 4) ctx.closePath();
    ctx.strokeStyle = '#27A37C';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
  pts.forEach(([x, y], i) => {
    ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.fillStyle = '#27A37C'; ctx.fill();
    ctx.fillStyle = '#04120D';
    ctx.font = 'bold 11px system-ui';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(String(i + 1), x, y);
  });
}

el('cam-save').onclick = async () => {
  // Fractions -> real pixels, using the picture's own size.
  const points = camPoints.map(([x, y]) => [x * camSize[0], y * camSize[1]]);
  const r = await api('/api/camera/calibrate', { points });
  const box = el('cam-status');
  if (!r.ok) {
    box.className = 'cam-status bad';
    box.textContent = r.error || 'could not save';
    return;
  }
  box.className = 'cam-status ' + (r.quality === 'poor' ? 'bad' : 'ready');
  box.textContent = `Saved. Average error ${r.error_mm} mm (${r.quality}).` +
    (r.quality === 'poor' ? ' Re-do it: click exactly where the cloth meets the rail.' : '');
};

// --- go -------------------------------------------------------------------
mini = new MiniTable(el('mini'));
renderFeed();
renderRoster();
connect();
