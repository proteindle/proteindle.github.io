"""
Tests for the download layer against a deliberately hostile local server.

    python pipeline/test_download.py

The real bug this exists for: UniProt's /stream dropped a chunked response
part-way through, raising http.client.IncompleteRead — which subclasses
HTTPException, not OSError, so the original `except (URLError, IOError)`
never saw it and the whole script died on source one of eight.

The mock server here reproduces that (short-write against a declared
Content-Length), plus cursor pagination and Range resume, so the retry
paths are actually executed rather than merely written.
"""

import gzip
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import download as dl  # noqa: E402

PORT = 8754
BASE = f"http://127.0.0.1:{PORT}"
FAILED = []

# How many times each flaky endpoint has been hit, so a handler can fail
# the first attempt and succeed later.
HITS = {}

TOTAL_ENTRIES = 2500
PAGE = 500
BIG_BODY = ("x" * 999 + "\n").encode() * 200        # ~200 KB


def check(label, cond, detail=""):
    if not cond:
        FAILED.append(f"{label}{(' — ' + detail) if detail else ''}")
    print(f"  [{'ok ' if cond else 'FAIL'}] {label}"
          + (f"  ({detail})" if detail and not cond else ""))


class Mock(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    # ---------------------------------------------------------- helpers
    def _count(self, key):
        HITS[key] = HITS.get(key, 0) + 1
        return HITS[key]

    # ------------------------------------------------------------- GET
    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/uniprotkb/search":
            return self._uniprot()
        if path == "/flaky-once":
            return self._flaky_once()
        if path == "/range-file":
            return self._range_file()
        if path == "/always-500":
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/html-error":
            # Padded past MIN_PLAUSIBLE_BYTES on purpose: a *small* error
            # page is already rejected at download time, so to test that
            # verify() also catches one it has to be big enough to survive
            # the size check. Real portal interstitials usually are.
            body = (b"<!DOCTYPE html><html><body>Service unavailable"
                    + b"<!-- " + b"pad " * 500 + b"-->"
                    + b"</body></html>")
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ----------------------------------------------------- uniprot mock
    def _uniprot(self):
        """Cursor pagination, and page 2 fails once to exercise the retry."""
        qs = dict(
            kv.split("=", 1) for kv in self.path.split("?", 1)[1].split("&")
            if "=" in kv
        ) if "?" in self.path else {}
        cursor = int(qs.get("cursor", "0"))

        n = self._count(f"uniprot:{cursor}")
        if cursor == PAGE and n == 1:
            # Kill page 2 on its first attempt: declare a length, send less.
            body = b"Entry\tGene\n" + b"P00001\tAAA\n" * 10
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) * 4))
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True
            return

        rows = []
        for i in range(cursor, min(cursor + PAGE, TOTAL_ENTRIES)):
            rows.append(f"P{i:05d}\tGENE{i}\tprotein {i}")
        body = ("Entry\tGene Names (primary)\tProtein names\n"
                + "\n".join(rows) + "\n").encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-total-results", str(TOTAL_ENTRIES))
        nxt = cursor + PAGE
        if nxt < TOTAL_ENTRIES:
            # Shaped like the real thing: the URL carries a comma-separated
            # fields list, which is exactly what defeats a Link parser that
            # splits the header on commas.
            self.send_header(
                "Link",
                f'<{BASE}/uniprotkb/search?fields=accession,id,gene_primary,'
                f'xref_ensembl&query=%28reviewed%3Atrue%29&cursor={nxt}'
                f'&size={PAGE}>; rel="next"')
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------- short-write mock
    def _flaky_once(self):
        """First attempt truncates mid-body; later attempts succeed."""
        n = self._count("flaky-once")
        self.send_response(200)
        self.send_header("Content-Length", str(len(BIG_BODY)))
        self.end_headers()
        if n == 1:
            self.wfile.write(BIG_BODY[: len(BIG_BODY) // 3])
            self.close_connection = True
            return
        self.wfile.write(BIG_BODY)

    # ------------------------------------------------------ range mock
    def _range_file(self):
        """Truncates on attempt 1, then honours Range to finish the job."""
        n = self._count("range-file")
        rng = self.headers.get("Range")

        if rng and rng.startswith("bytes="):
            start = int(rng.split("=", 1)[1].split("-")[0])
            chunk = BIG_BODY[start:]
            self.send_response(206)
            self.send_header("Content-Length", str(len(chunk)))
            self.send_header(
                "Content-Range",
                f"bytes {start}-{len(BIG_BODY) - 1}/{len(BIG_BODY)}")
            self.end_headers()
            self.wfile.write(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Length", str(len(BIG_BODY)))
        self.end_headers()
        if n == 1:
            self.wfile.write(BIG_BODY[: len(BIG_BODY) // 2])
            self.close_connection = True
            return
        self.wfile.write(BIG_BODY)


def main():
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Mock)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    tmpdir = Path(tempfile.mkdtemp(prefix="proteindle-dl-"))
    dl.UNIPROT_SEARCH = f"{BASE}/uniprotkb/search"
    dl.PAGE_SIZE = PAGE

    print("\nLink header parsing\n")

    def eq(label, got, want):
        check(label, got == want, f"got {got!r}, wanted {want!r}")

    eq("extracts the next cursor",
       dl.parse_next_link('<https://x/y?cursor=abc>; rel="next"'),
       "https://x/y?cursor=abc")
    eq("ignores a link with no next",
       dl.parse_next_link('<https://x/y>; rel="prev"'), None)
    eq("handles a missing header", dl.parse_next_link(None), None)
    eq("picks next out of several",
       dl.parse_next_link('<https://a>; rel="prev", <https://b>; rel="next"'),
       "https://b")

    # The bug that killed the first real run: UniProt's next-page URL
    # contains the comma-separated fields list, so splitting the header on
    # ',' returns the fragment 'xref_ensembl&query=...' and urllib rejects
    # it with "unknown url type".
    real = ('<https://rest.uniprot.org/uniprotkb/search?fields=accession,id,'
            'gene_primary,gene_synonym,protein_name,length,mass,xref_ensembl'
            '&query=%28reviewed%3Atrue%29&cursor=bkf6tu31j3a6ulb4&size=200>'
            '; rel="next"')
    got = dl.parse_next_link(real)
    check("a URL containing commas survives intact",
          got is not None and got.startswith("https://rest.uniprot.org")
          and got.endswith("size=200"),
          f"got {got!r}")
    eq("unquoted rel=next is accepted",
       dl.parse_next_link("<https://x/y?a=1,2>; rel=next"), "https://x/y?a=1,2")

    print("\nUniProt cursor pagination\n")
    dest = tmpdir / "uniprot_human.tsv.gz"
    ok = dl.download_uniprot("uniprot_human.tsv.gz", dest)
    check("paginated download reports success", ok)

    if dest.exists():
        with gzip.open(dest, "rt", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        check("every entry is present",
              len(lines) == TOTAL_ENTRIES + 1,
              f"{len(lines)} lines, wanted {TOTAL_ENTRIES + 1}")
        check("header appears exactly once",
              sum(1 for line in lines if line.startswith("Entry\t")) == 1,
              str(sum(1 for line in lines if line.startswith("Entry\t"))))
        check("first data row is intact", lines[1].startswith("P00000\t"),
              lines[1][:30])
        check("last data row is intact",
              lines[-1].startswith(f"P{TOTAL_ENTRIES - 1:05d}\t"),
              lines[-1][:30])
        check("a page that died mid-response was retried, not lost",
              HITS.get(f"uniprot:{PAGE}", 0) >= 2,
              f"page 2 fetched {HITS.get(f'uniprot:{PAGE}', 0)}x")

    print("\nIncompleteRead is caught and retried\n")
    HITS.clear()
    dest2 = tmpdir / "flaky.bin"
    ok = dl.download_plain("flaky.bin", f"{BASE}/flaky-once", dest2)
    check("a truncated response does not abort the run", ok)
    check("the retry produced a complete file",
          dest2.exists() and dest2.stat().st_size == len(BIG_BODY),
          f"{dest2.stat().st_size if dest2.exists() else 0} of {len(BIG_BODY)}")

    print("\nByte-range resume\n")
    HITS.clear()
    dest3 = tmpdir / "resumed.bin"
    ok = dl.download_plain("resumed.bin", f"{BASE}/range-file", dest3)
    check("resumed download succeeds", ok)
    check("resumed file is byte-exact",
          dest3.exists() and dest3.read_bytes() == BIG_BODY,
          f"{dest3.stat().st_size if dest3.exists() else 0} bytes")

    print("\nUniProt resume from a checkpoint\n")
    HITS.clear()
    dest_r = tmpdir / "resume_uniprot.tsv.gz"
    part = dest_r.with_name(dest_r.name + ".part")
    ckpt = dest_r.with_name(dest_r.name + ".cursor")

    # Simulate a run that died after two pages: one gzip member on disk
    # plus a checkpoint pointing at page three.
    with gzip.open(part, "wt", encoding="utf-8", newline="") as fh:
        fh.write("Entry\tGene Names (primary)\tProtein names\n")
        for i in range(2 * PAGE):
            fh.write(f"P{i:05d}\tGENE{i}\tprotein {i}\n")
    ckpt.write_text(f"{BASE}/uniprotkb/search?cursor={2 * PAGE}\n{2 * PAGE}\n",
                    encoding="utf-8")

    ok = dl.download_uniprot("resume_uniprot.tsv.gz", dest_r)
    check("a checkpointed run resumes", ok)
    if dest_r.exists():
        with gzip.open(dest_r, "rt", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        check("resumed file holds every entry exactly once",
              len(lines) == TOTAL_ENTRIES + 1,
              f"{len(lines)} lines, wanted {TOTAL_ENTRIES + 1}")
        check("no duplicate header from the appended member",
              sum(1 for line in lines if line.startswith("Entry\t")) == 1)
        check("pages already on disk were not re-fetched",
              HITS.get("uniprot:0", 0) == 0,
              f"page 1 fetched {HITS.get('uniprot:0', 0)}x")
    check("checkpoint file is cleaned up on success", not ckpt.exists())

    print("\nA poisoned checkpoint is discarded, not obeyed\n")
    HITS.clear()
    dest_p = tmpdir / "poisoned.tsv.gz"
    part_p = dest_p.with_name(dest_p.name + ".part")
    ckpt_p = dest_p.with_name(dest_p.name + ".cursor")

    with gzip.open(part_p, "wt", encoding="utf-8", newline="") as fh:
        fh.write("Entry\tGene Names (primary)\tProtein names\n")
        for i in range(PAGE):
            fh.write(f"P{i:05d}\tGENE{i}\tprotein {i}\n")
    # Exactly what the broken Link parser wrote to disk: a URL fragment.
    ckpt_p.write_text("xref_ensembl&query=%28reviewed%3Atrue%29&cursor=abc\n"
                      f"{PAGE}\n", encoding="utf-8")

    ok = dl.download_uniprot("poisoned.tsv.gz", dest_p)
    check("a run poisoned by a bad checkpoint still recovers", ok)
    if dest_p.exists():
        with gzip.open(dest_p, "rt", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        check("recovery restarts and yields a complete file",
              len(lines) == TOTAL_ENTRIES + 1,
              f"{len(lines)} lines, wanted {TOTAL_ENTRIES + 1}")
        check("no rows were duplicated by the restart",
              len(set(lines)) == len(lines),
              f"{len(lines) - len(set(lines))} duplicates")

    print("\nGiving up cleanly\n")
    HITS.clear()
    dest4 = tmpdir / "dead.bin"
    ok = dl.download_plain("dead.bin", f"{BASE}/always-500", dest4, retries=2)
    check("a permanently broken source returns False, not an exception",
          ok is False)
    check("no corrupt output file is left behind", not dest4.exists())

    print("\nSkip and force\n")
    HITS.clear()
    before = HITS.copy()
    dl.download_plain("resumed.bin", f"{BASE}/range-file", dest3)
    check("an existing file is skipped", not HITS,
          f"server was hit {sum(HITS.values())}x")
    dl.download_plain("resumed.bin", f"{BASE}/range-file", dest3, force=True)
    check("--force re-fetches", sum(HITS.values()) >= 1)

    print("\nHTML error pages are detected\n")
    dest5 = tmpdir / "hgnc_complete_set.txt"
    dl.download_plain("hgnc_complete_set.txt", f"{BASE}/html-error", dest5)
    real_raw = dl.RAW
    try:
        dl.RAW = tmpdir
        issue = dl.verify("hgnc_complete_set.txt")
    finally:
        dl.RAW = real_raw
    check("verify rejects an HTML body", issue is not None
          and "HTML" in issue, str(issue))

    httpd.shutdown()
    shutil.rmtree(tmpdir, ignore_errors=True)

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILURE(S):")
        for f in FAILED:
            print(f"  - {f}")
        print()
        return 1
    print("Download tests passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
