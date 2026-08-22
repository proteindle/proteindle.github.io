"""
One parser per raw source. Each returns a plain dict keyed by UniProt
accession (or GeneID where that is the natural key) so build.py can just
join them.

Every parser is defensive about missing files: it returns an empty dict and
prints a warning rather than exploding, so a partial download still yields
a playable database with gaps flagged.
"""

import csv
import gzip
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    RAW, UNIPROT_FIELDS, GENE_AGES_MAP, EGGNOG_LEVEL_MAP,
    PATHWAY_EXCLUDE, MAX_PATHWAYS, FIELD_EXCLUDE,
    LOCALIZATION_BUCKETS, LOCALIZATION_FALLBACK, MAX_LOCALIZATIONS,
    FUNCTIONAL_CLASSES, FUNCTIONAL_FALLBACK,
)

csv.field_size_limit(1 << 30)

ECO_RE = re.compile(r"\{ECO:[^}]*\}")
NOTE_RE = re.compile(r"\bNote=.*$", re.DOTALL)
MIM_RE = re.compile(r"\[MIM:\d+\]")
ENSP_RE = re.compile(r"ENSP\d+")
# UniProtKB accession grammar, per uniprot.org/help/accession_numbers
ACCESSION_RE = re.compile(
    r"^[OPQ][0-9][A-Z0-9]{3}[0-9]$|^[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}$"
)


def _open(path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace",
                         newline="")
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


def _missing(name):
    print(f"  [warn] {name} not found in data/raw — that column will be empty")
    return {}


# ------------------------------------------------------------- UniProt

def clean_location(raw):
    """
    'SUBCELLULAR LOCATION: Nucleus {ECO:0000255}. Cytoplasm. Note=Shuttles...'
        -> ['Nucleus', 'Cytoplasm']
    """
    if not raw:
        return []
    txt = raw.replace("SUBCELLULAR LOCATION:", " ")
    txt = ECO_RE.sub(" ", txt)
    txt = NOTE_RE.sub(" ", txt)
    # UniProt separates locations with '.' and qualifies them with ';'
    parts = re.split(r"[.;]", txt)
    out = []
    for p in parts:
        p = p.strip().strip(",")
        # Drop isoform headers like '[Isoform 2]' and topology qualifiers
        p = re.sub(r"\[[^\]]*\]", "", p).strip()
        if not p or len(p) > 120:
            continue
        if p.lower().startswith(("single-pass", "multi-pass", "peripheral",
                                 "lipid-anchor", "gpi-anchor", "type i",
                                 "type ii", "type iii", "type iv")):
            continue
        out.append(p)
    return out


def short_protein_name(protein_name):
    """
    UniProt packs extras after the real name: alternatives in parentheses,
    and processed chains in square brackets, e.g. "Insulin [Cleaved into:
    Insulin B chain; Insulin A chain]". Cut at the first of either.
    """
    return re.split(r"\s*[(\[]", protein_name or "")[0].strip()


def bucket_locations(location_strings):
    """
    Collapse UniProt's free text onto our fixed bucket list, preserving
    UniProt's ordering so the primary location comes first.

    Each location string maps to at most one bucket — the first that
    matches, per LOCALIZATION_BUCKETS order, which is arranged
    most-specific-first so 'Cytoplasm, cytoskeleton' lands on Cytoskeleton
    rather than Cytoplasm.
    """
    if not location_strings:
        return []

    ordered = []
    for loc in location_strings:
        low = loc.lower()
        for bucket, patterns in LOCALIZATION_BUCKETS:
            if any(pat in low for pat in patterns):
                if bucket not in ordered:
                    ordered.append(bucket)
                break

    if not ordered:
        return [LOCALIZATION_FALLBACK]
    return ordered[:MAX_LOCALIZATIONS]


def _compile(patterns):
    """
    Leading word boundary only. Trailing is deliberately omitted so
    'kinase' still catches 'kinases' and 'matrix metallo' catches
    'matrix metalloproteinase-9'.
    """
    return [re.compile(r"\b" + re.escape(p)) for p in patterns]


# Precompiled once: 20k proteins x ~100 patterns is enough work to matter.
_RULES = [
    (cls, _compile(kw), ec, _compile(names))
    for cls, kw, ec, names in FUNCTIONAL_CLASSES
]


def _hit(compiled, text):
    return any(rx.search(text) for rx in compiled)


def classify_function(keywords, ec, protein_name, go_terms):
    """
    Single functional class. First matching rule wins, so rule order in
    config.py encodes priority.
    """
    kw = " ; ".join(keywords).lower()
    name = (protein_name or "").lower()
    go = (go_terms or "").lower()
    ecs = [e.strip() for e in (ec or "").split(";") if e.strip()]

    # Three passes, strongest signal first. Within each pass the rules are
    # tried in FUNCTIONAL_CLASSES order, so that list encodes priority.
    #
    # Name beats EC on purpose. Cytochrome c oxidase is EC 7.1.1.9, which
    # is formally a translocase, but no biologist calls it a transporter —
    # they call it an enzyme. The protein's name is what the player has in
    # their head, so the name wins.

    for cls, _kw, _ec, name_rx in _RULES:
        if _hit(name_rx, name):
            return cls

    for cls, _kw, ec_prefixes, _np in _RULES:
        if ec_prefixes and any(
            e.startswith(pref) for e in ecs for pref in ec_prefixes
        ):
            return cls

    for cls, kw_rx, _ec, _np in _RULES:
        if _hit(kw_rx, kw):
            return cls

    # Last resort: GO terms, which are noisy enough to only consult when
    # everything else came up empty.
    for cls, _kw, _ec, name_rx in _RULES:
        if _hit(name_rx, go):
            return cls

    return FUNCTIONAL_FALLBACK


def parse_uniprot():
    path = RAW / "uniprot_human.tsv.gz"
    if not path.exists():
        return _missing("uniprot_human.tsv.gz")

    out = {}
    with _open(path) as fh:
        reader = csv.reader(fh, delimiter="\t")
        header = next(reader)
        if len(header) != len(UNIPROT_FIELDS):
            print(f"  [warn] UniProt returned {len(header)} columns, expected "
                  f"{len(UNIPROT_FIELDS)}. Header: {header}")
        idx = {f: i for i, f in enumerate(UNIPROT_FIELDS)}

        def get(row, field):
            i = idx.get(field)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in reader:
            if not row:
                continue
            acc = get(row, "accession")
            if not acc:
                continue

            mass_raw = get(row, "mass").replace(",", "")
            try:
                mass = int(mass_raw)
            except ValueError:
                mass = None
            try:
                length = int(get(row, "length"))
            except ValueError:
                length = None

            keywords = [k.strip() for k in get(row, "keyword").split(";")
                        if k.strip()]
            synonyms = [s.strip() for s in get(row, "gene_synonym").split()
                        if s.strip()]
            locations = clean_location(get(row, "cc_subcellular_location"))
            disease_txt = get(row, "cc_disease")

            geneids = [g.strip() for g in get(row, "xref_geneid").split(";")
                       if g.strip()]
            ensps = ENSP_RE.findall(get(row, "xref_ensembl"))

            protein_name = get(row, "protein_name")
            short_name = short_protein_name(protein_name)

            out[acc] = {
                "accession": acc,
                "entry_name": get(row, "id"),
                "gene": get(row, "gene_primary"),
                "synonyms": synonyms,
                "protein_name": short_name,
                "protein_name_full": protein_name,
                "length": length,
                "mass_da": mass,
                "keywords": keywords,
                "localization": bucket_locations(locations),
                "localization_raw": locations[:6],
                "ec": get(row, "ec"),
                "families": get(row, "protein_families"),
                "geneid": geneids[0] if geneids else None,
                "ensps": ensps[:4],
                "disease": bool(MIM_RE.search(disease_txt)),
                "disease_names": _disease_names(disease_txt),
                "functional_class": classify_function(
                    keywords, get(row, "ec"), protein_name, get(row, "go")
                ),
            }
    print(f"  [ok  ] UniProt: {len(out)} reviewed human entries")
    return out


def _disease_names(txt):
    """Pull the human-readable disease names out of the DISEASE comment."""
    if not txt:
        return []
    names = []
    for chunk in txt.split("DISEASE:"):
        chunk = chunk.strip()
        if not chunk or "[MIM:" not in chunk:
            continue
        name = chunk.split("[MIM:")[0].strip()
        name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip(" :;,")
        if name and len(name) < 90:
            names.append(name)
    return names[:3]


# ---------------------------------------------------------------- fame

def parse_gene2pubmed():
    """GeneID -> number of PubMed papers. Our recognisability proxy."""
    path = RAW / "gene2pubmed.gz"
    if not path.exists():
        return _missing("gene2pubmed.gz")

    counts = defaultdict(int)
    with _open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or parts[0] != "9606":
                continue
            counts[parts[1]] += 1
    print(f"  [ok  ] gene2pubmed: paper counts for {len(counts)} human genes")
    return dict(counts)


def parse_gene_info():
    """GeneID -> (symbol, [synonyms], description). Extra alias source."""
    path = RAW / "Homo_sapiens.gene_info.gz"
    if not path.exists():
        return _missing("Homo_sapiens.gene_info.gz")

    out = {}
    with _open(path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 9:
                continue
            geneid, symbol, syns, desc = p[1], p[2], p[4], p[8]
            aliases = [s for s in syns.split("|") if s and s != "-"]
            out[geneid] = {
                "symbol": symbol,
                "aliases": aliases,
                "description": desc if desc != "-" else "",
            }
    print(f"  [ok  ] gene_info: {len(out)} genes with aliases")
    return out


# ------------------------------------------------------------ Reactome

def parse_reactome():
    """UniProt accession -> [top-level pathway names]."""
    mapping_path = RAW / "UniProt2Reactome_All_Levels.txt"
    relation_path = RAW / "ReactomePathwaysRelation.txt"
    names_path = RAW / "ReactomePathways.txt"

    if not mapping_path.exists():
        return _missing("UniProt2Reactome_All_Levels.txt")

    # child -> parent, human only
    parent = {}
    if relation_path.exists():
        with _open(relation_path) as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 2 and p[0].startswith("R-HSA-"):
                    parent[p[1]] = p[0]
    else:
        print("  [warn] ReactomePathwaysRelation.txt missing — pathways will "
              "not be rolled up to top level")

    names = {}
    if names_path.exists():
        with _open(names_path) as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3 and p[2] == "Homo sapiens":
                    names[p[0]] = p[1]

    def to_top(sid, _seen=None):
        seen = _seen or set()
        while sid in parent and sid not in seen:
            seen.add(sid)
            sid = parent[sid]
        return sid

    acc_pathways = defaultdict(set)
    with _open(mapping_path) as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or p[5] != "Homo sapiens":
                continue
            acc, sid, label = p[0], p[1], p[3]
            if not sid.startswith("R-HSA-"):
                continue
            top = to_top(sid)
            name = names.get(top, label)
            acc_pathways[acc].add(name)

    # Two different products from the same walk:
    #
    #   display — the Pathway clue column. Excludes filing-cabinet
    #             categories and is capped, because a cell listing eight
    #             pathways is not a clue.
    #   fields  — every top-level pathway the protein belongs to, used to
    #             filter answers by the player's field. Uncapped, because a
    #             DNA-repair person should get DNA-repair proteins whether
    #             or not that pathway made the protein's top two.
    display, fields = {}, {}
    for acc, paths in acc_pathways.items():
        keep = sorted(p for p in paths if p not in PATHWAY_EXCLUDE)
        if keep:
            display[acc] = keep[:MAX_PATHWAYS]
        usable = sorted(p for p in paths if p not in FIELD_EXCLUDE)
        if usable:
            fields[acc] = usable

    print(f"  [ok  ] Reactome: pathways for {len(display)} accessions, "
          f"field tags for {len(fields)}")
    return display, fields


# ---------------------------------------------------------------- HGNC

def parse_hgnc():
    """UniProt accession -> {'chromosome': '17', 'locus': '17p13.1'}."""
    path = RAW / "hgnc_complete_set.txt"
    if not path.exists():
        return _missing("hgnc_complete_set.txt")

    out = {}
    with _open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            loc = (row.get("location") or "").strip()
            uni = (row.get("uniprot_ids") or "").strip()
            if not uni:
                continue
            chrom = _chromosome_from_locus(loc)
            for acc in uni.split("|"):
                acc = acc.strip()
                if acc:
                    out[acc] = {"chromosome": chrom, "locus": loc or None}
    n_chrom = sum(1 for v in out.values() if v["chromosome"])
    print(f"  [ok  ] HGNC: {len(out)} accessions, {n_chrom} with a chromosome")
    return out


def _chromosome_from_locus(loc):
    if not loc:
        return None
    loc = loc.strip()
    if loc.lower().startswith("mitochondria"):
        return "MT"
    # HGNC locus strings look like '17p13.1', '11q22.1', 'Xq28', '19'.
    # A \b after the digits does NOT work here: '17p' has no word boundary
    # between '7' and 'p', so the arm must name the arm letters explicitly.
    m = re.match(r"^(\d{1,2}|X|Y)(?:[pq]|cen|$|\s|-)", loc, re.IGNORECASE)
    if not m:
        return None
    c = m.group(1).upper()
    if c.isdigit() and not (1 <= int(c) <= 22):
        return None
    return c


# -------------------------------------------------------- conservation

def parse_gene_ages():
    """UniProt accession -> conservation ladder key."""
    path = RAW / "main_HUMAN.csv"
    if not path.exists():
        return _missing("main_HUMAN.csv")

    out = {}
    unmapped = defaultdict(int)
    with _open(path) as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []

        # The published file is a pandas dump: the accession sits in the
        # index column, which has no name, so the header line begins with a
        # bare comma. Look for a named column first in case that ever
        # changes, then fall back to the unnamed first column.
        acc_col = None
        for cand in ("UniProt_acc", "UniProt", "uniprot", "Entry", "acc"):
            if cand in fields:
                acc_col = cand
                break
        if acc_col is None and fields and not (fields[0] or "").strip():
            acc_col = fields[0]          # the unnamed index column
        if acc_col is None and fields:
            acc_col = fields[0]
            print(f"  [warn] Gene-Ages: guessing accession column {acc_col!r}")
        if acc_col is None:
            print("  [warn] Gene-Ages: no columns found")
            return {}

        if "modeAge" not in fields:
            print(f"  [warn] Gene-Ages: no 'modeAge' column. Header is "
                  f"{fields[:6]}")
            return {}

        for row in reader:
            acc = (row.get(acc_col) or "").strip()
            mode = (row.get("modeAge") or "").strip()
            if not acc or not mode:
                continue
            key = GENE_AGES_MAP.get(mode)
            if key:
                out[acc] = key
            else:
                unmapped[mode] += 1

    # Cheap sanity check that we read accessions and not, say, row numbers.
    sample = list(out)[:200]
    looks_right = sum(1 for a in sample if ACCESSION_RE.match(a))
    if sample and looks_right < len(sample) * 0.8:
        print(f"  [warn] Gene-Ages: column {acc_col!r} does not look like "
              f"UniProt accessions (e.g. {sample[:3]}) — conservation will "
              f"not join")

    if unmapped:
        print(f"  [warn] Gene-Ages: unmapped modeAge values {dict(unmapped)}")
    print(f"  [ok  ] Gene-Ages: conservation for {len(out)} accessions")
    return out


def parse_eggnog(ensp_to_acc):
    """
    Optional enrichment. Streams the big gzip and records, for each human
    protein, the deepest (most basal) orthologous-group level it appears in.
    """
    path = RAW / "e7.og_info_kegg_go.tsv.gz"
    if not path.exists():
        return {}

    from config import CONSERVATION_RANK
    best = {}
    seen_levels = defaultdict(int)
    rows = 0

    with _open(path) as fh:
        for line in fh:
            rows += 1
            if rows % 500_000 == 0:
                print(f"        ...{rows:,} eggNOG rows", end="\r", flush=True)
            if "9606." not in line:
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < 6:
                continue
            level = p[2].strip()
            key = EGGNOG_LEVEL_MAP.get(level)
            seen_levels[level] += 1
            if not key:
                continue
            rank = CONSERVATION_RANK[key]
            for member in p[5].split(","):
                if not member.startswith("9606."):
                    continue
                ensp = member.split(".", 1)[1]
                acc = ensp_to_acc.get(ensp)
                if not acc:
                    continue
                if acc not in best or rank < best[acc][0]:
                    best[acc] = (rank, key)

    out = {acc: key for acc, (_r, key) in best.items()}
    print(f"  [ok  ] eggNOG: conservation for {len(out)} accessions "
          f"({rows:,} rows scanned)")
    return out
