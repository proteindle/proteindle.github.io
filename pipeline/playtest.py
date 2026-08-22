"""
Headless playtest of the web app. Drives a real browser through a real
round and asserts on what the player would actually see.

    python pipeline/playtest.py            # runs against web/data/proteins.json
    python pipeline/playtest.py --shots    # also writes screenshots

Requires playwright. This is the check that the grid, the arrows, the
autocomplete and the endgame modal all still work after a change.
"""

import argparse
import json
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT  # noqa: E402

WEB = ROOT / "web"
PORT = 8731
FAILED = []


def check(label, cond, detail=""):
    if not cond:
        FAILED.append(f"{label}{(' — ' + detail) if detail else ''}")
    print(f"  [{'ok ' if cond else 'FAIL'}] {label}"
          + (f"  ({detail})" if detail and not cond else ""))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_a):
        pass


def dismiss(page, tries=6):
    """
    Close any open overlay and keep it closed.

    The finished-daily reveal re-opens on a 250 ms timer after load, so a
    single Escape can fire before the modal even exists and the next click
    then hits the backdrop instead of the button it wanted.
    """
    clear_streak = 0
    for _ in range(tries * 2):
        page.wait_for_timeout(200)
        open_ids = [i for i in ("modal-backdrop", "field-backdrop")
                    if page.is_visible(f"#{i}")]
        if open_ids:
            clear_streak = 0
            page.keyboard.press("Escape")
            continue
        # Two consecutive clear reads, 200 ms apart, so a reveal still
        # sitting on its timer has had time to appear and be dismissed.
        clear_streak += 1
        if clear_streak >= 2:
            return True
    return not (page.is_visible("#modal-backdrop")
                or page.is_visible("#field-backdrop"))


def serve():
    handler = partial(QuietHandler, directory=str(WEB))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    data = json.loads((WEB / "data" / "proteins.json").read_text())
    proteins = data["proteins"]
    genes = [p["g"] for p in proteins]
    print(f"\nPlaytesting with {len(proteins)} proteins: "
          f"{', '.join(genes[:8])}{'…' if len(genes) > 8 else ''}\n")

    httpd = serve()
    time.sleep(0.4)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1180, "height": 950})

        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                if m.type == "error" else None)

        page.goto(f"http://127.0.0.1:{PORT}/index.html")
        page.wait_for_selector("#guess-input:not([disabled])", timeout=8000)

        print("first visit\n")
        # No stored field yet, so the picker must be the first thing shown.
        check("field picker opens on a first visit",
              page.is_visible("#field-backdrop"))
        opts = page.query_selector_all("#field-grid .field-option")
        check("picker lists Everything plus the fields", len(opts) >= 4,
              f"{len(opts)} options")
        first = page.inner_text("#field-grid .field-option:first-child")
        check("Everything is offered first", "Everything" in first, first)

        page.click('#field-grid .field-option[data-key=""]')
        page.wait_for_timeout(350)
        check("choosing a field closes the picker",
              not page.is_visible("#field-backdrop"))
        check("the chip reflects the choice",
              page.inner_text("#field-name").strip() == "Everything",
              page.inner_text("#field-name"))

        print("\nload\n")
        check("database loads and input enables", True)
        status = page.inner_text("#status-text")
        check("status line shows the daily number", "Daily #" in status, status)

        # ---------------------------------------------------- autocomplete
        print("\nautocomplete\n")
        page.fill("#guess-input", "TP")
        page.wait_for_timeout(220)
        sug_visible = page.is_visible("#suggestions")
        check("suggestions appear while typing", sug_visible)
        if sug_visible:
            first = page.inner_text("#suggestions li:first-child .sug-gene")
            check("prefix match ranks first", first == "TP53", first)

        # alias lookup: P53 is a TP53 synonym, not its primary symbol
        page.fill("#guess-input", "P53")
        page.wait_for_timeout(220)
        if page.is_visible("#suggestions"):
            txt = page.inner_text("#suggestions")
            check("alias 'P53' finds TP53", "TP53" in txt, txt[:60])

        # ------------------------------------------------------- guessing
        print("\nguessing\n")
        target_acc = data["dailyOrder"][0]  # day index may differ; recompute
        day_status = page.inner_text("#status-text")
        day_no = int(day_status.split("#")[1].split(" ")[0]) - 1
        target_acc = data["dailyOrder"][day_no % len(data["dailyOrder"])]
        target = next(p for p in proteins if p["a"] == target_acc)
        print(f"       today's answer is {target['g']} ({target_acc})")

        wrong = [p for p in proteins if p["a"] != target_acc]

        page.fill("#guess-input", wrong[0]["g"])
        page.wait_for_timeout(180)
        page.press("#guess-input", "Enter")
        page.wait_for_timeout(600)

        rows = page.query_selector_all("#board-body tr")
        check("a guess adds a row", len(rows) == 1, f"{len(rows)} rows")

        cells = page.query_selector_all("#board-body tr:first-child td .cell")
        check("row has 8 cells (subject + 7 clues)", len(cells) == 8,
              f"{len(cells)} cells")

        classes = [c.get_attribute("class") for c in cells[1:]]
        check("every clue cell is coloured",
              all(any(s in c for s in ("correct", "partial", "wrong"))
                  for c in classes),
              str(classes))

        glyphs = page.query_selector_all("#board-body .cell-glyph")
        check("cells carry a non-colour glyph too", len(glyphs) == 7,
              f"{len(glyphs)} glyphs")

        # duplicate guard
        page.fill("#guess-input", wrong[0]["g"])
        page.wait_for_timeout(180)
        page.press("#guess-input", "Enter")
        page.wait_for_timeout(300)
        hint = page.inner_text("#hint")
        check("duplicate guess is rejected", "already guessed" in hint.lower(),
              hint)
        check("duplicate did not add a row",
              len(page.query_selector_all("#board-body tr")) == 1)

        # arrows: guess something with a very different length
        by_len = sorted([p for p in wrong if p.get("len")],
                        key=lambda p: p["len"])
        extreme = by_len[0] if target.get("len", 0) > by_len[0]["len"] \
            else by_len[-1]
        if extreme["a"] != wrong[0]["a"]:
            page.fill("#guess-input", extreme["g"])
            page.wait_for_timeout(180)
            page.press("#guess-input", "Enter")
            page.wait_for_timeout(600)
            arrows = page.query_selector_all("#board-body tr:first-child "
                                             ".cell-arrow")
            check("numeric mismatch renders an arrow", len(arrows) >= 1,
                  f"{len(arrows)} arrows")

        if args.shots:
            page.screenshot(path=str(ROOT / "data" / "build" /
                                     "playtest-board.png"), full_page=True)

        # --------------------------------------------------------- winning
        print("\nendgame\n")
        page.fill("#guess-input", target["g"])
        page.wait_for_timeout(180)
        page.press("#guess-input", "Enter")
        page.wait_for_timeout(1200)

        check("modal opens on a win", page.is_visible("#modal-backdrop"))
        verdict = page.inner_text("#modal-verdict")
        check("verdict says solved", "solved" in verdict.lower(), verdict)
        title = page.inner_text("#modal-title")
        check("modal names the protein", title == target["g"], title)
        reveal = page.inner_text("#reveal")
        check("reveal card is populated", len(reveal) > 60,
              f"{len(reveal)} chars")
        link = page.get_attribute("#uniprot-link", "href")
        check("UniProt link points at the answer", target_acc in (link or ""),
              str(link))

        if args.shots:
            page.screenshot(path=str(ROOT / "data" / "build" /
                                     "playtest-modal.png"))

        # persistence across reload
        page.click("#modal-close")
        page.reload()
        page.wait_for_selector("#guess-input", timeout=8000)
        page.wait_for_timeout(700)
        rows_after = page.query_selector_all("#board-body tr")
        check("daily progress survives a reload", len(rows_after) >= 2,
              f"{len(rows_after)} rows after reload")

        # ------------------------------------------------------- give up
        print("\ngive up\n")
        check("overlays can be dismissed", dismiss(page))
        page.click('.mode-btn[data-mode="freeplay"]')
        page.wait_for_timeout(350)

        check("give-up is hidden before the first guess",
              not page.is_visible("#giveup-btn"))
        st = page.inner_text("#status-text")
        check("free play advertises no guess limit", "no limit" in st, st)

        page.fill("#guess-input", proteins[0]["g"])
        page.wait_for_timeout(160)
        page.press("#guess-input", "Enter")
        page.wait_for_timeout(500)

        if page.is_visible("#modal-backdrop"):        # lucky first guess
            page.keyboard.press("Escape")
            page.click("#new-round")
            page.wait_for_timeout(300)
            page.fill("#guess-input", proteins[0]["g"])
            page.wait_for_timeout(160)
            page.press("#guess-input", "Enter")
            page.wait_for_timeout(500)

        check("give-up appears once a guess is on the board",
              page.is_visible("#giveup-btn"))
        page.click("#giveup-btn")
        page.wait_for_timeout(500)
        check("give-up opens the reveal", page.is_visible("#modal-backdrop"))
        check("verdict says revealed, not lost",
              page.inner_text("#modal-verdict").strip().lower() == "revealed",
              page.inner_text("#modal-verdict"))
        check("input is locked after giving up",
              page.get_attribute("#guess-input", "disabled") is not None)
        dismiss(page)

        # ---------------------------------------------------- field mode
        print("\nfields\n")
        field_keys = [f["key"] for f in data.get("fields", [])]
        if field_keys:
            dismiss(page)
            page.click("#field-btn")
            page.wait_for_timeout(250)
            check("the chip reopens the picker",
                  page.is_visible("#field-backdrop"))
            page.click(f'#field-grid .field-option[data-key="{field_keys[0]}"]')
            page.wait_for_timeout(400)

            label = next(f["label"] for f in data["fields"]
                         if f["key"] == field_keys[0])
            check("chip shows the chosen field",
                  page.inner_text("#field-name").strip() == label,
                  page.inner_text("#field-name"))
            check("Hard tab is hidden inside a field",
                  not page.is_visible('.mode-btn[data-mode="hard"]'))

            page.click('.mode-btn[data-mode="daily"]')
            page.wait_for_timeout(350)
            st = page.inner_text("#status-text")
            check("daily is labelled with the field",
                  label.lower() in st.lower(), st)

            in_field = {p["a"] for p in proteins
                        if field_keys[0] in (p.get("fld") or [])}
            answer = page.evaluate("() => state.target.a")
            check("the answer comes from that field", answer in in_field,
                  f"{answer} not among {len(in_field)} field members")

            # A field daily must not inherit the global daily's saved state.
            page.reload()
            page.wait_for_selector("#guess-input", timeout=8000)
            page.wait_for_timeout(600)
            check("the field choice survives a reload",
                  page.inner_text("#field-name").strip() == label,
                  page.inner_text("#field-name"))
            check("no picker on a return visit",
                  not page.is_visible("#field-backdrop"))
            check("the field daily starts fresh, not with the global board",
                  len(page.query_selector_all("#board-body tr")) == 0)

            dismiss(page)
            page.click("#field-btn")
            page.wait_for_timeout(250)
            page.click('#field-grid .field-option[data-key=""]')
            page.wait_for_timeout(400)
            check("switching back to Everything restores Hard",
                  page.is_visible('.mode-btn[data-mode="hard"]'))

        # ----------------------------------------------------- other modes
        print("\nmodes\n")
        # Returning to a finished daily re-opens its reveal, and the backdrop
        # covers the whole viewport, so the mode buttons are genuinely
        # unreachable until it is gone. Same for a real player.
        check("the reveal can be cleared before switching mode", dismiss(page))
        page.click('.mode-btn[data-mode="freeplay"]')
        page.wait_for_timeout(400)
        check("free play resets the board",
              len(page.query_selector_all("#board-body tr")) == 0)
        check("free play offers a new round",
              page.is_visible("#new-round"))
        st = page.inner_text("#status-text")
        check("free play shows the pool size", "possible answers" in st, st)

        page.click("#new-round")
        page.wait_for_timeout(300)
        check("new round clears guesses",
              len(page.query_selector_all("#board-body tr")) == 0)

        # ------------------------------------------------------- js errors
        print("\nruntime\n")
        real_errors = [e for e in errors if "favicon" not in e.lower()]
        check("no JavaScript errors", not real_errors,
              "; ".join(real_errors[:3]))

        browser.close()

    httpd.shutdown()

    print()
    if FAILED:
        print(f"{len(FAILED)} FAILURE(S):")
        for f in FAILED:
            print(f"  - {f}")
        print()
        return 1
    print("Playtest passed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
