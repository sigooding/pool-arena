// The tablet view: scores, whose turn it is, and the four buttons that run a
// night. Intentionally separate from the projector page so it can live on a
// phone on the rail while the projector shows only the table.

const el = (id) => document.getElementById(id);
let ws = null;
let games = [];
let board = null;

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { el('sub').textContent = 'connected'; send({ type: 'games' }); };
  ws.onclose = () => { el('sub').textContent = 'reconnecting…'; setTimeout(connect, 800); };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === 'games') { games = msg.games; renderGames(); }
    if (msg.type === 'scoreboard') { board = msg.scoreboard; render(); }
    if (msg.type === 'shot') flashShot(msg.shot);
    if (msg.type === 'error') showError(msg.error);
  };
}

const send = (o) => ws && ws.readyState === 1 && ws.send(JSON.stringify(o));

function renderGames() {
  el('game').innerHTML = games
    .map((g) => `<option value="${g.name}">${g.title} — ${g.description}</option>`)
    .join('');
}

function render() {
  if (!board) return;
  el('title').textContent = board.title;
  el('sub').textContent = board.over
    ? (board.winner !== null ? `${board.players[board.winner].name} wins` : 'game over')
    : `shot ${board.shot_number + 1} · ${board.players[board.turn].name} to play`;

  el('players-list').innerHTML = board.players.map((p, i) => {
    const bits = [];
    if (p.group) bits.push(`<span class="tag">${p.group}</span>`);
    if (p.balls_left && p.balls_left.length) bits.push(`<span class="meta">left: ${p.balls_left.join(' ')}</span>`);
    if (p.lives) bits.push(`<span class="meta">${'♥'.repeat(p.lives)}</span>`);
    return `<div class="player ${i === board.turn && !board.over ? 'turn' : ''} ${p.out ? 'out' : ''}">
      <span class="name">${p.name}</span>${bits.join(' ')}
      <span class="score">${p.score}</span></div>`;
  }).join('');

  el('log').innerHTML = (board.log || []).slice().reverse()
    .map((l) => `<div>${l}</div>`).join('');
}

// Its own element, not the subtitle: a game in progress pushes a scoreboard
// update every shot, and that would wipe the message before it was read.
function showError(text) {
  const box = el('error');
  box.textContent = text;
  box.hidden = false;
  clearTimeout(showError.timer);
  showError.timer = setTimeout(() => { box.hidden = true; }, 8000);
}

function flashShot(shot) {
  const r = shot.result || {};
  if (r.foul) el('sub').textContent = `foul: ${r.foul}`;
}

// Pre-fill a sensible roster when the game changes, so picking cut-throat
// does not fail on the two names left over from 8-ball.
el('game').onchange = () => {
  const g = games.find((x) => x.name === el('game').value);
  if (!g) return;
  const have = el('players').value.split(',').map((s) => s.trim()).filter(Boolean);
  if (have.length >= g.min_players && have.length <= g.max_players) return;
  const n = Math.max(g.min_players, Math.min(g.max_players, have.length || g.min_players));
  const names = [...have];
  while (names.length < n) names.push(`Player ${names.length + 1}`);
  el('players').value = names.slice(0, n).join(', ');
};

el('start').onclick = () => {
  el('error').hidden = true;
  send({
    type: 'start_game',
    game: el('game').value,
    players: el('players').value.split(',').map((s) => s.trim()).filter(Boolean),
  });
};
el('pass').onclick = () => send({ type: 'next_turn' });
el('boom').onclick = () => send({
  type: 'test_effect', name: 'fireworks', args: { duration: 2500, palette: 'rainbow' },
});

connect();
