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
    _chromosome_from_locus, _disease_names,
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
check("actin-binding protein is Structural",
      classify_function(["Cytoskeleton"], "", "Actin-binding LIM protein 1", ""),
      "Structural")
check_not("'interacting protein' is not Structural",
          classify_function(["Signal"], "", "Ras-interacting protein 1", ""),
          "Structural")

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
check("bucket order is most-specific-first",
      bucket_locations(["Nucleus", "Cytoplasm", "Secreted"]),
      ["Secreted", "Nucleus", "Cytoplasm"])
check("unknown location falls back",
      bucket_locations(["Virion"]), ["Other"])
check("no annotation yields no buckets",
      bucket_locations([]), [])


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
