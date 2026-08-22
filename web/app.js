/* -------------------------------------------------------------------
   Proteindle

   No framework, no build step, no backend. The whole game is this file
   plus data/proteins.json.

   Daily answers come from a fixed permutation baked into the JSON at
   build time, indexed by days since the epoch, so every player sees the
   same protein and nobody needs a server to tell them which.
   ------------------------------------------------------------------- */

'use strict';

// Per mode, overridden by whatever the database was built with; see
// MAX_GUESSES in pipeline/config.py. 0 means unlimited.
let MAX_GUESSES = { daily: 8, freeplay: 0, hard: 0 };
const DATA_URL = 'data/proteins.json';
const FIELD_KEY = 'proteindle:field';
const EVERYTHING = '';        // sentinel for "no field filter"

const state = {
  db: null,
  meta: {},            // lookup tables handed to the scoring rules
  ladderRank: {},      // conservation key -> rung number
  ladderLabel: {},
  ladderBlurb: {},
  byAccession: new Map(),
  searchIndex: [],
  mode: 'daily',
  field: EVERYTHING,   // '' = no filter; otherwise a key from data.fields
  fields: [],
  pool: [],            // eligible answers for the current mode + field
  target: null,
  guesses: [],
  over: false,
  won: false,
  dayIndex: 0,
  sugIndex: -1,
  sugItems: [],
  easyRound: false,   // this free-play round was drawn from past dailies
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
  giveup:   $('giveup-btn'),
  easier:   $('easier-btn'),
  fieldBtn: $('field-btn'),
  fieldName: $('field-name'),
  fieldBack: $('field-backdrop'),
  fieldGrid: $('field-grid'),
  fieldClose: $('field-close'),
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
  // The single-file build inlines the database, so there is nothing to
  // fetch — which is also what lets that build work straight off file://,
  // where fetch() is blocked.
  const inline = document.getElementById('proteindle-data');
  try {
    if (inline) {
      data = JSON.parse(inline.textContent);
    } else {
      const resp = await fetch(DATA_URL);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
    }
  } catch (err) {
    el.status.textContent = 'Could not load the protein database.';
    el.hint.className = 'hint warn';
    el.hint.textContent =
      'If you opened this file directly, serve the folder instead: ' +
      'run "python -m http.server 8000" in web/ and visit localhost:8000.';
    return;
  }

  state.db = data;
  // Older databases stored a single number rather than a per-mode map.
  if (typeof data.maxGuesses === 'number') {
    MAX_GUESSES = { daily: data.maxGuesses, freeplay: data.maxGuesses,
                    hard: data.maxGuesses };
  } else if (data.maxGuesses) {
    MAX_GUESSES = data.maxGuesses;
  }
  state.fields = data.fields || [];
  state.meta = {
    ladderRank: state.ladderRank,
    functionGroups: data.functionGroups || {},
  };
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
  buildFieldPicker();
  wireEvents();

  const saved = loadLocal(FIELD_KEY);
  const known = state.fields.some((f) => f.key === saved);
  if (saved === EVERYTHING || known) {
    applyField(saved === null ? EVERYTHING : saved, false);
  } else {
    // First visit: ask before starting, so the very first puzzle already
    // comes from something they care about.
    applyField(EVERYTHING, false);
    openFieldPicker();
  }
}

/* --------------------------------------------------------------- field */

function fieldByKey(key) {
  return state.fields.find((f) => f.key === key) || null;
}

function buildFieldPicker() {
  el.fieldGrid.innerHTML = '';

  const everything = document.createElement('button');
  everything.className = 'field-option is-everything';
  everything.dataset.key = EVERYTHING;
  everything.innerHTML =
    `<span class="field-option-name">Everything</span>` +
    `<span class="field-option-count">${state.db.proteins.length} proteins</span>`;
  el.fieldGrid.appendChild(everything);

  state.fields.forEach((f) => {
    const b = document.createElement('button');
    b.className = 'field-option';
    b.dataset.key = f.key;
    b.innerHTML =
      `<span class="field-option-name">${escapeHtml(f.label)}</span>` +
      `<span class="field-option-count">${f.size} proteins</span>`;
    el.fieldGrid.appendChild(b);
  });
}

function applyField(key, restart = true) {
  state.field = key;
  saveLocal(FIELD_KEY, key);

  const f = fieldByKey(key);
  el.fieldName.textContent = f ? f.label : 'Everything';

  [...el.fieldGrid.children].forEach((b) =>
    b.classList.toggle('is-active', b.dataset.key === key)
  );

  // The depth tiers only mean something for "Everything". A field pool is
  // already its full depth, so Hard would be an identical third tab.
  const hardBtn = el.modes.querySelector('.mode-btn[data-mode="hard"]');
  if (hardBtn) hardBtn.hidden = !!f;
  if (f && state.mode === 'hard') state.mode = 'freeplay';

  setMode(state.mode);
  if (!restart) return;
}

function openFieldPicker() { el.fieldBack.hidden = false; }
function closeFieldPicker() { el.fieldBack.hidden = true; }

function computeDayIndex() {
  const epoch = Date.parse(state.db.epoch + 'T00:00:00Z');
  const now = new Date();
  const localMidnightAsUTC = Date.UTC(
    now.getFullYear(), now.getMonth(), now.getDate()
  );
  // Clamped so a pre-launch preview shows Daily #1 rather than #-3.
  state.dayIndex = Math.max(
    0, Math.floor((localMidnightAsUTC - epoch) / 86400000)
  );
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
  if (state.field) {
    // Inside a field, every mode draws from the same pool — the field IS
    // the depth setting.
    state.pool = all.filter((p) => (p.fld || []).includes(state.field));
  } else if (mode === 'daily') {
    state.pool = all.filter((p) => p.t === 'daily');
  } else if (mode === 'freeplay') {
    state.pool = all.filter((p) => p.t === 'daily' || p.t === 'freeplay');
  } else {
    state.pool = all;
  }

  el.newRound.hidden = (mode === 'daily');
  el.easier.hidden = (mode === 'daily');
  startRound();
}

function startRound(opts) {
  state.easyRound = !!(opts && opts.easier);
  if (!state.easyRound) state.easyNote = '';
  state.guesses = [];
  state.over = false;
  state.won = false;
  state.gaveUp = false;
  state.round += 1;
  hideModal();

  if (state.easyRound && state.mode !== 'daily') {
    const { list, played } = easierCandidates();
    state.target = list[Math.floor(Math.random() * list.length)];
    state.easyNote = played
      ? 'Drawn from the best-known proteins and past dailies.'
      : 'Drawn from the best-known proteins.';
  } else if (state.mode === 'daily') {
    const orders = state.db.dailyOrders || {};
    const order = (state.field && orders[state.field]) || state.db.dailyOrder;
    const i = ((state.dayIndex % order.length) + order.length) % order.length;
    state.target = state.byAccession.get(order[i]) || state.pool[0];
    restoreDaily();
  } else {
    state.target = state.pool[Math.floor(Math.random() * state.pool.length)];
  }
  if (!state.target) state.target = state.pool[0];

  render();
  el.input.value = '';
  hideSuggestions();
  el.input.focus();
}

/* --------------------------------------------------- easier rounds */

/*
 * "Give me an easier one" draws from dailies that have already run.
 *
 * Those are the best possible easy pool: they are the most-cited proteins
 * by construction, and a regular player has very likely met them before.
 * Today's puzzle is excluded — handing over the current answer as a
 * practice round would be a strange thing to do.
 */
function playedDailyAccessions() {
  const orders = state.db.dailyOrders || {};
  const order = (state.field && orders[state.field])
    || state.db.dailyOrder || [];
  const n = order.length;
  if (!n) return [];

  const today = ((state.dayIndex % n) + n) % n;
  const elapsed = Math.max(0, Math.min(state.dayIndex, n));
  const out = [];
  for (let d = 0; d < elapsed; d++) {
    if (d !== today) out.push(order[d]);
  }
  return out;
}

function easierCandidates() {
  /*
   * Two things make a protein easier: being famous, and being one you have
   * already solved. Use both, always.
   *
   * An earlier version switched between them — best-known until ten
   * dailies had run, past dailies after that. Measured, day 10 moved the
   * pool from a mean fame rank of 30 to 214: the button got HARDER the day
   * it started doing what it advertised. Past dailies are a random sample
   * of the daily pool, so they are only "easy" in the sense that you have
   * seen them. Union, no switch, no cliff.
   */
  const pool = state.pool;
  if (!pool.length) return { list: [], played: 0 };

  const byFame = [...pool].sort((a, b) => a.rank - b.rank);
  const floorSize = Math.min(100, Math.max(25, Math.round(pool.length * 0.1)));
  const chosen = new Map(byFame.slice(0, floorSize).map((p) => [p.a, p]));

  const inPool = new Set(pool.map((p) => p.a));
  let played = 0;
  playedDailyAccessions().forEach((acc) => {
    if (!inPool.has(acc) || chosen.has(acc)) return;
    const p = state.byAccession.get(acc);
    if (p) { chosen.set(acc, p); played += 1; }
  });

  return { list: [...chosen.values()], played };
}

/* ----------------------------------------------------- daily progress */

function dailyKey() {
  // Field-scoped: today's DNA-repair puzzle is a different puzzle from
  // today's global one, and finishing one must not close the other.
  return `proteindle:daily:${state.field || 'all'}:${state.dayIndex}`;
}

function guessLimit() { return MAX_GUESSES[state.mode] || 0; }

function restoreDaily() {
  const saved = loadLocal(dailyKey());
  if (!saved || !Array.isArray(saved.guesses)) return;
  saved.guesses.forEach((acc) => {
    const p = state.byAccession.get(acc);
    if (p) state.guesses.push(p);
  });
  state.won = !!saved.won;
  state.over = !!saved.over;
  state.gaveUp = !!saved.gaveUp;
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
    gaveUp: state.gaveUp,
  });
}

/* ---------------------------------------------------------- comparison */

/* The comparison rules themselves live in scoring.js, shared verbatim with
   the offline analysis tools. Everything below is presentation: which glyph
   and which label go in the cell. */

const GLYPH = { correct: '✓', partial: '~', wrong: '✗' };

function compare(guess, target) {
  const S = window.ProteindleScoring;
  const results = S.compare(guess, target, state.meta);

  const displays = [
    guess.len == null ? '—' : String(guess.len),
    state.ladderLabel[guess.con] || '—',
    (guess.loc || []).join(' · ') || '—',
    guess.fn || '—',
    (guess.pw || []).join(' · ') || '—',
    guess.chr == null ? '—' : String(guess.chr),
    guess.dis ? 'Yes' : 'No',
  ];
  // Which columns render as stacked lines rather than one string.
  const stacked = [null, null, guess.loc, null, guess.pw, null, null];
  // A missing value is not the same as a wrong one; say so.
  const absent = [
    guess.len == null, guess.con == null, !(guess.loc || []).length,
    guess.fn == null, !(guess.pw || []).length, guess.chr == null,
    guess.dis == null,
  ];

  return results.map((r, i) => ({
    state: r.state,
    arrow: r.arrow,
    glyph: absent[i] ? '?' : GLYPH[r.state],
    display: displays[i],
    stacked: stacked[i],
  }));
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

  const limit = guessLimit();
  if (protein.a === state.target.a) {
    state.won = true;
    state.over = true;
  } else if (limit && state.guesses.length >= limit) {
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

function giveUp() {
  if (state.over) return;
  state.over = true;
  state.won = false;
  state.gaveUp = true;
  persistDaily();
  render();
  showModal();
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
  const limit = guessLimit();
  const left = limit ? limit - state.guesses.length : Infinity;
  const fieldLabel = state.field
    ? (fieldByKey(state.field) || {}).label : null;

  if (state.over) {
    el.status.textContent = state.won
      ? `Solved in ${state.guesses.length}.`
      : state.gaveUp
        ? `Gave up — it was ${state.target.g}.`
        : `Out of guesses — it was ${state.target.g}.`;
    el.input.disabled = true;
    el.guessBtn.disabled = true;
  } else {
    const poolNote = state.mode === 'daily'
      ? `${fieldLabel ? fieldLabel + ' daily' : 'Daily'} #${state.dayIndex + 1}`
      : `${state.pool.length} possible answers`;
    const guessNote = limit
      ? `${left} guess${left === 1 ? '' : 'es'} left`
      : `${state.guesses.length} guess${state.guesses.length === 1 ? '' : 'es'}`
        + ' · no limit';
    el.status.textContent = state.easyRound
      ? `Easier round · ${guessNote}`
      : `${poolNote} · ${guessNote}`;
    el.input.disabled = false;
    el.guessBtn.disabled = false;
  }

  // Only worth offering once they have actually tried something.
  el.giveup.hidden = state.over || state.guesses.length === 0;

  if (state.easyRound && state.easyNote && !state.guesses.length) {
    el.hint.className = 'hint';
    el.hint.textContent = state.easyNote;
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

  el.verdict.textContent = state.won
    ? 'Solved'
    : state.gaveUp ? 'Revealed' : 'Out of guesses';
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
  const f = state.field ? (fieldByKey(state.field) || {}).label : null;
  const head = state.mode === 'daily'
    ? `Proteindle${f ? ' · ' + f : ''} #${state.dayIndex + 1}`
    : `Proteindle${f ? ' · ' + f : ''} (${state.mode})`;
  const limit = guessLimit();
  const score = state.won
    ? `${state.guesses.length}/${limit || '∞'}`
    : `X/${limit || '∞'}`;
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
  // A missing element must degrade one feature, not kill the whole page.
  // An HTML edit that silently failed to apply once left el.giveup null,
  // and the resulting throw in here aborted init() before the field picker
  // ever opened — a blank-looking bug two layers from its cause.
  const missing = Object.entries(el)
    .filter(([, node]) => !node)
    .map(([name]) => name);
  if (missing.length) {
    console.error('Proteindle: missing DOM nodes:', missing.join(', '));
  }
  const on = (node, ev, fn) => { if (node) node.addEventListener(ev, fn); };

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

  on(el.giveup, 'click', giveUp);

  on(el.fieldBtn, 'click', openFieldPicker);
  on(el.fieldClose, 'click', closeFieldPicker);
  on(el.fieldBack, 'click', (e) => {
    if (e.target === el.fieldBack) closeFieldPicker();
  });
  on(el.fieldGrid, 'click', (e) => {
    const btn = e.target.closest('.field-option');
    if (!btn) return;
    closeFieldPicker();
    applyField(btn.dataset.key);
  });

  on(el.newRound, 'click', () => startRound());
  on(el.easier, 'click', () => startRound({ easier: true }));
  on(el.again, 'click', () => {
    hideModal();
    startRound(state.easyRound ? { easier: true } : undefined);
  });
  on(el.close, 'click', hideModal);
  on(el.share, 'click', copyResult);

  el.backdrop.addEventListener('click', (e) => {
    if (e.target === el.backdrop) hideModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (!el.backdrop.hidden) hideModal();
    else if (!el.fieldBack.hidden) closeFieldPicker();
  });
}

init();
