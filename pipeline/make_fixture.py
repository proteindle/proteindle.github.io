"""
Generate tiny fake raw files that match each real source's format exactly,
so the whole pipeline can be smoke-tested without a 300 MB download.

    python pipeline/make_fixture.py        # writes into data/raw_fixture/
    python pipeline/make_fixture.py --run  # ...then builds from them

This is how the parsers were debugged before the real data existed. If a
source ever changes its format, this fixture is the thing to update first:
make the fixture match reality, watch the test fail, then fix the parser.
"""

import argparse
import gzip
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

FIXTURE = config.ROOT / "data" / "raw_fixture"

UNIPROT_HEADER = [
    "Entry", "Entry Name", "Gene Names (primary)", "Gene Names (synonym)",
    "Protein names", "Length", "Mass", "Subcellular location [CC]",
    "Keywords", "Gene Ontology (GO)", "EC number",
    "Involvement in disease", "Protein families", "GeneID", "HGNC",
    "Ensembl",
]

# Real-ish rows, hand-written from memory of the actual entries. The point
# is format fidelity, not biological precision.
UNIPROT_ROWS = [
    # TP53 — nuclear TF, disease-linked, vertebrate-ish age
    ["P04637", "P53_HUMAN", "TP53", "P53", "Cellular tumor antigen p53",
     "393", "43,653",
     "SUBCELLULAR LOCATION: Nucleus {ECO:0000269|PubMed:1234}. Cytoplasm. "
     "Note=Shuttles between nucleus and cytoplasm.",
     "Activator;Apoptosis;DNA-binding;Nucleus;Transcription;Tumor suppressor",
     "nucleus [GO:0005634]; DNA-binding transcription factor activity",
     "", "DISEASE: Li-Fraumeni syndrome (LFS) [MIM:151623]: A rare "
     "autosomal dominant disorder.", "P53 family", "7157;", "HGNC:11998;",
     "ENST00000269305 [P04637-1];ENSP00000269305;ENSG00000141510;"],

    # EGFR — receptor kinase, membrane
    ["P00533", "EGFR_HUMAN", "EGFR", "ERBB ERBB1", "Epidermal growth factor "
     "receptor (EC 2.7.10.1) (Proto-oncogene c-ErbB-1)",
     "1210", "134,277",
     "SUBCELLULAR LOCATION: Cell membrane {ECO:0000269}; Single-pass type I "
     "membrane protein. Endoplasmic reticulum membrane. Nucleus.",
     "ATP-binding;Kinase;Receptor;Transferase;Tyrosine-protein kinase",
     "plasma membrane [GO:0005886]; protein tyrosine kinase activity",
     "2.7.10.1", "DISEASE: Lung cancer (LNCR) [MIM:211980]: A common "
     "malignancy.", "Protein kinase superfamily", "1956;", "HGNC:3236;",
     "ENST00000275493;ENSP00000275493;ENSG00000146648;"],

    # ACTB — universal cytoskeleton
    ["P60709", "ACTB_HUMAN", "ACTB", "", "Actin, cytoplasmic 1 (Beta-actin)",
     "375", "41,737",
     "SUBCELLULAR LOCATION: Cytoplasm, cytoskeleton. Nucleus.",
     "Cytoskeleton;ATP-binding;Methylation",
     "cytoskeleton [GO:0005856]; actin filament binding",
     "", "", "Actin family", "60;", "HGNC:132;",
     "ENST00000646664;ENSP00000494750;ENSG00000075624;"],

    # INS — tiny secreted hormone
    ["P01308", "INS_HUMAN", "INS", "", "Insulin", "110", "11,981",
     "SUBCELLULAR LOCATION: Secreted {ECO:0000269|PubMed:5555}.",
     "Cleavage on pair of basic residues;Diabetes mellitus;Hormone;Secreted",
     "extracellular region [GO:0005576]; hormone activity",
     "", "DISEASE: Diabetes mellitus, permanent neonatal (PNDM) "
     "[MIM:606176]: A form of diabetes.", "Insulin family", "3630;",
     "HGNC:6081;", "ENST00000381330;ENSP00000370680;ENSG00000254647;"],

    # MT-CO1 — mitochondrial, universal
    ["P00395", "COX1_HUMAN", "MT-CO1", "COI COX1",
     "Cytochrome c oxidase subunit 1 (EC 7.1.1.9)", "513", "57,001",
     "SUBCELLULAR LOCATION: Mitochondrion inner membrane; Multi-pass "
     "membrane protein.",
     "Electron transport;Membrane;Mitochondrion;Respiratory chain",
     "mitochondrial inner membrane [GO:0005743]",
     "7.1.1.9", "", "Heme-copper respiratory oxidase family", "4512;",
     "HGNC:7419;", "ENSP00000354499;"],

    # An unfamous one that should land outside the daily pool
    ["Q9H0A0", "NAT10_HUMAN", "NAT10", "ALP KIAA1709",
     "RNA cytidine acetyltransferase (EC 2.3.1.-)", "1025", "115,724",
     "SUBCELLULAR LOCATION: Nucleus, nucleolus.",
     "Acyltransferase;Nucleus;RNA-binding;Transferase",
     "nucleolus [GO:0005730]; RNA binding", "2.3.1.-", "",
     "RNA cytidine acetyltransferase family", "55226;", "HGNC:29830;",
     "ENST00000268695;ENSP00000268695;ENSG00000135372;"],

    # No gene symbol — must be dropped by build.py
    ["P0DTC2", "SPIKE_TEST", "", "", "Test entry with no gene symbol",
     "1273", "141,178", "SUBCELLULAR LOCATION: Virion membrane.",
     "Membrane", "", "", "", "", "", "", ""],
]

GENE2PUBMED = [
    ("9606", "7157", 9000),    # TP53 — most-studied gene
    ("9606", "1956", 5000),    # EGFR
    ("9606", "60", 3000),      # ACTB
    ("9606", "3630", 4000),    # INS
    ("9606", "4512", 400),     # MT-CO1
    ("9606", "55226", 60),     # NAT10
    ("10090", "22059", 50),    # mouse Trp53 — must be filtered out
]

GENE_INFO = [
    ("7157", "TP53", "BCC7|LFS1|P53|TRP53", "tumor protein p53"),
    ("1956", "EGFR", "ERBB|ERBB1|HER1|mENA", "epidermal growth factor receptor"),
    ("60", "ACTB", "BRWS1|PS1TP5BP1", "actin beta"),
    ("3630", "INS", "IDDM2|ILPR|IRDN", "insulin"),
    ("4512", "MT-CO1", "COI|COX1|MTCO1", "mitochondrially encoded "
                                          "cytochrome c oxidase I"),
    ("55226", "NAT10", "ALP|KIAA1709", "N-acetyltransferase 10"),
]

# accession, pathway stable id, url, event name, evidence, species
REACTOME_MAP = [
    ("P04637", "R-HSA-5633007", "-", "Regulation of TP53 Activity", "TAS",
     "Homo sapiens"),
    ("P04637", "R-HSA-73857", "-", "RNA Polymerase II Transcription", "TAS",
     "Homo sapiens"),
    ("P00533", "R-HSA-177929", "-", "Signaling by EGFR", "TAS",
     "Homo sapiens"),
    ("P60709", "R-HSA-2029482", "-", "Regulation of actin dynamics", "TAS",
     "Homo sapiens"),
    ("P01308", "R-HSA-74749", "-", "Signal attenuation", "TAS",
     "Homo sapiens"),
    ("P00395", "R-HSA-611105", "-", "Respiratory electron transport", "TAS",
     "Homo sapiens"),
    ("Q9H0A0", "R-HSA-8876725", "-", "Protein methylation", "TAS",
     "Homo sapiens"),
    # a non-human row that must be filtered
    ("P02769", "R-BTA-114608", "-", "Platelet degranulation", "IEA",
     "Bos taurus"),
]

# child -> parent, so to_top() has something to walk
REACTOME_RELATION = [
    ("R-HSA-162582", "R-HSA-5633007"),   # Signal Transduction -> Reg of TP53
    ("R-HSA-74160", "R-HSA-73857"),      # Gene expression -> RNAPII
    ("R-HSA-162582", "R-HSA-177929"),    # Signal Transduction -> EGFR
    ("R-HSA-1430728", "R-HSA-611105"),   # Metabolism -> Resp electron
]

REACTOME_NAMES = [
    ("R-HSA-162582", "Signal Transduction", "Homo sapiens"),
    ("R-HSA-74160", "Gene expression (Transcription)", "Homo sapiens"),
    ("R-HSA-1430728", "Metabolism", "Homo sapiens"),
    ("R-HSA-5633007", "Regulation of TP53 Activity", "Homo sapiens"),
    ("R-HSA-73857", "RNA Polymerase II Transcription", "Homo sapiens"),
    ("R-HSA-177929", "Signaling by EGFR", "Homo sapiens"),
    ("R-HSA-2029482", "Regulation of actin dynamics", "Homo sapiens"),
    ("R-HSA-74749", "Signal attenuation", "Homo sapiens"),
    ("R-HSA-611105", "Respiratory electron transport", "Homo sapiens"),
    ("R-HSA-8876725", "Protein methylation", "Homo sapiens"),
]

HGNC_ROWS = [
    ("HGNC:11998", "TP53", "17p13.1", "P04637"),
    ("HGNC:3236", "EGFR", "7p11.2", "P00533"),
    ("HGNC:132", "ACTB", "7p22.1", "P60709"),
    ("HGNC:6081", "INS", "11p15.5", "P01308"),
    ("HGNC:7419", "MT-CO1", "mitochondria", "P00395"),
    ("HGNC:29830", "NAT10", "11q22.1", "Q9H0A0"),
]

GENE_AGES = [
    ("P04637", "Vertebrata"),
    ("P00533", "Eumetazoa"),
    ("P60709", "Eukaryota"),
    ("P01308", "Vertebrata"),
    ("P00395", "Cellular_organisms"),
    ("Q9H0A0", "Euk_Archaea"),
]


def write_tsv_gz(path, header, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        if header:
            fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")


def write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        if header:
            fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")


def build_fixture():
    FIXTURE.mkdir(parents=True, exist_ok=True)

    write_tsv_gz(FIXTURE / "uniprot_human.tsv.gz",
                 UNIPROT_HEADER, UNIPROT_ROWS)

    g2p_rows = []
    for tax, gene, n in GENE2PUBMED:
        for i in range(n):
            g2p_rows.append((tax, gene, 10_000_000 + i))
    write_tsv_gz(FIXTURE / "gene2pubmed.gz", ["#tax_id", "GeneID",
                                              "PubMed_ID"], g2p_rows)

    gi_rows = []
    for geneid, symbol, syns, desc in GENE_INFO:
        gi_rows.append(("9606", geneid, symbol, "-", syns, "-", "-", "-",
                        desc, "protein-coding", symbol, desc, "O", "-",
                        "20260801", "-"))
    write_tsv_gz(FIXTURE / "Homo_sapiens.gene_info.gz",
                 ["#tax_id"] + ["c"] * 15, gi_rows)

    write_tsv(FIXTURE / "UniProt2Reactome_All_Levels.txt", None, REACTOME_MAP)
    write_tsv(FIXTURE / "ReactomePathwaysRelation.txt", None,
              REACTOME_RELATION)
    write_tsv(FIXTURE / "ReactomePathways.txt", None, REACTOME_NAMES)

    # HGNC has 54 columns; only four matter, so pad the rest.
    hgnc_header = ["hgnc_id", "symbol", "location", "uniprot_ids"] + \
                  [f"pad{i}" for i in range(50)]
    hgnc_rows = [list(r) + [""] * 50 for r in HGNC_ROWS]
    write_tsv(FIXTURE / "hgnc_complete_set.txt", hgnc_header, hgnc_rows)

    with open(FIXTURE / "main_HUMAN.csv", "w", encoding="utf-8",
              newline="") as fh:
        fh.write("UniProt_acc,modeAge,NumDBsContributing\n")
        for acc, age in GENE_AGES:
            fh.write(f"{acc},{age},13\n")

    print(f"Fixture written to {FIXTURE}")
    for p in sorted(FIXTURE.iterdir()):
        print(f"  {p.name:<38} {p.stat().st_size:>8,} bytes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true",
                    help="build from the fixture (swaps data/raw aside)")
    args = ap.parse_args()

    build_fixture()
    if not args.run:
        print("\nRe-run with --run to build from it.\n")
        return 0

    # Point the pipeline at the fixture by swapping the RAW dir.
    real_raw = config.RAW
    stash = config.ROOT / "data" / "_raw_real"
    swapped = False
    if real_raw.exists() and any(real_raw.iterdir()):
        real_raw.rename(stash)
        swapped = True
    if real_raw.exists():
        real_raw.rmdir()
    shutil.copytree(FIXTURE, real_raw)

    try:
        import importlib
        import parsers, build  # noqa: E402
        importlib.reload(parsers)
        importlib.reload(build)
        rc = build.build()
    finally:
        shutil.rmtree(real_raw, ignore_errors=True)
        if swapped:
            stash.rename(real_raw)
        else:
            real_raw.mkdir(parents=True, exist_ok=True)

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
