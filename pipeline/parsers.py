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
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    RAW, UNIPROT_FIELDS, GENE_AGES_MAP, EGGNOG_LEVEL_MAP,
    PATHWAY_EXCLUDE, MAX_PATHWAYS, SCORE_PATHWAYS,
    PATHWAY_MIN_SHARE, FIELD_EXCLUDE, FIELD_MIN_SHARE,
    FIELD_MIN_ANNOTATIONS, FIELD_MAX_PER_PROTEIN,
    LOCALIZATION_BUCKETS, LOCALIZATION_FALLBACK, MAX_LOCALIZATIONS,
    FUNCTIONAL_CLASSES, FUNCTIONAL_FALLBACK, FUNCTION_OVERRIDES,
    NOT_A_MODIFIER, WORD_GUARDS,
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


def _only_groups(rest):
    """True if `rest` is nothing but balanced (...) groups and whitespace."""
    depth = 0
    for ch in rest:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
        elif depth == 0 and not ch.isspace():
            return False
    return depth == 0


# The two square-bracket suffixes UniProt appends after a finished name.
_NAME_SUFFIX_RE = re.compile(r"\s*\[(?:Cleaved into|Includes|Contains):.*$",
                             re.IGNORECASE | re.DOTALL)


def short_protein_name(protein_name):
    """
    UniProt packs extras after the real name: alternative names and EC
    numbers in parentheses, processed chains in square brackets.

    Square brackets are the trap. They mark a suffix in "Insulin [Cleaved
    into: Insulin B chain; Insulin A chain]" but they are part of the name
    itself in "Poly [ADP-ribose] polymerase 1", "Superoxide dismutase
    [Cu-Zn]" and "Isocitrate dehydrogenase [NADP] cytoplasmic". Cutting at
    every bracket left PARP1 displayed to players as "Poly", and did the
    same to 176 other proteins.

    Parentheses have exactly the same trap, and it is the more common one.
    They mark alternative names in "Epidermal growth factor receptor (EC
    2.7.10.1) (Proto-oncogene c-ErbB-1)" but they are part of the name in
    "DNA (cytosine-5)-methyltransferase 1", "D(2) dopamine receptor" and
    "Collagen alpha-1(I) chain". Cutting at the first one shipped DNMT1 as
    "DNA", DRD2 as "D", NQO1 as "NAD", and — worse — gave COL1A1, COL2A1
    and COL3A1 the identical display name "Collagen alpha-1", which is
    three unwinnable rows in the autocomplete.

    What separates them is position, not content: UniProt's alternative
    names are a run of bracketed groups that continues to the END of the
    string. So cut at the first parenthesis with nothing but balanced
    groups after it, and at no other.
    """
    name = _NAME_SUFFIX_RE.sub("", protein_name or "")

    depth = 0
    for i, ch in enumerate(name):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "(" and depth == 0 and _only_groups(name[i:]):
            return name[:i].strip()
    return name.strip()


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


def _compile(patterns, name_pass=False):
    """
    Leading word boundary only. Trailing is deliberately omitted so
    'kinase' still catches 'kinases' and 'matrix metallo' catches
    'matrix metalloproteinase-9'.

    A pattern prefixed "re:" is taken as a raw regex instead, for the few
    rules that need a lookaround — telling "kinase inhibitor" (not a
    kinase) from "inhibitor of NF-kappa-B kinase" (very much a kinase)
    cannot be done with a literal.

    Name patterns get two extra guards; keyword patterns get neither,
    because a UniProt keyword is a controlled term with no prose around it.

      WORD_GUARDS   the handful of patterns whose missing trailing
                    boundary does real damage ('cytokine' on 'cytokinesis')
      NOT_A_MODIFIER  refuse the match when the pattern is modifying some
                    other head noun ('receptor-associated', 'kinase
                    substrate'). Applied per occurrence, so a name that
                    uses the word both ways still matches on the good one.
    """
    out = []
    for p in patterns:
        if p.startswith("re:"):
            out.append(re.compile(p[3:]))
            continue
        rx = r"\b" + re.escape(p)
        if name_pass:
            rx += WORD_GUARDS.get(p, "") + NOT_A_MODIFIER
        out.append(re.compile(rx))
    return out


# Precompiled once: 20k proteins x ~100 patterns is enough work to matter.
_RULES = [
    (cls, _compile(kw), ec, _compile(names, name_pass=True))
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

    # There used to be a last-resort pass over GO terms here. It was
    # measurably worse than saying nothing: GO strings mix molecular
    # function with process and location, so "protein phosphatase binding"
    # made BCL2 a phosphatase, "protein kinase binding" made alpha-
    # synuclein, VHL, leptin and caveolin-1 kinases, and a mention of
    # repair made BAX and MCL1 DNA repair proteins. Twenty-two of the 365
    # daily answers carried a class that was simply false.
    #
    # "Other" is a real answer — it tells the player this is not an enzyme,
    # a receptor or a channel — and an honest one is worth more than a
    # confident wrong one in a game where people reason from the clue.
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

            # For 68 entries UniProt lists several gene symbols under one
            # accession, because the genes are duplicates coding an
            # identical protein: "H4C1; H4C2; H4C3; ...". Printed whole
            # that is a row nobody can read and nobody can type. Keep the
            # first as the symbol and let the others stay searchable.
            gene = get(row, "gene_primary")
            if ";" in gene:
                parts = [g.strip() for g in gene.split(";") if g.strip()]
                gene = parts[0] if parts else ""
                synonyms = parts[1:] + synonyms
            synonyms = [s for s in synonyms if s and s != ";"]

            out[acc] = {
                "accession": acc,
                "entry_name": get(row, "id"),
                "gene": gene,
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
                "functional_class": FUNCTION_OVERRIDES.get(
                    gene,
                    classify_function(keywords, get(row, "ec"),
                                      protein_name, get(row, "go")),
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
    """
    Returns {accession: {"display": [...], "score": [...], "fields": [...]}}.

    All three come from one measurement: ANNOTATION WEIGHT, the number of
    distinct Reactome annotations a protein has under each top-level
    pathway. It is a serviceable proxy for what the protein mostly does.
    EGFR is 52% Signal Transduction, CDK1 66% Cell Cycle, BRAF 72% Signal
    Transduction.

    The previous version took sorted(names)[:2] — alphabetically. That hid
    Signal Transduction from EGFR behind Developmental Biology, hid
    Metabolism from SREBF1 behind Circadian clock, and labelled ATM an
    autophagy protein. Players reasoned correctly from wrong clues.
    """
    mapping_path = RAW / "UniProt2Reactome_All_Levels.txt"
    relation_path = RAW / "ReactomePathwaysRelation.txt"
    names_path = RAW / "ReactomePathways.txt"

    if not mapping_path.exists():
        return _missing("UniProt2Reactome_All_Levels.txt")

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

    _top_cache = {}

    def to_top(sid):
        if sid in _top_cache:
            return _top_cache[sid]
        seen, cur = set(), sid
        while cur in parent and cur not in seen:
            seen.add(cur)
            cur = parent[cur]
        _top_cache[sid] = cur
        return cur

    weight = defaultdict(Counter)
    with _open(mapping_path) as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or p[5] != "Homo sapiens":
                continue
            acc, sid = p[0], p[1]
            if not sid.startswith("R-HSA-"):
                continue
            weight[acc][names.get(to_top(sid), p[3])] += 1

    # Baseline share of each top-level across the whole annotation corpus.
    # Used to rank a protein's FIELDS by enrichment rather than raw count:
    # "Signal Transduction" is 13% of every annotation in Reactome, so a
    # protein that is 20% Signal Transduction is unremarkable, whereas one
    # that is 20% Autophagy (0.8% baseline) is an autophagy protein.
    #
    # This only decides WHICH of the qualifying fields to keep when a
    # protein has more than FIELD_MAX_PER_PROTEIN of them. Raw count still
    # decides the displayed pathways, where the question is the different
    # one of "what does this protein spend its time doing".
    corpus = Counter()
    for counts in weight.values():
        corpus.update(counts)
    corpus_total = sum(corpus.values()) or 1
    baseline = {n: c / corpus_total for n, c in corpus.items()}

    out = {}
    for acc, counts in weight.items():
        total = sum(counts.values())
        if not total:
            continue
        # Ranked by weight, noise floor applied, filing cabinets removed.
        ranked = [(n, c) for n, c in counts.most_common()
                  if c / total >= PATHWAY_MIN_SHARE]

        shown = [n for n, _ in ranked if n not in PATHWAY_EXCLUDE]
        scored = shown[:SCORE_PATHWAYS]

        eligible = [(n, c) for n, c in ranked if n not in FIELD_EXCLUDE]
        qualified = [(n, c) for n, c in eligible
                     if c >= FIELD_MIN_ANNOTATIONS
                     and c / total >= FIELD_MIN_SHARE]
        qualified.sort(
            key=lambda t: (t[1] / total) / baseline.get(t[0], 1.0),
            reverse=True,
        )
        fields = [n for n, _ in qualified[:FIELD_MAX_PER_PROTEIN]]
        # A protein always belongs to whatever it does most, even if that
        # falls under the share threshold because its work is spread wide.
        if not fields and eligible:
            fields = [eligible[0][0]]

        out[acc] = {
            "display": shown[:MAX_PATHWAYS],
            "score": scored,
            "fields": fields,
        }

    n_disp = sum(1 for v in out.values() if v["display"])
    n_fld = sum(1 for v in out.values() if v["fields"])
    per = sum(len(v["fields"]) for v in out.values()) / max(n_fld, 1)
    print(f"  [ok  ] Reactome: {n_disp} accessions with a pathway, "
          f"{n_fld} with field tags ({per:.1f} fields each on average)")
    return out


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
