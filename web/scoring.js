/* -------------------------------------------------------------------
   Proteindle scoring — the single definition of what a guess tells you.

   Loaded as a plain <script> by the game and require()d by the Node-side
   cross-check test. pipeline/scoring.py mirrors it exactly, and
   pipeline/test_scoring.py runs both over random pairs and asserts they
   agree — because the simulator's conclusions about game difficulty are
   worthless if it scores differently from the game itself.

   Every comparison returns {state, arrow}:
     state — 'correct' | 'partial' | 'wrong'
     arrow — '↑' (answer is higher) | '↓' (lower) | null
   ------------------------------------------------------------------- */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ProteindleScoring = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Sex chromosomes and the mitochondrial genome sort after the autosomes
  // so the up/down arrow stays meaningful across the whole karyotype.
  function chromOrder(c) {
    if (c === null || c === undefined || c === '') return null;
    if (c === 'X') return 23;
    if (c === 'Y') return 24;
    if (c === 'MT') return 25;
    const n = parseInt(c, 10);
    return Number.isNaN(n) ? null : n;
  }

  function cmpNumeric(guessVal, targetVal, closeFraction) {
    if (guessVal === null || guessVal === undefined ||
        targetVal === null || targetVal === undefined) {
      return { state: 'wrong', arrow: null };
    }
    if (guessVal === targetVal) return { state: 'correct', arrow: null };
    const arrow = targetVal > guessVal ? '↑' : '↓';
    if (closeFraction) {
      const diff = Math.abs(targetVal - guessVal) / Math.max(targetVal, 1);
      if (diff <= closeFraction) return { state: 'partial', arrow: arrow };
    }
    return { state: 'wrong', arrow: arrow };
  }

  function cmpOrdinal(guessKey, targetKey, ladderRank) {
    const g = ladderRank[guessKey];
    const t = ladderRank[targetKey];
    if (g === undefined || t === undefined) {
      return { state: 'wrong', arrow: null };
    }
    if (g === t) return { state: 'correct', arrow: null };
    const arrow = t > g ? '↑' : '↓';
    // One rung apart is genuinely close on a seven-rung ladder.
    const near = Math.abs(t - g) === 1;
    return { state: near ? 'partial' : 'wrong', arrow: arrow };
  }

  function cmpSet(guessArr, targetArr) {
    const g = guessArr || [];
    const t = targetArr || [];
    if (g.length === 0 && t.length === 0) {
      return { state: 'correct', arrow: null };
    }
    const ts = new Set(t);
    if (g.length === t.length && g.every(function (v) { return ts.has(v); })) {
      return { state: 'correct', arrow: null };
    }
    const overlap = g.some(function (v) { return ts.has(v); });
    return { state: overlap ? 'partial' : 'wrong', arrow: null };
  }

  function cmpExact(guessVal, targetVal) {
    return {
      state: guessVal === targetVal ? 'correct' : 'wrong',
      arrow: null,
    };
  }

  // Exact class is green; a different class in the same family is amber.
  // "Kinase" against "Protease" both being enzymes is a real, useful hint.
  function cmpGrouped(guessVal, targetVal, groups) {
    if (guessVal === targetVal) return { state: 'correct', arrow: null };
    const g = groups[guessVal];
    const t = groups[targetVal];
    if (g !== undefined && g === t) return { state: 'partial', arrow: null };
    return { state: 'wrong', arrow: null };
  }

  // Column order here is the column order on the board.
  const COLUMNS = ['len', 'con', 'loc', 'fn', 'pw', 'chr', 'dis'];

  // Length tolerance. Proteins vary over three orders of magnitude, so a
  // proportional band reads better than an absolute one: 10% of a 100 aa
  // peptide is 10 aa, 10% of a 2000 aa monster is 200.
  const LENGTH_CLOSE = 0.10;

  /* `meta` carries the lookup tables the rules need: {ladderRank,
     functionGroups}. Both are emitted into proteins.json at build time so
     the rules here stay data-driven rather than hard-coding biology. */
  function compare(guess, target, meta) {
    const ladderRank = (meta && meta.ladderRank) || {};
    const groups = (meta && meta.functionGroups) || {};
    return [
      cmpNumeric(guess.len, target.len, LENGTH_CLOSE),
      cmpOrdinal(guess.con, target.con, ladderRank),
      cmpSet(guess.loc, target.loc),
      cmpGrouped(guess.fn, target.fn, groups),
      cmpSet(guess.pw, target.pw),
      cmpNumeric(chromOrder(guess.chr), chromOrder(target.chr), 0),
      cmpExact(guess.dis, target.dis),
    ];
  }

  /* A compact, comparable signature of one guess's feedback. Two answers
     that produce the same signature are indistinguishable to the player
     after that guess — which is exactly what the solver needs to prune
     candidates, and what the entropy report needs to count. */
  function signature(guess, target, meta) {
    return compare(guess, target, meta)
      .map(function (r) { return r.state + (r.arrow || ''); })
      .join('|');
  }

  return {
    chromOrder: chromOrder,
    cmpNumeric: cmpNumeric,
    cmpOrdinal: cmpOrdinal,
    cmpSet: cmpSet,
    cmpExact: cmpExact,
    cmpGrouped: cmpGrouped,
    compare: compare,
    signature: signature,
    COLUMNS: COLUMNS,
    LENGTH_CLOSE: LENGTH_CLOSE,
  };
}));
