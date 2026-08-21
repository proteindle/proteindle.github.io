#!/usr/bin/env python3
"""
Serve the game locally.

    python serve.py            -> http://localhost:8000
    python serve.py 8080       -> http://localhost:8080

You need this rather than double-clicking index.html: the page fetches
data/proteins.json, and browsers block fetch() on file:// URLs.
"""

import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Always serve fresh data during development.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if "200" not in (args[1] if len(args) > 1 else ""):
            super().log_message(fmt, *args)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    if not (WEB / "data" / "proteins.json").exists():
        print("\nweb/data/proteins.json is missing. Build it first:\n")
        print("    python pipeline/download.py")
        print("    python pipeline/build.py\n")
        print("Or try the tiny fixture dataset:\n")
        print("    python pipeline/make_fixture.py --run\n")
        return 1

    url = f"http://localhost:{port}"
    print(f"\nProteindle running at {url}")
    print("Ctrl-C to stop.\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    httpd = ThreadingHTTPServer(
        ("0.0.0.0", port), partial(Handler, directory=str(WEB))
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
