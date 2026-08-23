# Proteindle

Guess the human protein. Every column is a clue.

**▶ Play at [proteindle.github.io](https://proteindle.github.io)**

![The board after three guesses](assets/screenshot.png)

A daily puzzle shaped like Wordle, except the answer is a human protein and
the feedback is biology: how long it is, how far back in evolution it goes,
where in the cell it sits, what it does, which pathway it belongs to, which
chromosome it is on, and whether it is linked to disease.

Guess any of the 20,190 reviewed human proteins. Answers are drawn from the
well-known ones — nobody wants to guess ZNF493 — but the thing you type does
not have to be in that set.

Pick your field on the first visit — DNA repair, immunology, metabolism, one
of 23 — and every answer comes from it, with its own daily rotation. A
specialist gets the proteins they actually know.

No accounts, no tracking, no backend. It is a static page and a JSON file.

---

## How to play

Type any human gene symbol or protein name. Each column compares your guess
to the answer:

| | meaning |
|---|---|
| 🟩 green | exact match |
| 🟨 amber | close — it means something different per column |
| 🟥 red | no match |
| ↑ ↓ | the answer is higher / lower than your guess |

Amber is not one thing. On **Length** it means within 10%. On **Conserved
back to**, one rung away. On **Localization** and **Pathway**, the sets
overlap without being identical. On **Function**, a different class in the
same family — guess a kinase when the answer is a protease and you get
amber, because both are enzymes.

Under each guess is its protein **family**, which is not scored and not in
the shared grid. It turns green when it is the answer's family and amber
when the two are related. Guess a receptor tyrosine kinase when the answer
is a different one and every column can still come back red, because the
columns measure size, age, location and pathway rather than relatedness —
the family line is the part a biologist actually reasons with.

Eight guesses on the daily. Free play and Hard are unlimited, with a give-up
button and an **Easier one** button that draws from well-known proteins and
from dailies that have already run.

---

## The columns

| Column | Type | Source |
|---|---|---|
| **Length** | numeric ↑↓ | UniProt |
| **Conserved back to** | ordinal ↑↓ | Gene-Ages consensus |
| **Localization** | multi-value | UniProt subcellular location, collapsed to 9 buckets |
| **Function** | single | rules over UniProt keywords, EC number and protein name |
| **Pathway** | multi-value | Reactome, rolled up to top-level pathways |
| **Chromosome** | numeric ↑↓ | HGNC cytogenetic location |
| **Disease-linked** | boolean | UniProt disease annotations with an OMIM anchor |

Disease-linked means UniProt lists at least one named inherited or acquired
disease caused by variants in this protein — not "has been studied in a
disease", which is nearly everything. A quarter of the proteome qualifies;
among answers, which are the well-studied end, it is closer to half.

### The conservation ladder

This is the column that makes the game worth playing, so it is worth being
precise about what it claims:

1. **Universal** — bacteria, archaea and eukaryotes alike
2. **Ancient** — shared with one prokaryotic domain
3. **Eukaryota**
4. **Opisthokonta** — animals and fungi; present in yeast
5. **Eumetazoa** — animals; in flies and worms, not yeast
6. **Vertebrata**
7. **Mammalia**

Gene-Ages ships eight age bins. Two of them — "shared with archaea" and
"shared with bacteria" — are **siblings, not rungs**: neither is deeper than
the other, so ordering them would make the up/down arrow lie. They are
collapsed into one "Ancient" rung, which leaves a scale that is honestly
ordinal end to end. That is the only kind an arrow can hint at.

Coverage is 19,099 of 20,190 human proteins, spread across all seven rungs
with none dominating.

---

## Fields

Fields are Reactome's top-level pathways, which sit at about the granularity
people use to describe their own work.

Membership is measured, not asserted. A protein joins a field only if a real
share of its Reactome annotations sit under that top-level pathway — at
least three of them, and at least a fifth of its total. Without that bar,
membership meant "appears under it at all", which put AKT1 in eleven fields
and made ATM an autophagy protein on the strength of four annotations out of
sixty-one. Where a protein clears the bar in more than three fields, the
three kept are the most *enriched* ones: its share under a pathway measured
against that pathway's share of Reactome as a whole, so a small field can
win a slot from Signal Transduction, which is 13% of every annotation in the
database.

Three rules then shape the list itself:

- Categories nobody identifies with are dropped. "Disease" spans a third of
  the proteome; "Drug ADME" is plumbing.
- Anything under 40 members is dropped — its daily rotation would repeat too
  soon. Circadian clock and DNA Replication lose out here.
- Anything over 250 is capped by how well known its members are. Immune
  System has ~1,300 candidates and Signal Transduction ~1,500; uncapped,
  they stop being a filter at all.

Field pools are drawn from the best-known 8,000 proteins rather than the
3,000 the other modes use, on the reasoning that a specialist knows the
less-famous proteins in their own area — that knowledge is what the mode
exists to reward. It is also what keeps the small fields alive: Autophagy
has 25 members inside the famous 3,000 and 46 inside 8,000. Large fields are
unaffected, since their top 250 by fame sit inside the 3,000 either way.

---

## Browse and Train

The game is a guessing game, but the database underneath it is a study
resource, and a Reddit comment asked for exactly that: "would be nice if we
could see the list of proteins in each category with their attributes, like
you should be able to study them." Two views answer it.

**Browse** is the whole database as a table — all 20,190 reviewed human
proteins, not just the 4,331 that can be answers, with every attribute the
game scores on. Filter by function, conservation, localization, field,
chromosome or disease link, search names and aliases, sort any column, and
export the result as CSV. Rows render a hundred at a time, because twenty
thousand `<tr>` elements is not a table, it is a stall.

**Train** turns any selection into spaced repetition. Filter Browse to what
you care about, press *Study these*, and it becomes a deck.

Scheduling is **Leitner**, not SM-2: five boxes with fixed intervals of 1,
3, 7, 21 and 60 days, and a missed card drops to box 1. The appeal over a
proper ease-factor algorithm is that you can see why a card came back, which
matters for an audience that will reasonably want to know. Progress is kept
per deck in `localStorage`, so several decks can be on the go at once, and
there is a daily streak.

A card is a **protein**, not a protein-column pair. Asking "TP53 —
function?" and "TP53 — chromosome?" as separate cards would multiply a
200-protein deck into 1,400 and make it feel endless; instead the column is
drawn fresh each time the protein comes up, so a protein you actually know
has to survive questions from several angles. Which columns can be asked,
and in which direction, are settings.

Two directions ship on by default and mix: *protein → attribute* ("TP53 —
what is its function?") and *attributes → protein*, which is the game's own
logic as a flashcard. Closed columns — function, conservation, chromosome,
disease, length — are multiple choice and graded objectively; open-ended
ones — localization, pathway, family — are self-graded flips.

The attributes → protein direction ranks its clues by how few cards in the
deck share that value, and drops any attribute the whole deck has in common.
Without that, a deck filtered to Function = Chromatin opens every card with
"Function: Chromatin", which is a wasted line and no help at all.

---

## Running it yourself

```bash
# six hand-written proteins plus synthetic filler, no download needed
python pipeline/make_fixture.py --run
python serve.py

# the real database (~400 MB of one-off downloads)
python pipeline/download.py
python pipeline/build.py
python serve.py
```

This writes two files. `web/data/proteins.json` holds every answer plus the
puzzle calendar and is what the page waits for;
`web/data/proteins-rest.json` holds the other 15,859 proteins, which are
guessable but never the answer, and is fetched after the board is already
up.

Python 3.8+ and nothing else — the pipeline is pure standard library, so
there is no virtualenv and no `pip install`. Use `serve.py` rather than
opening `index.html` directly: the page fetches its database, and browsers
block `fetch()` on `file://`.

Downloads resume. Finished sources are skipped, half-finished flat files
restart at the byte they stopped on, and UniProt resumes at the last
completed page. `--only uniprot` retries a single source; `--page-size 50`
shrinks each request on a lossy connection.

### One self-contained file

```bash
python pipeline/bundle.py     # -> web/proteindle.html
```

Inlines the CSS, JS and database into a single page. Nothing is fetched, so
this one *does* work off `file://` — mail it, or drop it on any host.

### Deploying

`.github/workflows/pages.yml` publishes `web/` to GitHub Pages on every push
to `main`. Set Settings → Pages → Source to **GitHub Actions**.

The workflow exists because branch-based Pages publishing only accepts the
repository root or a folder named `/docs`; there is no way to point it at
`web/`.

---

## Design notes

**Answers are ranked by how well known they are.** Nobody wants to guess
`ZNF493`. Every protein is ranked by how many PubMed papers cite its gene,
and the pools are cut from the top of that list: 365 for the daily (all
seven columns present), 1,000 for free play, 3,000 for hard. The build
prints the least famous protein in each tier as a sanity check.

**Guessing is not ranked at all.** Several people reported that their own
protein was missing when it was in the database and the search could not
find it, so the search matches whole words at word boundaries across gene
symbol, synonyms, protein name and description, in any order: "beta catenin"
finds CTNNB1, "SLC" finds the transporters, "collagen" leads with a collagen
rather than a collagenase. Word matches beat prefix matches and the name
beats the description, so the ranking prefers the protein that is called
what you typed over the one that is merely described that way.

**One entry per gene symbol.** UniProt carries several reviewed entries for
some genes — GNAS has four; CDKN2A has p16INK4a and p14ARF separately. Two
autocomplete rows both reading "NRXN1" is a coin flip the player cannot win,
so the build keeps one: fewest missing columns, then longest sequence, with
`CANONICAL_OVERRIDES` for the cases that rule gets wrong.

**The first fortnight of every rotation** is that pool's best-known
proteins, shuffled among themselves, minus a short exclusion list for the
ones whose clue row gives them away on sight. New players get a run of wins
during the window in which they decide whether to come back.

**The daily needs no server.** At build time each rotation is written into
`proteins.json` as a fixed permutation; the client computes days since the
epoch and indexes into it, so every player sees the same protein. Field
rotations are seeded from the field key with `zlib.crc32` rather than
Python's `hash()`, which is salted per process and would silently reshuffle
everyone's puzzles on each rebuild.

**The calendar is canon only as far as it has been played.** `data/schedule.json`
records every rotation and how many days of it have gone out. Days already
played never move — somebody has a shared grid of them — but the tail is a
permutation nobody has seen, so it is regenerated on every build. Freezing
the whole thing would lock a year of puzzles to whatever the pools looked
like on launch day.

A determined player can read tomorrow's answer out of the JSON. Every game
in this genre can be beaten that way; it is not worth engineering around.

**Columns are measured, not assumed.** `pipeline/entropy.py` reports, per
column, how its values are spread across the pool and — more usefully — what
a guess actually tells the player: how often it comes back green, amber or
red, and how many bits that carries. `pipeline/simulate.py` plays thousands
of rounds under three strategies and reports the distribution of guesses
needed.

Read the simulator with one caveat: it holds the whole database and filters
by exact feedback signature, whereas a person has to *recall* which proteins
fit. It measures how much information the board carries, not how hard the
game feels.

---

## Tests

```bash
python pipeline/test_classify.py    # annotation rules
python pipeline/test_download.py    # retry, resume and pagination
python pipeline/test_scoring.py     # Python scoring == JS scoring
python pipeline/playtest.py         # the game itself, in a real browser
python pipeline/smoke_study.py      # Browse and Train, in a real browser
python pipeline/smoke_study.py --bundle   # ...and in the single-file build
```

`smoke_study.py` is run twice on purpose. In the split build `init()` awaits
`fetch`, so `study.js` has been parsed by the time the database is ready; in
the single-file build the data is inlined, `init()` never awaits, and the
ready event fires before `study.js` exists. Browse would have been empty in
exactly the build meant to work off a USB stick. `study.js` therefore checks
for an already-initialised app as well as listening, and the `--bundle` run
is what keeps that honest.

The comparison rules exist twice — `web/scoring.js` for the game,
`pipeline/scoring.py` for the offline analysis — and every tuning decision
comes from the Python side. `test_scoring.py` runs both over 4,000 real
protein pairs through Node and demands identical output, so the simulator
can never end up measuring a game nobody is playing.

`test_download.py` runs against a local server that deliberately misbehaves:
truncating responses mid-body, failing a page once, honouring `Range` only
on the second attempt.

---

## Credits

Built on five open databases. If you use the data, cite them rather than
this repository.

- **[UniProt](https://www.uniprot.org/)** — protein annotations. CC BY 4.0.
  The UniProt Consortium, *Nucleic Acids Research* 53:D609–D617 (2025).
  [doi:10.1093/nar/gkae1010](https://doi.org/10.1093/nar/gkae1010)
- **[Reactome](https://reactome.org/)** — pathways. CC0. Ragueneau et al.,
  *Nucleic Acids Research* (2025).
  [doi:10.1093/nar/gkaf1223](https://doi.org/10.1093/nar/gkaf1223)
- **[HGNC](https://www.genenames.org/)** — gene symbols and locations. CC0.
  Seal et al., *Nucleic Acids Research* 54:D1098–D1107 (2026).
  [doi:10.1093/nar/gkaf1229](https://doi.org/10.1093/nar/gkaf1229)
- **[NCBI Gene](https://www.ncbi.nlm.nih.gov/gene)** — publication counts
  and gene aliases. Public domain. Source: National Library of Medicine.
- **[Gene-Ages](https://github.com/marcottelab/Gene-Ages)** — conservation
  depth. MIT, © 2016 Benjamin J. Liebeskind. Liebeskind, McWhite &
  Marcotte, *Genome Biology and Evolution* 8:1812–1823 (2016).
  [doi:10.1093/gbe/evw113](https://doi.org/10.1093/gbe/evw113)

## Licence

Source code is [MIT](LICENSE).

The derived dataset at `web/data/proteins.json` is
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), the most
restrictive of its inbound terms, inherited from UniProt. It is a modified
work — columns are bucketed, renamed, filtered and joined. Details in
[`web/data/LICENSE`](web/data/LICENSE).
