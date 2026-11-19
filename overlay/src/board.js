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
// Which games have artwork on disk. Asked for once, so the picker can skip
// building an <img> for a file that is not there — the games list itself
// arrives over the socket and has no business knowing about the web root.
let gameArt = [];
fetch('/api/games')
  .then((r) => r.json())
  .then((d) => { gameArt = d.art || []; if (games.length) renderGames(); })
  .catch(() => {});
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
      if (msg.projector !== undefined) hasProjector = msg.projector;
      if (msg.live !== undefined) el('sim-badge').hidden = msg.live;
      if (msg.ball_set) applyBallSet(msg.ball_set);
      renderGames();
      break;
    case 'table':
      if (msg.ball_set) applyBallSet(msg.ball_set);
      if (msg.projector !== undefined) hasProjector = msg.projector;
      if (msg.live !== undefined) el('sim-badge').hidden = msg.live;
      mini.setTable(msg.table);
      break;
    case 'state':      mini.setBalls(msg.state.balls || []); break;
    case 'scoreboard': board = msg.scoreboard; render(); break;
    case 'effects':    applyGuides(msg); break;
    case 'shot':       break;      // the feed comes from history, below
    case 'history':    setFeed(msg.history || []); break;
    case 'error':      showAlert(msg.error); break;
    case 'undo_result':
      if (!msg.ok) showAlert(msg.error || 'nothing to undo');
      break;
    default: break;
  }
}

// Mirror the projector's persistent guides onto the table view. Without a
// projector this is the only place the nominated pocket or the live zones
// appear, so Pocket Roulette and Hotspots remain playable — you glance at
// the tablet instead of at the cloth.
let guides = { zones: [], pockets: [], marked: [], aim: null };

function applyGuides(msg) {
  if (msg.clear === 'all' || msg.clear === 'guide') {
    guides = { zones: [], pockets: [], marked: [], aim: null };
  }
  for (const e of msg.effects || []) {
    const a = e.args || {};
    if (e.name === 'zones') guides.zones = a.zones || [];
    else if (e.name === 'target_zone' && a.zone) guides.zones = [a.zone];
    else if (e.name === 'pocket_glow' && a.persist && a.pocket) {
      guides.pockets = [{ pocket: a.pocket, color: a.color }];
    } else if (e.name === 'highlight_balls') guides.marked = a.balls || [];
    else if (e.name === 'aim_line' || e.name === 'aim_assist') {
      guides.aim = { cue: a.cue, target: a.target, pocket: a.pocket };
    }
  }
  mini.setGuides(guides);
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
let hasProjector = true;

function applyBallSet(bs) {
  ballSetInfo = bs;
  setBallSet(bs);
  mini.draw();
  renderFeed();          // player names come from the scoreboard
}

function renderGames() {
  // Two places show the same picker — the splash and the setup tab — and
  // they have to agree, so they are built from the same list rather than
  // kept in step by hand.
  for (const id of ['games', 'splash-games']) renderGamesInto(id);
  const hint = el('roster-hint');
  if (hint) hint.dataset.set = ballSetInfo.title || '';
  const playable = games.filter((g) => g.supported !== false);
  if (playable.length && !playable.some((g) => g.name === picked)) {
    pick(playable[0].name, false);
  }
}

function renderGamesInto(containerId) {
  const wrap = el(containerId);
  if (!wrap) return;
  // On the splash a card IS the start button — tapping a game begins it,
  // which is the whole point of a front door. In the setup tab the same
  // card only selects, because there you are still picking players and
  // options before you commit.
  const startsOnTap = containerId === 'splash-games';
  wrap.textContent = '';
  for (const g of games) {
    const b = document.createElement('button');
    b.className = 'game-card';
    b.type = 'button';
    // The accent colour and the artwork are both keyed off this, so a game
    // added later picks up a sensible look without touching the CSS.
    b.dataset.game = g.name;
    b.disabled = g.supported === false;
    b.setAttribute('aria-pressed', String(picked === g.name));

    const art = document.createElement('span');
    art.className = 'art';
    // Artwork is optional on purpose. A game with none gets the accent glow
    // drawn in CSS, which is sharp at any size — so the picker never has a
    // hole in it while the art is still being made. The server says which
    // files exist rather than letting the browser find out by 404.
    const hasArt = gameArt.includes(g.name);
    if (hasArt) {
      const img = new Image();
      img.alt = '';
      img.loading = 'lazy';
      img.onload = () => art.classList.add('has-art');
      img.src = `img/games/${g.name}.webp`;
      art.appendChild(img);
    }

    const title = document.createElement('b');
    title.textContent = g.title;

    // The artwork carries its own title and description, and a title never
    // changes — "8-Ball" is always "8-Ball". What does change is everything
    // underneath: a game goes unplayable when the table is set to reds and
    // yellows, and a projector-only game has to say where its guides went.
    // So where there is artwork the card shuts up and lets it speak, and the
    // strip comes back only when it has something the picture cannot say.
    const live = [];
    if (g.supported === false) live.push('needs numbered balls');
    if (g.needs_projector && !hasProjector) live.push('guides shown here');

    const note = document.createElement('i');
    note.textContent = hasArt && live.length ? live.join(' — ')
      : hasArt ? ''
      : g.description + (live.length ? ' — ' + live.join(' — ') : '');
    note.hidden = hasArt && !live.length;
    if (hasArt) b.classList.add('arted');

    b.append(art, title, note);
    if (!b.disabled) {
      b.onclick = () => {
        pick(g.name);              // also fits the roster to this game
        if (startsOnTap) askWho();
      };
    }
    wrap.appendChild(b);
  }
}

// One field per player, rather than a comma-separated string nobody can see
// the shape of. The list resizes itself to whatever the chosen game accepts.
let roster = ['Player 1', 'Player 2'];

function renderRoster() {
  for (const id of ['name-list', 'who-names']) renderRosterInto(id);
  const g = games.find((x) => x.name === picked);
  if (g) {
    const span = g.min_players === g.max_players
      ? `${g.min_players} players` : `${g.min_players}-${g.max_players} players`;
    for (const [hintId, addId, remId] of [['roster-hint', 'add-player', 'remove-player'],
                                          ['who-hint', 'who-add', 'who-remove']]) {
      const hint = el(hintId);
      if (hint) hint.textContent = `${g.title}: ${span}`;
      if (el(addId)) el(addId).disabled = roster.length >= g.max_players;
      if (el(remId)) el(remId).disabled = roster.length <= g.min_players;
    }
    const wg = el('who-game');
    if (wg) wg.textContent = g.title;
  }
}

function renderRosterInto(listId) {
  const list = el(listId);
  if (!list) return;
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
  for (const id of ['games', 'splash-games']) {
    const wrap = el(id);
    if (!wrap) continue;
    [...wrap.children].forEach((c, i) =>
      c.setAttribute('aria-pressed', String(games[i] && games[i].name === name)));
  }
  if (fixRoster) fitRoster(); else renderRoster();
}

const rosterNames = () =>
  roster.map((s) => s.trim()).filter(Boolean);

// --- scoreboard -----------------------------------------------------------
// --- the game clock -------------------------------------------------------
// The scoreboard counts down on its own between updates, for the same reason
// the projector does: the number is arithmetic, and putting it on the wire
// thirty times a second to say what the client could work out itself would be
// the busiest message in the system by far. Each scoreboard push re-syncs it.
let clockState = null;
let clockSeen = 0;

function setClock(c) {
  clockState = c || null;
  clockSeen = performance.now();
  drawClock();
}

function clockLeft() {
  if (!clockState) return 0;
  if (!clockState.running) return clockState.remaining;
  return Math.max(0, clockState.remaining - (performance.now() - clockSeen) / 1000);
}

function drawClock() {
  const box = el('game-clock');
  if (!box) return;
  if (!clockState) { box.hidden = true; return; }
  box.hidden = false;
  const left = clockLeft();
  el('clock-left').textContent = left >= 10 ? left.toFixed(0) : left.toFixed(1);
  el('clock-note').textContent = clockState.running ? 'left'
    : left <= 0 ? 'boom' : 'held';
  box.classList.toggle('held', !clockState.running && left > 0);
  box.classList.toggle('warn', left <= 10 && left > 5);
  box.classList.toggle('critical', left <= 5);
}

setInterval(drawClock, 100);

function render() {
  showSplash(!board);
  if (!board) return;
  el('game-title').textContent = board.title;
  el('shot-no').textContent = board.shot_number + 1;
  setClock(board.clock);

  if (board.over) {
    const w = board.winner !== null && board.players[board.winner];
    setState(w ? `${w.name} wins` : 'game over', false);
  } else {
    setState(`${board.players[board.turn].name} to play`, true);
  }

  el('undo').disabled = !board.can_undo;
  el('redo').disabled = !board.can_redo;
  el('redo').hidden = !board.can_redo;

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

    const adjust = document.createElement('div');
    adjust.className = 'adjust';
    for (const [label, delta, title] of [['\u2212', -1, 'one less'],
                                         ['+', 1, 'one more']]) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = label;
      btn.title = `${p.name}: ${title}`;
      btn.onclick = () => send({ type: 'adjust_score', player: i, delta });
      adjust.appendChild(btn);
    }

    card.append(name, meta, score, adjust);
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
// be classified and coloured instead of being one more grey line. The whole
// list is replaced from the engine's history on every change, which means a
// page opened mid-frame is populated and undo needs no client-side special
// case — the list simply comes back shorter.
let feed = [];

function setFeed(history) {
  // Keep the raw records and resolve player names at render time: history can
  // arrive before the scoreboard does, and a row that says "P1" because of
  // one frame's ordering would never correct itself.
  feed = history.slice().reverse();
  renderFeed();
}

function feedRow(shot) {
  const r = shot.result || {};
  const ev = shot.events || {};
  const who = (board && board.players[shot.shooter]
               && board.players[shot.shooter].name) || `P${(shot.shooter ?? 0) + 1}`;
  let kind = 'safe';
  let text = r.message || 'safe';
  if (r.winner !== null && r.winner !== undefined) kind = 'win';
  else if (r.foul) { kind = 'foul'; text = r.foul; }
  else if ((ev.pocketed || []).length) kind = 'pot';
  return { who, text, kind, balls: ev.pocketed || [] };
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
  for (const shot of feed) {
    const f = feedRow(shot);
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
  if (want === 'detector') refreshDetector();
};
el('pass').onclick = () => send({ type: 'next_turn' });
el('undo').onclick = () => send({ type: 'undo' });
// Any other command wakes the table, so this is a toggle the engine tracks
// rather than one the page has to remember.
let attracting = false;
el('attract').onclick = () => {
  attracting = !attracting;
  el('attract').textContent = attracting ? 'Stop attract' : 'Attract mode';
  send({ type: 'attract', on: attracting });
};
el('redo').onclick = () => send({ type: 'redo' });
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

// --- detector -------------------------------------------------------------
// Everything here is explicit on purpose. Installing a model means fetching
// somebody else's code and running it, so nothing is downloaded, selected or
// enabled without a press, and the page says what it is about to do.
let detector = { detector: 'color', weights: '', installed: [], runtime: {} };

async function refreshDetector() {
  try { detector = await api('/api/detector'); }
  catch (e) { el('det-status').textContent = String(e); return; }

  const rt = detector.runtime || {};
  const box = el('det-status');
  const bits = [`Using the ${detector.detector === 'yolo' ? 'YOLO' : 'colour'} detector.`];
  if (detector.detector === 'yolo' && detector.weights) {
    bits.push(`Model: ${detector.weights.split(/[\\/]/).pop()}.`);
  }
  bits.push(rt.ready
    ? `YOLO support installed (torch ${rt.torch_version || '?'}, running on ${rt.device}${rt.cuda ? '' : ' — no GPU found'}).`
    : 'YOLO support is not installed.');
  box.textContent = bits.join(' ');
  box.className = 'cam-status ' + (detector.detector === 'yolo' && !rt.ready ? 'bad' : 'ready');

  el('use-color').setAttribute('aria-pressed', String(detector.detector !== 'yolo'));
  el('use-yolo').setAttribute('aria-pressed', String(detector.detector === 'yolo'));
  el('yolo-panel').hidden = detector.detector !== 'yolo';
  el('runtime-hint').textContent = rt.ready
    ? 'already installed' : 'about 2-3 GB, mostly PyTorch';
  el('install-runtime').disabled = !!rt.ready;
  renderModels();
}

function renderModels() {
  const list = el('model-list');
  list.textContent = '';
  if (!detector.installed.length) {
    const p = document.createElement('p');
    p.className = 'note';
    p.textContent = 'No models yet. Add one above, or drop a .pt file into '
      + detector.weights_dir + ' and reopen this tab.';
    list.appendChild(p);
    return;
  }
  for (const m of detector.installed) {
    const row = document.createElement('div');
    row.className = 'model-row' + (m.path === detector.weights ? ' active' : '');
    const name = document.createElement('span');
    name.className = 'mname';
    name.textContent = m.name;
    const size = document.createElement('span');
    size.className = 'msize';
    size.textContent = m.size_mb + ' MB';
    const use = document.createElement('button');
    use.textContent = m.path === detector.weights ? 'In use' : 'Use this';
    use.disabled = m.path === detector.weights;
    use.onclick = async () => {
      await api('/api/detector/select', { detector: 'yolo', weights: m.path });
      await refreshDetector();
      el('test-model').disabled = false;
    };
    row.append(name, size, use);
    list.appendChild(row);
  }
  el('test-model').disabled = !detector.weights;
}

el('use-color').onclick = async () => {
  await api('/api/detector/select', { detector: 'color' });
  await refreshDetector();
};
el('use-yolo').onclick = () => {
  el('yolo-panel').hidden = false;
  el('use-yolo').setAttribute('aria-pressed', 'true');
  el('use-color').setAttribute('aria-pressed', 'false');
};

el('install-runtime').onclick = async () => {
  const btn = el('install-runtime');
  btn.disabled = true;
  el('det-status').className = 'cam-status';
  el('det-status').textContent = 'Installing ultralytics and PyTorch. This is a '
    + 'few gigabytes and can take several minutes — leave this page open.';
  const r = await api('/api/detector/install_runtime', {});
  if (!r.ok) {
    el('det-status').className = 'cam-status bad';
    el('det-status').textContent = 'Install failed. Run this in a terminal: '
      + (r.command || 'pip install ultralytics') + (r.log ? '  —  ' + r.log : '');
    btn.disabled = false;
    return;
  }
  await refreshDetector();
};

el('install-model').onclick = async () => {
  const src = el('model-src').value.trim();
  if (!src) return;
  el('det-status').className = 'cam-status';
  el('det-status').textContent = 'Fetching ' + src + ' …';
  const r = await api('/api/detector/install_model', { source: src });
  if (!r.ok) {
    el('det-status').className = 'cam-status bad';
    el('det-status').textContent = r.error;
    return;
  }
  el('model-src').value = '';
  await api('/api/detector/select', { detector: 'yolo', weights: r.path });
  await refreshDetector();
  el('det-status').textContent = `Added ${r.name} (${r.size_mb} MB) and selected it. `
    + 'Test it on the camera before a match.';
};

el('test-model').onclick = async () => {
  el('det-status').className = 'cam-status';
  el('det-status').textContent = 'Loading the model and running one frame…';
  const r = await api('/api/detector/test', { weights: detector.weights });
  if (!r.ok) {
    el('det-status').className = 'cam-status bad';
    el('det-status').textContent = r.error
      + (r.install_command ? '  —  ' + r.install_command : '');
    return;
  }
  el('det-status').className = 'cam-status ready';
  el('det-status').textContent = r.found === undefined
    ? `Model loads on ${r.device}. Connect a camera to try it on a real frame.`
    : `Found ${r.found} balls in ${r.ms} ms on ${r.device}`
      + (r.numbers && r.numbers.length ? ` (numbers: ${r.numbers.join(', ')})` : '');
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

el('cam-markers').onclick = async () => {
  el('cam-status').className = 'cam-status';
  el('cam-status').textContent = 'Looking for the four markers…';
  const r = await api('/api/camera/markers', {});
  if (!r.ok) {
    el('cam-status').className = 'cam-status bad';
    el('cam-status').textContent = r.error || 'no markers found';
    return;
  }
  el('cam-status').className = 'cam-status ready';
  el('cam-status').textContent =
    `Calibrated from four markers, ${r.error_mm} mm average error. ${r.note}`;
};

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

// Which sensor the four corners being clicked belong to. The colour camera
// and the depth sensor see the table differently enough that one homography
// cannot serve both, so the same clicking flow is pointed at either.
let camSensor = 'colour';

el('cam-snap').onclick = async () => {
  camSensor = 'colour';
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
    ? `Tap the ${CORNERS[camPoints.length]} corner of the cushion `
      + `(where the cloth meets the rail) — arrow keys nudge the last one, `
      + `and a pixel here is worth a millimetre on the table`
    : 'Four corners set — save the calibration';
  el('cam-undo').disabled = !camPoints.length;
  el('cam-save').disabled = camPoints.length !== 4;
}

// A loupe. Measured on this project's own geometry, click precision is the
// single biggest source of position error: clicking the cushion corners to
// within a pixel puts balls within ~1.6 mm, being 5 px out costs ~7 mm, and
// 8 px out costs ~11 mm with outliers past 40 mm — worse than parallax and
// worse than anything the detector does. The picture is displayed far
// smaller than the camera's real resolution, so a pixel on screen can be
// three in the frame. Hence: magnify while placing, and allow a nudge after.
let camHover = null;

function drawLoupe(ctx, w, h) {
  if (!camHover || camPoints.length >= 4) return;
  const img = el('cam-img');
  const R = 74, Z = 5;
  // Keep the loupe away from the cursor's own quadrant so it never covers
  // the corner being placed.
  const lx = camHover[0] * w < w / 2 ? w - R - 14 : R + 14;
  const ly = camHover[1] * h < h / 2 ? h - R - 14 : R + 14;
  ctx.save();
  ctx.beginPath(); ctx.arc(lx, ly, R, 0, Math.PI * 2);
  ctx.closePath(); ctx.clip();
  ctx.fillStyle = '#000';
  ctx.fillRect(lx - R, ly - R, R * 2, R * 2);
  ctx.drawImage(img,
    camHover[0] * img.naturalWidth - R / Z, camHover[1] * img.naturalHeight - R / Z,
    (R * 2) / Z, (R * 2) / Z,
    lx - R, ly - R, R * 2, R * 2);
  ctx.strokeStyle = '#27A37C';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(lx - R, ly); ctx.lineTo(lx + R, ly);
  ctx.moveTo(lx, ly - R); ctx.lineTo(lx, ly + R);
  ctx.stroke();
  ctx.restore();
  ctx.beginPath(); ctx.arc(lx, ly, R, 0, Math.PI * 2);
  ctx.strokeStyle = '#27A37C'; ctx.lineWidth = 2; ctx.stroke();
}

el('cam-overlay').onpointermove = (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  camHover = [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  drawCamPoints();
};
el('cam-overlay').onpointerleave = () => { camHover = null; drawCamPoints(); };

el('cam-overlay').onpointerdown = (e) => {
  if (camPoints.length >= 4) return;
  const r = e.currentTarget.getBoundingClientRect();
  camPoints.push([(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]);
  camHover = null;
  drawCamPoints();
  updateCamPrompt();
};

// Nudge the corner just placed, a single camera pixel at a time.
window.addEventListener('keydown', (e) => {
  if (!e.key.startsWith('Arrow') || !camPoints.length) return;
  if (el('setup').hidden) return;
  const panel = document.querySelector('.tab[data-panel="camera"]');
  if (!panel || panel.hidden || !camSize) return;
  const step = (e.shiftKey ? 5 : 1);
  const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0],
              ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
  if (!d) return;
  const i = camPoints.length - 1;
  camPoints[i] = [camPoints[i][0] + d[0] / camSize[0],
                  camPoints[i][1] + d[1] / camSize[1]];
  drawCamPoints();
  e.preventDefault();
});

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
    // A ring rather than a filled blob: you need to see the corner you are
    // placing it on, and the last one placed is the one the arrows move.
    const last = i === pts.length - 1 && camPoints.length < 4;
    ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2);
    ctx.strokeStyle = last ? '#FFD24A' : '#27A37C';
    ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath(); ctx.arc(x, y, 1.5, 0, Math.PI * 2);
    ctx.fillStyle = last ? '#FFD24A' : '#27A37C'; ctx.fill();
    ctx.font = 'bold 11px system-ui';
    ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    ctx.fillText(String(i + 1), x + 12, y - 10);
  });
  drawLoupe(ctx, w, h);
}

el('cam-save').onclick = async () => {
  // Fractions -> real pixels, using the picture's own size.
  const points = camPoints.map(([x, y]) => [x * camSize[0], y * camSize[1]]);
  const r = await api(camSensor === 'depth'
    ? '/api/camera/calibrate_depth' : '/api/camera/calibrate', { points });
  const box = el('cam-status');
  if (!r.ok) {
    box.className = 'cam-status bad';
    box.textContent = r.error || 'could not save';
    return;
  }
  box.className = 'cam-status ' + (r.quality === 'poor' ? 'bad' : 'ready');
  box.textContent = `Saved. Average error ${r.error_mm} mm (${r.quality}).` +
    (r.quality === 'poor' ? ' Re-do it: click exactly where the cloth meets the rail.' : '');
  // Calibrating depth is what unlocks the depth toggle, so ask again rather
  // than leaving it greyed out until somebody thinks to reload the page.
  if (camSensor === 'depth' && r.ok) refreshDepth();
};

// --- go -------------------------------------------------------------------
mini = new MiniTable(el('mini'));
renderFeed();
renderRoster();
connect();

// --- the pre-flight check -------------------------------------------------
// The same checks as `python -m poolarena doctor`, run from the tablet. The
// person setting up a table has the tablet in their hands and the question
// "is this going to work?" in their head; making them find a terminal to
// answer it is the wrong way round.
const CHECK_MARK = { ok: '✓', warn: '!', fail: '✕', skip: '–' };

function renderChecks(checks) {
  const list = el('check-list');
  list.textContent = '';
  for (const c of checks) {
    const row = document.createElement('div');
    row.className = `check ${c.status}`;

    // Not 'mark': the header's brand logo already owns that class, and a
    // glyph styled as a pool ball is not a tick.
    const mark = document.createElement('span');
    mark.className = 'verdict';
    mark.textContent = CHECK_MARK[c.status] || '?';

    const body = document.createElement('div');
    const name = document.createElement('b');
    name.textContent = c.name;
    const detail = document.createElement('span');
    detail.className = 'detail';
    detail.textContent = c.detail;
    body.append(name, detail);

    // The remedy only when there is something to do about it; on a passing
    // check it is noise, and a wall of advice is how a report stops being read.
    if (c.remedy && (c.status === 'fail' || c.status === 'warn')) {
      const fix = document.createElement('p');
      fix.className = 'remedy';
      fix.textContent = c.remedy;
      body.appendChild(fix);
    }
    row.append(mark, body);
    list.appendChild(row);
  }
}

el('check-run').onclick = async () => {
  const btn = el('check-run');
  const status = el('check-status');
  btn.disabled = true;
  status.className = 'cam-status';
  status.textContent = 'Reading the table — leave it alone…';
  el('check-list').textContent = '';
  try {
    const r = await api('/api/camera/check', {
      frames: 40,
      expect: Number(el('check-expect').value) || 16,
    });
    if (!r.ok) {
      status.className = 'cam-status bad';
      status.textContent = [r.error, r.hint].filter(Boolean).join(' — ');
      return;
    }
    renderChecks(r.checks);
    // Prefill with what it just measured, so acting on the finding is one
    // click rather than a trip to a text editor.
    const size = (r.checks || []).find((c) => c.name === 'ball size');
    const seen = size && size.numbers && size.numbers.measured_radius_mm;
    if (seen) el('ball-radius').value = seen;
    status.className = `cam-status ${r.ready ? 'ready' : 'bad'}`;
    status.textContent = r.ready
      ? 'Ready — nothing here stops a game.'
      : 'Not ready. Fix the ✕ lines; the rest cannot be trusted until they pass.';
  } catch (err) {
    status.className = 'cam-status bad';
    status.textContent = String(err);
  } finally {
    btn.disabled = false;
  }
};

// --- ball size ------------------------------------------------------------
// Closes the loop on the check above: it measures the balls, this applies the
// number. Without it the only way to act on "these are English balls" is to
// edit a JSON file, which is a poor thing to discover at nine o'clock with a
// table racked.
async function saveBallRadius(mm) {
  const status = el('ball-radius-status');
  status.hidden = false;
  status.className = 'cam-status';
  status.textContent = 'Saving…';
  const r = await api('/api/table/ball_radius', { radius_mm: mm });
  if (!r.ok) {
    status.className = 'cam-status bad';
    status.textContent = r.error || 'could not save';
    return;
  }
  el('ball-radius').value = r.now;
  status.className = 'cam-status ready';
  status.textContent = r.restart_needed
    ? `Saved: ${r.now} mm. Restart to use it — the detector is sized when it starts.`
    : `Saved: ${r.now} mm.`;
}

el('ball-radius-save').onclick = () =>
  saveBallRadius(Number(el('ball-radius').value));
el('ball-radius-english').onclick = () => saveBallRadius(25.4);
el('ball-radius-american').onclick = () => saveBallRadius(28.6);

// --- which balls ----------------------------------------------------------
async function saveBallSet(name) {
  const status = el('ball-set-status');
  status.hidden = false;
  status.className = 'cam-status';
  status.textContent = 'Saving…';
  const r = await api('/api/table/ball_set', { name });
  if (!r.ok) {
    status.className = 'cam-status bad';
    status.textContent = r.error || 'could not save';
    return;
  }
  el('set-english').setAttribute('aria-pressed', String(name === 'english'));
  el('set-american').setAttribute('aria-pressed', String(name === 'american'));
  status.className = 'cam-status ready';
  status.textContent = `Saved. Restart to use it — the rules and the colour `
    + `model are both chosen when it starts.`;
}
el('set-english').onclick = () => saveBallSet('english');
el('set-american').onclick = () => saveBallSet('american');

// --- where the camera is --------------------------------------------------
// Asked as a place and a distance, not as coordinates: nobody up a ladder
// wants to work out that the point under the lens is x=1117, y=-1000.
let camWhere = 'overhead';

function pickCamWhere(where) {
  camWhere = where;
  for (const [id, w] of [['cam-overhead', 'overhead'], ['cam-side', 'long-side'],
                         ['cam-end', 'end']]) {
    el(id).setAttribute('aria-pressed', String(w === where));
  }
  el('cam-out-wrap').hidden = where === 'overhead';
}
el('cam-overhead').onclick = () => pickCamWhere('overhead');
el('cam-side').onclick = () => pickCamWhere('long-side');
el('cam-end').onclick = () => pickCamWhere('end');

el('cam-pos-save').onclick = async () => {
  const status = el('cam-pos-status');
  status.hidden = false;
  status.className = 'cam-status';
  status.textContent = 'Saving…';
  const r = await api('/api/camera/position', {
    height_mm: Number(el('cam-height').value) || 0,
    where: camWhere,
    out_mm: Number(el('cam-out').value) || 0,
  });
  if (!r.ok) {
    status.className = 'cam-status bad';
    status.textContent = r.error || 'could not save';
    return;
  }
  status.className = 'cam-status ready';
  status.textContent = r.enabled
    ? `Saved. Takes out up to ${r.corrects_up_to_mm} mm of parallax at the `
      + `far corner. Restart to use it.`
    : 'Parallax correction turned off. Restart to use it.';
};

// Show what is already set, rather than a page of blank boxes: an empty
// field cannot tell you whether a thing is off or merely unshown, and "is
// parallax correction on?" is the question these boxes exist to answer.
fetch('/api/settings')
  .then((r) => r.json())
  .then((s) => {
    if (s.ball_radius) el('ball-radius').value = s.ball_radius;
    if (s.ball_set) {
      el('set-english').setAttribute('aria-pressed', String(s.ball_set === 'english'));
      el('set-american').setAttribute('aria-pressed', String(s.ball_set === 'american'));
    }
    const c = s.camera;
    if (c && c.height_mm) {
      el('cam-height').value = c.height_mm;
      if (c.out_mm) el('cam-out').value = c.out_mm;
      pickCamWhere(c.where || 'overhead');
      const st = el('cam-pos-status');
      st.hidden = false;
      st.className = 'cam-status ready';
      st.textContent = `Parallax correction is on: ${c.height_mm} mm up, `
        + `${(c.where || 'overhead').replace('-', ' ')}.`;
    }
  })
  .catch(() => {});

// --- depth ----------------------------------------------------------------
// Ball-finding in depth was written and tested and then could not be turned
// on, because it needs its own calibration and nothing could make one. This
// is the missing half: the same four corners, clicked on the depth picture.
async function refreshDepth() {
  const s = await fetch('/api/settings').then((r) => r.json()).catch(() => ({}));
  const state = el('depth-state');
  if (!state) return;
  state.textContent = s.depth_calibrated
    ? ' It is calibrated.'
    : ' It is not calibrated yet.';
  el('depth-on').disabled = !s.depth_calibrated;
  el('depth-hint').textContent = s.depth_calibrated
    ? '' : 'Calibrate depth first.';
}
refreshDepth();

el('depth-snap').onclick = async () => {
  camSensor = 'depth';
  el('cam-prompt').textContent = 'reading the depth sensor…';
  el('cam-shot').hidden = false;
  const r = await api('/api/camera/depth_snapshot', {});
  if (!r.ok) {
    el('cam-prompt').textContent = [r.error, r.hint].filter(Boolean).join(' — ');
    return;
  }
  camSize = [r.width, r.height];
  const img = el('cam-img');
  img.onload = () => { sizeCamOverlay(); drawCamPoints(); };
  img.src = r.image;
  camPoints = [];
  updateCamPrompt();
  // The picture is near-bright: the cushions are the bright rectangle, the
  // cloth is dark inside it, and black is where the sensor read nothing.
  el('cam-prompt').textContent =
    `Depth, ${r.near_mm}–${r.far_mm} mm. Tap the four inside corners of the `
    + `bright rail.`;
};

el('depth-on').onclick = async () => {
  const on = el('depth-on').getAttribute('aria-pressed') !== 'true';
  const r = await api('/api/camera/depth_balls', { on });
  const box = el('cam-status');
  if (!r.ok) {
    box.className = 'cam-status bad';
    box.textContent = r.error || 'could not save';
    return;
  }
  el('depth-on').setAttribute('aria-pressed', String(r.depth_balls));
  box.className = 'cam-status ' + (r.note ? 'bad' : 'ready');
  box.textContent = r.note || (r.depth_balls
    ? 'Depth will find the balls from the next restart. Colour still names them.'
    : 'Back to colour only, from the next restart.');
};

// --- the splash -----------------------------------------------------------
// With no game on, a table view has nothing to show and a scoreboard of
// zeroes reads as a fault rather than as a beginning. So the page is a
// picker and nothing else until somebody chooses.
function showSplash(on) {
  const splash = el('splash');
  if (!splash) return;
  splash.hidden = !on;
  if (on) el('who').hidden = true;      // a new splash starts at step one
  if (el('quit')) el('quit').hidden = !!on;
  document.body.classList.toggle('no-game', !!on);
  el('game-title').textContent = on ? 'Pool Arena' : el('game-title').textContent;
  if (on) {
    setState('no game yet', false);
    const who = el('splash-players');
    if (who) {
      who.textContent = roster.length
        ? `Tap a game to start — ${roster.join(' v ')}`
        : 'Tap a game to start';
    }
  }
}

el('splash-options').onclick = () => {
  el('toggle-setup').click();
  const panel = el('setup');
  if (panel && !panel.hidden) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
};


// --- who is playing -------------------------------------------------------
// Tapping a game asks who, then starts. Names matter more often than they
// do not, and typing them after the break means racking up again.
function askWho() {
  renderRoster();
  el('who').hidden = false;
  const first = el('who-names').querySelector('input');
  if (first) { first.focus(); first.select(); }
}

el('who-back').onclick = () => { el('who').hidden = true; };
el('who-start').onclick = () => { el('who').hidden = true; startGame(); };
el('who-add').onclick = () => {
  roster.push(`Player ${roster.length + 1}`);
  renderRoster();
};
el('who-remove').onclick = () => { roster.pop(); renderRoster(); };

// Escape backs out, which is what everybody tries first.
el('who').addEventListener('keydown', (e) => {
  if (e.key === 'Escape') el('who').hidden = true;
});
el('who').addEventListener('pointerdown', (e) => {
  if (e.target === el('who')) el('who').hidden = true;   // tap the dimmed area
});

// --- quitting -------------------------------------------------------------
// A game that cannot be left is a game you have to restart the program to
// get out of. Confirmed, because it throws away the frame in progress.
el('quit').onclick = () => {
  const n = board && board.shot_number ? board.shot_number : 0;
  const mid = n > 0 && !(board && board.over);
  if (mid && !confirm(`End this game? ${n} shot${n === 1 ? '' : 's'} played.`)) return;
  send({ type: 'end_game' });
};
