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


# A protein name says what a protein IS in its head noun; the rest of the
# name usually says what it acts on, binds to or hangs off. With only a
# leading boundary the rules could not tell the two apart, so "receptor"
# fired on "TNF receptor-associated factor 6" and "kinase" on "S-phase
# kinase-associated protein 1". 575 entries were classified off a modifier
# this way — the largest single error shape in the column, and it spanned
# every class, which is why it is fixed here once rather than in 575
# override entries.
#
# Applied per OCCURRENCE, not per name, and that distinction is the whole
# safety margin. "Toll-like receptor 2 (Toll/interleukin-1 receptor-like
# protein 4)" contains both a modifier use and a real one; the lookahead
# skips the blocked occurrence and matches the good one, so TLR2 stays a
# Receptor.
#
# "-like" and "homolog" are deliberately NOT in this list. IL1RL1 is
# "Interleukin-1 receptor-like 1" and is a genuine receptor; so is CCR5 via
# "C-C chemokine receptor type 5". Adding them moves another 294 proteins
# and most of those moves are wrong.
NOT_A_MODIFIER = (
    r"(?!\w*(?:-|\s)(?:related|associated|dependent|independent|binding|"
    r"bound|interacting|inducible|regulated|responsive|activating|"
    r"inactivating|anchored|substrate|antagonist|stimulating|inhibiting|"
    r"targeting|deficient|coupling|linking|linked|modulating|enhancing|"
    r"anchor|adaptor|adapter|chaperone)\b)"
)

# Per-pattern guards, for the handful of name patterns that need something
# narrower than a word boundary.
#
# The first three are the missing boundary at the other end: a pattern
# firing inside a longer, unrelated word. A blanket trailing \b is NOT the
# fix — it would break "kinase" -> "kinases" and "matrix metallo" ->
# "matrix metalloproteinase", both of which are wanted.
#
# The last three are protein families whose names double as DOMAIN names,
# and the domain sense is the commoner one: 18 of the 23 uses of
# "thrombospondin" are "thrombospondin type-1 domain" or "with
# thrombospondin motifs", and nearly every use of "fibronectin" outside FN1
# itself is "fibronectin type III domain". Without these, the daily answer
# ADAMTS13 ("...with thrombospondin motifs 13") becomes a Structural
# protein instead of a protease, and FNDC5 — which is the precursor of
# irisin, a myokine — stops being Signalling.
WORD_GUARDS = {
    "cytokine":       r"(?!sis)",    # "Protein regulator of cytokinesis 1"
    "keratin":        r"(?!ocyte)",  # "Keratinocyte growth factor"
    "actin":          r"(?!g\b)",    # "...acting..."
    "thrombospondin": r"(?!\s+(?:type|motifs?))",
    "fibronectin":    r"(?!\s+type|-like)",
    "fibrinogen":     r"(?!\s+domain|-like|/)",
    # ...and three more of the same shape, where the longer word is the
    # name of an ENZYME that acts on the structural protein rather than
    # the protein itself: the aggrecanases ADAMTS4/5, the tubulinyl-Tyr
    # carboxypeptidases VASH1/2, and NEDD9 ("Enhancer of filamentation 1").
    # The last two were wrong before any of this work and are fixed here
    # because the guard costs one line.
    "aggrecan":       r"(?!ase)",
    "tubulin":        r"(?!yl)",
    "filament":       r"(?!ation)",
}

# Structural protein families, by name.
#
# These exist because the Structural class used to rest on the UniProt
# keywords "Cytoskeleton" (759 proteins) and "Cell adhesion" (235) — 59% of
# the class — and both are LOCATION and PROCESS keywords rather than
# function ones. They say where a protein is and what it takes part in,
# which is the same mistake that got the GO-terms pass deleted: BCL2L1,
# NPM1, CCNB1, MEFV, S100B and HSPB1 all arrived in Structural that way.
#
# Deleting the two keywords alone was measured and is worse: it sends 927
# proteins to "Other", and among them VIM, FN1, DMD and DES, which really
# are structural and had no other rule to catch them. The keyword was
# simultaneously the dumping ground and the only thing holding the class
# together, so it is replaced rather than removed.
#
# "catenin" is deliberately absent: it pulls CTNNB1 out of Transcription
# factor, and beta-catenin is famous for Wnt signalling, not for structure.
# The second block, from "filamin" down, is there because the first draft
# of this list overshot: dropping the keywords sent FLNA, EZR, CTTN, PFN1,
# CFL1, CLTC and NF2 to "Other". Those are canonical cytoskeletal proteins
# and the keyword had been the only thing holding them. They are named
# here rather than recovered by re-adding the keyword, because the keyword
# also brought 750 proteins that are merely LOCATED at the cytoskeleton.
#
# "catenin alpha" and not "catenin": alpha-catenin is an adherens-junction
# protein, beta-catenin is a Wnt transducer, and CTNNB1 must stay out.
STRUCTURAL_NAMES = [
    "vimentin", "desmin", "fibronectin", "laminin", "elastin", "titin",
    "troponin", "tropomyosin", "dystrophin", "utrophin", "plectin",
    "vinculin", "talin", "septin", "nestin", "syndecan", "tenascin",
    "fibulin", "periostin", "thrombospondin", "nebulin", "dystroglycan",
    "sarcoglycan", "desmoplakin", "desmoglein", "desmocollin",
    "plakophilin", "plakoglobin", "emerin", "vitronectin", "fibrinogen",
    "aggrecan", "versican", "decorin", "biglycan", "lumican", "matrilin",
    "nidogen", "perlecan", "agrin", "myomesin", "obscurin", "dynein",
    "kinesin", "microfibril",

    "filamin", "ezrin", "moesin", "radixin", "merlin", "cofilin",
    "profilin", "gelsolin", "clathrin", "villin", "tropomodulin",
    "dematin", "adducin", "ankyrin", "zyxin", "paxillin", "palladin",
    "drebrin", "coronin", "fascin", "myotilin", "synemin", "catenin alpha",
    "cortactin",
]

FUNCTIONAL_CLASSES = [
    # ---- these two run first, because they exist to BEAT a later rule ----

    # Inhibitors of enzymes, which the enzyme rules were claiming as the
    # enzyme itself. p21 and p27 were "Kinase" — they are CDK inhibitors,
    # the opposite thing — and alpha-1-antitrypsin and cystatin C were
    # "Protease", off the UniProt keyword "Protease inhibitor" matching the
    # pattern "protease".
    #
    # The name rule needs a lookaround, hence "re:". "Cyclin-dependent
    # kinase inhibitor 1" is an inhibitor; "Inhibitor of nuclear factor
    # kappa-B kinase subunit beta" is a kinase, and no literal tells them
    # apart. The test is whether the enzyme word sits immediately before
    # "inhibitor", optionally with a number between.
    ("Inhibitor",
     ["protease inhibitor", "protein phosphatase inhibitor"],
     [],
     [r"re:\b(?:kinase|protease|proteinase|peptidase|metalloproteinase"
      r"|metallopeptidase|phosphatase|elastase|trypsin|chymotrypsin)"
      r"(?:\s+\d+[a-z]?)?\s+inhibitor\b",
      "activator inhibitor", "antitrypsin", "antichymotrypsin",
      "antithrombin", "antiplasmin", "cystatin", "serpin"]),

    # Ligands, which the Receptor and Kinase rules were claiming. PD-L1,
    # FasL and RANKL came out as receptors; "Fms-related tyrosine kinase 3
    # ligand" came out as a kinase. Same class as the row above: it has to
    # run before the rule it corrects.
    #
    # Not anchored at the start, and not followed by a hyphen, so
    # "Ligand-dependent corepressor" and "Ligand of Numb protein X 2" are
    # left to the rules that already get them right.
    ("Signalling",
     [],
     [],
     [r"re:(?<!^)\bligand\b(?!-)"]),

    # Small GTPases, by EC number alone.
    #
    # RHOA, CDC42 and the ARF/RAB/RAS-like families were "Enzyme (other)"
    # while HRAS, KRAS, NRAS and RAC1 were "Signalling" -- 30 of the 163
    # small-GTPase-family proteins disagreeing with the other 133, purely
    # because the lucky ones have "GTPase" or "Ras-related" in their names
    # and RhoA is called "Transforming protein RhoA".
    #
    # This is an EC rule rather than a name rule on purpose. Matching the
    # names was measured first and reached much too far: the aliases
    # "ATP/GTP-binding protein 1" made the cytosolic carboxypeptidases
    # AGBL1-5 signalling proteins instead of proteases, and
    # "ADP-ribosylation factor-like protein 6-interacting protein" caught
    # ARL6IP1/4/6, which interact with an ARF rather than being one.
    # EC 3.6.5.2 IS "small monomeric GTPase" and says so exactly.
    #
    # It has to sit above Enzyme (other) because that rule claims all of
    # EC 3, and the EC pass takes the first matching rule in this list.
    ("Signalling", [], ["3.6.5.2"], []),

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

    # Genome maintenance. Sits above Transcription factor because the two
    # were being confused: "DNA-binding" used to be enough to be called a
    # transcription factor, which made MSH2, MSH6, ERCC1 and BRCA2
    # transcription factors. They bind DNA to repair it.
    #
    # Deliberately narrow. Enzymes that happen to act on DNA — polymerases,
    # ligases, topoisomerases, PARP — stay enzymes, and ATM and ATR stay
    # kinases, because that is the more useful thing to know about them and
    # it is what a player would say out loud.
    # The keyword "DNA damage" is gone. UniProt applies it to anything a
    # damage response touches, which made CCND1, BRD4, FMR1, CCAR2, CIP2A
    # and TANK repair proteins — 30 entries, wrong nearly every time. The
    # keyword "DNA repair" stays: it is right for BRCA2, FANCD2, NBN, PALB2
    # and RPA1, and only HMGB1 is arguable.
    #
    # The NAME pattern "dna damage" stays too, and DDIT3 no longer needs it
    # removed: "DNA damage-inducible transcript 3" is a modifier, so
    # NOT_A_MODIFIER declines it and DDIT3 lands on Transcription factor.
    ("DNA repair",
     ["dna repair", "mismatch repair"],
     [],
     ["dna repair", "mismatch repair", "excision repair", "dna damage",
      "double-strand break repair", "crossover junction"]),

    # Writers, erasers, readers and remodellers of chromatin.
    #
    # Added because these were scattered across five classes with no honest
    # home: HDAC6 and the SMARC proteins were "Structural" (off "tubulin"
    # and "actin" in their names), DNMT1 and KMT2A "Transcription factor",
    # EZH2 and EP300 "Enzyme (other)", BRD4 "DNA repair". 22 of the 365
    # daily answers are in here, and "the thing that modifies chromatin" is
    # what a biologist says out loud about every one of them.
    #
    # Sits above Transcription factor because the overlap is real and
    # chromatin is the more specific statement, and above Structural and
    # Enzyme so that HDAC6 stops being a tubulin and EZH2 stops being a
    # generic enzyme.
    #
    # The enzyme-activity patterns are qualified with their substrate on
    # purpose. A bare "acetyltransferase" catches NAT2, which is drug
    # metabolism; a bare "demethylase" catches FTO, which acts on RNA; and
    # a bare "deacetylase" catches the esterases ESD and CES1. Naming the
    # substrate costs nothing and keeps all three out.
    #
    # Known and accepted: the mitochondrial sirtuins SIRT3 and SIRT5 land
    # here, because they genuinely are protein deacetylases and the name
    # gives no hint they work outside the nucleus. Neither is a daily
    # answer. Fixing them would need a per-protein override, which is
    # exactly what this class exists to avoid.
    ("Chromatin",
     ["chromatin regulator"],
     [],
     ["histone", "chromatin", "heterochromatin", "bromodomain",
      "chromodomain", "nucleosome", "polycomb", "swi/snf",
      "protein deacetylase", "protein deacylase", "histone deacetylase",
      "histone acetyltransferase", "protein-lysine n-methyltransferase",
      "dna (cytosine-5)-methyl", "methylcytosine dioxygenase"]),

    ("Transcription factor",
     ["transcription", "activator", "repressor", "homeobox"],
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
     ["transporter", "carrier", "permease", "solute carrier",
      "exchanger", "pump"]),

    # "Cytoskeleton" and "Cell adhesion" have been removed from the keyword
    # list and replaced by STRUCTURAL_NAMES — see the note there. Net
    # effect: the class goes from 1,690 proteins to about 880, VIM, FN1,
    # DMD and DES all survive, and TTN and SDC1 are gained.
    ("Structural",
     ["structural protein", "keratin", "collagen", "muscle protein"],
     [],
     ["collagen", "keratin", "tubulin", "actin", "myosin", "lamin",
      "fibrillin", "spectrin", "filament", "cadherin", "integrin"]
     + STRUCTURAL_NAMES),

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

# Gene symbol -> class, applied after the rules have had their say.
#
# Keep this list SHORT. It is a patch on a rule, not a substitute for one:
# anything needing more than a handful of entries is a rule that should be
# fixed instead. Every entry needs a reason.
FUNCTION_OVERRIDES = {
    # Formally an E3 ubiquitin ligase, EC 2.3.2.27, which is what the EC
    # pass sees — and nobody thinks of BRCA1 as an enzyme. The general fix,
    # letting the "DNA repair" keyword outrank EC, was measured and is
    # worse: it also drags in YY1, HSF1, CLOCK, SIRT6, METTL3 and the
    # ribosomal protein uS3, because that keyword marks any involvement in
    # repair rather than the protein's job.
    "BRCA1": "DNA repair",
}

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

    # Amber families. The name is internal — it only decides which pairs of
    # classes count as "close" — so it can be broader than any one label.
    "Transcription factor": "Nucleic acid",
    "RNA-binding":          "Nucleic acid",
    "DNA repair":           "Nucleic acid",

    "Ion channel":          "Transport",
    "Transporter":          "Transport",

    "Receptor":             "Signalling",
    "Signalling":           "Signalling",
    "Immune":               "Signalling",

    "Chromatin":            "Nucleic acid",

    "Structural":           "Structural",
    # An inhibitor of an enzyme is close enough to an enzyme to be worth an
    # amber: guess a protease against a serpin and you have learned something.
    "Inhibitor":            "Enzyme",
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

# How many pathways are SHOWN in the clue cell.
#
# Which two matters more than how many. They used to be chosen with
# sorted(paths)[:2], i.e. alphabetically, which is how EGFR came to display
# "Developmental Biology, Gene expression" while hiding Signal Transduction,
# and how ATM was labelled an autophagy protein. Players reasoned correctly
# from wrong clues and gave up.
#
# Pathways are now ranked by ANNOTATION WEIGHT: how many distinct Reactome
# annotations the protein has under each top-level pathway. That is a decent
# proxy for "what does this protein mostly do". EGFR is 52% Signal
# Transduction; CDK1 is 66% Cell Cycle; ATM leads with DNA Repair and
# Autophagy does not reach its top five.
MAX_PATHWAYS = 2

# How many are COMPARED. Scoring on a slightly wider set than is displayed
# stops a protein's second-most-characteristic pathway from being invisible
# to the comparison. Tuned against the entropy report.
SCORE_PATHWAYS = 4

# Annotation weight below this share of a protein's total is noise rather
# than biology, and never counts for display, scoring or field membership.
PATHWAY_MIN_SHARE = 0.05


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
FIELD_MIN_SIZE = 40

# Field membership is now strict — a protein joins a field only if that
# top-level pathway is a real share of its annotations — and strictness has
# a cost: measured against the famous 3,000 alone, Autophagy has 25 members,
# Muscle contraction 36 and Sensory Perception 19. All three would be cut,
# and the fix is not to loosen membership (that is what put ATM in
# Autophagy) but to look further down the fame list for the proteins that
# genuinely belong.
#
# So field pools are drawn from the best-known 8,000 rather than the 3,000
# the other modes use. Large fields are unaffected: FIELD_MAX_POOL takes
# their top 250 by fame and those all sit inside the 3,000 anyway. Only the
# small fields dig deeper, which is exactly the trade the mode exists to
# make — someone who picks "Autophagy" knows GABARAPL1.
#
# Every protein a field pool reaches has to be a shippable answer, so the
# build adds them to the game file on top of the 3,000 tier.
FIELD_SOURCE_MAX_RANK = 8000

# A protein joins a field only if a real share of its Reactome annotations
# sit under that top-level pathway. Without this, membership was "appears
# under it at all", which put AKT1 in ELEVEN fields and made ATM an
# autophagy protein off a single annotation. People picked a field and met
# answers that had no business being there.
FIELD_MIN_SHARE = 0.20
FIELD_MIN_ANNOTATIONS = 3
FIELD_MAX_PER_PROTEIN = 3

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
