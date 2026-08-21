"""
Download every raw source into data/raw/.

Run this on a machine with normal internet access:

    python pipeline/download.py
    python pipeline/download.py --with-eggnog     # + ~920 MB, better coverage
    python pipeline/download.py --force           # re-download everything

Pure stdlib, so `python` is the only requirement. Resumable: a file that
already exists and is non-trivially sized is skipped unless --force.

Total download without --with-eggnog is roughly 300 MB, dominated by
Reactome (112 MB) and gene2pubmed (~150 MB).
"""

import argparse
import gzip
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import RAW, SOURCES, OPTIONAL_SOURCES  # noqa: E402

UA = "Proteindle/1.0 (dataset build; contact: local user)"
MIN_PLAUSIBLE_BYTES = 1024


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download(name, url, dest_dir, force=False, retries=3):
    dest = dest_dir / name
    if dest.exists() and dest.stat().st_size > MIN_PLAUSIBLE_BYTES and not force:
        print(f"  [skip] {name}  ({human(dest.stat().st_size)} already on disk)")
        return True

    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})

    for attempt in range(1, retries + 1):
        try:
            started = time.time()
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = resp.headers.get("Content-Length")
                total = int(total) if total else None
                got = 0
                last_print = 0.0
                with open(tmp, "wb") as fh:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if now - last_print > 0.5:
                            last_print = now
                            if total:
                                pct = 100.0 * got / total
                                msg = (f"  [get ] {name}  {human(got)}"
                                       f" / {human(total)}  ({pct:.0f}%)")
                            else:
                                msg = f"  [get ] {name}  {human(got)}"
                            print(msg.ljust(70), end="\r", flush=True)

            if got < MIN_PLAUSIBLE_BYTES:
                raise IOError(f"suspiciously small response ({got} bytes)")

            tmp.replace(dest)
            secs = time.time() - started
            print(f"  [ok  ] {name}  {human(got)} in {secs:.0f}s".ljust(70))
            return True

        except (urllib.error.URLError, urllib.error.HTTPError, IOError,
                TimeoutError) as exc:
            print(f"  [warn] {name} attempt {attempt}/{retries} failed: {exc}"
                  .ljust(70))
            if tmp.exists():
                tmp.unlink()
            if attempt < retries:
                time.sleep(3 * attempt)

    print(f"  [FAIL] {name} — could not download after {retries} attempts")
    return False


def verify(name, dest_dir):
    """Cheap sanity check that we got the file we expected, not an error page."""
    path = dest_dir / name
    if not path.exists():
        return None

    try:
        if name.endswith(".gz"):
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
                head = fh.readline().strip()
        else:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                head = fh.readline().strip()
    except Exception as exc:
        return f"unreadable: {exc}"

    if head.lower().startswith("<!doctype") or head.lower().startswith("<html"):
        return "got an HTML page instead of data (bad URL or a redirect)"

    expectations = {
        "uniprot_human.tsv.gz": "Entry",
        "gene2pubmed.gz": "#tax_id",
        "Homo_sapiens.gene_info.gz": "#tax_id",
        "hgnc_complete_set.txt": "hgnc_id",
        "main_HUMAN.csv": "UniProt",
    }
    want = expectations.get(name)
    if want and want.lower() not in head.lower():
        return f"header does not look right (expected {want!r}, got {head[:60]!r})"

    return None


def main():
    ap = argparse.ArgumentParser(description="Download Proteindle raw data.")
    ap.add_argument("--with-eggnog", action="store_true",
                    help="also fetch eggNOG 7 (~920 MB) for richer "
                         "conservation coverage")
    ap.add_argument("--force", action="store_true",
                    help="re-download files that already exist")
    args = ap.parse_args()

    sources = dict(SOURCES)
    if args.with_eggnog:
        sources.update(OPTIONAL_SOURCES)

    print(f"\nDownloading {len(sources)} sources into {RAW}\n")

    failed = []
    for name, (url, required) in sources.items():
        ok = download(name, url, RAW, force=args.force)
        if not ok and required:
            failed.append(name)

    print("\nVerifying...\n")
    problems = []
    for name in sources:
        issue = verify(name, RAW)
        if issue:
            problems.append((name, issue))
            print(f"  [BAD ] {name}: {issue}")
        elif (RAW / name).exists():
            print(f"  [ok  ] {name}")

    print()
    if failed or problems:
        print("Some sources are missing or malformed. The build will still")
        print("run on what is present, but affected columns will have gaps.")
        print("Re-run with --force to retry.")
        return 1

    total = sum(p.stat().st_size for p in RAW.iterdir() if p.is_file())
    print(f"All sources present. {human(total)} in data/raw/")
    print("\nNext:  python pipeline/build.py\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
