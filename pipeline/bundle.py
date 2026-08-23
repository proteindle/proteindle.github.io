"""
Fold the whole game into one self-contained HTML file.

    python pipeline/bundle.py                  -> web/proteindle.html
    python pipeline/bundle.py --artifact       -> web/proteindle.artifact.html

Why bother, when the site is already static? Because "one file" is the
lowest-friction thing to host: mail it, drop it on any web server, open it
straight off disk. The multi-file version needs a server purely because
browsers block fetch() on file:// — inlining the database removes that.

    default    a complete document, doctype through </html>. Drop it
               anywhere, including file://.
    --artifact body content only, for hosts that supply their own document
               skeleton and reject a nested <html>.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT, WEB_DATA  # noqa: E402

WEB = ROOT / "web"


def read(name):
    path = WEB / name
    if not path.exists():
        raise SystemExit(f"\nMissing {path}. Run pipeline/build.py first.\n")
    return path.read_text(encoding="utf-8")


def build(artifact=False):
    html = read("index.html")
    css = read("style.css")
    scoring = read("scoring.js")
    app = read("app.js")
    study = read("study.js")

    data_path = WEB_DATA / "proteins.json"
    if not data_path.exists():
        raise SystemExit(f"\nMissing {data_path}. Run pipeline/build.py "
                         f"first.\n")
    data = json.loads(data_path.read_text(encoding="utf-8"))

    # The app fetches its database. Inlined, there is nothing to fetch, so
    # hand it the parsed object directly and let init() skip the request.
    payload = json.dumps(data, separators=(",", ":"))
    # Inside a <script> element the HTML parser ends the block at the
    # first "</script", wherever it appears — including inside a string.
    # "\/" is a legal JSON escape for "/", so this is safe to unescape.
    payload = payload.replace("</", "<\\/")

    # The second file — every protein that is guessable but never the
    # answer. In the split build it is fetched after first paint; here
    # there is nothing to fetch, so it rides along inline.
    rest_path = WEB_DATA / "proteins-rest.json"
    rest_payload = ""
    if rest_path.exists():
        rest = json.loads(rest_path.read_text(encoding="utf-8"))
        rest_payload = json.dumps(rest, separators=(",", ":"))
        rest_payload = rest_payload.replace("</", "<\\/")

    html = html.replace(
        '<link rel="stylesheet" href="style.css">',
        f"<style>\n{css}\n</style>",
    )
    # study.js must stay last: it waits on the proteindle:ready event that
    # app.js fires, and in the inlined build every script runs to
    # completion in document order, so a listener registered afterwards
    # would miss the event entirely.
    tags = ('<script src="scoring.js"></script>\n'
            '<script src="app.js"></script>\n'
            '<script src="study.js"></script>')
    if tags not in html:
        raise SystemExit("\nCould not find the script tags to replace — has "
                         "index.html changed?\n")

    html = html.replace(
        tags,
        f'<script id="proteindle-data" type="application/json">{payload}'
        f"</script>\n"
        + (f'<script id="proteindle-rest" type="application/json">'
           f'{rest_payload}</script>\n' if rest_payload else "")
        +
        f"<script>\n{scoring}\n</script>\n"
        f"<script>\n{app}\n</script>\n"
        f"<script>\n{study}\n</script>",
    )

    if "proteindle-data" not in html:
        raise SystemExit("\nThe database was not inlined — bundle is broken.\n")

    if artifact:
        # Strip the outer document: the host supplies its own.
        body = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
        if not body:
            raise SystemExit("\nNo <body> found in index.html.\n")
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        head_bits = []
        if title:
            head_bits.append(f"<title>{title.group(1)}</title>")
        out = "\n".join(head_bits) + "\n" + body.group(1)
        name = "proteindle.artifact.html"
    else:
        out = html
        name = "proteindle.html"

    dest = WEB / name
    dest.write_text(out, encoding="utf-8")

    kb = dest.stat().st_size / 1024
    print(f"\nWrote {dest}  ({kb:,.0f} KB, {len(data['proteins'])} proteins)")
    if not artifact:
        print("Open it directly in a browser, or drop it on any static host.")
    print()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", action="store_true",
                    help="emit body content only, without a document wrapper")
    args = ap.parse_args()
    raise SystemExit(build(artifact=args.artifact))
