"""
Proteindle pipeline configuration.

Everything here is pure stdlib. No pip install required, on any OS.

The conservation ladder is the heart of the game, so it gets the most
attention below. Everything else is plumbing.
"""

from pathlib import Path
from urllib.parse import urlencode

# ---------------------------------------------------------------- paths

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BUILD = ROOT / "data" / "build"
WEB_DATA = ROOT / "web" / "data"

for _d in (RAW, BUILD, WEB_DATA):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- sources

UNIPROT_FIELDS = [
    "accession",
    "id",
    "gene_primary",
    "gene_synonym",
    "protein_name",
    "length",
    "mass",
    "cc_subcellular_location",
    "keyword",
    "go",
    "ec",
    "cc_disease",
    "protein_families",
    "xref_geneid",
    "xref_hgnc",
    "xref_ensembl",
]

UNIPROT_URL = "https://rest.uniprot.org/uniprotkb/stream?" + urlencode(
    {
        "format": "tsv",
        "compressed": "true",
        "query": "(reviewed:true) AND (organism_id:9606)",
        "fields": ",".join(UNIPROT_FIELDS),
    }
)

# name -> (url, required?)
# "required" sources must be present for build.py to run at all.
SOURCES = {
    "uniprot_human.tsv.gz": (UNIPROT_URL, True),
    "gene2pubmed.gz": (
        "https://ftp.ncbi.nlm.nih.gov/gene/DATA/gene2pubmed.gz",
        True,
    ),
    "Homo_sapiens.gene_info.gz": (
        "https://ftp.ncbi.nlm.nih.gov/gene/DATA/GENE_INFO/Mammalia/"
        "Homo_sapiens.gene_info.gz",
        True,
    ),
    "UniProt2Reactome_All_Levels.txt": (
        "https://reactome.org/download/current/UniProt2Reactome_All_Levels.txt",
        True,
    ),
    "ReactomePathwaysRelation.txt": (
        "https://reactome.org/download/current/ReactomePathwaysRelation.txt",
        True,
    ),
    "ReactomePathways.txt": (
        "https://reactome.org/download/current/ReactomePathways.txt",
        True,
    ),
    "hgnc_complete_set.txt": (
        "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/"
        "hgnc_complete_set.txt",
        True,
    ),
    # Gene-Ages: consensus gene age across 13 orthology databases, keyed
    # directly by UniProt accession. 2.4 MB and it is literally the column
    # we want, which is why it beat a 922 MB eggNOG download for primary.
    "main_HUMAN.csv": (
        "https://raw.githubusercontent.com/marcottelab/Gene-Ages/master/"
        "Main/main_HUMAN.csv",
        True,
    ),
}

# Opt-in, --with-eggnog. Better coverage than Gene-Ages (which is a 2016
# snapshot) but it is a ~920 MB download for a column we already have.
OPTIONAL_SOURCES = {
    "e7.og_info_kegg_go.tsv.gz": (
        "https://eggnogdb.org/public/eggnog7/e7.og_info_kegg_go.tsv.gz",
        False,
    ),
    "e7.taxid_info.tsv.gz": (
        "https://eggnogdb.org/public/eggnog7/e7.taxid_info.tsv.gz",
        False,
    ),
}


# ---------------------------------------------------------- conservation

# Gene-Ages ships eight boolean-ish age columns plus a `modeAge` consensus
# call. Two of those eight ("Euk_Archaea" and "Euk+Bac") are siblings, not
# rungs: a protein shared with archaea is not deeper or shallower than one
# shared with bacteria, so ordering them would make the up/down arrow lie.
# We collapse them into a single "Ancient" rung. That leaves a ladder that
# is honestly ordinal end to end, which is the only kind an arrow can hint at.

CONSERVATION_LADDER = [
    # (rung, internal key, display label, blurb for the reveal card)
    (1, "universal", "Universal",
     "Found across bacteria, archaea and eukaryotes — older than the "
     "split between the three domains of life."),
    (2, "ancient", "Ancient",
     "Shared with one prokaryotic domain. Predates eukaryotes."),
    (3, "eukaryota", "Eukaryota",
     "Traces back to the last common ancestor of all eukaryotes."),
    (4, "opisthokonta", "Opisthokonta",
     "Shared by animals and fungi — present in yeast."),
    (5, "eumetazoa", "Eumetazoa",
     "An animal invention. Present in flies and worms, absent in yeast."),
    (6, "vertebrata", "Vertebrata",
     "Arose with the vertebrates — present in fish, absent in insects."),
    (7, "mammalia", "Mammalia",
     "A mammalian innovation, or at least a mammalian-specific version."),
]

CONSERVATION_RANK = {key: rung for rung, key, _, _ in CONSERVATION_LADDER}
CONSERVATION_LABEL = {key: label for _, key, label, _ in CONSERVATION_LADDER}
CONSERVATION_BLURB = {key: blurb for _, key, _, blurb in CONSERVATION_LADDER}

# Gene-Ages `modeAge` string -> our ladder key
GENE_AGES_MAP = {
    "Cellular_organisms": "universal",
    "Euk_Archaea": "ancient",
    "Euk+Bac": "ancient",
    "Eukaryota": "eukaryota",
    "Opisthokonta": "opisthokonta",
    "Eumetazoa": "eumetazoa",
    "Vertebrata": "vertebrata",
    "Mammalia": "mammalia",
}

# eggNOG taxonomic level name -> our ladder key (used only with --with-eggnog)
EGGNOG_LEVEL_MAP = {
    "cellular organisms": "universal",
    "Bacteria": "universal",
    "Archaea": "ancient",
    "Eukaryota": "eukaryota",
    "Opisthokonta": "opisthokonta",
    "Fungi": "opisthokonta",
    "Metazoa": "eumetazoa",
    "Eumetazoa": "eumetazoa",
    "Bilateria": "eumetazoa",
    "Chordata": "vertebrata",
    "Vertebrata": "vertebrata",
    "Craniata": "vertebrata",
    "Euteleostomi": "vertebrata",
    "Tetrapoda": "vertebrata",
    "Amniota": "vertebrata",
    "Mammalia": "mammalia",
    "Eutheria": "mammalia",
    "Boreoeutheria": "mammalia",
    "Euarchontoglires": "mammalia",
    "Primates": "mammalia",
    "Haplorrhini": "mammalia",
    "Catarrhini": "mammalia",
    "Hominidae": "mammalia",
    "Homo sapiens": "mammalia",
}


# --------------------------------------------------------- localization

# UniProt subcellular location is free text with an enormous tail. These
# buckets are checked in order and a protein keeps every bucket it matches,
# because "nucleus and cytoplasm" is a real and useful answer, not a
# data-quality problem. Order matters: more specific patterns first.

LOCALIZATION_BUCKETS = [
    ("Secreted",     ["secreted"]),
    ("Cell membrane", ["cell membrane", "plasma membrane", "cell surface",
                       "apical membrane", "basolateral membrane",
                       "lateral cell membrane", "sarcolemma"]),
    ("Nucleus",      ["nucleus", "nuclear", "nucleoplasm", "nucleolus",
                      "chromosome"]),
    ("Mitochondrion", ["mitochondri"]),
    ("ER",           ["endoplasmic reticulum", "sarcoplasmic reticulum",
                      "microsome"]),
    ("Golgi",        ["golgi"]),
    ("Cytoskeleton", ["cytoskeleton", "centrosome", "spindle", "microtubule",
                      "actin", "myofibril", "cilium", "flagellum",
                      "basal body"]),
    ("Lysosome",     ["lysosome", "endosome", "vacuole", "phagosome",
                      "melanosome", "peroxisome"]),
    ("Cytoplasm",    ["cytoplasm", "cytosol"]),
]

# Anything that matched nothing above.
LOCALIZATION_FALLBACK = "Other"

# Buckets are kept in the order UniProt lists them, because UniProt puts the
# PRIMARY location first and the incidental ones after.
#
# An earlier version reordered by a hand-written "specificity" ranking, on
# the theory that Mitochondrion is a more interesting clue than Cytoplasm.
# The result was that TP53 lost Nucleus entirely and came out as
# "Mitochondrion + ER + Cytoskeleton", EGFR lost Cell membrane, and MTOR —
# whose first annotation is Lysosome membrane — was labelled Mitochondrion
# off the back of one minor annotation buried in its CC line. Rarity is not
# the same as importance. Trust the curator's ordering.
MAX_LOCALIZATIONS = 3


# ------------------------------------------------------ functional class

# Single-valued. Three passes run over this list — name, then EC, then
# keyword — and within each pass the first matching rule wins, so the order
# below encodes priority.
#
# Name beats EC deliberately. Anything called "... receptor" reads as a
# Receptor to a player even when it is formally a kinase (EGFR) — and
# cytochrome c oxidase is formally EC 7 translocase but nobody calls it a
# transporter. The name is what is in the player's head.
#
# Each rule is (class name, keyword patterns, EC prefixes, name patterns).
# Name and keyword patterns are matched with a LEADING word boundary, so
# "actin" does not fire on "inter-ACTIN-g protein", while "kinase" still
# catches "kinases". Keep keyword lists narrow: they are the last pass and
# a broad term there (e.g. "transferase") hijacks whole classes.

FUNCTIONAL_CLASSES = [
    ("Kinase",
     ["kinase"],
     ["2.7.1", "2.7.4", "2.7.10", "2.7.11", "2.7.12", "2.7.13"],
     ["kinase"]),

    ("Phosphatase",
     ["protein phosphatase"],
     ["3.1.3"],
     ["phosphatase"]),

    ("Protease",
     ["protease", "zymogen"],
     ["3.4"],
     ["protease", "peptidase", "proteinase", "caspase", "cathepsin",
      "matrix metallo", "granzyme", "trypsin", "chymotrypsin", "elastase"]),

    ("Transcription factor",
     ["dna-binding", "transcription", "activator", "repressor",
      "homeobox"],
     [],
     ["transcription factor", "homeobox", "zinc finger protein",
      "nuclear receptor", "forkhead", "sox-", "gata-", "kruppel"]),

    ("Ion channel",
     ["ion channel", "ionic channel", "voltage-gated channel",
      "ligand-gated ion channel", "potassium channel", "sodium channel",
      "calcium channel", "chloride channel", "porin"],
     [],
     ["channel", "porin", "aquaporin", "connexin"]),

    ("Receptor",
     ["receptor", "g-protein coupled receptor"],
     [],
     ["receptor"]),

    ("Transporter",
     ["transport", "symport", "antiport", "translocase", "ion transport",
      "amino-acid transport", "sugar transport", "lipid transport"],
     ["7."],
     ["transporter", "carrier", "permease", "solute carrier", "atpase",
      "exchanger", "pump"]),

    ("Structural",
     ["structural protein", "cytoskeleton", "keratin", "collagen",
      "muscle protein", "cell adhesion"],
     [],
     ["collagen", "keratin", "tubulin", "actin", "myosin", "laminin",
      "fibrillin", "spectrin", "filament", "cadherin", "integrin"]),

    ("Enzyme (other)",
     ["oxidoreductase", "lyase", "isomerase", "ligase", "hydrolase",
      "transferase", "glycosidase", "acyltransferase", "methyltransferase"],
     ["1.", "2.", "3.", "4.", "5.", "6."],
     ["synthase", "synthetase", "dehydrogenase", "reductase", "oxidase",
      "isomerase", "ligase", "lyase", "hydrolase", "transferase",
      "carboxylase", "mutase", "esterase"]),

    ("Signalling",
     ["gtpase", "gtp-binding", "guanine-nucleotide releasing factor",
      "adapter", "growth factor", "cytokine", "hormone", "chemotaxis"],
     [],
     ["gtpase", "growth factor", "interleukin", "chemokine", "cytokine",
      "hormone", "ras-related", "rho-related", "adapter"]),

    ("Immune",
     ["immunity", "innate immunity", "adaptive immunity", "antimicrobial",
      "mhc i", "mhc ii", "complement pathway"],
     [],
     # NOT bare "antigen" — it fires on "Cellular tumor antigen p53".
     ["immunoglobulin", "hla class", "complement c", "interferon",
      "t-cell receptor", "antigen-presenting"]),

    ("RNA-binding",
     ["rna-binding", "ribosomal protein", "ribonucleoprotein", "spliceosome",
      "mrna processing", "mrna splicing", "translation regulation"],
     [],
     ["ribosomal protein", "splicing factor", "rna-binding",
      "small nuclear ribonucleoprotein", "eukaryotic translation"]),
]

FUNCTIONAL_FALLBACK = "Other"

# Partial credit for the Function column. Without it the column is pure
# hit-or-miss: 12% green, 88% red, and only 0.52 bits of feedback — the
# weakest column on the board. Grouping related classes so a near miss
# shows amber roughly doubles what the column teaches, and it matches how
# people actually reason ("some kind of enzyme, then").
FUNCTION_GROUPS = {
    "Kinase":               "Enzyme",
    "Phosphatase":          "Enzyme",
    "Protease":             "Enzyme",
    "Enzyme (other)":       "Enzyme",

    "Transcription factor": "Gene expression",
    "RNA-binding":          "Gene expression",

    "Ion channel":          "Transport",
    "Transporter":          "Transport",

    "Receptor":             "Signalling",
    "Signalling":           "Signalling",
    "Immune":               "Signalling",

    "Structural":           "Structural",
    "Other":                "Other",
}


# ------------------------------------------------------------ pathways

# Reactome top-level pathways that are filing cabinets rather than biology.
# "Disease" in particular sat on 41% of the daily pool and simply restates
# the Disease column, so it was costing a clue slot to say nothing new.
PATHWAY_EXCLUDE = {
    "Disease",
    "Drug ADME",
}

# Kept per protein. Scoring is set-overlap, so more values means more amber
# and fewer greens; three made an exact match nearly impossible.
MAX_PATHWAYS = 2


# ----------------------------------------------------------- game rules

# Per mode. 0 means unlimited.
#
# The solver simulation says six is plenty — but the solver has the whole
# database in front of it and filters by exact feedback signature, while a
# person has to RECALL which proteins fit. That gap is the whole game, and
# it is not something a simulation can measure. Eight for the daily.
#
# Free play and hard are practice: no limit, with the give-up button as the
# way out. Nobody needs a losing streak in a mode they chose for drilling.
MAX_GUESSES = {
    "daily": 8,
    "freeplay": 0,
    "hard": 0,
}

# The first N days of EVERY rotation — the global daily and each field's —
# are that pool's best-known proteins in fame order; the rest is shuffled.
#
# Without this, launch day is whatever the shuffle happened to put first,
# which on this build was TNFSF13B: the 382nd most-cited protein, and the
# least memorable of the first ten. Two weeks of proteins everyone knows
# gives new players a run of wins before the difficulty goes random, which
# is the window in which they decide whether to come back.
ONBOARDING_DAYS = 14

# Famous enough that the clue row gives them away on sight, which makes a
# flat opening puzzle. "Transcription factor, chromosome 17, disease-linked"
# is p53 to anyone who would be playing this, and a one-guess win on day one
# is anticlimax, not a hook. These go into the shuffled tail instead — they
# still come up, just not as the first thing anyone sees.
ONBOARDING_EXCLUDE = {
    "TP53",
}

# One entry per gene symbol, always.
#
# UniProt legitimately carries several reviewed entries for some genes —
# GNAS has four, CDKN2A has p16INK4a and p14ARF as separate proteins. For a
# guessing game that is unplayable: you type "GNAS", pick one of four
# identical-looking rows, and get marked wrong for naming the right gene.
#
# The automatic rule keeps the entry with the fewest missing columns, then
# the longest sequence (usually the canonical isoform). Where that picks
# badly, name the accession you want here. GNAS is the case in point: the
# longest entry is the XLas isoform, but the protein people mean by "GNAS"
# is the canonical Gs-alpha.
CANONICAL_OVERRIDES = {
    # Longest entry is the XLas isoform; "GNAS" means Gs-alpha.
    "GNAS":   "P63092",   # 394 aa, GNAS2_HUMAN
    # The automatic rule kept ARF_HUMAN (p14ARF, 132 aa) because it has
    # marginally better column coverage. CDKN2A means p16INK4a to almost
    # everyone, and it sits at rank 49 — squarely in the daily pool.
    "CDKN2A": "P42771",   # 156 aa, CDN2A_HUMAN
    # MACF1_HUMAN is the canonical entry; O94854 is a separate isoform
    # record that happened to score better on coverage.
    "MACF1":  "Q9UPN3",   # 7388 aa, MACF1_HUMAN
}


# --------------------------------------------------------------- fields

# Reactome's top-level pathways double as "what do you work on?" — they are
# roughly the granularity at which people describe their own field ("I'm in
# DNA repair", "I do immunology"), and we already load them.

# Not fields anyone identifies with. "Disease" is a filing cabinet spanning
# a third of the proteome; "Drug ADME" is pharmacology plumbing; the last
# one has two members.
FIELD_EXCLUDE = {
    "Disease",
    "Drug ADME",
    "Digestion and absorption",
}

# Below this, a daily rotation repeats too soon to be worth offering.
FIELD_MIN_SIZE = 50

# Above this, a field is really "most of biology" and stops being a
# usable filter. Immune System has 1,009 members in the 3,000 pool and
# Signal Transduction 1,006; capped by fame, both become a set of proteins
# an immunologist or a signalling person would actually recognise. Small
# fields like DNA Repair (168) are kept whole — a specialist knows the
# less-famous proteins in their own area, which is the point of the mode.
FIELD_MAX_POOL = 250

# Reactome's names are accurate and clunky. These are the ones worth
# rewording for a button.
FIELD_DISPLAY_NAMES = {
    "Gene expression (Transcription)":      "Gene expression",
    "Cellular responses to stimuli":        "Stress responses",
    "Metabolism of proteins":               "Protein metabolism",
    "Metabolism of RNA":                    "RNA metabolism",
    "Transport of small molecules":         "Small-molecule transport",
    "Organelle biogenesis and maintenance": "Organelle biogenesis",
    "Extracellular matrix organization":    "Extracellular matrix",
    "Vesicle-mediated transport":           "Vesicle transport",
    "Cell-Cell communication":              "Cell-cell communication",
}


# --------------------------------------------------------------- tiers

# How many proteins go in each pool. Daily is deliberately small and very
# famous: a year of answers that a working biologist will recognise every
# single day. Free play widens it.
TIER_DAILY = 365
TIER_FREEPLAY = 1000
TIER_HARD = 3000

# A protein is only eligible for the daily pool if it has every column.
# Free play tolerates one gap, hard mode two.
MAX_MISSING_DAILY = 0
MAX_MISSING_FREEPLAY = 1
MAX_MISSING_HARD = 2

# Columns that count toward the completeness score.
SCORED_COLUMNS = [
    "length", "conservation", "localization", "functional_class",
    "pathway", "chromosome", "disease",
]
