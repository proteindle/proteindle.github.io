"""
Cross-check pipeline/scoring.py against web/scoring.js.

    python pipeline/test_scoring.py

Two implementations of the same rules will drift. The simulator uses the
Python one to decide whether the game is too easy or too hard; the game
uses the JS one to tell the player what they learned. If they disagree,
every tuning decision made from simulator output is built on sand.

So: run both over thousands of real protein pairs and demand byte-identical
signatures. Requires node, which ships with the repo's dev setup; if node
is missing the test says so and skips rather than pretending to pass.
"""

import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring  # noqa: E402
from config import ROOT, WEB_DATA  # noqa: E402

PAIRS = 4000
SEED = 7


def build_js_harness(tmpdir, pairs_path, out_path):
    js = f"""
const path = require('path');
const fs = require('fs');
const S = require({str(ROOT / 'web' / 'scoring.js')!r});
const input = JSON.parse(fs.readFileSync({str(pairs_path)!r}, 'utf8'));
const meta = input.meta;
const out = input.pairs.map(function (p) {{
  return S.signature(p[0], p[1], meta);
}});
fs.writeFileSync({str(out_path)!r}, JSON.stringify(out));
"""
    harness = tmpdir / "harness.js"
    harness.write_text(js, encoding="utf-8")
    return harness


def main():
    data_path = WEB_DATA / "proteins.json"
    if not data_path.exists():
        print(f"\n{data_path} not found. Run pipeline/build.py first "
              f"(or make_fixture.py --run).\n")
        return 1

    if shutil.which("node") is None:
        print("\nnode not found — cannot cross-check the JS implementation.")
        print("Install node, or accept that scoring.py and scoring.js are "
              "unverified against each other.\n")
        return 1

    data = json.loads(data_path.read_text(encoding="utf-8"))
    proteins = data["proteins"]
    meta = scoring.meta_from(data)

    rng = random.Random(SEED)
    keys = ("len", "con", "loc", "fn", "pw", "chr", "dis")
    pairs = []
    for _ in range(PAIRS):
        a = rng.choice(proteins)
        b = rng.choice(proteins)
        pairs.append(({k: a.get(k) for k in keys},
                      {k: b.get(k) for k in keys}))

    # Deliberately include the awkward cases random sampling may miss.
    edge = [
        ({"len": None, "con": None, "loc": [], "fn": None, "pw": [],
          "chr": None, "dis": None},
         {"len": 100, "con": "universal", "loc": ["Nucleus"], "fn": "Kinase",
          "pw": ["Metabolism"], "chr": "X", "dis": True}),
        ({"len": 100, "con": "mammalia", "loc": ["Nucleus", "Cytoplasm"],
          "fn": "Kinase", "pw": ["Metabolism"], "chr": "MT", "dis": False},
         {"len": 110, "con": "vertebrata", "loc": ["Cytoplasm", "Nucleus"],
          "fn": "Kinase", "pw": ["Metabolism"], "chr": "Y", "dis": False}),
        ({"len": 1, "con": "universal", "loc": [], "fn": "Other", "pw": [],
          "chr": "1", "dis": True},
         {"len": 1, "con": "universal", "loc": [], "fn": "Other", "pw": [],
          "chr": "1", "dis": True}),
        ({"len": 2000, "con": "mammalia", "loc": ["Secreted"], "fn": "X",
          "pw": ["A", "B"], "chr": "22", "dis": True},
         {"len": 200, "con": "universal", "loc": ["Nucleus"], "fn": "Y",
          "pw": ["B", "A"], "chr": "1", "dis": False}),
    ]
    pairs.extend(edge)

    tmpdir = Path(tempfile.mkdtemp(prefix="proteindle-scoring-"))
    try:
        pairs_path = tmpdir / "pairs.json"
        out_path = tmpdir / "out.json"
        pairs_path.write_text(
            json.dumps({"meta": meta, "pairs": pairs}),
            encoding="utf-8")

        harness = build_js_harness(tmpdir, pairs_path, out_path)
        proc = subprocess.run([shutil.which("node"), str(harness)],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            print("\nnode harness failed:\n")
            print(proc.stderr[:2000])
            return 1

        js_sigs = json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    py_sigs = [scoring.signature(g, t, meta) for g, t in pairs]

    print(f"\nCompared {len(pairs):,} protein pairs "
          f"({len(pairs) - len(edge):,} random + {len(edge)} edge cases)\n")

    mismatches = [(i, p, j) for i, (p, j) in enumerate(zip(py_sigs, js_sigs))
                  if p != j]

    if mismatches:
        print(f"  [FAIL] {len(mismatches)} signature mismatch(es)\n")
        for i, p, j in mismatches[:8]:
            g, t = pairs[i]
            print(f"    pair {i}")
            print(f"      guess  {g}")
            print(f"      target {t}")
            print(f"      python {p}")
            print(f"      js     {j}\n")
        return 1

    print("  [ok  ] scoring.py and scoring.js agree on every pair")

    # A signature set that never varies would mean the test is vacuous.
    distinct = len(set(py_sigs))
    ok = distinct > 50
    print(f"  [{'ok ' if ok else 'FAIL'}] the sample exercises "
          f"{distinct} distinct feedback signatures")
    if not ok:
        return 1

    states = {"correct": 0, "partial": 0, "wrong": 0}
    for sig in py_sigs:
        for cell in sig.split("|"):
            for s in states:
                if cell.startswith(s):
                    states[s] += 1
                    break
    total = sum(states.values())
    print(f"  [ok  ] all three states occur "
          f"(green {states['correct'] / total:.0%}, "
          f"amber {states['partial'] / total:.0%}, "
          f"red {states['wrong'] / total:.0%})")

    print("\nScoring cross-check passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
