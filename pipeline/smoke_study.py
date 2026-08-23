"""
Headless smoke test for Browse and Train.

    python pipeline/smoke_study.py            # split build
    python pipeline/smoke_study.py --bundle   # the single-file build
    python pipeline/smoke_study.py --shots    # also write screenshots

Deliberately separate from playtest.py, which owns the game. This drives
the two study views: filter the table, hand the filter to Train as a
deck, answer a card each way, and check the Leitner state actually
persists.
"""

import argparse
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ROOT  # noqa: E402

WEB = ROOT / "web"
PORT = 8739
FAILED = []


def check(label, cond, detail=""):
    if not cond:
        FAILED.append(f"{label}{(' — ' + detail) if detail else ''}")
    print(f"  [{'ok ' if cond else 'FAIL'}] {label}"
          + (f"  ({detail})" if detail and not cond else ""))


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_a):
        pass


SHOTS = ROOT / "data" / "build" / "shots"


def run(bundle=False, shots=False):
    def shot(name):
        if not shots:
            return
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"{name}.png"))

    from playwright.sync_api import sync_playwright

    handler = partial(QuietHandler, directory=str(WEB))
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    page_name = "proteindle.html" if bundle else "index.html"
    url = f"http://127.0.0.1:{PORT}/{page_name}"
    print(f"\nstudy smoke test — {page_name}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text)
                if m.type == "error" else None)
        page.goto(url, wait_until="load")

        # The field picker opens on a first visit and covers everything.
        for _ in range(6):
            page.wait_for_timeout(200)
            if page.is_visible("#field-backdrop"):
                page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        # ---------------------------------------------------- browse
        page.click('.view-btn[data-view="browse"]')
        page.wait_for_timeout(400)
        check("browse view opens", page.is_visible("#view-browse"))
        check("play chrome is hidden in browse",
              not page.is_visible("#play-chrome"))

        # Wait for the second half of the database.
        for _ in range(40):
            if "20,190" in page.inner_text("#browse-count"):
                break
            page.wait_for_timeout(250)
        rows = page.eval_on_selector_all("#browse-body tr", "n => n.length")
        check("rows render", rows > 0, f"{rows} rows")
        shot("browse")
        count = page.inner_text("#browse-count")
        check("all 20,190 proteins are browsable", "20,190" in count, count)

        page.click("#browse-more")
        page.wait_for_timeout(200)
        rows2 = page.eval_on_selector_all("#browse-body tr", "n => n.length")
        check("show more appends", rows2 > rows, f"{rows} -> {rows2}")

        # Filter to one function class and confirm every visible row obeys.
        page.select_option("#bf-fn", "Chromatin")
        page.wait_for_timeout(400)
        fns = page.eval_on_selector_all(
            "#browse-body tr td:nth-child(6)",
            "n => Array.from(new Set(n.map(x => x.textContent)))")
        check("function filter is exact", fns == ["Chromatin"], str(fns[:4]))
        n_chromatin = page.inner_text("#browse-count")
        check("filter reports a count", "protein" in n_chromatin, n_chromatin)

        # Sorting.
        page.click('#browse-head th[data-sort="len"]')
        page.wait_for_timeout(300)
        lens = page.eval_on_selector_all(
            "#browse-body tr td:nth-child(3)",
            "n => n.slice(0, 12).map(x => parseInt(x.textContent, 10))")
        check("sort by length descends", lens == sorted(lens, reverse=True),
              str(lens[:6]))

        # Search.
        page.fill("#bf-q", "histone")
        page.wait_for_timeout(400)
        genes = page.eval_on_selector_all(
            "#browse-body tr th", "n => n.length")
        check("text search narrows", genes > 0, f"{genes} hits")
        page.click("#bf-reset")
        page.wait_for_timeout(400)
        check("clear restores everything",
              "20,190" in page.inner_text("#browse-count"))

        # ----------------------------------------------------- train
        page.select_option("#bf-fn", "Chromatin")
        page.wait_for_timeout(400)
        page.click("#browse-study")
        page.wait_for_timeout(500)
        check("study hands off to train", page.is_visible("#view-train"))
        deck = page.inner_text("#deck-name")
        check("deck is named after the filter", "Chromatin" in deck, deck)
        check("a card is showing", page.is_visible("#card"))
        shot("train-card")

        # Answer 6 cards, whichever form each takes.
        answered = mc = flip = 0
        for _ in range(6):
            page.wait_for_timeout(250)
            if page.is_visible("#card-choices") and \
                    page.eval_on_selector_all("#card-choices .choice",
                                              "n => n.length") > 0:
                page.click("#card-choices .choice >> nth=0")
                mc += 1
            elif page.is_visible("#card-reveal"):
                page.click("#card-reveal")
                page.wait_for_timeout(150)
                page.click(".grade-got")
                flip += 1
            else:
                break
            answered += 1
            page.wait_for_timeout(250)
            if page.is_visible("#card-next"):
                page.click("#card-next")
        check("cards can be answered", answered >= 5, f"{answered} answered")
        check("both card forms appear over a run", mc > 0,
              f"mc={mc} flip={flip}")

        streak = page.inner_text("#train-stats")
        check("streak is tracked", "day streak" in streak, streak)

        # ------------------------------------------- the playability rule
        #
        # Bio Grid's rule, inverted for flashcards: an attribute earns its
        # place only if someone shown the protein could recall the answer.
        # Chromosome and length fail it — nobody knows what is on
        # chromosome 12. Bio Grid has a test so its eleven chromosome
        # criteria cannot come back; this is the same guard.
        offered = page.eval_on_selector_all(
            "#set-cols input", "n => n.map(x => x.dataset.col)")
        check("no chromosome card is offered", "chr" not in offered,
              str(offered))
        check("no length card is offered", "len" not in offered, str(offered))
        check("the disease Yes/No card is gone", "dis" not in offered,
              str(offered))
        check("the named disease card is offered", "disn" in offered,
              str(offered))

        # Generate a run of cards and read what they actually ask.
        prompts = page.evaluate("""async () => {
            const seen = [];
            for (let i = 0; i < 60; i++) {
                const el = document.getElementById('card-prompt');
                if (el && el.textContent) seen.push(el.textContent.trim());
                // Only click what a person could actually click: an
                // element inside a hidden container still answers
                // querySelector.
                const vis = (el) => el && el.offsetParent !== null;
                const c = document.querySelector('#card-choices .choice');
                if (vis(c)) { c.click(); }
                else {
                    const r = document.getElementById('card-reveal');
                    if (vis(r)) { r.click(); }
                    const g = document.querySelector('.grade-got');
                    if (vis(g)) g.click();
                }
                const n = document.getElementById('card-next');
                if (vis(n)) n.click();
                await new Promise(r => setTimeout(r, 12));
            }
            return seen;
        }""")
        bad = [t for t in prompts
               if "chromosome" in t.lower() or "how long" in t.lower()
               or "length" in t.lower()]
        check("no card asks a look-it-up question", not bad,
              f"{len(prompts)} prompts, offenders: {bad[:3]}")
        check("conservation is asked in recallable terms",
              not any("opisthokonta" in t.lower() or "eumetazoa" in t.lower()
                      for t in prompts))

        # And the conservation answers must be the three coarse buckets.
        buckets = page.evaluate("""() => {
            const out = new Set();
            document.querySelectorAll('.choice-label').forEach(
                n => out.add(n.textContent));
            return Array.from(out);
        }""")
        fine = [b for b in buckets if b in
                ("Opisthokonta", "Eumetazoa", "Vertebrata", "Mammalia",
                 "Eukaryota", "Universal", "Ancient")]
        check("the seven-rung ladder is not offered as answers", not fine,
              str(fine))

        # Leitner state must survive a reload.
        stored = page.evaluate(
            "() => Object.keys(localStorage)"
            ".filter(k => k.startsWith('proteindle:study:srs:')).length")
        check("scheduling is persisted", stored > 0, f"{stored} deck(s)")
        boxes = page.evaluate("""() => {
            const k = Object.keys(localStorage)
              .find(k => k.startsWith('proteindle:study:srs:'));
            const v = JSON.parse(localStorage.getItem(k));
            return Object.values(v).map(x => x.b);
        }""")
        check("answered cards moved up a box", any(b >= 1 for b in boxes),
              str(boxes[:8]))

        page.reload(wait_until="load")
        page.wait_for_timeout(800)
        for _ in range(6):
            if page.is_visible("#field-backdrop"):
                page.keyboard.press("Escape")
            page.wait_for_timeout(150)
        page.click('.view-btn[data-view="train"]')
        page.wait_for_timeout(500)
        check("deck is restored after reload",
              "Chromatin" in page.inner_text("#deck-name"),
              page.inner_text("#deck-name"))

        # -------------------------------------------------- settings
        page.click("#train-settings-btn")
        page.wait_for_timeout(250)
        check("settings open", page.is_visible("#settings-backdrop"))
        shot("settings")
        # Turn everything off; the code must refuse an unanswerable config.
        page.eval_on_selector_all(
            "#set-cols input:checked", "n => n.forEach(x => x.click())")
        page.click("#settings-done")
        page.wait_for_timeout(400)
        left = page.evaluate(
            "() => (JSON.parse(localStorage.getItem("
            "'proteindle:study:settings')) || {}).cols || []")
        check("an empty column set falls back to the defaults",
              len(left) > 0, str(left))
        check("the fallback contains no cut column",
              not ({"chr", "len", "dis"} & set(left)), str(left))
        check("a card still renders after that",
              page.is_visible("#card") or page.is_visible("#train-done"))

        # ------------------------------------------------ game intact
        page.click('.view-btn[data-view="play"]')
        page.wait_for_timeout(300)
        check("the game is still reachable", page.is_visible("#view-play"))
        check("play chrome comes back", page.is_visible("#play-chrome"))
        check("the board is intact",
              page.eval_on_selector_all("#board thead th", "n => n.length") == 8)

        real = [e for e in errors if "favicon" not in e.lower()]
        check("no JavaScript errors", not real, "; ".join(real[:3]))

        browser.close()

    srv.shutdown()
    print()
    if FAILED:
        print(f"{len(FAILED)} FAILURE(S):\n")
        for f in FAILED:
            print(f"  - {f}")
        print()
        return 1
    print("Study smoke test passed.\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", action="store_true",
                    help="test web/proteindle.html instead of index.html")
    ap.add_argument("--shots", action="store_true",
                    help="also write screenshots to data/build/shots")
    a = ap.parse_args()
    raise SystemExit(run(bundle=a.bundle, shots=a.shots))
