"""
Column entropy check.

A column is only worth a slot in the grid if it actually splits the answer
pool. If 90% of proteins say "Cytoplasm", that column is decoration: it
looks like information and costs the player a guess to learn nothing.

    python pipeline/entropy.py

Reports, per column and per tier: Shannon entropy in bits, the share held
by the single most common value, and a verdict.
"""

import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import WEB_DATA  # noqa: E402

# (display name, key in the slim record, is it multi-valued?)
COLUMNS = [
    ("Length",        "len", False),
    ("Conservation",  "con", False),
    ("Localization",  "loc", True),
    ("Function",      "fn",  False),
    ("Pathway",       "pw",  True),
    ("Chromosome",    "chr", False),
    ("Disease",       "dis", False),
]

# Length is continuous; bucket it the way a player experiences it.
LENGTH_BINS = [(0, 150), (150, 300), (300, 500), (500, 800),
               (800, 1200), (1200, 2000), (2000, 10 ** 9)]


def bin_length(v):
    if v is None:
        return None
    for lo, hi in LENGTH_BINS:
        if lo <= v < hi:
            return f"{lo}-{hi if hi < 10**9 else '+'}"
    return None


def entropy(counter, total):
    if total == 0:
        return 0.0
    h = 0.0
    for n in counter.values():
        p = n / total
        if p > 0:
            h -= p * math.log2(p)
    return h


def verdict(h, top_share, n_values):
    if n_values <= 1:
        return "DEAD — one value only, remove this column"
    if top_share > 0.80:
        return "WEAK — one value dominates, players learn almost nothing"
    if h < 1.0:
        return "THIN — carries under one bit"
    if h > 2.0:
        return "STRONG"
    return "ok"


def analyse(proteins, tier_name):
    print(f"\n{'=' * 72}")
    print(f"  {tier_name}  ({len(proteins)} proteins)")
    print(f"{'=' * 72}\n")
    print(f"  {'Column':<14} {'bits':>6} {'values':>7} {'top value':>26} "
          f"{'share':>7}")
    print(f"  {'-' * 68}")

    rows = []
    for label, key, multi in COLUMNS:
        counter = Counter()
        n_with_value = 0
        for p in proteins:
            v = p.get(key)
            if key == "len":
                v = bin_length(v)
            if v is None or v == "" or v == []:
                continue
            n_with_value += 1
            if multi:
                # Score the value-set, since that is what the player sees.
                counter[" + ".join(sorted(v))] += 1
            else:
                counter[str(v)] += 1

        total = sum(counter.values())
        h = entropy(counter, total)
        if counter:
            top_val, top_n = counter.most_common(1)[0]
            top_share = top_n / total
        else:
            top_val, top_share = "-", 0.0

        rows.append((label, h, len(counter), top_val, top_share,
                     n_with_value, len(proteins)))
        print(f"  {label:<14} {h:>6.2f} {len(counter):>7} "
              f"{top_val[:26]:>26} {top_share:>6.0%}")

    print()
    for label, h, n_vals, _tv, top_share, n_with, n_tot in rows:
        cov = n_with / n_tot if n_tot else 0
        v = verdict(h, top_share, n_vals)
        flag = "  " if v in ("ok", "STRONG") else "! "
        print(f"  {flag}{label:<14} {v}"
              + (f"   (coverage {cov:.0%})" if cov < 0.98 else ""))
    print()

    total_bits = sum(r[1] for r in rows)
    print(f"  Total information available per guess: {total_bits:.1f} bits")
    print(f"  Pool needs {math.log2(len(proteins)):.1f} bits to pin down "
          f"one answer.")
    if total_bits > 0:
        print(f"  Theoretical floor: ~{math.log2(len(proteins)) / total_bits:.1f} "
              f"perfect guesses.")
    print()


def main():
    path = WEB_DATA / "proteins.json"
    if not path.exists():
        print(f"\n{path} not found. Run pipeline/build.py first.\n")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    proteins = data["proteins"]

    daily = [p for p in proteins if p["t"] == "daily"]
    freeplay = [p for p in proteins if p["t"] in ("daily", "freeplay")]

    analyse(daily, "DAILY POOL")
    analyse(freeplay, "FREE PLAY POOL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
