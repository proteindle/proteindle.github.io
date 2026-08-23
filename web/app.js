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
const REST_URL = 'data/proteins-rest.json';
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
  buckets: new Map(),     // two-char token prefix -> entries
  geneFirst: new Map(),   // first letter -> entries, for one-char queries
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
  restLoaded: false,  // the guessable-only half of the database
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
  loadRest();

  // Browse and Train (study.js) read this same database rather than
  // fetching a second copy — 7 MB is not worth downloading twice. They
  // wait on the events below instead of polling.
  window.Proteindle = {
    state, saveLocal, loadLocal, escapeHtml,
    restReady: () => state.restLoaded === true,
  };
  document.dispatchEvent(new CustomEvent('proteindle:ready'));

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

  // Not proteins.length: the game file also carries the extra members that
  // field pools reached for past rank 3,000, and those are answers only
  // inside the field that claimed them.
  const everywhere = state.db.proteins.filter(
    (p) => p.t === 'daily' || p.t === 'freeplay' || p.t === 'hard').length;

  const everything = document.createElement('button');
  everything.className = 'field-option is-everything';
  everything.dataset.key = EVERYTHING;
  everything.innerHTML =
    `<span class="field-option-name">Everything</span>` +
    `<span class="field-option-count">${everywhere} proteins</span>`;
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

/* -------------------------------------------------- the rest of them */

/*
 * Answers come from proteins.json. Guesses can be any reviewed human
 * protein, all 20,190 of them, which is another megabyte — so they arrive
 * in a second file, fetched once the board is already up and playable.
 *
 * The split exists because the two files answer different questions. The
 * first has to be small: nothing happens until it lands. The second only
 * has to arrive before someone types a gene nobody has heard of, and by
 * then it has had a few hundred milliseconds' head start.
 */
function loadRest() {
  const inline = document.getElementById('proteindle-rest');
  const finish = (list) => {
    const fresh = list.filter((p) => !state.byAccession.has(p.a));
    fresh.forEach((p) => state.byAccession.set(p.a, p));
    extendSearchIndex(fresh);
    state.restLoaded = true;
    document.dispatchEvent(new CustomEvent('proteindle:rest'));
    // Someone may be mid-word in the box; redo the lookup so the protein
    // that was missing a moment ago appears without them retyping.
    if (el.input && el.input.value && document.activeElement === el.input) {
      showSuggestions(el.input.value);
    }
  };

  if (inline) {
    try { finish(JSON.parse(inline.textContent).proteins || []); }
    catch (_) { state.restLoaded = true; }
    return;
  }
  const url = (state.db && state.db.rest) || REST_URL;
  fetch(url)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
    .then((d) => finish(d.proteins || []))
    .catch(() => {
      // Not fatal: every answer is already here, and so is every protein
      // famous enough that someone is likely to type it.
      state.restLoaded = 'failed';
      console.warn('Proteindle: the full protein list did not load.');
    });
}

/* ------------------------------------------------------------- search */

/*
 * The first version matched a single normalized string: punctuation
 * stripped, then substring. It failed the way people actually type.
 * "beta catenin" found nothing, because the entry reads "Catenin beta-1"
 * and the words are the other way round. "SLC" found nothing beyond the
 * genes starting with it. "collagen" surfaced whatever happened to sort
 * first. Several people on Reddit reported they could not find their own
 * protein and assumed it was missing; it was there, and the search was
 * the thing that was broken.
 *
 * So: tokens, not one string. Every query word has to match the START of
 * some word in the entry, in any order, across gene symbol, synonyms,
 * protein name and the HGNC description.
 */

function normalize(s) {
  return (s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

// "Collagen alpha-1(I) chain" -> COLLAGEN ALPHA 1 I CHAIN
// "SLC2A1" -> SLC2A1 SLC, so that a family prefix finds its family.
//
// Only the LEADING letter run is split out, and only when it is two or
// more letters. Splitting a symbol into every run instead produces junk
// single-letter tokens — the synonym "P450C3" yields a bare "C", which
// made CYP3A4 a whole-word match for "cytochrome c" and, being far more
// cited than cytochrome c itself, it won.
function tokenize(s) {
  const out = [];
  const raw = (s || '').toUpperCase().split(/[^A-Z0-9]+/);
  for (const t of raw) {
    if (!t) continue;
    out.push(t);
    const head = /^[A-Z]{2,}(?=[0-9])/.exec(t);
    if (head) out.push(head[0]);
  }
  return out;
}

/* One haystack string per protein, every token prefixed by a space, so
   `hay.indexOf(' ' + word)` is a word-boundary prefix test — no per-query
   allocation over 20,000 entries. */
function haystack(bits, prefixes) {
  const seen = new Set();
  let hay = '';
  for (const bit of bits) {
    for (const tok of tokenize(bit)) {
      if (seen.has(tok)) continue;
      seen.add(tok);
      hay += ' ' + tok;
      if (prefixes) prefixes.add(tok.slice(0, 2));
    }
  }
  return hay + ' ';
}

function indexEntry(p, prefixes) {
  return {
    p,
    gene: normalize(p.g),
    aliases: (p.s || []).map(normalize),
    // What the protein is called, kept apart from what it is described as
    // doing. Both are searchable; the name is the better signal. Otherwise
    // "collagen" leads with adiponectin, whose HGNC description happens to
    // read "C1Q and collagen domain containing" and which is more cited
    // than any actual collagen.
    hay: haystack([p.g, ...(p.s || []), p.n], prefixes),
    // Kept apart rather than folded in. The name is the better signal, and
    // scanning 20,000 entries twice on every keystroke is the difference
    // between instant and laggy on a cheap phone.
    desc: p.d ? haystack([p.d], prefixes) : '',
  };
}

/*
 * A posting list from two-character token prefix to the entries containing
 * a token that starts with it, plus a smaller one from first letter to
 * gene symbol.
 *
 * Without it, every keystroke walked all 20,190 entries: 85 ms on a
 * throttled phone, which is a visibly stuttering text box. Any query of
 * two characters or more now touches a few hundred candidates instead,
 * and a one-character query falls back to gene symbols, which is the only
 * sensible reading of a single letter anyway.
 */
function addToIndex(p) {
  const prefixes = new Set();
  const entry = indexEntry(p, prefixes);
  state.searchIndex.push(entry);
  for (const key of prefixes) {
    const bucket = state.buckets.get(key);
    if (bucket) bucket.push(entry);
    else state.buckets.set(key, [entry]);
  }
  const first = entry.gene.charAt(0);
  if (first) {
    const bucket = state.geneFirst.get(first);
    if (bucket) bucket.push(entry);
    else state.geneFirst.set(first, [entry]);
  }
}

function buildSearchIndex(proteins) {
  state.searchIndex = [];
  state.buckets = new Map();
  state.geneFirst = new Map();
  for (const p of proteins) addToIndex(p);
}

function extendSearchIndex(proteins) {
  for (const p of proteins) addToIndex(p);
}

/* The smallest posting list that every result must appear in. */
function candidates(words, q) {
  let best = null;
  for (const w of words) {
    if (w.length < 2) continue;
    const bucket = state.buckets.get(w.slice(0, 2)) || [];
    if (best === null || bucket.length < best.length) best = bucket;
  }
  if (best !== null) return best;
  return state.geneFirst.get(q.charAt(0)) || [];
}

/* base for a whole-word hit, base + 1 for a prefix hit, null for neither */
function tokenScore(hay, words, base) {
  let whole = true;
  for (const w of words) {
    if (hay.indexOf(' ' + w) < 0) return null;
    if (hay.indexOf(' ' + w + ' ') < 0) whole = false;
  }
  return whole ? base : base + 1;
}

function search(query, limit = 10) {
  const words = tokenize(query);
  if (!words.length) return [];
  const q = normalize(query);

  // Lower is better. Ties break on fame, which is the only ranking signal
  // that reliably matches "the one they meant".
  const scored = [], rest = [];
  for (const entry of candidates(words, q)) {
    let score;
    if (entry.gene === q) score = 0;
    // Gene prefix outranks an exact synonym on purpose. "TP" is a real
    // synonym of both TMPO and TYMP, and putting either above TP53 is a
    // bad guess about what was meant.
    else if (entry.gene.startsWith(q)) score = 1;
    else if (entry.aliases.includes(q)) score = 2;
    else if (entry.aliases.some((a) => a.startsWith(q))) score = 3;
    else {
      // Whole words beat prefixes, or "collagen" leads with collagenases.
      score = tokenScore(entry.hay, words, 4);
      if (score === null) { rest.push(entry); continue; }
    }
    scored.push([score, entry.p.rank || 1e9, entry]);
  }

  // Descriptions are only consulted if the names came up short. "tumor
  // suppressor" needs this pass; "TP53" never reaches it. Skipping it is
  // most of what keeps typing responsive on a slow phone.
  if (scored.length < limit) {
    for (const entry of rest) {
      if (!entry.desc) continue;
      const score = tokenScore(entry.desc, words, 6);
      if (score !== null) scored.push([score, entry.p.rank || 1e9, entry]);
    }
  }

  scored.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
  return scored.slice(0, limit).map((s) => s[2]);
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
    // Not `all`: the game file also carries the extra members that field
    // pools reached for past rank 3,000. Those are answers inside their
    // own field and nowhere else — hard mode is still the famous 3,000.
    state.pool = all.filter((p) => p.t === 'daily' || p.t === 'freeplay'
                                || p.t === 'hard');
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

/* Until the second file lands, a miss might just be a miss in the half
   of the database that has not arrived yet. Say so rather than claiming
   the protein does not exist. */
function noMatchMessage() {
  if (state.restLoaded === true || state.restLoaded === 'failed') {
    return 'No protein by that name. Try the gene symbol, or a word from '
         + 'the protein name.';
  }
  return 'Still loading the full protein list \u2014 try again in a moment.';
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

/*
 * The protein family of whatever you just guessed, shown under its name.
 *
 * This is the answer to the most common complaint about the board: guess
 * a receptor tyrosine kinase when the answer is a different receptor
 * tyrosine kinase and every column can still come back red, because the
 * columns measure size, age, location and pathway — not relatedness. The
 * family is the one thing a biologist reasons with that the board was not
 * showing.
 *
 * UniProt's family string is a hierarchy, comma-separated, general to
 * specific: "Protein kinase superfamily, Tyr protein kinase family, EGF
 * receptor subfamily". So it grades naturally — same string is green,
 * a shared prefix is amber, and no relation is left plain. It is not a
 * scored column and it stays out of the share grid, so a shared result
 * still means the same thing it did yesterday.
 */
function familyParts(fam) {
  return (fam || '').split(',').map((s) => s.trim()).filter(Boolean);
}

function familySignal(guess, target) {
  const g = familyParts(guess && guess.fam);
  if (!g.length) return null;
  const t = familyParts(target && target.fam);

  let shared = 0;
  while (shared < g.length && shared < t.length &&
         g[shared].toLowerCase() === t[shared].toLowerCase()) shared += 1;

  const state = (shared && shared === g.length && shared === t.length)
    ? 'correct'
    : shared ? 'partial' : '';
  // The deepest level is the informative one; the superfamily is usually
  // the part they can already guess from the Function column.
  return { state, label: g[g.length - 1] };
}

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
    const fam = familySignal(guess, state.target);
    subject.innerHTML =
      `<div class="cell subject">
         <span class="subject-gene">${escapeHtml(guess.g)}</span>
         <span class="subject-name">${escapeHtml(guess.n)}</span>` +
      (fam
        ? `<span class="subject-family ${fam.state}"
                 title="${escapeHtml(guess.fam)}">${escapeHtml(fam.label)}</span>`
        : '') +
      `</div>`;
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
  // Free play has no guess limit, and a forty-row grid is not a result
  // anybody reads — it is a wall. Keep the opening two rows and the last
  // eight, which is the shape of the round: where you started and how you
  // closed it.
  const rows = state.guesses
    .map((g) => compare(g, state.target).map((r) => squares[r.state]).join(''));
  const MAX_ROWS = 10;
  const shown = rows.length > MAX_ROWS
    ? [...rows.slice(0, 2), `⋯ ${rows.length - MAX_ROWS} more`,
       ...rows.slice(-8)]
    : rows;
  return `${head} ${score}\n\n${shown.join('\n')}\n\nproteindle.github.io`;
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

  // Coalesced, not throttled: the list still updates on the very next
  // frame after you stop, but a fast typist gets one search instead of one
  // per key. Over 20,000 proteins on a low-end phone that is the whole
  // difference between a responsive box and a stuttering one.
  let searchTimer = null;
  el.input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => showSuggestions(el.input.value), 70);
  });

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
        else flashHint(noMatchMessage());
      }
    }
  });

  el.input.addEventListener('blur', () => setTimeout(hideSuggestions, 120));

  el.guessBtn.addEventListener('click', () => {
    const hits = search(el.input.value, 1);
    if (hits.length) submitGuess(hits[0].p);
    else flashHint(noMatchMessage());
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
