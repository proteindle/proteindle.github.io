"""
Per-column diagnostics.

    python pipeline/entropy.py
    python pipeline/entropy.py --pairs 40000

Reports two different things, because they answer two different questions.

1. VALUE SPREAD — how the column's values are distributed across the pool.
   Reported as efficiency: entropy divided by the maximum a column with
   that many distinct values could carry. This matters because raw bits
   are not comparable across columns. A yes/no column tops out at exactly
   1 bit, so judging it against a 23-value chromosome column on raw bits
   is meaningless — the first version of this script did exactly that and
   flagged a near-perfect 62/38 binary split as "THIN".

2. FEEDBACK SPREAD — what the player actually learns. Over random
   (guess, answer) pairs, how often does the column come back green,
   amber, or red, and how many bits does that carry? A column can have a
   beautiful value spread and still be useless if every guess returns red.

The second is the one to tune on.
"""

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring  # noqa: E402
from config import WEB_DATA  # noqa: E402

MULTI = {"loc", "pw"}
LENGTH_BINS = [(0, 150), (150, 300), (300, 500), (500, 800),
               (800, 1200), (1200, 2000), (2000, 10 ** 9)]


def bin_length(v):
    if v is None:
        return None
    for lo, hi in LENGTH_BINS:
        if lo <= v < hi:
            return f"{lo}-{hi if hi < 10 ** 9 else '+'}"
    return None


def entropy(counter):
    total = sum(counter.values())
    if total == 0:
        return 0.0
    h = 0.0
    for n in counter.values():
        p = n / total
        if p > 0:
            h -= p * math.log2(p)
    return h


def value_spread(proteins, key):
    counter = Counter()
    present = 0
    for p in proteins:
        v = p.get(key)
        if key == "len":
            v = bin_length(v)
        if v is None or v == "" or v == []:
            continue
        present += 1
        counter[" + ".join(sorted(v)) if isinstance(v, list) else str(v)] += 1
    h = entropy(counter)
    ceiling = math.log2(len(counter)) if len(counter) > 1 else 0.0
    top = counter.most_common(1)[0] if counter else ("-", 0)
    return {
        "bits": h,
        "ceiling": ceiling,
        "efficiency": (h / ceiling) if ceiling > 0 else 0.0,
        "values": len(counter),
        "top_value": top[0],
        "top_share": top[1] / present if present else 0.0,
        "coverage": present / len(proteins) if proteins else 0.0,
    }


def feedback_spread(proteins, meta, pairs, rng):
    """Sample random (guess, answer) pairs and tally what each column says."""
    per_col = [Counter() for _ in scoring.COLUMNS]
    joint = Counter()

    for _ in range(pairs):
        g = rng.choice(proteins)
        t = rng.choice(proteins)
        if g is t:
            continue
        results = scoring.compare(g, t, meta)
        joint["|".join(s + (a or "") for s, a in results)] += 1
        for i, (st, arrow) in enumerate(results):
            per_col[i][st + (arrow or "")] += 1

    return per_col, joint


def verdict(vs, fb_bits, green, amber, dead):
    """
    Judge on feedback, with value spread as supporting evidence.

    `dead` is the share of feedback that is red WITH NO ARROW — a cell
    saying only "not this". Red *with* an arrow still narrows the range,
    so a numeric column can be 95% red and highly informative. An
    earlier version counted all red as uninformative and flagged
    Chromosome, one of the strongest columns, as dead weight.
    """
    if vs["values"] <= 1:
        return "DEAD", "only one value in the pool — remove this column"
    if vs["coverage"] < 0.60:
        return "SPARSE", (f"only {vs['coverage']:.0%} of the pool has a "
                          f"value; most guesses compare nothing")
    if dead > 0.85 and fb_bits < 0.60:
        return "COLD", ("nearly every guess returns a bare red with no "
                        "arrow — the column rarely says anything")
    if fb_bits < 0.35:
        return "THIN", "feedback barely varies between guesses"
    if vs["efficiency"] < 0.55:
        return "SKEWED", (f"one value holds {vs['top_share']:.0%} of the "
                          f"pool")
    if fb_bits > 1.2 and green + amber > 0.12:
        return "STRONG", ""
    return "ok", ""


def analyse(proteins, meta, label, pairs, rng):
    print(f"\n{'=' * 78}")
    print(f"  {label}  ({len(proteins)} proteins)")
    print(f"{'=' * 78}")

    per_col, joint = feedback_spread(proteins, meta, pairs, rng)

    print(f"\n  VALUE SPREAD — how the column varies across the pool\n")
    print(f"  {'Column':<14} {'values':>7} {'bits':>6} {'of max':>7} "
          f"{'top value':>24} {'share':>6} {'cov':>5}")
    print(f"  {'-' * 74}")

    spreads = []
    for key, name in zip(scoring.COLUMNS, scoring.COLUMN_LABELS):
        vs = value_spread(proteins, key)
        spreads.append(vs)
        print(f"  {name:<14} {vs['values']:>7} {vs['bits']:>6.2f} "
              f"{vs['efficiency']:>6.0%} {vs['top_value'][:24]:>24} "
              f"{vs['top_share']:>5.0%} {vs['coverage']:>5.0%}")

    print(f"\n  FEEDBACK SPREAD — what a guess actually tells the player\n")
    print(f"  {'Column':<14} {'green':>7} {'amber':>7} {'red':>7} "
          f"{'bare':>6} {'bits':>6}   verdict")
    print(f"  {'-' * 74}")

    total_fb = 0.0
    for i, name in enumerate(scoring.COLUMN_LABELS):
        c = per_col[i]
        n = sum(c.values()) or 1
        green = sum(v for k, v in c.items() if k.startswith("correct")) / n
        dead = c.get("wrong", 0) / n
        amber = sum(v for k, v in c.items() if k.startswith("partial")) / n
        red = sum(v for k, v in c.items() if k.startswith("wrong")) / n
        bits = entropy(c)
        total_fb += bits
        v, why = verdict(spreads[i], bits, green, amber, dead)
        flag = "  " if v in ("ok", "STRONG") else "! "
        print(f"  {flag}{name:<12} {green:>7.1%} {amber:>7.1%} {red:>7.1%} "
              f"{dead:>6.0%} {bits:>6.2f}   {v}")
        if why:
            print(f"    {'':<12} {'':>23}   {why}")

    joint_bits = entropy(joint)
    need = math.log2(len(proteins)) if proteins else 0.0
    print(f"\n  Distinct feedback patterns seen : {len(joint):,}")
    print(f"  Bits per guess (joint, sampled) : {joint_bits:.2f}")
    print(f"  Bits needed to isolate an answer: {need:.2f}")
    print(f"  Sum of per-column bits          : {total_fb:.2f}  "
          f"(columns overlap, so this overstates the joint figure)")
    print(f"\n  For how many guesses this actually takes, run "
          f"pipeline/simulate.py —\n  bit counts assume perfect play and "
          f"independent columns, and neither holds.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=20000,
                    help="random guess/answer pairs to sample (default 20000)")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    path = WEB_DATA / "proteins.json"
    if not path.exists():
        print(f"\n{path} not found. Run pipeline/build.py first.\n")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    meta = scoring.meta_from(data)
    proteins = data["proteins"]
    rng = random.Random(args.seed)

    daily = [p for p in proteins if p["t"] == "daily"]
    freeplay = [p for p in proteins if p["t"] in ("daily", "freeplay")]

    analyse(daily, meta, "DAILY POOL", args.pairs, rng)
    analyse(freeplay, meta, "FREE PLAY POOL", args.pairs, rng)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
