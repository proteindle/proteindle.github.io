/* -------------------------------------------------------------------
   Proteindle

   No framework, no build step, no backend. The whole game is this file
   plus data/proteins.json.

   Daily answers come from a fixed permutation baked into the JSON at
   build time, indexed by days since the epoch, so every player sees the
   same protein and nobody needs a server to tell them which.
   ------------------------------------------------------------------- */

'use strict';

const MAX_GUESSES = 8;
const DATA_URL = 'data/proteins.json';

const state = {
  db: null,
  ladderRank: {},      // conservation key -> rung number
  ladderLabel: {},
  ladderBlurb: {},
  byAccession: new Map(),
  searchIndex: [],
  mode: 'daily',
  pool: [],            // eligible answers for the current mode
  target: null,
  guesses: [],
  over: false,
  won: false,
  dayIndex: 0,
  sugIndex: -1,
  sugItems: [],
  round: 0,           // bumped every startRound, so deferred callbacks
                      // from an abandoned round can tell they are stale
};

const $ = (id) => document.getElementById(id);

const el = {
  status:   $('status-text'),
  newRound: $('new-round'),
  input:    $('guess-input'),
  guessBtn: $('guess-btn'),
  sugs:     $('suggestions'),
  hint:     $('hint'),
  body:     $('board-body'),
  modes:    $('modes'),
  backdrop: $('modal-backdrop'),
  verdict:  $('modal-verdict'),
  title:    $('modal-title'),
  sub:      $('modal-sub'),
  reveal:   $('reveal'),
  blurb:    $('modal-blurb'),
  share:    $('share-btn'),
  uniprot:  $('uniprot-link'),
  again:    $('again-btn'),
  close:    $('modal-close'),
};

/* ------------------------------------------------------------ storage */
/* Wrapped because private windows and locked-down browsers throw on
   access rather than returning null. A failed save must never break play. */

function saveLocal(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
}

function loadLocal(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

/* --------------------------------------------------------------- init */

async function init() {
  let data;
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    el.status.textContent = 'Could not load the protein database.';
    el.hint.className = 'hint warn';
    el.hint.textContent =
      'If you opened this file directly, serve the folder instead: ' +
      'run "python -m http.server 8000" in web/ and visit localhost:8000.';
    return;
  }

  state.db = data;
  data.ladder.forEach((rung) => {
    state.ladderRank[rung.key] = rung.rank;
    state.ladderLabel[rung.key] = rung.label;
    state.ladderBlurb[rung.key] = rung.blurb;
  });

  data.proteins.forEach((p) => state.byAccession.set(p.a, p));
  buildSearchIndex(data.proteins);
  computeDayIndex();

  el.input.disabled = false;
  el.guessBtn.disabled = false;
  wireEvents();
  setMode('daily');
}

function computeDayIndex() {
  const epoch = Date.parse(state.db.epoch + 'T00:00:00Z');
  const now = new Date();
  const localMidnightAsUTC = Date.UTC(
    now.getFullYear(), now.getMonth(), now.getDate()
  );
  state.dayIndex = Math.floor((localMidnightAsUTC - epoch) / 86400000);
}

/* ------------------------------------------------------------- search */

function normalize(s) {
  return (s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function buildSearchIndex(proteins) {
  state.searchIndex = proteins.map((p) => ({
    p,
    gene: normalize(p.g),
    aliases: (p.s || []).map(normalize),
    name: normalize(p.n),
    nameRaw: p.n,
  }));
}

function search(query, limit = 8) {
  const q = normalize(query);
  if (q.length < 1) return [];

  const exact = [], genePrefix = [], aliasPrefix = [], nameHit = [];

  for (const entry of state.searchIndex) {
    if (entry.gene === q) { exact.push(entry); continue; }
    if (entry.gene.startsWith(q)) { genePrefix.push(entry); continue; }
    if (entry.aliases.some((a) => a === q || a.startsWith(q))) {
      aliasPrefix.push(entry); continue;
    }
    if (q.length >= 3 && entry.name.includes(q)) { nameHit.push(entry); }
  }

  const byFame = (a, b) => a.p.rank - b.p.rank;
  genePrefix.sort(byFame); aliasPrefix.sort(byFame); nameHit.sort(byFame);

  return [...exact, ...genePrefix, ...aliasPrefix, ...nameHit].slice(0, limit);
}

function matchedAlias(entry, query) {
  const q = normalize(query);
  if (!q || entry.gene.startsWith(q)) return '';
  const idx = entry.aliases.findIndex((a) => a.startsWith(q));
  return idx >= 0 ? entry.p.s[idx] : '';
}

/* --------------------------------------------------------------- mode */

function setMode(mode) {
  state.mode = mode;
  [...el.modes.querySelectorAll('.mode-btn')].forEach((b) =>
    b.classList.toggle('is-active', b.dataset.mode === mode)
  );

  const all = state.db.proteins;
  if (mode === 'daily') {
    state.pool = all.filter((p) => p.t === 'daily');
  } else if (mode === 'freeplay') {
    state.pool = all.filter((p) => p.t === 'daily' || p.t === 'freeplay');
  } else {
    state.pool = all;
  }

  el.newRound.hidden = (mode === 'daily');
  startRound();
}

function startRound() {
  state.guesses = [];
  state.over = false;
  state.won = false;
  state.round += 1;
  hideModal();

  if (state.mode === 'daily') {
    const order = state.db.dailyOrder;
    const i = ((state.dayIndex % order.length) + order.length) % order.length;
    state.target = state.byAccession.get(order[i]) || state.pool[0];
    restoreDaily();
  } else {
    state.target = state.pool[Math.floor(Math.random() * state.pool.length)];
  }

  render();
  el.input.value = '';
  hideSuggestions();
  el.input.focus();
}

/* ----------------------------------------------------- daily progress */

function dailyKey() { return `proteindle:daily:${state.dayIndex}`; }

function restoreDaily() {
  const saved = loadLocal(dailyKey());
  if (!saved || !Array.isArray(saved.guesses)) return;
  saved.guesses.forEach((acc) => {
    const p = state.byAccession.get(acc);
    if (p) state.guesses.push(p);
  });
  state.won = !!saved.won;
  state.over = !!saved.over;
  if (state.over) {
    // Re-open the reveal so a returning player sees their result — but
    // only if they are still on this round when the timer fires. Without
    // the guard, switching to free play during the delay pops the daily
    // answer over the new game.
    const round = state.round;
    setTimeout(() => {
      if (state.round === round && state.mode === 'daily' && state.over) {
        showModal();
      }
    }, 250);
  }
}

function persistDaily() {
  if (state.mode !== 'daily') return;
  saveLocal(dailyKey(), {
    guesses: state.guesses.map((g) => g.a),
    won: state.won,
    over: state.over,
  });
}

/* ---------------------------------------------------------- comparison */

const CHROM_ORDER = (c) => {
  if (c === null || c === undefined) return null;
  if (c === 'X') return 23;
  if (c === 'Y') return 24;
  if (c === 'MT') return 25;
  const n = parseInt(c, 10);
  return Number.isNaN(n) ? null : n;
};

function cmpNumeric(guessVal, targetVal, closeFraction) {
  if (guessVal == null || targetVal == null) {
    return { state: 'wrong', arrow: null, glyph: '?' };
  }
  if (guessVal === targetVal) {
    return { state: 'correct', arrow: null, glyph: '✓' };
  }
  const arrow = targetVal > guessVal ? '↑' : '↓';
  if (closeFraction) {
    const diff = Math.abs(targetVal - guessVal) / Math.max(targetVal, 1);
    if (diff <= closeFraction) {
      return { state: 'partial', arrow, glyph: '~' };
    }
  }
  return { state: 'wrong', arrow, glyph: '✗' };
}

function cmpOrdinal(guessKey, targetKey) {
  const g = state.ladderRank[guessKey];
  const t = state.ladderRank[targetKey];
  if (g == null || t == null) {
    return { state: 'wrong', arrow: null, glyph: '?' };
  }
  if (g === t) return { state: 'correct', arrow: null, glyph: '✓' };
  const arrow = t > g ? '↑' : '↓';
  // One rung apart is genuinely close on a seven-rung ladder.
  const st = Math.abs(t - g) === 1 ? 'partial' : 'wrong';
  return { state: st, arrow, glyph: st === 'partial' ? '~' : '✗' };
}

function cmpSet(guessArr, targetArr) {
  const g = new Set(guessArr || []);
  const t = new Set(targetArr || []);
  if (g.size === 0 && t.size === 0) {
    return { state: 'correct', arrow: null, glyph: '✓' };
  }
  if (g.size === t.size && [...g].every((v) => t.has(v))) {
    return { state: 'correct', arrow: null, glyph: '✓' };
  }
  const overlap = [...g].some((v) => t.has(v));
  return overlap
    ? { state: 'partial', arrow: null, glyph: '~' }
    : { state: 'wrong', arrow: null, glyph: '✗' };
}

function cmpExact(guessVal, targetVal) {
  const same = guessVal === targetVal;
  return {
    state: same ? 'correct' : 'wrong',
    arrow: null,
    glyph: same ? '✓' : '✗',
  };
}

function compare(guess, target) {
  return [
    { ...cmpNumeric(guess.len, target.len, 0.10),
      display: guess.len == null ? '—' : String(guess.len) },

    { ...cmpOrdinal(guess.con, target.con),
      display: state.ladderLabel[guess.con] || '—' },

    { ...cmpSet(guess.loc, target.loc),
      display: (guess.loc || []).join(' · ') || '—', stacked: guess.loc },

    { ...cmpExact(guess.fn, target.fn),
      display: guess.fn || '—' },

    { ...cmpSet(guess.pw, target.pw),
      display: (guess.pw || []).join(' · ') || '—', stacked: guess.pw },

    { ...cmpNumeric(CHROM_ORDER(guess.chr), CHROM_ORDER(target.chr), 0),
      display: guess.chr == null ? '—' : String(guess.chr) },

    { ...cmpExact(guess.dis, target.dis),
      display: guess.dis ? 'Yes' : 'No' },
  ];
}

/* ------------------------------------------------------------ guessing */

function submitGuess(protein) {
  if (state.over || !protein) return;

  if (state.guesses.some((g) => g.a === protein.a)) {
    flashHint(`You already guessed ${protein.g}.`);
    return;
  }

  state.guesses.push(protein);
  el.input.value = '';
  hideSuggestions();
  el.hint.textContent = '';

  if (protein.a === state.target.a) {
    state.won = true;
    state.over = true;
  } else if (state.guesses.length >= MAX_GUESSES) {
    state.over = true;
  }

  persistDaily();
  render();

  if (state.over) {
    const round = state.round;
    setTimeout(() => {
      if (state.round === round && state.over) showModal();
    }, 700);
  }
}

function flashHint(msg) {
  el.hint.className = 'hint warn';
  el.hint.textContent = msg;
  setTimeout(() => {
    if (el.hint.textContent === msg) {
      el.hint.className = 'hint';
      el.hint.textContent = '';
    }
  }, 2400);
}

/* ------------------------------------------------------------- render */

function render() {
  const left = MAX_GUESSES - state.guesses.length;

  if (state.over) {
    el.status.textContent = state.won
      ? `Solved in ${state.guesses.length}.`
      : `Out of guesses — it was ${state.target.g}.`;
    el.input.disabled = true;
    el.guessBtn.disabled = true;
  } else {
    const poolNote = state.mode === 'daily'
      ? `Daily #${state.dayIndex + 1}`
      : `${state.pool.length} possible answers`;
    el.status.textContent =
      `${poolNote} · ${left} guess${left === 1 ? '' : 'es'} left`;
    el.input.disabled = false;
    el.guessBtn.disabled = false;
  }

  el.body.innerHTML = '';
  // Newest guess on top, so you never have to scroll to see what just
  // happened.
  [...state.guesses].reverse().forEach((guess, revIdx) => {
    const results = compare(guess, state.target);
    const tr = document.createElement('tr');

    const subject = document.createElement('td');
    subject.innerHTML =
      `<div class="cell subject">
         <span class="subject-gene">${escapeHtml(guess.g)}</span>
         <span class="subject-name">${escapeHtml(guess.n)}</span>
       </div>`;
    tr.appendChild(subject);

    results.forEach((r, i) => {
      const td = document.createElement('td');
      const cell = document.createElement('div');
      cell.className = `cell ${r.state}`;
      // Only animate the row that just landed.
      cell.style.animationDelay = revIdx === 0 ? `${i * 90}ms` : '0ms';
      if (revIdx !== 0) cell.style.animation = 'none';

      const glyph = document.createElement('span');
      glyph.className = 'cell-glyph';
      glyph.textContent = r.glyph;
      glyph.setAttribute('aria-hidden', 'true');
      cell.appendChild(glyph);

      const val = document.createElement('span');
      val.className = 'cell-value';
      if (r.stacked && r.stacked.length > 1) {
        val.classList.add('stacked');
        r.stacked.forEach((s) => {
          const line = document.createElement('span');
          line.textContent = s;
          val.appendChild(line);
        });
      } else {
        val.textContent = r.display;
      }
      cell.appendChild(val);

      if (r.arrow) {
        const arr = document.createElement('span');
        arr.className = 'cell-arrow';
        arr.textContent = r.arrow;
        cell.appendChild(arr);
      }

      cell.setAttribute('aria-label',
        `${r.display}. ${r.state}${r.arrow ? ', answer is ' +
          (r.arrow === '↑' ? 'higher' : 'lower') : ''}`);

      td.appendChild(cell);
      tr.appendChild(td);
    });

    el.body.appendChild(tr);
  });
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* -------------------------------------------------------- suggestions */

function showSuggestions(query) {
  const hits = search(query);
  state.sugItems = hits;
  state.sugIndex = -1;

  if (!hits.length) { hideSuggestions(); return; }

  el.sugs.innerHTML = '';
  hits.forEach((entry, i) => {
    const li = document.createElement('li');
    li.setAttribute('role', 'option');
    li.dataset.index = String(i);
    const alias = matchedAlias(entry, query);
    li.innerHTML =
      `<span class="sug-gene">${escapeHtml(entry.p.g)}</span>` +
      `<span class="sug-name">${escapeHtml(entry.p.n)}</span>` +
      (alias ? `<span class="sug-alias">${escapeHtml(alias)}</span>` : '');
    li.addEventListener('mousedown', (e) => {
      e.preventDefault();
      submitGuess(entry.p);
    });
    el.sugs.appendChild(li);
  });
  el.sugs.hidden = false;
}

function hideSuggestions() {
  el.sugs.hidden = true;
  el.sugs.innerHTML = '';
  state.sugItems = [];
  state.sugIndex = -1;
}

function moveSelection(delta) {
  if (!state.sugItems.length) return;
  state.sugIndex =
    (state.sugIndex + delta + state.sugItems.length) % state.sugItems.length;
  [...el.sugs.children].forEach((li, i) =>
    li.setAttribute('aria-selected', String(i === state.sugIndex))
  );
  const active = el.sugs.children[state.sugIndex];
  if (active) active.scrollIntoView({ block: 'nearest' });
}

/* -------------------------------------------------------------- modal */

function showModal() {
  const t = state.target;

  el.verdict.textContent = state.won ? 'Solved' : 'Out of guesses';
  el.verdict.className = 'modal-verdict' + (state.won ? '' : ' lose');
  el.title.textContent = t.g;
  el.sub.textContent = t.n + (t.d ? ` — ${t.d}` : '');

  const rows = [
    ['Length', t.len != null ? `${t.len} aa` +
      (t.mass ? ` · ${(t.mass / 1000).toFixed(1)} kDa` : '') : '—'],
    ['Conserved to', state.ladderLabel[t.con] || '—'],
    ['Localization', (t.loc || []).join(', ') || '—'],
    ['Function', t.fn || '—'],
    ['Pathway', (t.pw || []).join(', ') || '—'],
    ['Locus', t.locus || t.chr || '—'],
    ['Disease', t.dis ? ((t.disn || []).join('; ') || 'Yes') : 'No known link'],
    ['Family', t.fam || '—'],
    ['Papers', t.pap ? `${t.pap.toLocaleString()} (rank #${t.rank})` : '—'],
  ];

  el.reveal.innerHTML = rows.map(([k, v]) =>
    `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd>`
  ).join('');

  el.blurb.textContent = state.ladderBlurb[t.con] || '';
  el.uniprot.href = `https://www.uniprot.org/uniprotkb/${t.a}/entry`;
  el.again.hidden = (state.mode === 'daily');
  el.backdrop.hidden = false;
}

function hideModal() { el.backdrop.hidden = true; }

function shareText() {
  const squares = { correct: '🟩', partial: '🟨', wrong: '🟥' };
  const head = state.mode === 'daily'
    ? `Proteindle #${state.dayIndex + 1}`
    : `Proteindle (${state.mode})`;
  const score = state.won ? `${state.guesses.length}/${MAX_GUESSES}`
                          : `X/${MAX_GUESSES}`;
  const grid = state.guesses
    .map((g) => compare(g, state.target).map((r) => squares[r.state]).join(''))
    .join('\n');
  return `${head} ${score}\n\n${grid}`;
}

async function copyResult() {
  const text = shareText();
  try {
    await navigator.clipboard.writeText(text);
    el.share.textContent = 'Copied';
  } catch (_) {
    // Clipboard API needs a secure context; fall back to the old trick.
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); el.share.textContent = 'Copied'; }
    catch (_e) { el.share.textContent = 'Copy failed'; }
    document.body.removeChild(ta);
  }
  setTimeout(() => { el.share.textContent = 'Copy result'; }, 1800);
}

/* ------------------------------------------------------------- events */

function wireEvents() {
  el.input.addEventListener('input', () => showSuggestions(el.input.value));

  el.input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveSelection(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveSelection(-1); }
    else if (e.key === 'Escape') { hideSuggestions(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (state.sugIndex >= 0 && state.sugItems[state.sugIndex]) {
        submitGuess(state.sugItems[state.sugIndex].p);
      } else {
        const hits = search(el.input.value, 1);
        if (hits.length) submitGuess(hits[0].p);
        else flashHint('No protein by that name in the database.');
      }
    }
  });

  el.input.addEventListener('blur', () => setTimeout(hideSuggestions, 120));

  el.guessBtn.addEventListener('click', () => {
    const hits = search(el.input.value, 1);
    if (hits.length) submitGuess(hits[0].p);
    else flashHint('No protein by that name in the database.');
  });

  el.modes.addEventListener('click', (e) => {
    const btn = e.target.closest('.mode-btn');
    if (btn) setMode(btn.dataset.mode);
  });

  el.newRound.addEventListener('click', startRound);
  el.again.addEventListener('click', () => { hideModal(); startRound(); });
  el.close.addEventListener('click', hideModal);
  el.share.addEventListener('click', copyResult);

  el.backdrop.addEventListener('click', (e) => {
    if (e.target === el.backdrop) hideModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !el.backdrop.hidden) hideModal();
  });
}

init();
