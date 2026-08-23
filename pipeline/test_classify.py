"""
Regression tests for the annotation rules.

    python pipeline/test_classify.py

Every case in here is a bug that actually happened. Add to it whenever a
protein shows up in the game with a category that makes you wince.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parsers import (  # noqa: E402
    classify_function, clean_location, bucket_locations,
    _chromosome_from_locus, _disease_names, short_protein_name,
)

FAILED = []


def check(label, got, want):
    ok = got == want
    if not ok:
        FAILED.append(f"{label}\n      got  {got!r}\n      want {want!r}")
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}")


def check_not(label, got, forbidden):
    ok = got != forbidden
    if not ok:
        FAILED.append(f"{label}\n      got the forbidden value {got!r}")
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}")


print("\nfunctional class\n")

# 'actin' must not fire on 'interacting'. This mis-filed a large number of
# adapter proteins as Structural.
check_not("'interacting protein' is not Structural",
          classify_function(["Signal"], "", "Ras-interacting protein 1", ""),
          "Structural")

# DELIBERATE REVERSAL. This used to assert that "Actin-binding LIM protein
# 1" is Structural, on the strength of the "Cytoskeleton" keyword. Both
# halves of that have since been withdrawn on purpose:
#
#   - "actin-binding" describes what the protein binds, not what it is, so
#     NOT_A_MODIFIER declines it (same rule that stops "TNF receptor-
#     associated factor 6" being a Receptor); and
#   - the "Cytoskeleton" keyword is no longer a Structural rule at all,
#     because it is a LOCATION and on its own it made 759 proteins
#     Structural, BCL2L1 and cyclin B1 among them.
#
# The proteins this test was really protecting are still Structural, but
# by name rather than by association -- see the FLNA/CFL1/CLTC block
# below. An "X-binding protein" with no other signal now says "Other",
# which is the honest answer.
check("'actin-binding protein' alone is not enough for Structural",
      classify_function(["Cytoskeleton"], "", "Actin-binding LIM protein 1",
                        ""),
      "Other")

# 'antigen' fired on 'Cellular tumor antigen p53' and made TP53 an immune
# protein, which is the single most embarrassing possible bug here.
check_not("p53 is not Immune",
          classify_function([], "", "Cellular tumor antigen p53", ""),
          "Immune")
check("p53 is a Transcription factor",
      classify_function(["DNA-binding", "Transcription", "Activator"], "",
                        "Cellular tumor antigen p53", ""),
      "Transcription factor")

# Name beats EC: formally a kinase, but everyone calls it a receptor.
check("EGFR is a Receptor",
      classify_function(["Kinase", "Receptor"], "2.7.10.1",
                        "Epidermal growth factor receptor", ""),
      "Receptor")

# Name beats EC the other way: EC 7 is translocase, but this is an enzyme.
check("cytochrome c oxidase is an Enzyme",
      classify_function(["Electron transport"], "7.1.1.9",
                        "Cytochrome c oxidase subunit 1", ""),
      "Enzyme (other)")

# A broad keyword must not hijack a class. 'transferase' used to be in the
# Kinase keyword list and captured every acetyl-/methyltransferase.
check("acetyltransferase is not a Kinase",
      classify_function(["Transferase", "Acyltransferase"], "2.3.1.-",
                        "RNA cytidine acetyltransferase", ""),
      "Enzyme (other)")

check("MMP-9 is a Protease",
      classify_function([], "3.4.24.35", "Matrix metalloproteinase-9", ""),
      "Protease")
check("interleukin is Signalling",
      classify_function(["Cytokine"], "", "Interleukin-6", ""),
      "Signalling")
check("a plain kinase is a Kinase",
      classify_function([], "2.7.11.1", "Serine/threonine-protein kinase mTOR",
                        ""),
      "Kinase")
check("aquaporin is an Ion channel",
      classify_function(["Transport"], "", "Aquaporin-1", ""),
      "Ion channel")


# ---- NOT_A_MODIFIER: a name pattern must not fire on a modifier ----
#
# Every pair below is one case the guard has to fix and one it must not
# break. The "must not break" half is the point: the guard works per
# OCCURRENCE, so a name that uses the word both ways still matches on the
# good one.

check("GRB2 is not a Receptor",
      classify_function([], "", "Growth factor receptor-bound protein 2", ""),
      "Signalling")
check("TLR2 is still a Receptor",
      classify_function(["Receptor"], "",
                        "Toll-like receptor 2 (Toll/interleukin-1 "
                        "receptor-like protein 4)", ""),
      "Receptor")
check("IL1RL1 is still a Receptor ('-like' is not a demoting suffix)",
      classify_function(["Receptor"], "", "Interleukin-1 receptor-like 1", ""),
      "Receptor")
check_not("'kinase-associated' is not a Kinase",
          classify_function([], "", "S-phase kinase-associated protein 1", ""),
          "Kinase")
check("a real kinase is untouched",
      classify_function([], "2.7.11.1", "Serine/threonine-protein kinase ATR",
                        ""),
      "Kinase")
check_not("'actin-dependent regulator' is not Structural",
          classify_function(["Chromatin regulator"], "",
                            "SWI/SNF-related matrix-associated actin-dependent "
                            "regulator of chromatin subfamily B member 1", ""),
          "Structural")
check("actin itself is still Structural",
      classify_function([], "", "Actin, aortic smooth muscle", ""),
      "Structural")
check_not("'DNA damage-inducible' is not DNA repair",
          classify_function(["Transcription"], "",
                            "DNA damage-inducible transcript 3 protein", ""),
          "DNA repair")
check("a real repair protein is untouched",
      classify_function(["DNA repair"], "", "DNA repair protein XRCC1", ""),
      "DNA repair")


# ---- WORD_GUARDS: a pattern must not fire inside a longer word ----

check("cytokinesis is not a cytokine",
      classify_function([], "", "Protein regulator of cytokinesis 1", ""),
      "Other")
check("a real cytokine still is one",
      classify_function(["Cytokine"], "", "Interleukin-8", ""),
      "Signalling")
# ADAMTS13 is a daily answer. "...with thrombospondin motifs" made it a
# Structural protein when STRUCTURAL_NAMES first went in.
check("ADAMTS13 is a Protease, not a thrombospondin",
      classify_function([], "3.4.24.87",
                        "A disintegrin and metalloproteinase with "
                        "thrombospondin motifs 13", ""),
      "Protease")
check("thrombospondin-1 is still Structural",
      classify_function([], "", "Thrombospondin-1 (Glycoprotein G)", ""),
      "Structural")
check("FNDC5 is Signalling, not a fibronectin",
      classify_function(["Cytokine"], "",
                        "Fibronectin type III domain-containing protein 5", ""),
      "Signalling")
check("fibronectin itself is Structural",
      classify_function([], "", "Fibronectin (FN) (Cold-insoluble globulin)",
                        ""),
      "Structural")
check("aggrecanase is a Protease, not an aggrecan",
      classify_function([], "3.4.24.82",
                        "A disintegrin and metalloproteinase with "
                        "thrombospondin motifs 5 (Aggrecanase-2)", ""),
      "Protease")


# ---- Structural: keywords out, names in ----
#
# "Cytoskeleton" and "Cell adhesion" are location and process keywords. On
# their own they made 994 proteins Structural, including these three.

for _gene, _name, _kw in [
    ("BCL2L1", "Bcl-2-like protein 1 (Apoptosis regulator Bcl-X)",
     ["Cytoskeleton"]),
    ("CCNB1", "G2/mitotic-specific cyclin-B1", ["Cytoskeleton"]),
    ("CKAP4", "Cytoskeleton-associated protein 4", ["Cytoskeleton"]),
]:
    check_not(f"{_gene} is not Structural",
              classify_function(_kw, "", _name, ""), "Structural")

# ...but the class must still hold the proteins that really are structural,
# which is why deleting the keywords alone was not the fix.
for _gene, _name in [
    ("VIM", "Vimentin"),
    ("DMD", "Dystrophin"),
    ("DES", "Desmin"),
    ("FLNA", "Filamin-A (Actin-binding protein 280)"),
    ("CFL1", "Cofilin-1"),
    ("CLTC", "Clathrin heavy chain 1"),
]:
    check(f"{_gene} is still Structural",
          classify_function([], "", _name, ""), "Structural")

# beta-catenin must NOT be dragged in with alpha-catenin.
check("CTNNB1 stays a Transcription factor",
      classify_function(["Transcription", "Activator"], "", "Catenin beta-1",
                        ""),
      "Transcription factor")
check("CTNNA1 is Structural",
      classify_function([], "", "Catenin alpha-1 (Alpha E-catenin)", ""),
      "Structural")


# ---- Chromatin ----

check("HDAC6 is Chromatin, not a tubulin",
      classify_function([], "3.5.1.-", "Protein deacetylase HDAC6", ""),
      "Chromatin")
check("histones are Chromatin",
      classify_function([], "", "Histone H4", ""), "Chromatin")
check("EZH2 is Chromatin, not a generic enzyme",
      classify_function([], "2.1.1.356",
                        "Histone-lysine N-methyltransferase EZH2", ""),
      "Chromatin")
# The substrate qualifiers earn their keep: these two are not chromatin.
check("NAT2 is an Enzyme, not Chromatin",
      classify_function(["Transferase"], "2.3.1.5",
                        "Arylamine N-acetyltransferase 2", ""),
      "Enzyme (other)")
check("ESD is an Enzyme, not Chromatin",
      classify_function([], "3.1.2.12",
                        "S-formylglutathione hydrolase (Esterase D) "
                        "(Methylumbelliferyl-acetate deacetylase)", ""),
      "Enzyme (other)")


# ---- Section D: small GTPases, and 'atpase' ----

check("RHOA is Signalling like the other small GTPases",
      classify_function([], "3.6.5.2", "Transforming protein RhoA", ""),
      "Signalling")
check("HRAS is unchanged",
      classify_function([], "3.6.5.2", "GTPase HRas", ""), "Signalling")
check_not("VCP is not a Transporter",
          classify_function([], "3.6.4.6",
                            "Transitional endoplasmic reticulum ATPase", ""),
          "Transporter")
check_not("a proteasome subunit is not a Transporter",
          classify_function([], "",
                            "26S proteasome regulatory subunit 4 "
                            "(26S proteasome AAA-ATPase subunit RPT2)", ""),
          "Transporter")
check("a real pump is still a Transporter",
      classify_function(["Ion transport"], "7.2.2.13",
                        "Sodium/potassium-transporting ATPase subunit alpha-1",
                        ""),
      "Transporter")


print("\nchromosome parsing\n")

# The original regex used \b after the digits, which never matches in
# '17p13.1' because '7' and 'p' are both word characters.
for locus, want in [
    ("17p13.1", "17"), ("11q22.1", "11"), ("7p22.1", "7"),
    ("Xq28", "X"), ("Yq11.222", "Y"), ("19", "19"),
    ("1p36.33", "1"), ("22q11.21", "22"), ("mitochondria", "MT"),
    ("unplaced", None), ("", None), ("reserved", None),
]:
    check(f"{locus!r} -> {want!r}", _chromosome_from_locus(locus), want)


print("\nsubcellular location\n")

check("ECO evidence codes are stripped",
      clean_location("SUBCELLULAR LOCATION: Nucleus {ECO:0000269|PubMed:1}. "
                     "Cytoplasm."),
      ["Nucleus", "Cytoplasm"])
check("topology qualifiers are dropped",
      clean_location("SUBCELLULAR LOCATION: Cell membrane; Single-pass type I "
                     "membrane protein."),
      ["Cell membrane"])
check("Note= tail is dropped",
      clean_location("SUBCELLULAR LOCATION: Nucleus. Note=Shuttles between "
                     "the nucleus and the cytoplasm during mitosis."),
      ["Nucleus"])
check("mitochondrion buckets correctly",
      bucket_locations(["Mitochondrion inner membrane"]),
      ["Mitochondrion"])
# UniProt's own ordering is preserved: the curator puts the primary
# location first. An earlier version reordered by a hand-written
# "specificity" ranking and produced the three disasters below.
check("UniProt ordering is preserved",
      bucket_locations(["Nucleus", "Cytoplasm", "Secreted"]),
      ["Nucleus", "Cytoplasm", "Secreted"])

# TP53 used to come out as Mitochondrion + ER + Cytoskeleton, with Nucleus
# dropped entirely, because reordering promoted three incidental
# annotations above the two that matter.
check("TP53 keeps Nucleus",
      bucket_locations(["Cytoplasm", "Nucleus", "Nucleus, PML body",
                        "Endoplasmic reticulum", "Mitochondrion matrix",
                        "Cytoplasm, cytoskeleton, microtubule organizing "
                        "center, centrosome"]),
      ["Cytoplasm", "Nucleus", "ER"])

# EGFR used to lose Cell membrane — for a cell-surface receptor.
check("EGFR leads with Cell membrane",
      bucket_locations(["Cell membrane", "Endoplasmic reticulum membrane",
                        "Golgi apparatus membrane", "Nucleus membrane",
                        "Endosome"]),
      ["Cell membrane", "ER", "Golgi"])

# MTOR was labelled Mitochondrion off one minor annotation, when its first
# and defining location is the lysosomal membrane.
check("MTOR leads with Lysosome",
      bucket_locations(["Lysosome membrane", "Cytoplasmic side",
                        "Endoplasmic reticulum membrane",
                        "Golgi apparatus membrane", "Mitochondrion outer "
                        "membrane"]),
      ["Lysosome", "Cytoplasm", "ER"])

check("one location maps to exactly one bucket",
      bucket_locations(["Cytoplasm, cytoskeleton"]), ["Cytoskeleton"])
check("duplicates collapse",
      bucket_locations(["Nucleus", "Nucleus, nucleolus", "Nucleus speckle"]),
      ["Nucleus"])
check("the cap is respected",
      len(bucket_locations(["Secreted", "Nucleus", "Cytoplasm",
                            "Mitochondrion", "Golgi"])), 3)
check("unknown location falls back",
      bucket_locations(["Virion"]), ["Other"])
check("no annotation yields no buckets",
      bucket_locations([]), [])


print("\nprotein name shortening\n")

check("parenthesised alternatives are cut",
      short_protein_name("Epidermal growth factor receptor (EC 2.7.10.1) "
                         "(Proto-oncogene c-ErbB-1)"),
      "Epidermal growth factor receptor")
# INS rendered as "Insulin [Cleaved into: Insulin B chain; Insuli..." on the
# board until the shortener learned about square brackets too.
check("processed-chain lists are cut",
      short_protein_name("Insulin [Cleaved into: Insulin B chain; "
                         "Insulin A chain]"),
      "Insulin")
check("a plain name is untouched",
      short_protein_name("Cellular tumor antigen p53"),
      "Cellular tumor antigen p53")
# The other kind of square bracket: part of the name, not a suffix. This
# one shipped as "Poly" on the board, along with 176 others.
check("brackets inside a name are kept",
      short_protein_name("Poly [ADP-ribose] polymerase 1 (PARP-1) "
                         "(EC 2.4.2.30)"),
      "Poly [ADP-ribose] polymerase 1")
check("a cofactor bracket is kept",
      short_protein_name("Superoxide dismutase [Cu-Zn] (EC 1.15.1.1)"),
      "Superoxide dismutase [Cu-Zn]")
check("a parenthesis inside a bracket does not cut",
      short_protein_name("All-trans-retinol dehydrogenase [NAD(+)] ADH1B "
                         "(EC 1.1.1.105)"),
      "All-trans-retinol dehydrogenase [NAD(+)] ADH1B")
# Parentheses are the same trap and the more common one: part of the name
# far more often than not. DNMT1 shipped as "DNA" and DRD2 as "D".
check("a parenthesis inside a name is kept",
      short_protein_name("DNA (cytosine-5)-methyltransferase 1"),
      "DNA (cytosine-5)-methyltransferase 1")
check("a leading parenthesised number is kept",
      short_protein_name("D(2) dopamine receptor (Dopamine D2 receptor)"),
      "D(2) dopamine receptor")
# COL1A1, COL2A1 and COL3A1 all rendered as "Collagen alpha-1".
check("collagen chain numbers survive",
      short_protein_name("Collagen alpha-1(II) chain"),
      "Collagen alpha-1(II) chain")
check("trailing alternative names are still cut",
      short_protein_name("Epidermal growth factor receptor (EC 2.7.10.1) "
                         "(Proto-oncogene c-ErbB-1)"),
      "Epidermal growth factor receptor")
check("an Includes list is cut",
      short_protein_name("N-glycosylase/DNA lyase [Includes: 8-oxoguanine "
                         "DNA glycosylase (EC 3.2.2.-)]"),
      "N-glycosylase/DNA lyase")


print("\ninhibitors and ligands\n")

# p21 and p27 were classified "Kinase" — they inhibit kinases.
for name in ("Cyclin-dependent kinase inhibitor 1",
             "Cyclin-dependent kinase 4 inhibitor B",
             "Metalloproteinase inhibitor 1"):
    check(f"{name!r} is an inhibitor",
          classify_function([], "", name, ""), "Inhibitor")
check("a protease-inhibitor keyword does not mean protease",
      classify_function(["Protease inhibitor"], "", "Alpha-1-antitrypsin", ""),
      "Inhibitor")
# ...but IKK really is a kinase, and the name says "inhibitor" too.
check("inhibitor OF a thing is not an inhibitor of the enzyme",
      classify_function(["Kinase"], "2.7.11.10",
                        "Inhibitor of nuclear factor kappa-B kinase "
                        "subunit beta", ""),
      "Kinase")

# PD-L1, FasL and RANKL were all "Receptor"; FLT3LG was "Kinase".
for name in ("Programmed cell death 1 ligand 1",
             "Tumor necrosis factor ligand superfamily member 11",
             "Fms-related tyrosine kinase 3 ligand"):
    check(f"{name!r} is a ligand",
          classify_function([], "", name, ""), "Signalling")
check("a receptor is still a receptor",
      classify_function([], "2.7.10.1", "Fibroblast growth factor receptor 1",
                        ""),
      "Receptor")
check("ligand-dependent is not a ligand",
      classify_function([], "", "Ligand-dependent corepressor", "")
      != "Signalling", True)


print("\ndisease\n")

check("MIM-anchored disease names are extracted",
      _disease_names("DISEASE: Li-Fraumeni syndrome (LFS) [MIM:151623]: A "
                     "rare autosomal dominant disorder."),
      ["Li-Fraumeni syndrome"])
check("a Note-only DISEASE block yields nothing",
      _disease_names("DISEASE: Note=Defects may be a cause of cancer."),
      [])


print()
if FAILED:
    print(f"{len(FAILED)} FAILURE(S):\n")
    for f in FAILED:
        print(f"  - {f}")
    print()
    raise SystemExit(1)
print("All rule tests passed.\n")
