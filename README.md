# Cronicón Mayoricense — a non-hallucinated digital edition

Álvaro Campaner y Fuertes, *Cronicón Mayoricense. Noticias y relaciones históricas
de Mallorca desde 1229 á 1800* (Palma, 1881): 671 leaves, a chronicle of Mallorca
year by year. Part of the [Corpus Balear](https://corpusbalear.org) family of
digital editions of public-domain Balearic sources.

**Live at <https://cronicon.corpusbalear.org/>**, deployed from this repository
on every push.

## What it is

The text is read by **six independent OCR engines voting word by word** over two
different scans of the book (BNE and Internet Archive). No generative model writes
the transcription: every accepted word is one several engines saw, and every word
carries its certainty tier, so the site marks the doubtful ones and links each
page to the facsimile. Nothing is modernised; Campaner's spelling and his own
errors stand.

The one exception is stated and counted: the Jurats lists and the account tables
of leaves 159–164, where the engines could not agree on the reading order, were
read off the facsimile with the help of a vision model and checked against every
engine. 167 positions of the text rest on no engine's reading.

The book has been parsed into its own structure: **528 years, 3 459 dated
notices, 382 footnotes, 2 436 Jurats, 25 documents, 45 tables** and the sources
Campaner cites, all in a 6.5 MB parquet the site queries in the browser.

## How reliable

Measured against 870 positions adjudicated against the facsimile:

| | today | after reviewing the contested words |
|---|---:|---:|
| the chronicle — 79% of the words | 1 wrong word in **113** | 1 in **706** |
| the documents — 21% | 1 in **39** | 1 in **96** |

The review of the 20 137 contested words (4.3%) has not been done yet.

## Running it

```sh
nix develop     # tesseract + uv, pinned by flake.lock
uv sync         # Python, pinned by uv.lock

# the site alone, from a clone
python scripts/build_db.py --from-parquet web/data
python scripts/build_site.py
python scripts/check_site.py
python scripts/dev_server.py    # http://127.0.0.1:8788
```

## Documentation

- [`docs/METHOD.md`](docs/METHOD.md) — the method, the measurements, what was
  tried and rejected, and what the book has been parsed into
- [`docs/OCR_BENCHMARK.md`](docs/OCR_BENCHMARK.md) — the pilot benchmark in full
- [`docs/EDITORIAL.md`](docs/EDITORIAL.md) — what this edition changes, and what
  it refuses to
- [`docs/PIPELINE.md`](docs/PIPELINE.md) — every script and data file, and the
  full rebuild from the engines' output

## What remains

1. The human review of the contested words (`scripts/review.py`).
2. A stratified round on the leaves aligned line by line, whose positions are
   held back from the accepted share until measured.
3. Section X of the 16th-century appendix block, which is still not found.
4. The notes column of the annotated Jurats leaves (58–60, 114–121).

## Conventions and licence

Repository content is in English, the site in Catalan, and the transcription in
Campaner's 1881 Spanish, verbatim. The 1881 edition is public domain; code is
intended for AGPL-3.0-or-later and curated data for CC BY-NC, matching the
sibling Corpus Balear projects.
