# Pipeline: files and commands

What each script does, what is committed and what is not, and how to rebuild
everything from the engines' output — or the site alone from a clone.

---

## Layout

```
flake.nix                  Nix devShell: tesseract with spa_old/spa/cat/lat, uv
pyproject.toml + uv.lock   Python environment, locked
htr-requirements.txt       Kraken, in its own env (it pulls PyTorch)

scripts/
  inventory.py             all 671 leaves: section, class, columns, IA counterpart
  fetch_ia.py              Internet Archive derivatives, leaves, full image set
  render_pages.py          BNE PDF -> PNG
  prepare_ia_pages.py      IA JP2 -> PNG
  extract_abbyy_bne.py     ABBYY-BNE, text and word boxes
  parse_chocr_ia.py        ABBYY-IA
  ocr_tesseract.py         ocr_vision.py   ocr_paddle.py   ocr_kraken.py
  layout.py                the shared column split and reading order
  build_ordered.py         applies it, producing comparable readings
  scan_health.py           which of the two scans is legible on each leaf
  layout_health.py         the leaves where the engines disagree how many columns
  consensus.py             token-level vote + the conflict queue
  spans.py                 votes on a whole run where the engines tokenise differently
  sample_loci.py           stratified sample + facsimile review sheets
  benchmark.py             scoring any panel, ablations, census
  arbitrate.py             deterministic arbitration rules, measured
  score_engine.py          score any new engine on the frozen sample
  build_htr_dataset.py     unanimous lines -> Kraken training set
  editorial.py             the normalisation rules, applied by evidence
  build_text.py            the readable transcription
  parse_entries.py         years, dated entries, sigla, footnotes
  parse_jurats.py          the six Jurats series -> (year, seat, name)
  parse_documents.py       the appendix blocks and their numbered sections
  build_documents.py       each of those sections assembled as one document
  tables.py                the tables Campaner prints inside the prose
  review.py                the review tool: crops at native resolution, keyboard
  adjudicate_region.py     a region read off the facsimile line by line: text, lines, tables
  jurats_facsimile.py      the Jurats lists read off the facsimile, checked against every engine
  parse_sigla.py           the glossary the introduction prints
  audit_entries.py         every symptom ever found, swept over all 3 459 notices
  audit_documents.py       the same sweep over the 26 documents
  build_db.py              the parsed book -> DuckDB -> parquet
  build_site.py            the static site
  build_hero.py            the home page's frontispiece, cut from leaf 10
  doubt.py                 which words of a published text are disputed, by position
  themes.py                the thematic routes: a search someone has already typed
  check_site.py            lints the site against its own Content-Security-Policy
  dev_server.py            serves web/ locally with the headers production sends

data/inventory.json        the 671-leaf survey (committed)
data/scan_health.json      the leaves where the two scans disagree (committed)
data/adjudication/         the drawn sample — data, never regenerate (committed)
data/ground_truth/         550 adjudicated readings (committed — the slow part)
data/review/decisions.jsonl  review decisions, each with the source of its reading
data/audit/findings.json   what the sweep says is left, ranked
data/{entries,jurats,documents,sigla,tables,text}/  the parsed book (committed)
data/{raw,ia,pages,ocr}/   facsimiles and engine output (git-ignored, regenerable)
web/data/*.parquet         the published tables — the only committed copy of the
                           per-word certainty and the leaf index (6.5 MB)
docs/OCR_BENCHMARK.md      the full measurement report
docs/EDITORIAL.md          what this edition changes, and what it refuses to
wrangler.jsonc             the Cloudflare Worker: static assets from web/, the custom domain
.github/workflows/deploy.yml  rebuild web/ from the parquet, check it, deploy
```

**If `build_site.py` writes it, it does not belong in git.** What is tracked
under `web/` is the parquet and what a person wrote: `style.css`, `app.js`,
`search.js`, `home.js`, `theme.js`, `favicon.svg`, `_headers`, `robots.txt`,
`vendor/` (self-hosted fonts, with their licences) and `hero/frontispici.jpg`
(committed because its source pages are not).

The site runs under a strict Content-Security-Policy -- `script-src 'self';
style-src 'self'`, no inline anything, and one foreign origin for facsimile
images. After building, lint it and look at it with the real headers:

```sh
python scripts/check_site.py
python scripts/dev_server.py    # http://127.0.0.1:8788
```

## Reproducing it

```sh
nix develop     # toolchain, pinned by flake.lock
uv sync         # Python, pinned by uv.lock
```

The pilot's command sequence — fetching the scans, running the engines, drawing
and scoring the sample — is in [`OCR_BENCHMARK.md` §7](OCR_BENCHMARK.md).
Everything is idempotent and skips work already on disk.

From the engines' output to the site, over the whole book:

```sh
python scripts/scan_health.py            # which scan is legible on each leaf
python scripts/layout_health.py          # where the engines disagree on columns
python scripts/consensus.py --pages all --swap-paddle --swap-kraken \
       --per-leaf-scan --per-leaf-align

python scripts/build_text.py
python scripts/parse_entries.py --bootstrap   # first build only
python scripts/parse_documents.py
python scripts/parse_entries.py               # converges on the second pass
python scripts/build_documents.py
python scripts/parse_jurats.py
python scripts/parse_sigla.py
python scripts/tables.py
python scripts/audit_entries.py
python scripts/audit_documents.py

python scripts/build_db.py --parquet web/data
python scripts/build_site.py
python scripts/check_site.py
```

The entries and documents take about fifteen minutes; the rest is seconds.

### Rebuilding the site from a clone

The OCR itself is not in the repository and cannot be: the consensus is ten
thousand files and the per-word certainty is 100 MB of JSON. Its compact form
is — `web/data/*.parquet`, 6.5 MB of zstd holding all 467 484 words with their
tiers and boxes, which is what the site queries in the browser anyway. So the
whole site rebuilds from a clone without any of that:

```sh
python scripts/build_db.py --from-parquet web/data
python scripts/build_site.py
```

The rendered pages are therefore not committed. They were, and they were 73% of
the repository's history: 595 files regenerated whole on every build, and
neither HTML nor an already-compressed parquet deltas against its previous
version, so each rebuild added about 10 MB that could never be reclaimed.
