/* -------------------------------------------------------------------
   Proteindle — Browse and Train

   Two things the game itself is not: a table you can read, and a drill
   you can keep coming back to. Both run off the database app.js has
   already loaded; nothing here fetches anything.

   Scheduling is Leitner, not SM-2. Five boxes, fixed intervals, and a
   miss drops you to box 1. The appeal over a proper ease-factor
   algorithm is that a person can see why a card came back, which matters
   for an audience that will reasonably want to know.

   One scheduling decision worth stating: a card is a PROTEIN, not a
   protein-column pair. Asking "TP53 — function?" and "TP53 —
   chromosome?" as separate cards would multiply the deck by the number
   of enabled columns and make a 200-protein deck feel like 1,400. The
   column is picked fresh each time the protein comes up, so a protein
   you truly know has to survive questions from several angles.
   ------------------------------------------------------------------- */

'use strict';

(function () {

const $ = (id) => document.getElementById(id);

/* Leitner. Index is the box (1-based); value is days until it is due
   again. A new card is due immediately; a missed card returns to box 1. */
const BOXES = [0, 1, 3, 7, 21, 60];
const DAY_MS = 86400000;

const SET_KEY = 'proteindle:study:settings';
const DECK_KEY = 'proteindle:study:deck';
const STREAK_KEY = 'proteindle:study:streak';
const srsKey = (id) => `proteindle:study:srs:${id}`;

const PAGE = 100;          // browse rows per chunk

/* THE PLAYABILITY RULE, inherited from Bio Grid, where it is stated as:
   a criterion earns its place only if a working biologist, asked "name a
   protein that is X", could answer from memory — not "could look it up".
   Inverted for flashcards: an attribute earns its place only if someone
   shown the protein could RECALL the answer, or reason to it from what
   the protein does.

   Chromosome and length fail that outright and are gone. Nobody knows
   what sits on chromosome 12, or which side of 800 aa a protein falls;
   those cards were lookups wearing a quiz costume, and worse than
   useless in spaced repetition because a card you cannot reason about
   trains nothing and still eats a slot. Bio Grid cut eleven chromosome
   criteria and two length criteria for the same reason, and has a test
   so they cannot come back. So does this — see smoke_study.py.

   `closed`  a small, known value set, so multiple choice is possible.
   `ask`     may be the subject of a question.
   `clue`    may appear as a clue in the attributes-to-protein direction.

   The two are not the same. "Disease-linked: yes" is a fair clue and a
   terrible question — a coin flip that most famous proteins answer yes
   to, so it would climb the Leitner boxes on guesswork alone. The named
   disease is the opposite: a real question, and a clue that would simply
   hand over the answer. */
const COLUMNS = [
  { key: 'fn',   label: 'Function',       closed: true,  ask: true,  clue: true,
    q: 'What kind of protein is it?' },
  { key: 'loc',  label: 'Localization',   closed: false, ask: true,  clue: true,
    q: 'Where in the cell is it?' },
  { key: 'pw',   label: 'Pathway',        closed: false, ask: true,  clue: true,
    q: 'Which pathway does it work in?' },
  // Ask-only, and for the same reason as the named disease: the family
  // string usually contains the answer. "Cytochrome P450 family" against
  // CYP2C19 / IL6 / MTHFR / FASLG is not a question, and neither is
  // "IL-1 family" against IL1B. It is a good thing to be asked and a
  // useless thing to be told.
  { key: 'fam',  label: 'Family',         closed: false, ask: true,  clue: false,
    q: 'Which protein family?' },
  { key: 'con',  label: 'Conservation',   closed: true,  ask: true,  clue: true,
    q: 'How deeply conserved is it?' },
  { key: 'disn', label: 'Disease',        closed: false, ask: true,  clue: false,
    q: 'Which disease is it linked to?' },
  { key: 'dis',  label: 'Disease-linked', closed: true,  ask: false, clue: true,
    q: '' },
];

const ASKABLE = COLUMNS.filter((c) => c.ask).map((c) => c.key);

/* Conservation, collapsed from the seven-rung ladder to the three
   buckets Bio Grid kept. The full ladder is right for the game, where it
   is a clue with an up/down arrow; as a question it is not recallable —
   "Opisthokonta or Eumetazoa?" is a lookup, while "is it also in
   bacteria, in yeast, or animals only?" is something you can reason to
   from what the protein does. Splits the answer pool 733 / 1,822 / 1,750,
   so no bucket is a giveaway. */
const CONSERVATION_BUCKETS = {
  universal:    'Also found in bacteria',
  ancient:      'Also found in bacteria',
  eukaryota:    'Also found in yeast',
  opisthokonta: 'Also found in yeast',
  eumetazoa:    'Animals only',
  vertebrata:   'Animals only',
  mammalia:     'Animals only',
};

const DIRECTIONS = [
  { key: 'p2a', label: 'Protein → attribute',
    note: 'TP53 — what is its function?' },
  { key: 'a2p', label: 'Attributes → protein',
    note: 'Transcription factor, nucleus, apoptosis — which protein?' },
  { key: 'g2n', label: 'Gene ↔ protein name',
    note: 'TP53 — what is the protein called?' },
];

/* v2 dropped the chromosome and length cards. A returning player has the
   old set in localStorage, and merging it forward would quietly resurrect
   them, so a stored config without the current version is discarded
   rather than migrated — there are four booleans in it, not a document. */
const SETTINGS_VERSION = 2;

const DEFAULTS = {
  v: SETTINGS_VERSION,
  cols: ASKABLE.slice(),
  dirs: ['p2a', 'a2p'],
  limit: 20,
  mc: true,
};

const S = {
  ready: false,
  all: [],
  view: 'play',
  browse: {
    rows: [], shown: 0,
    sort: { key: 'pap', dir: -1 },
  },
  deck: null,        // { id, label, accs: [] }
  srs: {},           // accession -> { b: box, d: due ms }
  settings: Object.assign({}, DEFAULTS),
  session: null,
  card: null,
};

/* ------------------------------------------------------------ helpers */

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {}
}

function load(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch (_) { return null; }
}

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-`
       + `${String(d.getDate()).padStart(2, '0')}`;
}

function shuffle(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function sample(arr, n, exclude) {
  const pool = arr.filter((x) => x !== exclude);
  shuffle(pool);
  return pool.slice(0, n);
}

const db = () => window.Proteindle && window.Proteindle.state;
const ladderLabel = (k) => (db() && db().ladderLabel[k]) || k || '—';

/* The display value for a column, as a string a person can read. */
function valueOf(p, key) {
  switch (key) {
    case 'loc':  return (p.loc || []).join(' · ');
    case 'pw':   return (p.pw || []).join(' · ');
    case 'disn': return (p.disn || []).join(' · ');
    case 'dis':  return p.dis ? 'Yes' : 'No';
    case 'con':  return CONSERVATION_BUCKETS[p.con] || ladderLabel(p.con);
    default:     return p[key] || '—';
  }
}

function hasValue(p, key) {
  if (key === 'dis') return typeof p.dis === 'boolean';
  if (key === 'con') return !!CONSERVATION_BUCKETS[p.con];
  if (key === 'loc' || key === 'pw' || key === 'disn') {
    return (p[key] || []).length > 0;
  }
  return !!p[key];
}

/* ------------------------------------------------------------- boot */

function boot() {
  const st = db();
  if (!st || S.ready) return;     // the event and the fallback can both fire
  S.all = Array.from(st.byAccession.values());
  S.ready = true;

  const saved = load(SET_KEY);
  if (saved && saved.v === SETTINGS_VERSION) {
    S.settings = Object.assign({}, DEFAULTS, saved);
    // Belt and braces: even a correctly-versioned config is filtered, so
    // a hand-edited localStorage cannot reintroduce a cut column.
    S.settings.cols = S.settings.cols.filter((k) => ASKABLE.includes(k));
    if (!S.settings.cols.length) S.settings.cols = DEFAULTS.cols.slice();
  }

  buildFilterOptions();
  buildSettingsUI();
  wire();
  applyFilters();

  const lastDeck = load(DECK_KEY);
  if (lastDeck && lastDeck.accs && lastDeck.accs.length) setDeck(lastDeck, false);
  renderTrainStats();
}

/* The remaining 15,859 arrive a moment after first paint. Browse is the
   only thing that cares — a table claiming 4,331 proteins when the
   database holds 20,190 would be a quiet lie. */
function onRest() {
  const st = db();
  if (!st) return;
  S.all = Array.from(st.byAccession.values());
  buildFilterOptions();
  applyFilters();
}

/* -------------------------------------------------------- view switch */

function setView(view) {
  S.view = view;
  document.querySelectorAll('#views .view-btn').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.view === view);
    b.setAttribute('aria-selected', b.dataset.view === view ? 'true' : 'false');
  });
  $('view-play').hidden = view !== 'play';
  $('view-browse').hidden = view !== 'browse';
  $('view-train').hidden = view !== 'train';
  // The field chip and the Daily/Free play/Hard tabs belong to the game.
  $('play-chrome').hidden = view !== 'play';
  // Ten columns do not fit the 60rem the game is laid out in.
  document.body.classList.toggle('wide', view === 'browse');
  if (view === 'train') renderTrain();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ------------------------------------------------------------ browse */

function buildFilterOptions() {
  const st = db();
  if (!st || !st.db) return;

  const fill = (id, items, keep) => {
    const sel = $(id);
    if (!sel) return;
    const cur = keep === undefined ? sel.value : keep;
    sel.innerHTML = '<option value="">Any</option>'
      + items.map((it) => `<option value="${esc(it.value)}">`
          + `${esc(it.label)}</option>`).join('');
    sel.value = cur;
  };

  const groups = st.db.functionGroups || {};
  fill('bf-fn', Object.keys(groups).sort().map((k) => ({ value: k, label: k })));

  fill('bf-con', (st.db.ladder || []).map((r) => ({
    value: r.key, label: r.label,
  })));

  const locs = new Set();
  S.all.forEach((p) => (p.loc || []).forEach((l) => locs.add(l)));
  fill('bf-loc', Array.from(locs).sort().map((l) => ({ value: l, label: l })));

  fill('bf-fld', (st.db.fields || []).map((f) => ({
    value: f.key, label: f.label,
  })));

  const chrs = new Set();
  S.all.forEach((p) => { if (p.chr) chrs.add(p.chr); });
  const order = (c) => (/^\d+$/.test(c) ? +c : 100 + c.charCodeAt(0));
  fill('bf-chr', Array.from(chrs).sort((a, b) => order(a) - order(b))
    .map((c) => ({ value: c, label: c })));
}

function currentFilters() {
  return {
    q:    ($('bf-q').value || '').trim().toLowerCase(),
    fn:   $('bf-fn').value,
    con:  $('bf-con').value,
    loc:  $('bf-loc').value,
    fld:  $('bf-fld').value,
    chr:  $('bf-chr').value,
    dis:  $('bf-dis').value,
    tier: $('bf-tier').value,
  };
}

function matches(p, f) {
  if (f.fn && p.fn !== f.fn) return false;
  if (f.con && p.con !== f.con) return false;
  if (f.chr && p.chr !== f.chr) return false;
  if (f.loc && !(p.loc || []).includes(f.loc)) return false;
  if (f.fld && !(p.fld || []).includes(f.fld)) return false;
  if (f.dis === 'yes' && !p.dis) return false;
  if (f.dis === 'no' && p.dis) return false;
  if (f.tier === 'answers' && !p.t) return false;
  if (f.tier === 'daily' && p.t !== 'daily') return false;
  if (f.q) {
    const hay = `${p.g} ${p.n} ${(p.s || []).join(' ')} ${p.d || ''}`
      .toLowerCase();
    if (!hay.includes(f.q)) return false;
  }
  return true;
}

function applyFilters() {
  if (!S.ready) return;
  const f = currentFilters();
  S.browse.rows = S.all.filter((p) => matches(p, f));
  sortRows();
  S.browse.shown = 0;
  $('browse-body').innerHTML = '';
  renderMore();
  renderBrowseCount();
}

function sortRows() {
  const { key, dir } = S.browse.sort;
  const val = (p) => {
    if (key === 'loc' || key === 'pw') return (p[key] || []).join(' ');
    if (key === 'chr') {
      const c = p.chr || '';
      return /^\d+$/.test(c) ? +c : 100 + (c.charCodeAt(0) || 0);
    }
    if (key === 'dis') return p.dis ? 1 : 0;
    if (key === 'con') {
      return (db() && db().ladderRank[p.con]) || 0;
    }
    return p[key] == null ? '' : p[key];
  };
  S.browse.rows.sort((a, b) => {
    const x = val(a), y = val(b);
    if (x === y) return (a.g || '').localeCompare(b.g || '');
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y)) * dir;
  });
  document.querySelectorAll('#browse-head th').forEach((th) => {
    th.classList.toggle('sorted', th.dataset.sort === key);
    th.classList.toggle('desc', th.dataset.sort === key && dir === -1);
  });
}

/* 20,190 rows will not go in the DOM. A chunk at a time, which also
   means the first paint is immediate however wide the filter is. */
function renderMore() {
  const rows = S.browse.rows;
  const end = Math.min(S.browse.shown + PAGE, rows.length);
  const html = [];
  for (let i = S.browse.shown; i < end; i++) {
    const p = rows[i];
    html.push(
      `<tr><th scope="row" class="b-gene">`
      + `<a href="https://www.uniprot.org/uniprotkb/${esc(p.a)}" `
      + `target="_blank" rel="noopener">${esc(p.g)}</a></th>`
      + `<td class="b-name">${esc(p.n)}</td>`
      + `<td class="num">${p.len == null ? '—' : p.len}</td>`
      + `<td>${esc(ladderLabel(p.con))}</td>`
      + `<td>${esc((p.loc || []).join(' · ')) || '—'}</td>`
      + `<td>${esc(p.fn || '—')}</td>`
      + `<td>${esc((p.pw || []).join(' · ')) || '—'}</td>`
      + `<td class="num">${esc(p.chr || '—')}</td>`
      + `<td>${p.dis ? 'Yes' : 'No'}</td>`
      + `<td class="num">${p.pap == null ? '—' : p.pap.toLocaleString()}</td>`
      + `</tr>`);
  }
  $('browse-body').insertAdjacentHTML('beforeend', html.join(''));
  S.browse.shown = end;
  $('browse-more').hidden = end >= rows.length;
  renderBrowseCount();
}

function renderBrowseCount() {
  const n = S.browse.rows.length;
  const total = S.all.length;
  const loading = window.Proteindle && !window.Proteindle.restReady();
  $('browse-count').textContent =
    `${n.toLocaleString()} protein${n === 1 ? '' : 's'}`
    + (n < total ? ` of ${total.toLocaleString()}` : '')
    + (S.browse.shown < n ? ` — showing ${S.browse.shown.toLocaleString()}` : '')
    + (loading ? ' · still loading the rest…' : '');
  $('browse-study').disabled = n === 0;
}

function downloadCsv() {
  const head = ['gene', 'protein', 'accession', 'length_aa', 'conservation',
                'localization', 'function', 'pathway', 'chromosome',
                'disease_linked', 'papers'];
  const q = (v) => `"${String(v == null ? '' : v).replace(/"/g, '""')}"`;
  const lines = [head.join(',')];
  S.browse.rows.forEach((p) => lines.push([
    p.g, p.n, p.a, p.len, ladderLabel(p.con), (p.loc || []).join('; '),
    p.fn, (p.pw || []).join('; '), p.chr, p.dis ? 'yes' : 'no', p.pap,
  ].map(q).join(',')));
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'proteindle-selection.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function filterLabel() {
  const f = currentFilters();
  const bits = [];
  if (f.fn) bits.push(f.fn);
  if (f.con) bits.push(ladderLabel(f.con));
  if (f.loc) bits.push(f.loc);
  if (f.chr) bits.push(`chr ${f.chr}`);
  if (f.dis === 'yes') bits.push('disease-linked');
  if (f.dis === 'no') bits.push('not disease-linked');
  if (f.fld) {
    const fld = ((db().db.fields) || []).find((x) => x.key === f.fld);
    if (fld) bits.push(fld.label);
  }
  if (f.q) bits.push(`“${f.q}”`);
  if (f.tier === 'daily') bits.push('daily pool');
  if (f.tier === 'answers') bits.push('answerable');
  return bits.length ? bits.join(', ') : 'All proteins';
}

/* -------------------------------------------------------------- decks */

function presetDecks() {
  const st = db();
  const out = [];

  out.push({ group: 'Best known', decks: [50, 100, 250, 500].map((n) => ({
    id: `top${n}`, label: `Top ${n} by papers`,
    accs: S.all.filter((p) => p.rank).sort((a, b) => a.rank - b.rank)
      .slice(0, n).map((p) => p.a),
  })) });

  const byFn = new Map();
  S.all.forEach((p) => {
    if (!p.t || !p.fn) return;          // answerable proteins only
    if (!byFn.has(p.fn)) byFn.set(p.fn, []);
    byFn.get(p.fn).push(p.a);
  });
  out.push({ group: 'By function', decks: Array.from(byFn.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([fn, accs]) => ({ id: `fn:${fn}`, label: fn, accs })) });

  const fields = (st.db && st.db.fields) || [];
  out.push({ group: 'By field', decks: fields.map((f) => ({
    id: `fld:${f.key}`, label: f.label,
    accs: S.all.filter((p) => (p.fld || []).includes(f.key)).map((p) => p.a),
  })).filter((d) => d.accs.length >= 10) });

  return out;
}

function buildDeckPicker() {
  const html = presetDecks().map((g) => {
    if (!g.decks.length) return '';
    return `<section class="deck-group"><h3>${esc(g.group)}</h3>`
      + `<div class="deck-grid">`
      + g.decks.map((d) => {
          const due = dueCount(d.id, d.accs);
          return `<button class="deck-option" data-deck="${esc(d.id)}">`
            + `<span class="deck-label">${esc(d.label)}</span>`
            + `<span class="deck-size">${d.accs.length} cards`
            + (due ? ` · <strong>${due} due</strong>` : ' · none due')
            + `</span></button>`;
        }).join('')
      + `</div></section>`;
  }).join('');
  $('deck-groups').innerHTML =
    `<section class="deck-group"><h3>From Browse</h3>`
    + `<div class="deck-grid"><button class="deck-option" data-deck="__filter">`
    + `<span class="deck-label">Current browse filter</span>`
    + `<span class="deck-size">${S.browse.rows.length} proteins — `
    + `${esc(filterLabel())}</span></button></div></section>`
    + html;
}

function deckById(id) {
  if (id === '__filter') {
    return {
      id: `filter:${filterLabel()}`,
      label: filterLabel(),
      accs: S.browse.rows.map((p) => p.a),
    };
  }
  for (const g of presetDecks()) {
    const d = g.decks.find((x) => x.id === id);
    if (d) return d;
  }
  return null;
}

function setDeck(deck, persist = true) {
  S.deck = deck;
  S.srs = load(srsKey(deck.id)) || {};
  S.session = null;
  if (persist) save(DECK_KEY, deck);
  $('deck-name').textContent = deck.label;
  renderTrain();
}

/* ---------------------------------------------------------------- srs */

function dueCount(deckId, accs) {
  const srs = load(srsKey(deckId)) || {};
  const now = Date.now();
  return accs.filter((a) => !srs[a] || srs[a].d <= now).length;
}

function dueNow() {
  if (!S.deck) return [];
  const now = Date.now();
  return S.deck.accs.filter((a) => !S.srs[a] || S.srs[a].d <= now);
}

function grade(acc, ok) {
  const cur = S.srs[acc] || { b: 0, d: 0 };
  const box = ok ? Math.min(cur.b + 1, BOXES.length - 1) : 1;
  S.srs[acc] = { b: box, d: Date.now() + BOXES[box] * DAY_MS };
  save(srsKey(S.deck.id), S.srs);
}

function bumpStreak() {
  const s = load(STREAK_KEY) || { last: null, n: 0, best: 0 };
  const t = today();
  if (s.last === t) return s;
  const y = new Date(Date.now() - DAY_MS);
  const yst = `${y.getFullYear()}-${String(y.getMonth() + 1).padStart(2, '0')}-`
            + `${String(y.getDate()).padStart(2, '0')}`;
  s.n = s.last === yst ? s.n + 1 : 1;
  s.last = t;
  s.best = Math.max(s.best || 0, s.n);
  save(STREAK_KEY, s);
  return s;
}

/* -------------------------------------------------------------- train */

function renderTrainStats() {
  const s = load(STREAK_KEY) || { n: 0, best: 0 };
  const bits = [];
  if (S.deck) {
    const due = dueNow().length;
    bits.push(`<span><strong>${due}</strong> due</span>`);
    bits.push(`<span>${S.deck.accs.length} in deck</span>`);
  }
  bits.push(`<span title="Consecutive days studied">🔥 `
    + `<strong>${s.n || 0}</strong> day streak</span>`);
  if (S.session && S.session.run > 1) {
    bits.push(`<span>${S.session.run} in a row</span>`);
  }
  $('train-stats').innerHTML = bits.join('');
}

function renderTrain() {
  renderTrainStats();
  if (!S.deck) {
    $('train-empty').hidden = false;
    $('card').hidden = true;
    $('train-done').hidden = true;
    return;
  }
  $('train-empty').hidden = true;
  if (!S.session) startSession();
  else nextCard();
}

function startSession(force) {
  const due = force ? S.deck.accs.slice() : dueNow();
  if (!due.length) {
    S.session = null;
    $('card').hidden = true;
    $('train-done').hidden = false;
    const next = nextDueText();
    $('done-text').textContent =
      `Nothing due in “${S.deck.label}” right now. ${next}`;
    return;
  }
  shuffle(due);
  const limit = S.settings.limit || due.length;
  S.session = {
    queue: due.slice(0, limit || due.length),
    done: 0, right: 0, run: 0, best: 0, total: 0,
  };
  S.session.total = S.session.queue.length;
  $('train-done').hidden = true;
  nextCard();
}

function nextDueText() {
  if (!S.deck) return '';
  const times = S.deck.accs.map((a) => (S.srs[a] ? S.srs[a].d : 0))
    .filter((d) => d > Date.now());
  if (!times.length) return '';
  const soonest = Math.min.apply(null, times);
  const days = Math.max(1, Math.round((soonest - Date.now()) / DAY_MS));
  return `Next card is due in ${days} day${days === 1 ? '' : 's'}.`;
}

function askableColumns(p) {
  return COLUMNS.filter((c) => c.ask && S.settings.cols.includes(c.key)
                            && hasValue(p, c.key));
}

/* Clues for the attributes-to-protein direction. A different list: the
   named disease is ask-only because it would hand over the answer, and
   the disease yes/no is clue-only because as a question it is a coin
   flip. Not filtered by settings — turning off a card type should not
   also strip the board the other direction reasons from. */
function clueColumns(p) {
  return COLUMNS.filter((c) => c.clue && hasValue(p, c.key));
}

function buildCard() {
  const sess = S.session;
  if (!sess || !sess.queue.length) return null;
  const acc = sess.queue[0];
  const p = db().byAccession.get(acc);
  if (!p) { sess.queue.shift(); return buildCard(); }

  const dirs = S.settings.dirs.filter((d) => {
    if (d === 'g2n') return !!p.n;
    if (d === 'p2a') return askableColumns(p).length > 0;
    if (d === 'a2p') return clueColumns(p).length > 0;
    return false;
  });
  if (!dirs.length) { sess.queue.shift(); return buildCard(); }
  const dir = dirs[Math.floor(Math.random() * dirs.length)];

  if (dir === 'g2n') {
    return {
      p, dir, kicker: 'Name the protein',
      prompt: p.g, sub: p.d ? esc(p.d) : '',
      answer: p.n, choices: null,
    };
  }

  if (dir === 'a2p') {
    // Attributes in, protein out.
    //
    // Which clues to show is the whole difficulty of this direction. A
    // deck built by filtering Browse to Function = Chromatin has the same
    // function for every card, so leading with "Function: Chromatin" tells
    // the player nothing and wastes the most prominent line. Columns are
    // therefore ranked by how FEW deck members share the target's value,
    // and the most discriminating ones are shown.
    const members = S.deck.accs.map((a) => db().byAccession.get(a))
      .filter(Boolean);
    const shareCount = (c) => members.reduce((n, q) =>
      n + (hasValue(q, c.key) && valueOf(q, c.key) === valueOf(p, c.key)
           ? 1 : 0), 0);
    const ranked = clueColumns(p)
      .map((c) => ({ c, share: shareCount(c) }))
      .sort((a, b) => a.share - b.share);
    // Anything every single card shares is pure noise; drop it unless
    // dropping it would leave nothing to go on.
    const useful = ranked.filter((r) => r.share < members.length);
    const cols = (useful.length ? useful : ranked).slice(0, 4).map((r) => r.c);
    const clues = cols.map((c) =>
      `<span class="clue"><span class="clue-k">${esc(c.label)}</span>`
      + `<span class="clue-v">${esc(valueOf(p, c.key))}</span></span>`).join('');

    // A distractor has to be distinguishable from the answer on at least
    // one clue shown, or the question has more than one right answer.
    const differs = (q) => cols.some((c) =>
      !hasValue(q, c.key) || valueOf(q, c.key) !== valueOf(p, c.key));
    let pool = members.filter((q) => q.a !== p.a && differs(q));
    if (pool.length < 3) pool = members.filter((q) => q.a !== p.a);
    const opts = shuffle(sample(pool, 3).concat([p]));
    return {
      p, dir, kicker: 'Which protein?',
      prompt: '', sub: '', clues,
      answer: `${p.g} — ${p.n}`,
      choices: opts.map((q) => ({ label: q.g, sub: q.n, ok: q.a === p.a })),
    };
  }

  // Protein -> attribute
  const cols = askableColumns(p);
  const col = cols[Math.floor(Math.random() * cols.length)];
  const answer = valueOf(p, col.key);
  let choices = null;

  if (S.settings.mc && col.closed) {
    const values = new Set();
    S.deck.accs.forEach((a) => {
      const q = db().byAccession.get(a);
      if (q && hasValue(q, col.key)) values.add(valueOf(q, col.key));
    });
    values.delete(answer);
    let others;
    if (col.key === 'fn') {
      // Distractors from the same amber family first. The game already
      // groups Kinase/Protease/Phosphatase as "Enzyme" and
      // Receptor/Signalling/Immune as "Signalling"; reusing that here
      // turns "Protease / Phosphatase / Ion channel / Signalling" —
      // where the answer is the only plausible one — into a choice
      // between four things it could actually be. A near miss is where
      // the learning is.
      const groups = (db().db && db().db.functionGroups) || {};
      const near = Array.from(values).filter(
        (v) => groups[v] && groups[v] === groups[answer]);
      const far = Array.from(values).filter((v) => near.indexOf(v) === -1);
      others = sample(near, 3);
      if (others.length < 3) {
        others = others.concat(sample(far, 3 - others.length));
      }
    } else {
      others = sample(Array.from(values), 3);
    }
    // A deck can be too uniform to supply distractors — every protein in
    // a "Kinase" deck has the same function. Fall back to the whole
    // proteome rather than showing a question with one option.
    if (others.length < 3) {
      const wide = new Set();
      for (const q of S.all) {
        if (hasValue(q, col.key)) wide.add(valueOf(q, col.key));
        if (wide.size > 60) break;
      }
      wide.delete(answer);
      others = sample(Array.from(wide), 3);
    }
    if (others.length) {
      choices = shuffle(others.map((v) => ({ label: v, ok: false }))
        .concat([{ label: answer, ok: true }]));
    }
  }

  return {
    p, dir, kicker: p.g,
    prompt: col.q,
    sub: esc(p.n), answer, choices, col,
  };
}

function nextCard() {
  if (!S.session) { startSession(); return; }
  if (!S.session.queue.length) {
    finishSession();
    return;
  }
  const card = buildCard();
  if (!card) { finishSession(); return; }
  S.card = card;
  renderCard(card);
}

function renderCard(card) {
  $('train-done').hidden = true;
  $('card').hidden = false;
  $('card-kicker').textContent = card.kicker;
  $('card-prompt').innerHTML = card.clues
    ? `<span class="clues">${card.clues}</span>`
    : esc(card.prompt);
  $('card-sub').innerHTML = card.sub || '';
  $('card-sub').hidden = !card.sub;
  $('card-feedback').hidden = true;
  $('card-next-wrap').hidden = true;

  const choices = $('card-choices');
  const flip = $('card-flip');
  if (card.choices) {
    choices.hidden = false;
    flip.hidden = true;
    // Numbered A-to-D style badges. They read as a quiz rather than as
    // four anonymous buttons, and they double as the label for the 1-4
    // keyboard shortcuts, which were already wired but invisible.
    choices.innerHTML = card.choices.map((c, i) =>
      `<button class="choice" data-i="${i}">`
      + `<span class="choice-key" aria-hidden="true">${i + 1}</span>`
      + `<span class="choice-body">`
      + `<span class="choice-label">${esc(c.label)}</span>`
      + (c.sub ? `<span class="choice-sub">${esc(c.sub)}</span>` : '')
      + `</span></button>`).join('');
  } else {
    // Emptied, not merely hidden. A hidden element still answers
    // querySelector and can still be clicked by script, and the old
    // buttons would then be read against a card that has no choices.
    choices.innerHTML = '';
    choices.hidden = true;
    flip.hidden = false;
    $('card-reveal').hidden = false;
    $('card-answer').hidden = true;
    $('card-answer').textContent = card.answer;
    $('card-grade').hidden = true;
  }

  const st = S.srs[card.p.a];
  const box = st ? st.b : 0;
  $('card-meta').textContent =
    `${S.session.done + 1} of ${S.session.total}`
    + (box ? ` · box ${box} of ${BOXES.length - 1}` : ' · new card')
    // Not always four: "Is it disease-linked?" has exactly two, and a
    // hint promising keys 1-4 there is simply wrong.
    + (card.choices ? ` · keys 1–${card.choices.length}` : '');
  renderTrainStats();
}

function answerCard(ok) {
  const card = S.card;
  grade(card.p.a, ok);
  bumpStreak();
  S.session.done++;
  S.session.queue.shift();
  if (ok) {
    S.session.right++;
    S.session.run++;
    S.session.best = Math.max(S.session.best, S.session.run);
  } else {
    S.session.run = 0;
    // A missed card comes back at the end of this session too, not only
    // in a day's time. Getting it wrong and never seeing it again is the
    // one thing a drill must not do.
    S.session.queue.push(card.p.a);
  }

  const fb = $('card-feedback');
  fb.hidden = false;
  fb.className = 'card-feedback ' + (ok ? 'good' : 'bad');
  fb.innerHTML = ok
    ? `Correct — <strong>${esc(card.answer)}</strong>`
    : `<strong>${esc(card.p.g)}</strong> — ${esc(card.answer)}`;
  $('card-next-wrap').hidden = false;
  $('card-next').focus();
  renderTrainStats();
}

function finishSession() {
  const s = S.session;
  $('card').hidden = true;
  $('train-done').hidden = false;
  const pct = s && s.done ? Math.round((s.right / s.done) * 100) : 0;
  $('done-text').textContent = s
    ? `${s.right} of ${s.done} right (${pct}%), best run ${s.best}. `
      + nextDueText()
    : `Nothing due in “${S.deck.label}”. ${nextDueText()}`;
  S.session = null;
  renderTrainStats();
}

/* ----------------------------------------------------------- settings */

function buildSettingsUI() {
  $('set-cols').innerHTML = COLUMNS.filter((c) => c.ask).map((c) =>
    `<label class="setting-check"><input type="checkbox" data-col="${c.key}"`
    + `${S.settings.cols.includes(c.key) ? ' checked' : ''}>`
    + `<span>${esc(c.label)}`
    + `<em>${esc(c.closed ? 'multiple choice' : 'self-graded')}</em>`
    + `</span></label>`).join('');
  $('set-dirs').innerHTML = DIRECTIONS.map((d) =>
    `<label class="setting-check"><input type="checkbox" data-dir="${d.key}"`
    + `${S.settings.dirs.includes(d.key) ? ' checked' : ''}>`
    + `<span>${esc(d.label)}<em>${esc(d.note)}</em></span></label>`).join('');
  $('set-limit').value = String(S.settings.limit);
  $('set-mc').checked = !!S.settings.mc;
}

function readSettings() {
  const cols = Array.from(document.querySelectorAll('#set-cols input:checked'))
    .map((i) => i.dataset.col);
  const dirs = Array.from(document.querySelectorAll('#set-dirs input:checked'))
    .map((i) => i.dataset.dir);
  // Both lists must keep at least one entry or no card can be built.
  S.settings.cols = cols.length ? cols : DEFAULTS.cols.slice();
  S.settings.dirs = dirs.length ? dirs : DEFAULTS.dirs.slice();
  S.settings.limit = parseInt($('set-limit').value, 10) || 0;
  S.settings.mc = $('set-mc').checked;
  S.settings.v = SETTINGS_VERSION;
  if (!cols.length || !dirs.length) buildSettingsUI();
  save(SET_KEY, S.settings);
}

/* -------------------------------------------------------------- wiring */

function wire() {
  const on = (node, ev, fn) => node && node.addEventListener(ev, fn);

  on($('views'), 'click', (e) => {
    const b = e.target.closest('.view-btn');
    if (b) setView(b.dataset.view);
  });

  // browse
  let t = null;
  on($('bf-q'), 'input', () => {
    clearTimeout(t);
    t = setTimeout(applyFilters, 150);
  });
  ['bf-fn', 'bf-con', 'bf-loc', 'bf-fld', 'bf-chr', 'bf-dis', 'bf-tier']
    .forEach((id) => on($(id), 'change', applyFilters));
  on($('bf-reset'), 'click', () => {
    ['bf-fn', 'bf-con', 'bf-loc', 'bf-fld', 'bf-chr', 'bf-dis', 'bf-tier']
      .forEach((id) => { $(id).value = ''; });
    $('bf-q').value = '';
    applyFilters();
  });
  on($('browse-more'), 'click', renderMore);
  on($('browse-csv'), 'click', downloadCsv);
  on($('browse-head'), 'click', (e) => {
    const th = e.target.closest('th[data-sort]');
    if (!th) return;
    const key = th.dataset.sort;
    S.browse.sort = {
      key,
      dir: S.browse.sort.key === key ? -S.browse.sort.dir
        : (key === 'pap' || key === 'len' ? -1 : 1),
    };
    sortRows();
    S.browse.shown = 0;
    $('browse-body').innerHTML = '';
    renderMore();
  });
  on($('browse-study'), 'click', () => {
    const d = deckById('__filter');
    if (!d.accs.length) return;
    setDeck(d);
    setView('train');
  });

  // deck picker
  on($('deck-btn'), 'click', () => {
    buildDeckPicker();
    $('deck-backdrop').hidden = false;
  });
  on($('deck-close'), 'click', () => { $('deck-backdrop').hidden = true; });
  on($('deck-backdrop'), 'click', (e) => {
    if (e.target === $('deck-backdrop')) $('deck-backdrop').hidden = true;
  });
  on($('deck-groups'), 'click', (e) => {
    const b = e.target.closest('.deck-option');
    if (!b) return;
    const d = deckById(b.dataset.deck);
    $('deck-backdrop').hidden = true;
    if (d && d.accs.length) setDeck(d);
  });
  on($('done-deck'), 'click', () => {
    buildDeckPicker();
    $('deck-backdrop').hidden = false;
  });
  on($('done-again'), 'click', () => startSession(true));

  // settings
  on($('train-settings-btn'), 'click', () => {
    $('settings-backdrop').hidden = false;
  });
  const closeSettings = () => {
    readSettings();
    $('settings-backdrop').hidden = true;
    if (S.deck) { S.session = null; renderTrain(); }
  };
  on($('settings-close'), 'click', closeSettings);
  on($('settings-done'), 'click', closeSettings);
  on($('settings-backdrop'), 'click', (e) => {
    if (e.target === $('settings-backdrop')) closeSettings();
  });
  on($('settings-reset'), 'click', () => {
    S.settings = Object.assign({}, DEFAULTS);
    save(SET_KEY, S.settings);
    buildSettingsUI();
  });

  // cards
  on($('card-choices'), 'click', (e) => {
    const b = e.target.closest('.choice');
    if (!b || $('card-choices').classList.contains('answered')) return;
    if (!S.card || !S.card.choices) return;
    const i = +b.dataset.i;
    const picked = S.card.choices[i];
    $('card-choices').classList.add('answered');
    Array.from($('card-choices').children).forEach((node, j) => {
      const right = S.card.choices[j].ok;
      node.classList.toggle('is-right', right);
      node.classList.toggle('is-wrong', j === i && !picked.ok);
      // The badge carries the verdict as a glyph, not only as a colour.
      // Same reason the game board does: red against green is the one
      // pair a colourblind player cannot read.
      const key = node.querySelector('.choice-key');
      if (right) key.textContent = '✓';
      else if (j === i) key.textContent = '✗';
    });
    answerCard(!!picked.ok);
  });
  on($('card-reveal'), 'click', () => {
    $('card-reveal').hidden = true;
    $('card-answer').hidden = false;
    $('card-grade').hidden = false;
  });
  on($('card-grade'), 'click', (e) => {
    const b = e.target.closest('[data-grade]');
    if (b) answerCard(b.dataset.grade === 'got');
  });
  on($('card-next'), 'click', () => {
    $('card-choices').classList.remove('answered');
    nextCard();
  });

  document.addEventListener('keydown', (e) => {
    if (S.view !== 'train' || $('card').hidden) return;
    if (!$('settings-backdrop').hidden || !$('deck-backdrop').hidden) return;
    if (e.key === 'Enter' && !$('card-next-wrap').hidden) {
      e.preventDefault(); $('card-next').click();
    } else if (e.key === ' ' && !$('card-reveal').hidden) {
      e.preventDefault(); $('card-reveal').click();
    } else if (/^[1-4]$/.test(e.key) && !$('card-choices').hidden) {
      const node = $('card-choices').children[+e.key - 1];
      if (node) node.click();
    }
  });
}

document.addEventListener('proteindle:ready', boot);
document.addEventListener('proteindle:rest', onRest);

/* The single-file build inlines the database, so app.js's init() never
   awaits anything and has already fired proteindle:ready by the time this
   file is parsed. Listening alone would wait for an event that has been
   and gone, and Browse would sit empty in exactly the build that is
   meant to work off a USB stick. */
if (window.Proteindle) {
  boot();
  if (window.Proteindle.restReady()) onRest();
}

})();
