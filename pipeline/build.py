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
import datetime
import json
import random
import re
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    ROOT, BUILD, WEB_DATA, CONSERVATION_LADDER, CONSERVATION_RANK,
    CONSERVATION_LABEL, CONSERVATION_BLURB, SCORED_COLUMNS,
    FUNCTION_GROUPS, MAX_GUESSES,
    FIELD_MIN_SIZE, FIELD_MAX_POOL, FIELD_SOURCE_MAX_RANK,
    FIELD_DISPLAY_NAMES, ONBOARDING_DAYS,
    ONBOARDING_EXCLUDE,
    CANONICAL_OVERRIDES,
    TIER_DAILY, TIER_FREEPLAY, TIER_HARD,
    MAX_MISSING_DAILY, MAX_MISSING_FREEPLAY, MAX_MISSING_HARD,
)
import parsers  # noqa: E402

# Fixed forever. Changing this reshuffles everyone's daily answers, so don't.
DAILY_SHUFFLE_SEED = 20260821
# ---------------------------------------------------------------------
# LAUNCH DATE. Day 0 of the game calendar: on this date the site shows
# "Daily #1". Set it before you go live.
#
# After launch this is frozen. Changing it renumbers every puzzle and
# shifts which protein is today's, breaking every shared result. Same for
# DAILY_SHUFFLE_SEED above.
# ---------------------------------------------------------------------
EPOCH = "2026-08-22"


SCHEDULE = ROOT / "data" / "schedule.json"


def load_schedule():
    """The published calendar. Absent on a first build, canon thereafter."""
    if not SCHEDULE.exists():
        return {}
    try:
        data = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    except Exception as exc:                       # noqa: BLE001
        raise SystemExit(
            f"\n{SCHEDULE} is unreadable ({exc}).\n"
            f"This file is the published puzzle calendar. Do not delete it "
            f"to make the build pass — restore it from git.\n"
        )
    if data.get("epoch") != EPOCH:
        raise SystemExit(
            f"\nschedule.json was written for epoch {data.get('epoch')!r} "
            f"but build.py says {EPOCH!r}.\nChanging the epoch renumbers "
            f"every puzzle. If that is really intended, delete "
            f"data/schedule.json deliberately.\n"
        )
    out = {"global": data.get("global", []),
           "_locked": data.get("locked", 0)}
    out.update(data.get("fields", {}))
    return out


def locked_days(previous):
    """
    How much of the calendar is canon.

    A rotation is only untouchable as far as it has actually been played.
    Days that have already happened must never move — somebody has a shared
    grid of them — but the tail is just a permutation nobody has seen, and
    freezing it forever means every future improvement to the pools is
    locked out of the next year of puzzles.

    So: everything up to today plus a day of slack is frozen, and the rest
    is regenerated on each build. The count only ever grows, and it is
    written into schedule.json so a rebuild on a stopped clock — or in a
    container whose date is wrong — cannot shrink it.
    """
    epoch = datetime.date.fromisoformat(EPOCH)
    today = datetime.date.today()
    elapsed = max(0, (today - epoch).days)
    return max(previous, elapsed + 2)


def save_schedule(order, daily_orders, locked):
    # Merge rather than replace. A field can fall below FIELD_MIN_SIZE on a
    # rebuild and stop being offered; if its rotation were dropped from this
    # file, bringing the field back later would renumber every puzzle in it.
    # That happened once — four fields lost their published calendars to a
    # single build — so the file only ever grows.
    merged = dict(load_schedule())
    merged.pop("global", None)
    merged.pop("_locked", None)
    merged.update(daily_orders)
    SCHEDULE.write_text(json.dumps({
        "_comment": "Published puzzle calendar. The first `locked` entries "
                    "of every rotation are days that have already been "
                    "played: never reorder or delete those, or shared "
                    "results stop meaning anything. The tail is regenerated "
                    "on each build.",
        "epoch": EPOCH,
        "seed": DAILY_SHUFFLE_SEED,
        "locked": locked,
        "global": order,
        "fields": merged,
    }, indent=1), encoding="utf-8")


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


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
            "pathway": reactome.get(acc, {}).get("display", []),
            "pathway_score": reactome.get(acc, {}).get("score", []),
            "fields": reactome.get(acc, {}).get("fields", []),
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

    # ------------------------------------------- one entry per gene
    # Several reviewed UniProt entries can share a gene symbol. Two rows
    # reading "NRXN1" in the autocomplete is a coin flip the player cannot
    # win, so collapse to one before anything else looks at the list.
    by_gene = {}
    for r in records:
        by_gene.setdefault(r["gene"], []).append(r)

    dropped = []
    records = []
    for gene, group in by_gene.items():
        if len(group) == 1:
            records.append(group[0])
            continue
        pinned = CANONICAL_OVERRIDES.get(gene)
        keep = next((r for r in group if r["accession"] == pinned), None)
        if keep is None:
            keep = sorted(group, key=lambda r: (len(r["missing"]),
                                                -(r["length"] or 0),
                                                r["accession"]))[0]
        records.append(keep)
        dropped.append((gene, keep, [r for r in group if r is not keep]))
    # `tier` is assigned further down; the report reads it off these same
    # objects afterwards, so the list stays live rather than a snapshot.

    if dropped:
        print(f"  [ok  ] collapsed {len(dropped)} gene symbols with multiple "
              f"reviewed entries")

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

    # ------------------------------------------------------ field pools
    #
    # A field pool is drawn from the best-known FIELD_SOURCE_MAX_RANK
    # proteins rather than the 3,000 the other modes use: a specialist knows
    # the less-famous proteins in their own area, and that domain knowledge
    # is exactly what the mode is meant to reward. It is also the only way
    # the small fields survive strict membership — see FIELD_SOURCE_MAX_RANK.
    #
    # Members are ranked by (columns missing, fame) so complete entries come
    # first — a daily puzzle with a blank column is a bad puzzle — then
    # capped. Without the cap, "Immune System" would hold a third of the
    # database and stop being a filter at all. The cap is also why widening
    # the source costs the large fields nothing: their top 250 by fame sit
    # inside the 3,000 either way.
    by_field = {}
    for r in records:
        if r["fame_rank"] > FIELD_SOURCE_MAX_RANK:
            continue
        if len(r["missing"]) > MAX_MISSING_FREEPLAY:
            continue
        for f in r["fields"]:
            by_field.setdefault(f, []).append(r)

    fields = []
    for name, members in sorted(by_field.items()):
        if len(members) < FIELD_MIN_SIZE:
            continue
        members.sort(key=lambda r: (len(r["missing"]), r["fame_rank"]))
        pool = members[:FIELD_MAX_POOL]
        key = slugify(name)
        for r in pool:
            r.setdefault("field_keys", []).append(key)
        fields.append({
            "key": key,
            "label": FIELD_DISPLAY_NAMES.get(name, name),
            "source": name,
            "size": len(pool),
            "available": len(members),
        })

    fields.sort(key=lambda f: f["label"].lower())

    # Field pools reach past the 3,000, so their extra members have to ship
    # as answers as well. They get a tier of their own: reachable inside the
    # field that claimed them, never in the global daily, free play or hard
    # rotations, which stay strictly fame-ranked.
    field_extra = [r for r in records
                   if r.get("field_keys") and r["tier"] is None]
    for r in field_extra:
        r["tier"] = "field"
    answers = hard + field_extra
    if field_extra:
        print(f"  [ok  ] {len(field_extra)} extra answers pulled in by field "
              f"pools reaching past rank {TIER_HARD}")

    # Stable daily schedule. A permutation of the pool means no repeat
    # inside one full cycle, and the fixed seed means a rebuild does not
    # change what tomorrow's answer is.
    rank_of = {r["accession"]: r["fame_rank"] for r in records}

    gene_of = {r["accession"]: r["gene"] for r in records}

    def rotation(accessions, seed):
        """
        An opening fortnight of well-known proteins, then a fixed shuffle.

        Launch week decides whether anyone comes back, so it is not left to
        the shuffle. Two refinements on "just take the most famous":

        ONBOARDING_EXCLUDE keeps the giveaways out of the window — a puzzle
        solvable from the clue row at a glance is a flat opening.

        The window is then shuffled rather than run in fame order. All
        fourteen are easy either way, but a strict fame countdown is
        guessable: work out the pattern on day three and you know the next
        eleven answers.
        """
        rng = random.Random(seed)
        ranked = sorted(accessions, key=lambda a: rank_of.get(a, 10 ** 9))

        head, deferred = [], []
        for acc in ranked:
            if len(head) >= ONBOARDING_DAYS:
                break
            if gene_of.get(acc) in ONBOARDING_EXCLUDE:
                deferred.append(acc)
                continue
            head.append(acc)
        rng.shuffle(head)

        seen = set(head)
        tail = [a for a in accessions if a not in seen]
        rng.shuffle(tail)
        return head + tail

    frozen = load_schedule()
    locked = locked_days(frozen.pop("_locked", 0))

    def scheduled(key, members, seed):
        """
        The published calendar is canon. Data changes must never renumber a
        puzzle somebody has already played and shared, so a rotation that
        exists in schedule.json is reused verbatim and only extended: newly
        eligible proteins are appended after everything already scheduled.
        Entries are never removed, even if the protein has since dropped out
        of the tier, because deleting one shifts every day after it.
        """
        played = frozen.get(key, [])[:locked]
        seen = set(played)
        fresh = [a for a in rotation(members, seed) if a not in seen]
        return played + fresh

    order = scheduled("global",
                      [r["accession"] for r in daily], DAILY_SHUFFLE_SEED)

    # One rotation per field. Seeded off the field key with a STABLE hash —
    # Python's built-in hash() is salted per process, so using it here would
    # silently change everyone's puzzle on every rebuild.
    daily_orders = {}
    for f in fields:
        members = [r["accession"] for r in answers
                   if f["key"] in r.get("field_keys", [])]
        seed = DAILY_SHUFFLE_SEED ^ zlib.crc32(f["key"].encode("utf-8"))
        daily_orders[f["key"]] = scheduled(f["key"], members, seed)

    # Anything ever scheduled must still ship, or the client will land on a
    # day whose answer it cannot look up.
    shipped = {r["accession"] for r in answers}
    by_acc = {r["accession"]: r for r in records}
    rescued = []
    for key, accs in [("global", order)] + list(daily_orders.items()):
        for a in accs:
            if a in shipped:
                # Already an answer, but not necessarily still a member of
                # the field whose calendar scheduled it. Tighter membership
                # rules must not make a published puzzle unreachable in the
                # mode it was published in.
                rec = by_acc.get(a)
                if rec is not None and key != "global":
                    keys = rec.setdefault("field_keys", [])
                    if key not in keys:
                        keys.append(key)
                continue
            rec = by_acc.get(a)
            if rec is not None:
                rec["tier"] = rec["tier"] or ("hard" if key == "global"
                                              else "field")
                if key != "global":
                    keys = rec.setdefault("field_keys", [])
                    if key not in keys:
                        keys.append(key)
                answers.append(rec)
                shipped.add(a)
                rescued.append((key, rec["gene"]))

    # The rescue pass above can put a protein back into a field, so the
    # advertised sizes are counted last rather than at pool-building time.
    for f in fields:
        f["size"] = sum(1 for r in answers
                        if f["key"] in r.get("field_keys", []))

    save_schedule(order, daily_orders, locked)

    # ---------------------------------------------------------- outputs
    BUILD.mkdir(parents=True, exist_ok=True)
    WEB_DATA.mkdir(parents=True, exist_ok=True)

    full_path = BUILD / "proteins_full.json"
    full_path.write_text(json.dumps(records, indent=1), encoding="utf-8")

    def slim(r, answer=True):
        d = {
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
            "pws": r["pathway_score"],
            "chr": r["chromosome"],
            "dis": r["disease"],
            "mass": r["mass_da"],
            "locus": r["locus"],
            "disn": r["disease_names"],
            "fam": r["families"],
            "pap": r["papers"],
            "rank": r["fame_rank"],
            "t": r["tier"],
            "fld": r.get("field_keys", []),
        }
        if not answer:
            # Never the answer, so nothing that only the reveal card uses
            # needs to travel. Across 16,000 proteins this is ~2 MB.
            # "fam" stays: the board shows the family of whatever you
            # guessed, and you can guess anything in here.
            for k in ("disn", "pap", "t", "fld"):
                d.pop(k, None)
        # Empty lists and nulls are 6-10 bytes each, times 20,000.
        return {k: v for k, v in d.items()
                if v is not None and v != [] and v != ""}

    rest = [r for r in records if r["accession"] not in shipped]

    game = {
        "version": 2,
        "epoch": EPOCH,
        "maxGuesses": MAX_GUESSES,
        "ladder": [
            {"rank": rung, "key": key, "label": label, "blurb": blurb}
            for rung, key, label, blurb in CONSERVATION_LADDER
        ],
        # Drives partial credit on the Function column, and is read by the
        # game, the entropy report and the simulator alike.
        "functionGroups": FUNCTION_GROUPS,
        "fields": fields,
        "dailyOrder": order,
        "dailyOrders": daily_orders,
        "rest": "data/proteins-rest.json",
        "restCount": len(rest),
        "proteins": [slim(r) for r in answers],
    }
    game_path = WEB_DATA / "proteins.json"
    game_path.write_text(json.dumps(game, separators=(",", ":")),
                         encoding="utf-8")

    # Every remaining reviewed human protein, so that anything a player can
    # think of can be guessed. Split off rather than merged because the
    # first file has to be small enough to start playing on: this one is
    # four times the size and is fetched after the board is already up.
    rest_path = WEB_DATA / "proteins-rest.json"
    rest_path.write_text(
        json.dumps({"version": 2, "proteins": [slim(r, answer=False)
                                               for r in rest]},
                   separators=(",", ":")),
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
    add(f"  field     {len(field_extra):>5}  (extra field-pool members, "
        f"answerable only inside their field)")
    add("")
    add("Shipped:")
    add(f"  proteins.json       {len(answers):>6} answers")
    add(f"  proteins-rest.json  {len(rest):>6} guessable-only")
    add(f"  total               {len(answers) + len(rest):>6} "
        f"of {len(records)} reviewed human proteins")
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
    if dropped:
        # Only the collapses that reach a playable tier are worth reading.
        # The full list is 45 lines, most of it endogenous retrovirus genes
        # nobody will ever be asked to guess, and the four that matter get
        # buried. Daily-pool entries are the ones to check by eye: a wrong
        # canonical there is a puzzle the player cannot win.
        playable = [(g, k, o) for g, k, o in dropped if k["tier"]]
        playable.sort(key=lambda t: t[1]["fame_rank"])
        add(f"Gene symbols with several reviewed UniProt entries: "
            f"{len(dropped)} collapsed, {len(playable)} of them in a "
            f"playable tier.")
        add("Check these by eye — a wrong canonical is an unwinnable puzzle:")
        for gene, keep, others in playable:
            why = " PINNED" if CANONICAL_OVERRIDES.get(gene) else ""
            mark = " <-- DAILY" if keep["tier"] == "daily" else ""
            add(f"  {gene:<10} {keep['tier']:<9} kept {keep['accession']} "
                f"({keep['length']} aa){why}"
                f"   dropped "
                + ", ".join(f"{o['accession']} ({o['length']} aa)"
                            for o in others) + mark)
        add("")
        add("  Pin a different accession with CANONICAL_OVERRIDES in "
            "config.py.")
        add("")
    if rescued:
        add("Kept in the pool only because they are already scheduled:")
        for key, gene in rescued:
            add(f"  {gene} (in the {key} rotation)")
        add("")
    add(f"Opening fortnight (the first {ONBOARDING_DAYS} dailies, "
        f"best-known first):")
    for i, acc in enumerate(order[:ONBOARDING_DAYS]):
        r = next(x for x in records if x["accession"] == acc)
        add(f"  #{i + 1}  {r['gene']:<10} {r['papers']:>6} papers   "
            f"{r['name'][:44]}")
    add("")
    add(f"Fields offered ({len(fields)}), pool capped at {FIELD_MAX_POOL}:")
    for f in sorted(fields, key=lambda f: -f["size"]):
        capped = "  (capped)" if f["available"] > f["size"] else ""
        add(f"  {f['label']:<28} {f['size']:>4} of {f['available']:>4}"
            f"{capped}")
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
