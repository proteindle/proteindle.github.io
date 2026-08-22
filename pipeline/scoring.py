"""
Python mirror of web/scoring.js.

Kept in lockstep by pipeline/test_scoring.py, which runs both over random
protein pairs and asserts identical output. If you change one, change the
other and run that test — the simulator's verdict on game difficulty is
only meaningful if it scores exactly the way the game does.
"""

CORRECT, PARTIAL, WRONG = "correct", "partial", "wrong"
UP, DOWN = "↑", "↓"

COLUMNS = ["len", "con", "loc", "fn", "pw", "chr", "dis"]
COLUMN_LABELS = ["Length", "Conservation", "Localization", "Function",
                 "Pathway", "Chromosome", "Disease"]
LENGTH_CLOSE = 0.10


def chrom_order(c):
    """Autosomes 1-22, then X, Y, MT, so the arrow spans the karyotype."""
    if c is None or c == "":
        return None
    if c == "X":
        return 23
    if c == "Y":
        return 24
    if c == "MT":
        return 25
    try:
        return int(c)
    except (TypeError, ValueError):
        return None


def cmp_numeric(g, t, close_fraction):
    if g is None or t is None:
        return (WRONG, None)
    if g == t:
        return (CORRECT, None)
    arrow = UP if t > g else DOWN
    if close_fraction:
        if abs(t - g) / max(t, 1) <= close_fraction:
            return (PARTIAL, arrow)
    return (WRONG, arrow)


def cmp_ordinal(g_key, t_key, ladder_rank):
    g = ladder_rank.get(g_key)
    t = ladder_rank.get(t_key)
    if g is None or t is None:
        return (WRONG, None)
    if g == t:
        return (CORRECT, None)
    arrow = UP if t > g else DOWN
    return (PARTIAL if abs(t - g) == 1 else WRONG, arrow)


def cmp_set(g_arr, t_arr):
    g = list(g_arr or [])
    t = list(t_arr or [])
    if not g and not t:
        return (CORRECT, None)
    ts = set(t)
    if len(g) == len(t) and all(v in ts for v in g):
        return (CORRECT, None)
    return (PARTIAL if any(v in ts for v in g) else WRONG, None)


def cmp_exact(g, t):
    return (CORRECT if g == t else WRONG, None)


def cmp_grouped(g, t, groups):
    """Exact class green; a sibling class in the same family amber."""
    if g == t:
        return (CORRECT, None)
    gg = groups.get(g)
    if gg is not None and gg == groups.get(t):
        return (PARTIAL, None)
    return (WRONG, None)


def compare(guess, target, meta):
    """
    Seven (state, arrow) pairs, in board order.

    `meta` holds the lookup tables: {"ladderRank": ..., "functionGroups":
    ...}, both emitted into proteins.json at build time.
    """
    ladder_rank = meta.get("ladderRank", {})
    groups = meta.get("functionGroups", {})
    return [
        cmp_numeric(guess.get("len"), target.get("len"), LENGTH_CLOSE),
        cmp_ordinal(guess.get("con"), target.get("con"), ladder_rank),
        cmp_set(guess.get("loc"), target.get("loc")),
        cmp_grouped(guess.get("fn"), target.get("fn"), groups),
        cmp_set(guess.get("pw"), target.get("pw")),
        cmp_numeric(chrom_order(guess.get("chr")),
                    chrom_order(target.get("chr")), 0),
        cmp_exact(guess.get("dis"), target.get("dis")),
    ]


def signature(guess, target, meta):
    """
    A hashable summary of one guess's feedback. Two candidate answers with
    the same signature are indistinguishable to the player after that
    guess, which is what makes this the right key for pruning.
    """
    return "|".join(s + (a or "")
                    for s, a in compare(guess, target, meta))


def meta_from(data):
    """Build the lookup tables the rules need from a loaded proteins.json."""
    return {
        "ladderRank": {r["key"]: r["rank"] for r in data["ladder"]},
        "functionGroups": data.get("functionGroups", {}),
    }
