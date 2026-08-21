"""
Join every source into the playable database.

    python pipeline/build.py
    python pipeline/build.py --with-eggnog

Outputs:
    data/build/proteins_full.json   every reviewed human protein, all columns
    data/build/report.txt           coverage + tier report
    web/data/proteins.json          what the game actually loads
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    BUILD, WEB_DATA, CONSERVATION_LADDER, CONSERVATION_RANK,
    CONSERVATION_LABEL, CONSERVATION_BLURB, SCORED_COLUMNS,
    TIER_DAILY, TIER_FREEPLAY, TIER_HARD,
    MAX_MISSING_DAILY, MAX_MISSING_FREEPLAY, MAX_MISSING_HARD,
)
import parsers  # noqa: E402

# Fixed forever. Changing this reshuffles everyone's daily answers, so don't.
DAILY_SHUFFLE_SEED = 20260821
# Day 0 of the game calendar. Must be in the past or day 1 is negative.
EPOCH = "2026-08-01"


def missing_columns(rec):
    missing = []
    for col in SCORED_COLUMNS:
        val = rec.get(col)
        if val is None or val == "" or val == []:
            missing.append(col)
    return missing


def build(with_eggnog=False):
    print("\nParsing sources\n")
    uni = parsers.parse_uniprot()
    if not uni:
        print("\nNo UniProt data — nothing to build. Run download.py first.\n")
        return 1

    fame = parsers.parse_gene2pubmed()
    ginfo = parsers.parse_gene_info()
    reactome = parsers.parse_reactome()
    hgnc = parsers.parse_hgnc()
    conservation = parsers.parse_gene_ages()

    if with_eggnog:
        ensp_to_acc = {}
        for acc, rec in uni.items():
            for ensp in rec.get("ensps", []):
                ensp_to_acc.setdefault(ensp, acc)
        egg = parsers.parse_eggnog(ensp_to_acc)
        filled = 0
        for acc, key in egg.items():
            if acc not in conservation:
                conservation[acc] = key
                filled += 1
        if filled:
            print(f"  [ok  ] eggNOG filled {filled} conservation gaps")

    print("\nJoining\n")
    records = []
    for acc, u in uni.items():
        geneid = u.get("geneid")
        gi = ginfo.get(geneid, {}) if geneid else {}
        loc = hgnc.get(acc, {})
        cons_key = conservation.get(acc)

        aliases = set()
        for a in u.get("synonyms", []):
            aliases.add(a)
        for a in gi.get("aliases", []):
            aliases.add(a)
        aliases.discard(u.get("gene") or "")
        aliases = sorted(a for a in aliases if a and len(a) <= 24)

        rec = {
            "accession": acc,
            "gene": u.get("gene") or "",
            "name": u.get("protein_name") or "",
            "aliases": aliases[:12],
            "description": gi.get("description", ""),

            # --- game columns ---
            "length": u.get("length"),
            "conservation": cons_key,
            "localization": u.get("localization") or [],
            "functional_class": u.get("functional_class"),
            "pathway": reactome.get(acc, []),
            "chromosome": loc.get("chromosome"),
            "disease": u.get("disease"),

            # --- reveal card extras ---
            "mass_da": u.get("mass_da"),
            "locus": loc.get("locus"),
            "disease_names": u.get("disease_names", []),
            "families": u.get("families", ""),
            "entry_name": u.get("entry_name", ""),
            "papers": fame.get(geneid, 0) if geneid else 0,
        }

        # A protein with no gene symbol is unguessable. Drop it.
        if not rec["gene"]:
            continue

        rec["missing"] = missing_columns(rec)
        records.append(rec)

    records.sort(key=lambda r: (-r["papers"], r["gene"]))
    for i, r in enumerate(records):
        r["fame_rank"] = i + 1

    # ---------------------------------------------------------- tiers
    def take(pool, n, max_missing, exclude):
        out = []
        for r in pool:
            if r["accession"] in exclude:
                continue
            if len(r["missing"]) > max_missing:
                continue
            out.append(r)
            if len(out) >= n:
                break
        return out

    daily = take(records, TIER_DAILY, MAX_MISSING_DAILY, set())
    daily_accs = {r["accession"] for r in daily}
    freeplay = daily + take(records, TIER_FREEPLAY - len(daily),
                            MAX_MISSING_FREEPLAY, daily_accs)
    freeplay_accs = {r["accession"] for r in freeplay}
    hard = freeplay + take(records, TIER_HARD - len(freeplay),
                           MAX_MISSING_HARD, freeplay_accs)

    for r in records:
        r["tier"] = None
    for r in hard:
        r["tier"] = "hard"
    for r in freeplay:
        r["tier"] = "freeplay"
    for r in daily:
        r["tier"] = "daily"

    # Stable daily schedule. A permutation of the daily pool means no repeat
    # inside one full cycle, and the fixed seed means a rebuild does not
    # change what tomorrow's answer is.
    rng = random.Random(DAILY_SHUFFLE_SEED)
    order = [r["accession"] for r in daily]
    rng.shuffle(order)

    # ---------------------------------------------------------- outputs
    BUILD.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)

    full_path = BUILD / "proteins_full.json"
    full_path.write_text(json.dumps(records, indent=1), encoding="utf-8")

    def slim(r):
        return {
            "a": r["accession"],
            "g": r["gene"],
            "n": r["name"],
            "s": r["aliases"],
            "d": r["description"],
            "len": r["length"],
            "con": r["conservation"],
            "loc": r["localization"],
            "fn": r["functional_class"],
            "pw": r["pathway"],
            "chr": r["chromosome"],
            "dis": r["disease"],
            "mass": r["mass_da"],
            "locus": r["locus"],
            "disn": r["disease_names"],
            "fam": r["families"],
            "pap": r["papers"],
            "rank": r["fame_rank"],
            "t": r["tier"],
        }

    game = {
        "version": 1,
        "epoch": EPOCH,
        "ladder": [
            {"rank": rung, "key": key, "label": label, "blurb": blurb}
            for rung, key, label, blurb in CONSERVATION_LADDER
        ],
        "dailyOrder": order,
        "proteins": [slim(r) for r in hard],
    }
    game_path = WEB_DATA / "proteins.json"
    game_path.write_text(json.dumps(game, separators=(",", ":")),
                         encoding="utf-8")

    # ---------------------------------------------------------- report
    lines = []
    add = lines.append
    add("Proteindle build report")
    add("=" * 60)
    add(f"Reviewed human proteins with a gene symbol : {len(records)}")
    add("")
    add("Column coverage across all proteins:")
    for col in SCORED_COLUMNS:
        have = sum(1 for r in records if col not in r["missing"])
        pct = 100.0 * have / len(records)
        add(f"  {col:<18} {have:>6} / {len(records)}  ({pct:5.1f}%)")
    add("")
    complete = [r for r in records if not r["missing"]]
    add(f"Fully complete (all {len(SCORED_COLUMNS)} columns): "
        f"{len(complete)}")
    add("")
    add("Tiers:")
    add(f"  daily     {len(daily):>5}  (need all columns)")
    add(f"  freeplay  {len(freeplay):>5}  (<= {MAX_MISSING_FREEPLAY} missing)")
    add(f"  hard      {len(hard):>5}  (<= {MAX_MISSING_HARD} missing)")
    add("")
    add("Conservation distribution in the daily pool:")
    from collections import Counter
    cc = Counter(r["conservation"] for r in daily)
    for rung, key, label, _b in CONSERVATION_LADDER:
        add(f"  {rung}. {label:<16} {cc.get(key, 0):>4}")
    add("")
    add("Functional class distribution in the daily pool:")
    fc = Counter(r["functional_class"] for r in daily)
    for cls, n in fc.most_common():
        add(f"  {cls:<22} {n:>4}")
    add("")
    add("Least famous protein in each tier (sanity check — if you do not")
    add("recognise the daily one, the pool is too big):")
    for label, pool in (("daily", daily), ("freeplay", freeplay),
                        ("hard", hard)):
        if pool:
            last = pool[-1]
            add(f"  {label:<9} {last['gene']:<12} "
                f"{last['papers']:>6} papers   {last['name'][:44]}")
    add("")
    add(f"Wrote {full_path}")
    add(f"Wrote {game_path} "
        f"({game_path.stat().st_size / 1024:.0f} KB)")

    report = "\n".join(lines)
    (BUILD / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    print()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-eggnog", action="store_true")
    args = ap.parse_args()
    raise SystemExit(build(with_eggnog=args.with_eggnog))
