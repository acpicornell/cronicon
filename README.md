# Cronicón Mayoricense — a non-hallucinated digital edition

Álvaro Campaner y Fuertes, *Cronicón Mayoricense. Noticias y relaciones históricas
de Mallorca desde 1229 á 1800* (Palma, 1881). 671 leaves; 614 of them carry
running text, mostly in two columns.

Intended as a member of the [Corpus Balear](https://corpusbalear.org) family of
digital editions of public-domain Balearic sources.

**Status.** The OCR has been run over the whole book and measured. Not yet built:
the human review pass, the editorial normalisation, the parse into the chronicle's
own structure, and the site.

---

## The problem, and the constraint

The book exists as photographs of pages. We need text. No single OCR engine is
reliable enough on 19th-century two-column Spanish: the best one measured here
still misses one word in eighteen, and the value of a chronicle is concentrated in
exactly what OCR gets wrong — proper names, dates and figures.

The constraint that shapes everything else: **no generative model may write a
character of the transcription.** An LLM asked to read this material produces
fluent, plausible, wrong text, and — worse — silently modernises. Campaner prints
`formacion`, `dia`, `Setiembre`, `mallorquin`; a model "corrects" all four, and the
result looks right, which makes it far more dangerous than a visible misread. The
ABBYY layer shipped inside the BNE PDF already does this.

So the design goal is not "the most accurate text" but **text we can justify**:
every accepted word must be one that several independent recognisers, whose
mistakes are uncorrelated, all saw.

## The method

### 1. Two independent scans

| | source | resolution | OCR layer it ships with |
|---|---|---|---|
| **BNE** | Biblioteca Digital Hispánica | 200 dpi | ABBYY FineReader Server, embedded in the PDF |
| **IA** | [Internet Archive / Google Books](https://archive.org/details/CroniconMayoricenseCampaner) | ~630 dpi | Internet Archive's own ABBYY run (chOCR, with per-word confidence) |

Same 1881 edition, same pagination. `scripts/inventory.py` establishes the mapping
as a constant offset of **−2** (IA leaf = BNE PDF page − 2), confirmed by 377
leaves spanning the whole book.

Two scans are not redundancy. They carry **different physical defects** — a stain,
a bleed-through, a fold present on one is absent on the other — so an engine that
misreads because of a scan artefact is not echoed by the engines reading the other
copy. Measured: either scan alone costs 1.5–2.5 accuracy points and roughly
doubles the unresolvable ties.

### 2. Six engines, chosen for independence rather than quality

| engine | on which scan |
|---|---|
| ABBYY (embedded in the BNE PDF) | BNE |
| ABBYY (Internet Archive chOCR) | IA |
| Tesseract 5, `spa_old+cat+lat` | IA @300 dpi |
| Tesseract 5, `spa_old` | BNE @400 dpi |
| Apple Vision (`VNRecognizeTextRequest`) | BNE @400 dpi |
| Apple Vision | IA @300 dpi |

Three engine families × two scans. The selection rule is **uncorrelated errors,
not individual accuracy**, and the measurements make that concrete in both
directions:

- The *worst* engine is ABBYY-BNE at 88.32%. Removing it **lowers** the panel from
  97.25% to 96.92% and pushes ties from 18 to 25. It is wrong where the others are
  right, so it carries information despite being poor.
- A five-engine set scoring **97.51%** — higher than the recommendation — was
  **rejected**. It reaches that number by running two Tesseract variants over the
  same image. Near-clones vote together, inflating unanimity without adding
  evidence, and unanimity is the guarantee the accept rule rests on.

Tesseract's language set matters: `spa_old+cat+lat` beats `spa_old` alone, because
the book quotes Catalan documents and Latin formulae at length and the cedilla in
Mallorcan surnames (Gaçó, Çaoliva) needs the Catalan model.

### 3. One reading order for everyone

Comparing engines on their own output order measures their layout analysis, not
their recognition. The first disagreement survey came out at 40% of tokens, almost
all of it column interleaving.

So every engine is asked only for **positioned lines**, and one shared algorithm
(`scripts/layout.py`) does the column split and the top-to-bottom ordering for all
of them. Columns are found by clustering line **left edges**, not by looking for an
empty gutter: the gutter is not reliably empty, because ABBYY's line boxes overrun
it by a few points on some leaves. A candidate boundary is rejected if text
actually crosses it, which separates a real column break from a paragraph indent.

After this, all readings agree on the column count on every pilot leaf, and the
disagreement rate falls to 25%.

### 4. Token-level consensus

Every engine's token stream is aligned to a common reference and voted on, word by
word. Each position lands in one of four tiers:

| tier | tokens | share |
|---|---:|---:|
| all six agree | 337 542 | 71.3% |
| one dissenter | 77 820 | 16.4% |
| two dissenters | 31 620 | 6.7% |
| **contested** (three or more, or tied) | **26 298** | **5.6%** |
| **total** | **473 280** | |

The winner is always a string some engine actually produced. The pipeline can be
wrong, but only in ways some recogniser was wrong first.

### 5. Measurement against human ground truth

Agreement is not accuracy. To turn one into the other, 550 token positions were
adjudicated one by one against the facsimile — **stratified** by tier, so the rare
and costly cases are represented, with every reported figure re-weighted by each
tier's true share of the corpus.

| | accuracy |
|---|---:|
| best single engine (Tesseract `spa_old+cat+lat`, IA @300) | 94.51% |
| **six-engine majority vote** | **97.25%** |
| plus the book's own lexicon, on contested positions only | **98.01%** |

Per tier:

| tier | vote is right | n adjudicated |
|---|---:|---:|
| all six agree | **360 / 360 = 100%** | 360 |
| one dissenter | 98.6% | 70 |
| two dissenters | 96.7% | 60 |
| contested | 65.0% | 60 |

**The load-bearing row is the first.** In 360 positions where all six engines
agreed they were right 360 times, which is what makes it defensible to accept 71%
of the book without a human looking at it.

That claim has a stated limit: zero failures in 360 trials bounds the shared-error
rate at **0.83%** (95%, one-sided Clopper–Pearson), not at zero — at most ~2 700
undetected wrong words. It stood at 2.7% after the first 110 adjudications; the
second round of 250 was run specifically to tighten it.

### 6. What review buys

| policy | words reviewed | residual error |
|---|---:|---:|
| accept the vote everywhere | 0 | ~2.7% — 1 wrong word in 37 |
| **review the contested 5.6%** | **26 298** | **0.46% — 1 wrong word in 219** |
| review contested + two-dissent | 57 918 | ~0.23% — 1 wrong word in 440 |

At a few seconds per decision with the crop on screen, the recommended row is
25–30 hours: interruptible, and priority-orderable so proper nouns, dates and
figures come first.

---

## What was tried and rejected

Recording the failures matters as much as the successes; each looked reasonable
beforehand.

| approach | result | why |
|---|---|---|
| **Character-level voting** | 97.25%, no gain | Returned 6 strings no engine ever read. Inventing text is the one thing this pipeline exists to prevent, whatever produces it. |
| **Medoid** (candidate closest to all others) | 97.46%, ties 18→8 | Looks like a win, but the positions it newly decides are only 65% right — *below* the 71% of those plain majority already decided. It converts ties into confident wrong answers. |
| **Book lexicon applied everywhere** | 97.05% | Rescues contested positions (65%→77%) but damages the tiers where the panel was already nearly right (99%→96%, 97%→90%). Net loss. |
| **Book lexicon on contested only** | **98.01%** | **Kept.** Confining it to where the panel is genuinely stuck keeps the gain and drops the damage. |
| **A Spanish dictionary (hunspell)** | not run | Would "correct" `formacion`, `dia`, `Setiembre`, `mallorquin` into modern spellings — introducing errors that look right. The book's own vocabulary is used instead. |
| **LLM post-correction** | not adopted | The evidence is genuinely mixed: Gemini 2.0 Flash reached 0.84% CER post-correcting historical German directories, but [ICDAR 2026 runs a competition](https://arxiv.org/pdf/2607.08143) on the hallucination and over-correction this causes. The lexicon experiment above is the same mechanism in a far weaker form and it already lost when unconstrained. If revisited, the defensible form is a vote **restricted to the candidates the engines produced**, never free text, measured before being trusted. |

### The lexicon that is kept

Built from **every unanimous position in all 614 leaves**: 27 316 distinct words,
8 780 of them seen three times or more. A word must appear **at least three times**
elsewhere in the book before its presence counts as evidence — once is not
attestation, and a one-off unanimous misreading would otherwise be enshrined as a
real word and start winning arguments.

It is a dictionary of *this book*, not of Spanish. That is the entire point.

---

## In progress: a book-specific recogniser

The panel produces 8 849 printed lines on which all six engines agree on every
word. That is training data costing no human time, with label noise bounded at
0.83% by the adjudications.

`scripts/build_htr_dataset.py` crops them from the Internet Archive scan at native
resolution, and `ketos` fine-tunes [CATMuS-Print](https://readcoop.eu/model/) — a
diachronic Latin-script print model — on them with
[Kraken](https://github.com/mittagessen/kraken), the engine behind eScriptorium.

Two exclusions keep the evaluation honest:

- **The twelve pilot pages are held out entirely.** They carry the 550
  adjudications, the only ground truth not derived from the consensus itself.
- **The train/validation split is by leaf, not by line.** Lines from one leaf share
  paper, inking and wear; a random line split would leak and flatter the model.

Measured so far: the un-fine-tuned base scores **68.26%** on the adjudicated
positions — worst of everything tried, since it is a French-dominated model that
has never seen this typeface. Fine-tuning reaches 99.7% character accuracy on
held-out leaves after four epochs. Whether that becomes a useful seventh vote is
decided by `scripts/score_engine.py` against the 550 adjudications, not by the
validation figure, which is scored against consensus-derived labels and so partly
measures the model reproducing its own training distribution.

**The open methodological risk:** the model is trained on consensus output, so it
may have learned the panel's biases. If so its vote echoes rather than adds. Its
accuracy on the *contested* tier is the test that reveals this.

---

## Traps, and the guards against them

Every one of these was hit during development.

- **A drawn sample is data. Never regenerate it.** The strata depend on every
  engine's output, so any engine improvement changes which positions get drawn.
  Repairing the ABBYY-IA parser silently renumbered the sample and orphaned all
  550 adjudications. `benchmark.py` verifies a fingerprint of `(id, page, index)`
  and hard-fails on mismatch; `sample_loci.py` refuses to overwrite an existing
  sample without `--force`. When the guard fires, restore from git rather than
  re-drawing.
- **The same class of bug, caught the same way.** Adding the rounds mechanism
  changed round 1's RNG seed. The benchmark cheerfully reported 6.75% accuracy — a
  plausible-looking number produced by scoring every engine against the wrong
  words. The fingerprint check exists because of this.
- **Review crops must be at native resolution.** Adjudicating from 78-pixel-tall
  crops produced one wrong call (`asi` for `así`); at full resolution the acute
  accent is unmistakable. Accent-versus-dot is exactly what most disagreements
  turn on.
- **Five pages is not enough to estimate a rate.** The pilot projected 17 000
  review decisions; the census over all 614 leaves counted **26 298**. The gap is
  one class: the pilot's five body pages showed 2.1% contested where the real body
  average is 5.4%. The accuracy figures, resting on 550 adjudications, were
  unaffected — only the volume estimate was wrong.
- **ABBYY does not read display headings at all.** The letterspaced `APÉNDICES` on
  leaf 631 and `INTRODUCCION.` on leaf 14 are simply absent from the embedded
  layer. Section boundaries are anchored on ordinary body text instead, and each
  anchor must match exactly one leaf or `inventory.py` fails rather than guessing.
- **Never drive scan alignment off a per-leaf printed page number.** ABBYY drops
  the leading digit often enough (`5^ CRONICON` for 54) that an earlier version
  confidently mapped leaf 211 to IA leaf 29. The offset is established once from
  the modal match; printed numbers only ever validate it.
- **Running heads must be stripped by content, not position.** The two scans crop
  their margins differently — the head sits at y≈0.082 on BNE leaves and 0.094 on
  IA ones, with body text at 0.093 and 0.11 — so no single band separates them on
  both, and the panel ends up voting on whether `MAYORICENSE.` is there at all.
- **ABBYY-IA emits ~2.4% of "words" containing two words**, with a bounding box
  covering only part of them. The per-character boxes are correct, so words are
  rebuilt from their characters and the word-level box is never used.
- **Upscaling is not resolution.** Tesseract on the BNE scan interpolated to
  600 dpi scores *worse* than the same engine at its native 200 dpi.
- **PyTorch has no CTC loss on Apple's MPS backend**
  ([pytorch#160830](https://github.com/pytorch/pytorch/issues/160830); the Kraken
  feature request has been [open since 2022](https://github.com/mittagessen/kraken/issues/358)).
  With `PYTORCH_ENABLE_MPS_FALLBACK=1` the GPU idles waiting on transfers at
  0.85 it/s — marginally *slower* than plain CPU at 0.89 it/s. For a 1 MB model,
  train on CPU.

---

## Editorial position

- **Nothing is modernised.** 1881 orthography stands as printed: `á`, `ó`,
  `formacion`, `dia`, `Setiembre`, `mallorquin`.
- **Campaner's own errors stand.** The facsimile is the source of truth. The
  printed errata are recorded as an annotation layer, never silently applied.
- **Small capitals and line-end hyphenation are normalisation decisions**, handled
  deterministically and documented, not recognition results. The benchmark scores
  them separately so they neither flatter nor damn any engine.

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
  extract_abbyy_bne.py     engine A          parse_chocr_ia.py   engine B
  ocr_tesseract.py         engine C          ocr_vision.py       engine D
  layout.py                the shared column split and reading order
  build_ordered.py         applies it, producing comparable readings
  consensus.py             token-level vote + the conflict queue
  sample_loci.py           stratified sample + facsimile review sheets
  benchmark.py             scoring, ablations, census
  arbitrate.py             deterministic arbitration rules, measured
  score_engine.py          score any new engine on the frozen sample
  build_htr_dataset.py     unanimous lines -> Kraken training set
  ocr_kraken.py            the book-specific model as a seventh engine

data/inventory.json        the 671-leaf survey (committed)
data/adjudication/         the drawn sample — data, never regenerate (committed)
data/ground_truth/         550 adjudicated readings (committed — the slow part)
data/{raw,ia,pages,ocr}/   facsimiles and engine output (git-ignored, regenerable)
docs/OCR_BENCHMARK.md      the full measurement report
```

## Reproducing it

```sh
nix develop     # toolchain, pinned by flake.lock
uv sync         # Python, pinned by uv.lock
```

Full command sequence in [`docs/OCR_BENCHMARK.md` §7](docs/OCR_BENCHMARK.md).
Everything is idempotent and skips work already on disk.

## What remains

1. **The review tool** — native-resolution crops, keyboard-driven, decisions to an
   append-only file so re-runs replay them, ordered by what matters.
2. **Deterministic normalisation**, every rule written down in `docs/EDITORIAL.md`.
3. **The parse into the chronicle's structure** — `year → Mes día.—texto—SIGLA` —
   plus the glossary of manuscript sigla from the introduction.
4. **The site** — static SPA, Catalan UI, Cloudflare Worker, and a card on the
   Corpus Balear portal.

## Conventions

Repository content — code, comments, docs, commit messages — is in English. The
published site will be in Catalan, as with the sibling projects. The transcribed
text stays in Campaner's 1881 Spanish, verbatim.

## Licence

The 1881 edition is public domain. Code is intended for AGPL-3.0-or-later, curated
data for CC BY-NC, matching the sibling Corpus Balear projects.
