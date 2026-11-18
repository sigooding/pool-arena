// The tablet: whose turn it is, what the table looks like, what just happened.
//
// It subscribes to the same stream as the projector, so it needs no polling and
// no state of its own beyond what the engine last said.

import { ballRow } from './balls.js';
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
    case 'games':      games = msg.games; renderGames(); break;
    case 'table':      mini.setTable(msg.table); break;
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
function renderGames() {
  const wrap = el('games');
  wrap.textContent = '';
  for (const g of games) {
    const b = document.createElement('button');
    b.className = 'chip';
    b.type = 'button';
    b.setAttribute('aria-pressed', String(picked === g.name));
    b.innerHTML = `<b></b><i></i>`;
    b.querySelector('b').textContent = g.title;
    b.querySelector('i').textContent = g.description;
    b.onclick = () => pick(g.name);
    wrap.appendChild(b);
  }
  if (!picked && games.length) pick(games[0].name, false);
}

function pick(name, fixRoster = true) {
  picked = name;
  const g = games.find((x) => x.name === name);
  [...el('games').children].forEach((c, i) =>
    c.setAttribute('aria-pressed', String(games[i].name === name)));
  if (!g) return;
  const span = g.min_players === g.max_players
    ? `${g.min_players} players` : `${g.min_players}–${g.max_players} players`;
  el('roster-hint').textContent = span;
  if (!fixRoster) return;
  // Keep the roster legal for the chosen game, rather than letting Start fail.
  const have = rosterNames();
  const n = Math.max(g.min_players, Math.min(g.max_players, have.length || g.min_players));
  const names = [...have];
  while (names.length < n) names.push(`Player ${names.length + 1}`);
  el('players').value = names.slice(0, n).join(', ');
}

const rosterNames = () =>
  el('players').value.split(',').map((s) => s.trim()).filter(Boolean);

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
  const s = el('setup');
  s.hidden = !s.hidden;
  el('toggle-setup').setAttribute('aria-expanded', String(!s.hidden));
};
el('start').onclick = () => {
  el('alert').hidden = true;
  send({ type: 'start_game', game: picked, players: rosterNames() });
};
el('pass').onclick = () => send({ type: 'next_turn' });
el('boom').onclick = () => send({
  type: 'test_effect', name: 'fireworks', args: { duration: 2500, palette: 'rainbow' },
});

// --- go -------------------------------------------------------------------
mini = new MiniTable(el('mini'));
renderFeed();
connect();
