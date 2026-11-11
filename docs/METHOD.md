# Method

How the transcription is made and measured, what was tried and rejected,
and what the book has been parsed into. The edition in one page is the
[README](../README.md); the full pilot measurement is [OCR_BENCHMARK.md](OCR_BENCHMARK.md),
the normalisation rules [EDITORIAL.md](EDITORIAL.md), the files and commands
[PIPELINE.md](PIPELINE.md).

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

**Where that rule was relaxed, and how it is guarded.** On a few kinds of leaf the
engines read the words well and cannot agree in what order the page runs, so the
text that comes out is unusable even where every word is right: the six Jurats
lists (28 leaves) and the household accounts of 1307–1343 (leaves 159–164). There,
on the maintainer's decision, the page was read at native resolution with the help
of a vision model, and **every reading was compared against each engine's text of
that leaf**. 2 431 of the 2 436 Jurats match some engine letter for letter; the five
that do not carry a superior letter (`B.ª`) no engine renders. The comparison caught
the model normalising twice — an accent added by analogy, a `J` the press never
inked — and both were undone. Every such decision is recorded in
`data/review/decisions.jsonl` with its source, so the share of the edition that
rests on no engine's reading is counted, not assumed: **168 positions** of the
text, most of them ledger cells on leaves 159–164, plus four drop caps, one
line-initial syllable on leaf 487 and a few words of the 1542 booklet — and the five Jurats above. The site's method page
says the same.

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
are a genuine disagreement about characters. On **23 leaves the engines do not
agree how many columns there are** (`scripts/layout_health.py`), and there the
contested rate is 21.96% against 4.70% everywhere else — the tables, the annotated
Jurats lists, anything where a merged line hides the very boundary that would have
separated it.

`consensus.py --align line` is the answer: match a printed line against the engine
text that overlaps it on the page, so the reading order stops mattering. It is
dramatically better where the layout is contested (leaf 453 36.1% → 6.4%, leaf 312
38.7% → 11.1%) and **worse on ordinary prose**, where the page-wide match already
works and this one costs unanimity (leaf 200: 86.1% → 7.4% unanimous). So it is
applied per leaf, to those 23 and no others — with one exception that is a rule in
itself: **a leaf carrying adjudications is held page-aligned**, because aligning it
by line renumbers it. Leaf 642 is the only one.

**It does not come with the accept rule attached.** The 550 adjudications say what
unanimity is worth under the page-wide alignment, and not one of them falls on a
leaf aligned this way. Those leaves are marked `accept_unanimous: false`, and
their **9 000** non-contested positions are held back from the accepted share —
not because they are doubtful, but because nothing has measured them. A stratified
round on those leaves discharges the whole block, or condemns it; that is the
difference between a bound and an assumption.

### 4. Token-level consensus

Every engine's token stream is aligned to a common reference and voted on, word by
word. Each position lands in one of four tiers:

| tier | tokens | share |
|---|---:|---:|
| all six agree | 369 272 | 79.0% |
| one dissenter | 55 686 | 11.9% |
| two dissenters | 21 002 | 4.5% |
| **contested** (three or more, or tied) | **20 136** | **4.3%** |
| adjudicated against the facsimile | 1 388 | 0.3% |
| **total** | **467 484** | |

Those are the counts in `web/data/word.parquet`, which is what the site queries;
they move whenever the layout improves, and every figure below is the one that
matches them.

The winner is always a string some engine actually produced — **except** for the
positions in the last row, where a person read the facsimile and typed what is
printed. That tier exists so the share of the edition resting on no engine's
reading can be counted instead of assumed. It is 1 388 words in 467 484, of
which 168 no engine read at all.

### 5. Measurement against human ground truth

Agreement is not accuracy. To turn one into the other, 550 token positions were
adjudicated one by one against the facsimile — **stratified** by tier, so the rare
and costly cases are represented, with every reported figure re-weighted by each
tier's true share of the corpus.

A third round of 320 has since been adjudicated on the document leaves and is kept
as a **separate sample**, not merged into these. The two populations have different
strata shares — 78.7% unanimous on the document leaves against 70.4% on the pilot
ones — so merging them would weight medieval Catalan by the chronicle's proportions
and quietly corrupt every figure resting on them. The numbers in this section are
the chronicle's; the documents' are in the [README](../README.md).

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
engines agreed they were right, which is what makes it defensible to accept 79% of
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
| **review the contested 4.3%** | **20 137** | no residual measured; ≤0.65% at 95% |
| review contested + two-dissent | 41 139 | — |

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
| **Finding a table by "the figure comes first"** | 9 detections, 4 real | `24,294 hombres útiles para tomar las armas.` really is a table row, and so is nothing else that begins with a number: prose opens with a date or a price often enough (`19 de Febrero, por haber llovido…`, `15 ss. la barcilla`) that the family cannot carry a rule. Its mirror image, the figure **last**, is 16 detections and 16 real, and is kept. |
| **Repairing a doubled heading across a gap** | fires 95 times, nearly all false | `dedupe` drops a word the alignment gave two slots, and it is safe because the two copies are adjacent: `month_of` tolerates two wrong letters, so over a gap it turns `moro`, `cuyo` and `judío` into months. Adjacency is what makes the tolerance safe. |
| **Scanning up from a column's foot for a note continuing from the one before** | reads correctly, cost 3 years | It is right about leaf 105 and it swallowed the year headings of 1289, 1339 and 1730, because `1339.` alone on a line has no ascender or descender and measures like note type. Nine lines of apparatus are not worth a year of the chronicle, and the loss is silent where the gain is not. |
| **78-pixel contact sheets as the adjudication surface** | one wrong adjudication | See the trap below. Sheets are now opt-in and exist only so the frozen sample stays reproducible. |
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
24 607 — and to 23 647 once the scan and the alignment are chosen per leaf. (The
queue has since fallen further, to 20 137, but on layout work rather than on
anything to do with the panel; those are the figures the engine choice was made
on.)

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
- **The empty string was winning votes.** The vote runs one geometric slot at a
  time, which works while the engines agree where a word ends and fails completely
  where they do not: `cuartos.—J. V.—30.—Mataron` is one printed stretch and every
  engine cuts it somewhere else, so at three of five slots more engines returned
  `''` than returned any one word and `—30.—Mataron` lost 3–2 and vanished.
  **5 476 positions, up to 9 668 words.** An empty reading is not a recogniser
  saying the paper is blank; it is its tokens having landed in the neighbouring
  slot, and counting it as a vote is treating absence of evidence as evidence of
  absence. `scripts/spans.py` votes on the whole run at once, so the comparison is
  between readings of the same ink. The guard that keeps it honest: **a span may
  only recover text, never remove it**, because three engines skipping a display
  heading is the identical error one level up.
- **A rule wired into one assembly is wired into neither.** Three scripts turn the
  consensus into prose — the readable text, the notices, the documents — and every
  repair has at some point landed in one and been missing from the others. The
  joined words went into the published text and not the notices; the adjudicated
  cells of leaf 159 appeared in the text and vanished from the document the moment
  it was rebuilt. Nothing fails when this happens; the output is merely older.
  Repairs belong in the shared layer, and the invariants are re-checked across all
  three afterwards.
- **A section boundary is a point on the page, not a point in the reading order**,
  and on a two-column leaf those are not the same thing. Section V of the
  14th-century block opens in the *first* column of leaf 159, so everything after
  it in reading order was taken — including the top of the second column, where
  section IV is still finishing. The edition published a household account of 1307
  running straight into a fleet's storm damage. Nothing printed *above* a section's
  first line belongs to it.
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
  them separately so they neither flatter nor damn any engine. The rules are in
  [EDITORIAL.md](EDITORIAL.md).

---

## What the book has been parsed into

| | |
|---|---|
| `data/entries/` | the chronicle: **528 of 572 years**, **3 459 notices** as `Mes día.—texto—SIGLA`, and **320 footnotes** separated from the text they interrupt |
| `data/jurats/` | **2 436 names over 423 years**, all six series read off the facsimile and checked against every engine (`data/adjudication/jurats/`), one row per (year, seat, name) in the order the leaf prints them, plus 12 remarks where Campaner prints a sentence instead of names |
| `data/documents/` | the 6 appendix blocks Campaner prints between the centuries, 32 numbered sections over 187 leaves, every numeral found — **26 assembled as documents**, 96 614 words, cut into their **39 numbered pieces**, with Campaner's 49 notes and the certainty carried through |
| `data/tables/` | **45 tables, 229 rows** on 23 leaves — the harvests, the plagues, the census of 1784, the household accounts of 1307 |
| `data/sigla/` | the glossary, resolving **3 147 of 3 400** attributions (93%), plus a hand-entered dossier on 26 of the sources |
| `data/text/` | the readable transcription, with every editorially repaired word keeping the panel's reading under `printed` |

Three of those rows exist only because a rule was measured before it was believed.
**The footnotes** are found by the union of two tests — where they sit and how big
the type is — because leaf 86 is eleven lines of chronicle over 122 of a quoted
letter and the band alone published all 122 as chronicle. **The tables** recover
structure and not text: no character is added, removed or changed, only the record
of which words make up which row, and the signal is that leaf 569's figures end at
x 0.793, 0.796, 0.797 and 0.796 while prose does not do that. And **the pieces**
were declared unfindable in an earlier draft of the README — "20 salutations against
only 3 numbered pieces" — which turned out to be a measurement of our reading order
rather than of the book. All twenty-one numbers are on the page, set alone and
centred over the letter they open; it took the centred-line rule to see them.

Two things found along the way that are worth stating as results rather than
process. **Leaf 39 prints the year heading `1449.` above an entry that reads «año
de 1249…»** — Campaner's own error, and by this edition's rules it stays; it is
the only chronological anomaly in the whole book. And **leaves 335–367 are a
facsimile reprint of a 1542 booklet** in its own typography, which uses the long s;
`docs/EDITORIAL.md` documents the rule that repairs 1 481 tokens of it and, more
importantly, the veto that stops it corrupting 47 tokens of perfectly good Catalan.
