# Cronicón Mayoricense — a non-hallucinated digital edition

Álvaro Campaner y Fuertes, *Cronicón Mayoricense. Noticias y relaciones históricas
de Mallorca desde 1229 á 1800* (Palma, 1881). 671 leaves; 614 of them carry
running text, mostly in two columns.

Intended as a member of the [Corpus Balear](https://corpusbalear.org) family of
digital editions of public-domain Balearic sources.

**Status.** The OCR has been run over the whole book and measured, and the book has
been parsed into its own structure: 521 dated years, 244 footnotes separated from
the text they interrupt, 1 949 Jurats over 356 years, 29 numbered document
sections, and a glossary resolving 90% of the source attributions. Not yet built:
the human review pass over the 23 647 contested words, and the site.

**This is two books, and they are not equally reliable.** 870 positions have now
been adjudicated against the facsimile — 550 on the chronicle, 320 on the leaves
where Campaner prints letters, edicts and a 1541 booklet:

| | today | after reviewing the contested 5% |
|---|---:|---:|
| the chronicle — 79% of the words | 1 wrong word in **113** | 1 in **706** |
| the documents — 21% | 1 in **39** | 1 in **96** |

A single number would misdescribe both. Every word in `data/text/` carries its own
certainty tier, which is the honest way to publish this: mark the doubtful words,
link the facsimile, let the reader see which is which.

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

That is not only a general argument. `scripts/scan_health.py` asks each recogniser
to read **both** scans and compares it against itself — whatever makes a leaf hard
makes it hard on both, and cancels — and finds eleven leaves where the two
disagree by more than three points. The Internet Archive images are out of focus
on leaves 93, 94, 97 and 98, which between them carry **1 909 of the contested
positions**; the BNE copy has the facing page set off across leaf 122 in mirror
image. On those leaves `consensus.py --per-leaf-scan` swaps the panel onto the
legible copy, keeping six voters.

### 2. Six engines, chosen for independence rather than quality

| engine | on which scan |
|---|---|
| ABBYY (Internet Archive chOCR) | IA |
| Tesseract 5, `spa_old+cat+lat` | IA @300 dpi |
| Apple Vision (`VNRecognizeTextRequest`) | BNE @400 dpi |
| Apple Vision | IA @300 dpi |
| PaddleOCR PP-OCRv6 | IA |
| Kraken, fine-tuned on this book | IA |

The selection rule is **uncorrelated errors, not individual accuracy**, and the
measurements make that concrete in both directions:

- A five-engine set scoring **97.51%** — higher than the panel then in use — was
  **rejected**. It reaches that number by running two Tesseract variants over the
  same image. Near-clones vote together, inflating unanimity without adding
  evidence, and unanimity is the guarantee the accept rule rests on.
- **A seventh voter has been tried twice and made the queue worse both times**:
  Kraken took it from 26 298 to 35 328 contested positions (+34%), PaddleOCR to
  32 040 (+22%) — and both are *more* accurate than several sitting members.
  Accuracy and complementarity are different properties. What worked was
  **swapping**, not adding: putting them in place of the two weakest readings
  keeps six voters and takes the queue down to 23 647.
- **A three-engine fallback is not available.** The BNE-only trio is the one
  configuration with a *measured* shared error — 2 wrong in 386 unanimous
  positions — so however good its numbers look on a particular leaf, it cannot
  carry the accept rule.

Tesseract's language set matters: `spa_old+cat+lat` beats `spa_old` alone, because
the book quotes Catalan documents and Latin formulae at length and the cedilla in
Mallorcan surnames (Gaçó, Çaoliva) needs the Catalan model.

The panel is scored by `benchmark.py --consensus <dir>`, which reads the panel a
consensus directory recorded and recovers the engines drawn after the sample was
frozen **by word box** — an index renumbers when a leaf's geometry changes, a box
does not.

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

**This is also the pipeline's remaining weak point.** Two thirds of the review
queue is a segmentation artefact rather than a disagreement about characters:
measured over the queue as it then stood, 46.6% of contested positions have some
engine returning an empty string and 27.8% have a multi-word variant; only 34.8%
are a genuine disagreement about characters. On **25 leaves the engines do not
agree how many columns there are** (`scripts/layout_health.py`), and there the
contested rate is 21.96% against 4.70% everywhere else — the tables, the annotated
Jurats lists, anything where a merged line hides the very boundary that would have
separated it.

`consensus.py --align line` is the answer: match a printed line against the engine
text that overlaps it on the page, so the reading order stops mattering. It is
dramatically better where the layout is contested (leaf 453 36.1% → 6.4%, leaf 312
38.7% → 11.1%) and **worse on ordinary prose**, where the page-wide match already
works and this one costs unanimity (leaf 200: 86.1% → 7.4% unanimous). So it is
applied per leaf, to those 25 and no others.

**It does not come with the accept rule attached.** The 550 adjudications say what
unanimity is worth under the page-wide alignment, and not one of them falls on a
leaf aligned this way. Those leaves are marked `accept_unanimous: false`, and
their 11 114 non-contested positions are held back from the "accept unread" 78% —
not because they are doubtful, but because nothing has measured them. A stratified
round on those leaves discharges the whole block, or condemns it; that is the
difference between a bound and an assumption.

### 4. Token-level consensus

Every engine's token stream is aligned to a common reference and voted on, word by
word. Each position lands in one of four tiers:

| tier | tokens | share |
|---|---:|---:|
| all six agree | 367 923 | 77.7% |
| one dissenter | 58 322 | 12.3% |
| two dissenters | 23 531 | 5.0% |
| **contested** (three or more, or tied) | **23 647** | **5.0%** |
| **total** | **473 423** | |

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
| the panel as originally sampled | 97.25% |
| **the panel that builds the edition** | **99.04%** |
| plus the book's own lexicon, on contested positions only | 98.01% |

The last two rows are not on the same footing and the report says so: the
production panel is scored on the 495 positions every candidate panel can be
scored on, which excludes the 55 hardest, so the ordering between panels is what
that number is for. The 97.25% is the figure for the whole 550.

Per tier, for the production panel:

| tier | vote is right | n adjudicated |
|---|---:|---:|
| all six agree | **348 / 348 = 100%** | 348 |
| one dissenter | 98.9% | 87 |
| two dissenters | 100% | 37 |
| contested | 85.2% | 27 |

**The load-bearing row is the first.** In every adjudicated position where all six
engines agreed they were right, which is what makes it defensible to accept 78% of
the book without a human looking at it.

That claim has a stated limit: zero failures in 348 trials bounds the shared-error
rate at **0.86%** (95%, one-sided Clopper–Pearson), not at zero. It stood at 2.7%
after the first 110 adjudications; the second round of 250 was run specifically to
tighten it. And it is a bound on *Spanish chronicle prose* — see the caveat at the
top.

### 6. What review buys

| policy | words reviewed | residual error |
|---|---:|---:|
| accept the vote everywhere | 0 | ~0.96% — 1 wrong word in 105 |
| **review the contested 5.0%** | **23 647** | no residual measured; ≤0.65% at 95% |
| review contested + two-dissent | 48 004 | — |

The middle row does not say "zero". The production panel was right at all 461
adjudicated positions outside the contested tier, which makes the point estimate
zero and says nothing about the true rate; the bound is the honest number.

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
| **A seventh engine** | queue +34%, then +22% | Tried with Kraken and again with PaddleOCR, both more accurate than several sitting members. A seventh voice breaks agreements that were already right more often than it settles ones that were wrong. The panel is saturated at six. |
| **Folded-key alignment** (lowercase, accents and punctuation stripped, instead of exact equality) | no gain | Leaf 98 66.7% → 61.9% contested, leaf 163 worse. The alignment is not failing for want of anchors; on those leaves the readings genuinely diverge. |
| **Fitting a vertical scale between the scans** | 10× worse than doing nothing | The two differ by *where the page was cropped*, not by how much it was stretched. Fitting a slope turns a constant offset into an error that grows down the leaf. A plain shift, grid-searched, works. |
| **Swapping the geometry engine on the blurred leaves** | no gain | The word boxes were never the problem there; the image was. Fixed by swapping the *scan* instead. |
| **A layout detector (PP-DocLayout) for the columns** | 12/12 on the control, useless on the 25 | It is competent and genuinely independent of what the engines read — and it answers a different question. On the annotated Jurats leaves it returns a single `content` region spanning the width, which is *correct*: a table is one region, and decomposing it belongs to a different model. `TableCellsDetection` is that model and ships the **wired** detector, trained on tables drawn with rules; Campaner's are set typographically with none, so it finds one cell on leaf 631. Kept as `scripts/layout_paddle.py`, consumed by nothing. |
| **LLM post-correction** | not adopted | The evidence is genuinely mixed: Gemini 2.0 Flash reached 0.84% CER post-correcting historical German directories, but [ICDAR 2026 runs a competition](https://arxiv.org/pdf/2607.08143) on the hallucination and over-correction this causes. The lexicon experiment above is the same mechanism in a far weaker form and it already lost when unconstrained. If revisited, the defensible form is a vote **restricted to the candidates the engines produced**, never free text, measured before being trusted. |

### The lexicon that is kept

Built from **every unanimous position in all 614 leaves**: 27 316 distinct words,
8 780 of them seen three times or more. A word must appear **at least three times**
elsewhere in the book before its presence counts as evidence — once is not
attestation, and a one-off unanimous misreading would otherwise be enshrined as a
real word and start winning arguments.

It is a dictionary of *this book*, not of Spanish. That is the entire point.

---

## A book-specific recogniser, and what it taught

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

The un-fine-tuned base scores **68.26%** on the adjudicated positions — worst of
everything tried, since it is a French-dominated model that has never seen this
typeface. Fine-tuned it reaches 96.7% on body pages, better than any panel engine.

**And adding it as a seventh vote made the queue 34% bigger.** That is the single
most useful thing this experiment produced, and it generalised: PaddleOCR, whose
profile looked ideal for the job — 73% on the *contested* tier where the best panel
engine manages 48% — did the same thing at +22%. A panel is not improved by adding
accuracy to it. Both engines earn their seats only by **replacing** the two weakest
readings, which keeps six voters and takes the contested queue from 26 298 to
24 607 — and to 23 647 once the scan and the alignment are chosen per leaf.

The methodological risk that motivated the test was real and is worth stating: the
model is trained on consensus output, so it may have learned the panel's biases,
in which case its vote echoes rather than adds. Its accuracy on the contested tier
is the test that reveals this, and it is why the validation figure — scored against
consensus-derived labels — was never the thing that decided anything.

---

## Traps, and the guards against them

Every one of these was hit during development.

- **A drawn sample is data. Never regenerate it.** The strata depend on every
  engine's output, so any engine improvement changes which positions get drawn.
  Repairing the ABBYY-IA parser silently renumbered the sample and orphaned all
  550 adjudications. `benchmark.py` verifies a fingerprint of
  `(id, page, index, box)` and hard-fails on mismatch; `sample_loci.py` refuses to
  overwrite an existing sample without `--force`. When the guard fires, restore
  from git rather than re-drawing.
- **An index is not an identity; a word box is.** Anything that changes a leaf's
  geometry renumbers its positions, which is why two engines added after the
  sample was frozen could not be scored against it at all. Matching on the word
  box recovers 495 of the 550 — and refuses the other 55, because there some
  engine the two records share reads the position differently, which means the box
  has been re-tokenised and they are no longer the same word. `consensus.py`
  refuses outright to change the scan on a leaf that carries adjudications.
- **Two engines can read a leaf perfectly and still lose the vote**, if the panel
  puts most of its votes on a defective image. This is why the scan is chosen per
  leaf now, and why the check is a paired comparison of each recogniser against
  itself rather than an image-sharpness heuristic — sharpness is confounded by how
  much ink is on the page.
- **An engine reading a word is not the same as the panel being able to place it.**
  On leaf 115 every engine reads the Jurats' names correctly and the consensus
  returns them *empty*, because a page-wide token alignment drops them into the
  notes column's slots. The whole 13th-century series was missing for this reason
  and for no other.
- **Two scripts that know different things and do not talk.** `parse_documents.py`
  had the letters, edicts and reprinted booklets correctly delimited while
  `parse_entries.py` emitted 96 leaves of them as dated chronicle entries — 60 303
  words, one in six of the text, a medieval Catalan letter filed under 1400. Each
  script was right about what it measured. Nothing compared them.
- **A signature that separates two things on average may separate nothing.** The
  natural guard here — a document runs ten times longer than an entry, states no
  month, names no source, is alone on its leaf — is true of the medians and
  useless as a test: at every threshold there are *more* such entries outside the
  documents than inside, because twenty-eight leaves of continuous Germanía
  narrative look exactly the same. Measured before it was believed, and dropped.
- **The same class of bug, caught the same way.** Adding the rounds mechanism
  changed round 1's RNG seed. The benchmark cheerfully reported 6.75% accuracy — a
  plausible-looking number produced by scoring every engine against the wrong
  words. The fingerprint check exists because of this.
- **Review crops must be at native resolution.** Adjudicating from 78-pixel-tall
  crops produced one wrong call (`asi` for `así`); at full resolution the acute
  accent is unmistakable. Accent-versus-dot is exactly what most disagreements
  turn on.
- **Five pages is not enough to estimate a rate.** The pilot projected 17 000
  review decisions; the census over all 614 leaves counted **26 298** for the same
  panel. The gap is one class: the pilot's five body pages showed 2.1% contested
  where the real body average is 5.4%. The accuracy figures, resting on 550
  adjudications, were unaffected — only the volume estimate was wrong.
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
  extract_abbyy_bne.py     ABBYY-BNE, text and word boxes
  parse_chocr_ia.py        ABBYY-IA
  ocr_tesseract.py         ocr_vision.py   ocr_paddle.py   ocr_kraken.py
  layout.py                the shared column split and reading order
  build_ordered.py         applies it, producing comparable readings
  scan_health.py           which of the two scans is legible on each leaf
  consensus.py             token-level vote + the conflict queue
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
  review.py                the review tool: crops at native resolution, keyboard
  parse_sigla.py           the glossary the introduction prints

data/inventory.json        the 671-leaf survey (committed)
data/scan_health.json      the leaves where the two scans disagree (committed)
data/adjudication/         the drawn sample — data, never regenerate (committed)
data/ground_truth/         550 adjudicated readings (committed — the slow part)
data/{entries,jurats,documents,sigla,text}/   the parsed book (committed)
data/{raw,ia,pages,ocr}/   facsimiles and engine output (git-ignored, regenerable)
docs/OCR_BENCHMARK.md      the full measurement report
docs/EDITORIAL.md          what this edition changes, and what it refuses to
```

## Reproducing it

```sh
nix develop     # toolchain, pinned by flake.lock
uv sync         # Python, pinned by uv.lock
```

Full command sequence in [`docs/OCR_BENCHMARK.md` §7](docs/OCR_BENCHMARK.md).
Everything is idempotent and skips work already on disk.

### Rebuilding the site from a clone

The OCR itself is not in the repository and cannot be: the consensus is ten
thousand files and the per-word certainty is 100 MB of JSON. Its compact form
is — `web/data/*.parquet`, 4.7 MB of zstd holding all 467 318 words with their
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

## What the book has been parsed into

| | |
|---|---|
| `data/entries/` | the chronicle: 521 of 572 years found, **2 503 entries** as `Mes día.—texto—SIGLA`, with **244 footnotes** separated from the text they interrupt |
| `data/jurats/` | **1 949 names over 356 years**, one row per (year, seat, name) with its certainty tier |
| `data/documents/` | the 6 appendix blocks Campaner prints between the centuries, 29 numbered sections over 187 leaves — and **23 of them assembled as documents**, 97 595 words, each with its certainty carried through |
| `data/sigla/` | the glossary of manuscript sigla, resolving **1 632 of 1 804** attributions |
| `data/text/` | the readable transcription, with every editorially repaired word keeping the panel's reading under `printed` |

Two things found along the way that are worth stating as results rather than
process. **Leaf 39 prints the year heading `1449.` above an entry that reads «año
de 1249…»** — Campaner's own error, and by this edition's rules it stays; it is
the only chronological anomaly in the whole book. And **leaves 335–367 are a
facsimile reprint of a 1541 booklet** in its own typography, which uses the long s;
`docs/EDITORIAL.md` documents the rule that repairs 1 481 tokens of it and, more
importantly, the veto that stops it corrupting 47 tokens of perfectly good Catalan.

## What remains

1. **Do the review.** `scripts/review.py` is built and waiting: 34 761 positions,
   of which 8 986 carry a figure and 10 474 are capitalised, which is the order it
   serves them in. It is the same tool for the 23 647 contested words and for the
   adjudication round below.
2. **Measure the 159 document leaves.** The medieval Catalan and Latin have never
   been adjudicated. Their conflict rate is *lower* than the chronicle's (3.77%
   against 5.59%), which is not reassurance — it is exactly what correlated
   failure looks like. No reliability figure should be published for the edition
   until a round of adjudication covers them.
3. **Split the documents into their individual pieces.** The sections are
   assembled; the letters inside them are not separated. The Centellas section
   holds 20 salutations against 3 numbered pieces, so this needs a measured rule,
   not a guess.
4. **The site** — static SPA, Catalan UI, Cloudflare Worker, and a card on the
   Corpus Balear portal.

## Conventions

Repository content — code, comments, docs, commit messages — is in English. The
published site will be in Catalan, as with the sibling projects. The transcribed
text stays in Campaner's 1881 Spanish, verbatim.

## Licence

The 1881 edition is public domain. Code is intended for AGPL-3.0-or-later, curated
data for CC BY-NC, matching the sibling Corpus Balear projects.
