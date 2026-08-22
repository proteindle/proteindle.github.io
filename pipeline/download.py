"""
Download every raw source into data/raw/.

Run this on a machine with normal internet access:

    python pipeline/download.py
    python pipeline/download.py --only uniprot        # retry one source
    python pipeline/download.py --with-eggnog         # + ~920 MB
    python pipeline/download.py --force               # ignore what is on disk

Pure stdlib, so `python` is the only requirement.

Resilience notes, all of which are here because they actually bit:

  * UniProt's /stream endpoint sends one enormous chunked response and
    drops it often enough to be unusable on a corporate network. We use
    /search with cursor pagination instead: ~41 small requests, each
    independently retryable, and a half-finished run resumes at the page
    it died on.
  * Big flat files (gene2pubmed, Reactome) resume with an HTTP Range
    request against the .part file rather than starting over.
  * http.client.IncompleteRead subclasses HTTPException, NOT OSError, so
    a narrow `except (URLError, IOError)` misses it entirely and the whole
    script dies. Everything network-shaped is caught broadly now.
  * One dead source must never abort the others.
"""

import argparse
import gzip
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (  # noqa: E402
    RAW, SOURCES, OPTIONAL_SOURCES, UNIPROT_FIELDS,
)

UA = "Proteindle/1.0 (dataset build)"
MIN_PLAUSIBLE_BYTES = 1024

# Entries per UniProt page. The GO column is enormous, so 500 entries can
# be ~1 MB — big enough for a lossy connection to drop. 200 keeps each
# request small; the extra round trips cost seconds. Lower it further with
# --page-size if pages still fail.
PAGE_SIZE = 200

UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
UNIPROT_QUERY = "(reviewed:true) AND (organism_id:9606)"


def human(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def progress(msg):
    print(msg.ljust(78), end="\r", flush=True)


def done(msg):
    print(msg.ljust(78))


def opener(url, headers=None, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


# --------------------------------------------------------------- generic

def download_plain(name, url, dest, force=False, retries=5):
    """
    Straight file download with byte-range resume.

    A partially written .part file is kept between attempts and the next
    attempt asks the server to continue from that offset. Servers that do
    not honour Range just send 200 and we start clean.
    """
    if dest.exists() and dest.stat().st_size > MIN_PLAUSIBLE_BYTES and not force:
        done(f"  [skip] {name}  ({human(dest.stat().st_size)} on disk)")
        return True

    tmp = dest.with_name(dest.name + ".part")
    if force and tmp.exists():
        tmp.unlink()

    for attempt in range(1, retries + 1):
        have = tmp.stat().st_size if tmp.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        mode = "ab" if have else "wb"

        try:
            started = time.time()
            with opener(url, headers) as resp:
                if have and resp.status != 206:
                    # Server ignored the Range header; restart cleanly.
                    have, mode = 0, "wb"
                total = resp.headers.get("Content-Length")
                total = (int(total) + have) if total else None

                got = have
                last = 0.0
                with open(tmp, mode) as fh:
                    while True:
                        chunk = resp.read(1 << 16)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        now = time.time()
                        if now - last > 0.4:
                            last = now
                            if total:
                                progress(f"  [get ] {name}  {human(got)}"
                                         f" / {human(total)}"
                                         f"  ({100.0 * got / total:.0f}%)")
                            else:
                                progress(f"  [get ] {name}  {human(got)}")

            if got < MIN_PLAUSIBLE_BYTES:
                raise IOError(f"suspiciously small ({got} bytes)")
            if total and got < total:
                raise IOError(f"short read: {got} of {total}")

            tmp.replace(dest)
            done(f"  [ok  ] {name}  {human(got)} in {time.time() - started:.0f}s")
            return True

        except Exception as exc:               # noqa: BLE001 — see module docstring
            kept = tmp.stat().st_size if tmp.exists() else 0
            done(f"  [warn] {name} attempt {attempt}/{retries}: "
                 f"{type(exc).__name__}: {exc}"
                 + (f"  (kept {human(kept)}, will resume)" if kept else ""))
            if attempt < retries:
                time.sleep(min(3 * attempt, 15))

    done(f"  [FAIL] {name} — gave up after {retries} attempts")
    return False


# --------------------------------------------------------------- UniProt

# RFC 5988 separates multiple links with commas — but the URL itself may
# contain commas, and UniProt's does: `fields=accession,id,gene_primary,...`.
# Splitting the header on ',' therefore chops the next-page URL in half and
# yields a fragment like 'xref_ensembl&query=...', which urllib rejects as
# "unknown url type". Anchor on the angle brackets instead: <...> cannot
# contain a '>', so this is unambiguous regardless of the URL's contents.
_NEXT_LINK_RE = re.compile(r'<([^>]+)>\s*;\s*rel\s*=\s*"?next"?')


def parse_next_link(link_header):
    """Extract the rel="next" URL from an RFC 5988 Link header."""
    if not link_header:
        return None
    m = _NEXT_LINK_RE.search(link_header)
    return m.group(1).strip() if m else None


def download_uniprot(name, dest, force=False, retries=5):
    """
    Cursor-paginated fetch of the reviewed human proteome.

    Each page is an independent request, so a dropped connection costs one
    page rather than the whole 20,000-row response. Pages are appended to
    a .part gzip; a resumed run re-fetches from the first page but that is
    ~40 cheap requests, not a 20 MB single shot.
    """
    if dest.exists() and dest.stat().st_size > MIN_PLAUSIBLE_BYTES and not force:
        done(f"  [skip] {name}  ({human(dest.stat().st_size)} on disk)")
        return True

    params = (
        f"?format=tsv&size={PAGE_SIZE}"
        f"&query={urllib.parse.quote(UNIPROT_QUERY)}"
        f"&fields={','.join(UNIPROT_FIELDS)}"
    )
    url = UNIPROT_SEARCH + params

    tmp = dest.with_name(dest.name + ".part")
    ckpt = dest.with_name(dest.name + ".cursor")

    # Resume: gzip members concatenate legally, so each page can be appended
    # as its own member and the reader stitches them back together. The
    # checkpoint file holds the URL of the page we have NOT yet written.
    resumed_rows = 0
    if force:
        for p in (tmp, ckpt):
            if p.exists():
                p.unlink()
    elif ckpt.exists() and tmp.exists():
        try:
            saved_url, saved_rows = ckpt.read_text(encoding="utf-8").split("\n")[:2]
            saved_url = saved_url.strip()
            # A checkpoint is only trustworthy if it holds an absolute URL.
            # A buggy Link parser once wrote a URL fragment here, and
            # resuming from it failed identically on every later run — a
            # poisoned checkpoint is worse than no checkpoint.
            if saved_url.startswith(("http://", "https://")):
                url = saved_url
                resumed_rows = int(saved_rows)
                done(f"  [rsme] {name}  resuming at {resumed_rows:,} entries")
            else:
                done(f"  [warn] {name}  discarding an unusable checkpoint, "
                     f"starting over")
                tmp.unlink(missing_ok=True)
                ckpt.unlink(missing_ok=True)
        except Exception:                          # noqa: BLE001
            tmp.unlink(missing_ok=True)
            ckpt.unlink(missing_ok=True)

    started = time.time()
    total_expected = None
    rows = resumed_rows
    page = 0
    fresh = resumed_rows == 0
    if fresh:
        tmp.unlink(missing_ok=True)

    try:
        with gzip.open(tmp, "wt" if fresh else "at",
                       encoding="utf-8", newline="") as out:
            while url:
                page += 1
                text = None

                for attempt in range(1, retries + 1):
                    try:
                        with opener(url, timeout=120) as resp:
                            if total_expected is None:
                                hdr = resp.headers.get("x-total-results")
                                total_expected = int(hdr) if hdr else None
                            raw = resp.read()
                            next_url = parse_next_link(resp.headers.get("Link"))
                        text = raw.decode("utf-8", errors="replace")
                        break
                    except Exception as exc:      # noqa: BLE001
                        done(f"  [warn] {name} page {page} attempt "
                             f"{attempt}/{retries}: {type(exc).__name__}: {exc}")
                        if attempt == retries:
                            raise
                        time.sleep(min(2 * attempt, 10))

                lines = text.splitlines()
                if not lines:
                    break

                # Every page repeats the header row; keep only the first.
                if fresh and page == 1:
                    out.write(lines[0] + "\n")
                body = lines[1:]
                for line in body:
                    out.write(line + "\n")
                rows += len(body)

                # Flush and checkpoint so an abort resumes from here rather
                # than from page one.
                out.flush()
                ckpt.write_text(f"{next_url or ''}\n{rows}\n", encoding="utf-8")

                if total_expected:
                    progress(f"  [get ] {name}  {rows:,} / {total_expected:,} "
                             f"entries  (page {page})")
                else:
                    progress(f"  [get ] {name}  {rows:,} entries "
                             f"(page {page})")

                url = next_url

    except Exception as exc:                       # noqa: BLE001
        done(f"  [FAIL] {name} — {type(exc).__name__}: {exc}")
        if rows > resumed_rows:
            done(f"         kept {rows:,} entries — re-run to resume")
        return False

    if rows < 1000:
        done(f"  [FAIL] {name} — only {rows} entries, expected ~20,400")
        tmp.unlink(missing_ok=True)
        ckpt.unlink(missing_ok=True)
        return False

    tmp.replace(dest)
    ckpt.unlink(missing_ok=True)
    done(f"  [ok  ] {name}  {rows:,} entries, {human(dest.stat().st_size)} "
         f"in {time.time() - started:.0f}s")
    if total_expected and rows < total_expected:
        done(f"  [warn] {name} — got {rows:,} of {total_expected:,} "
             f"advertised entries")
    return True


# ---------------------------------------------------------------- verify

EXPECTED_HEADERS = {
    "uniprot_human.tsv.gz": "Entry",
    "gene2pubmed.gz": "#tax_id",
    "Homo_sapiens.gene_info.gz": "#tax_id",
    "hgnc_complete_set.txt": "hgnc_id",
    # Gene-Ages is a pandas dump with the accession in an UNNAMED index
    # column, so its header starts with a bare comma and there is no
    # "UniProt_acc" to look for. Anchor on an age column instead.
    "main_HUMAN.csv": "Cellular_organisms",
}

MIN_LINES = {
    "uniprot_human.tsv.gz": 1000,
    "gene2pubmed.gz": 10000,
    "Homo_sapiens.gene_info.gz": 1000,
    "UniProt2Reactome_All_Levels.txt": 10000,
    "ReactomePathwaysRelation.txt": 100,
    "ReactomePathways.txt": 100,
    "hgnc_complete_set.txt": 1000,
    "main_HUMAN.csv": 1000,
}


def verify(name):
    path = RAW / name
    if not path.exists():
        return "missing"

    try:
        op = (gzip.open(path, "rt", encoding="utf-8", errors="replace")
              if name.endswith(".gz")
              else open(path, "r", encoding="utf-8", errors="replace"))
        with op as fh:
            head = fh.readline().strip()
            count = 1
            limit = MIN_LINES.get(name, 0)
            for _ in fh:
                count += 1
                if count > limit:
                    break
    except Exception as exc:                       # noqa: BLE001
        return f"unreadable: {type(exc).__name__}: {exc}"

    low = head.lower()
    if low.startswith("<!doctype") or low.startswith("<html"):
        return "got an HTML page, not data"

    want = EXPECTED_HEADERS.get(name)
    if want and want.lower() not in low:
        return f"unexpected header (wanted {want!r}, got {head[:50]!r})"

    limit = MIN_LINES.get(name, 0)
    if limit and count <= limit:
        return f"only {count} lines, expected more than {limit}"

    return None


# ------------------------------------------------------------------ main

def main():
    global PAGE_SIZE                # must precede any use of the name here

    ap = argparse.ArgumentParser(description="Download Proteindle raw data.")
    ap.add_argument("--with-eggnog", action="store_true",
                    help="also fetch eggNOG 7 (~920 MB)")
    ap.add_argument("--force", action="store_true",
                    help="re-download files already on disk")
    ap.add_argument("--only", metavar="NAME",
                    help="download just the source whose filename contains "
                         "this (e.g. --only uniprot)")
    ap.add_argument("--page-size", type=int, default=PAGE_SIZE,
                    metavar="N",
                    help=f"UniProt entries per request (default {PAGE_SIZE}). "
                         f"Lower it if pages keep dropping on a flaky "
                         f"connection.")
    args = ap.parse_args()
    PAGE_SIZE = max(25, min(500, args.page_size))

    sources = dict(SOURCES)
    if args.with_eggnog:
        sources.update(OPTIONAL_SOURCES)
    if args.only:
        needle = args.only.lower()
        sources = {k: v for k, v in sources.items() if needle in k.lower()}
        if not sources:
            print(f"\nNothing matches --only {args.only!r}. Available:")
            for k in {**SOURCES, **OPTIONAL_SOURCES}:
                print(f"    {k}")
            print()
            return 2

    print(f"\nDownloading {len(sources)} source(s) into {RAW}\n")

    results = {}
    for name, (url, required) in sources.items():
        try:
            if name == "uniprot_human.tsv.gz":
                ok = download_uniprot(name, RAW / name, force=args.force)
            else:
                ok = download_plain(name, url, RAW / name, force=args.force)
        except KeyboardInterrupt:
            print("\n\nInterrupted. Partial downloads are kept — re-run to "
                  "resume.\n")
            return 130
        except Exception as exc:                   # noqa: BLE001
            done(f"  [FAIL] {name} — {type(exc).__name__}: {exc}")
            ok = False
        results[name] = (ok, required)

    print("\nVerifying\n")
    problems = []
    for name in sources:
        issue = verify(name)
        if issue:
            problems.append((name, issue, sources[name][1]))
            print(f"  [BAD ] {name}: {issue}")
        else:
            size = (RAW / name).stat().st_size
            print(f"  [ok  ] {name}  ({human(size)})")

    print()
    blocking = [n for n, _i, req in problems if req]
    if blocking:
        print("Missing or malformed REQUIRED sources:")
        for n in blocking:
            print(f"    {n}")
        print("\nRetry just those, e.g.:")
        print(f"    python pipeline/download.py --only "
              f"{blocking[0].split('.')[0][:14]}")
        print("\nPartial downloads are kept and will resume where they "
              "stopped.\n")
        return 1

    if problems:
        print("Some optional sources are missing; the build will fill those "
              "columns as best it can.\n")

    total = sum(p.stat().st_size for p in RAW.iterdir()
                if p.is_file() and not p.name.endswith(".part"))
    print(f"All required sources present. {human(total)} in data/raw/")
    print("\nNext:  python pipeline/build.py\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
