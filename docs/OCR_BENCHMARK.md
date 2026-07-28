# OCR pilot — Cronicón Mayoricense (Palma, 1881)

**Verdict: worth building.** A consensus of six independent readings, plus human
review of the 5.6% of words the engines argue about, gets the book to roughly one
wrong word in 220 — with no generative model anywhere near the transcription.

The panel has since been run over the whole book: 473 280 token positions across
614 leaves, of which 26 298 need a human. See §4.

Measured on twelve pages chosen to cover every page class in the book, against
**550 word positions** adjudicated one by one against the facsimile, in two
rounds: 300 stratified across all agreement levels, then 250 more concentrated on
the unanimous stratum to bound the errors that no amount of voting can catch.

---

## 1. What was tested

Two independent digitisations of the same 1881 edition:

| | source | resolution | OCR layer it ships with |
|---|---|---|---|
| **BNE** | `data/raw/Cronicon-mayoricense.pdf`, Biblioteca Digital Hispánica | **200 dpi** | ABBYY FineReader Server, embedded in the PDF |
| **IA** | [archive.org/details/CroniconMayoricenseCampaner](https://archive.org/details/CroniconMayoricenseCampaner), a Google Books scan | **~630 dpi** | Internet Archive's own ABBYY run (chOCR, with per-word confidence) |

The two are the same edition with the same pagination: matching printed page
numbers gives a constant offset of −2 (IA leaf = BNE PDF page − 2) on 415 of 480
pages that could be matched automatically, the rest being ABBYY misreads of the
running head rather than real divergence (`scripts/align_scans.py`).

Fourteen readings were produced per page: the two embedded ABBYY layers, eight
Tesseract 5.5.2 configurations (both scans × 200/300/400/600 dpi × `spa_old` /
`spa` / `spa_old+cat+lat` × psm 3/1) and four Apple Vision runs
(`VNRecognizeTextRequest`, accurate, `es-ES`, both scans, language correction on
and off).

**No generative model was used to produce or repair any transcription.** The only
LLM involvement was reading facsimile crops to settle disagreements — a
verification task with the evidence on screen, not free-form transcription.

### Reading order is imposed, not inherited

Comparing engines on their own output order measures their layout analysis, not
their recognition. The first survey came out at 40% of tokens disagreeing, almost
all of it column interleaving. So every engine is asked only for *positioned
lines*, and one shared algorithm (`scripts/layout.py`) does the column split and
the top-to-bottom ordering for all of them. After that, all fourteen readings
agree on the column count on every one of the twelve pages (1 column for the
introduction and errata, 2 for the body, 3 for the appendix name lists) — one
outlier aside — and the disagreement rate falls to 25%.

---

## 2. Is Tesseract enough? — the single-engine table

Corpus-weighted token accuracy (see §4 for the weighting):

| engine | accuracy |
|---|---:|
| **Tesseract `spa_old+cat+lat`, IA scan @300 dpi** | **94.51%** |
| Tesseract `spa`, IA @300 | 93.29% |
| Tesseract `spa_old`, IA @300 (psm 3 and psm 1 identical) | 93.07% |
| Apple Vision, BNE @400, language correction on | 92.15% |
| Apple Vision, BNE @400, correction off | 91.84% |
| ABBYY (Internet Archive) | 90.52% |
| Apple Vision, IA @300, correction on | 90.17% |
| Tesseract `spa`, BNE @400 | 89.81% |
| Tesseract `spa_old`, BNE @200 | 89.61% |
| Tesseract `spa_old`, BNE @400 | 88.52% |
| **ABBYY (BNE, the layer already in our PDF)** | **88.32%** |
| Tesseract `spa_old`, BNE @600 (upscaled) | 86.98% |

Four things fall out of this:

1. **Tesseract alone is not enough.** The best single configuration still misses
   one word in twenty. For a chronicle whose value is in proper names, dates and
   figures, that is not a scholarly transcription.
2. **Tesseract is nevertheless the best single engine here** — better than Apple
   Vision and better than either ABBYY — provided it reads the good scan and is
   given the right languages.
3. **`spa_old+cat+lat` beats `spa_old` by 2.4 points.** The Cronicón quotes
   Catalan documents and Latin formulae at length, and the cedilla in Mallorcan
   surnames (Gaçó, Çaoliva) is recovered by the Catalan model where the Spanish
   ones give `Gacó` or `Gagó`. Cheap, large win.
4. **The scan matters more than the engine.** Every IA (630 dpi) variant beats
   the corresponding BNE (200 dpi) one. And upscaling does not substitute for
   resolution: Tesseract on the BNE scan interpolated to 600 dpi is the *worst*
   reading in the table, 3 points below the same engine at the native 200 dpi.
   The Internet Archive scan should be the primary source of images.

Apple Vision deserves a note of its own: it is extraordinarily fast (48 page-runs
in 6.6 s on the M4 — the whole book would take about 90 seconds) and it is the
strongest engine on the BNE scan, but it is oddly *worse* on the better scan, and
it silently drops whole lines more often than the others. It earns its place in
the panel for independence, not for solo accuracy.

---

## 3. The consensus result

Majority vote over a panel of six deliberately uncorrelated readings — ABBYY×2,
Tesseract×2, Vision×2, spanning both scans:

| | accuracy |
|---|---:|
| best single engine | 94.51% |
| **six-engine majority vote** | **97.25%** |
| five engines (drop `abbyy-bne`, add `spa_old+cat+lat`) | **97.51%** |

Broken down by how much the panel agreed:

| agreement | share of tokens | vote is right | ties |
|---|---:|---:|---:|
| all six agree | 70.4% | **360 / 360 = 100%** | 0 |
| one dissenter | 15.3% | 98.6% | 0 |
| two dissenters | 7.8% | 96.7% | 0 |
| three or more, or tied | 6.5% | 65.0% | 18 / 60 |

**The load-bearing finding is the first row.** In 360 adjudicated positions where
all six engines agreed, they were right 360 times. That is what makes an
automatic pipeline defensible: the 70% of the book the engines are unanimous
about can be accepted without a human looking at it.

**How firm is that?** Zero failures in 360 trials bounds the shared-error rate at
**0.83% (95%, one-sided Clopper–Pearson)**. Since the unanimous stratum covers
70% of all tokens, the worst case consistent with the evidence is **0.58% of the
book's words wrong and undetected** — about 2 700 of 473 280. That is now the
same order as the 0.46% residual that survives the planned human review, so it no
longer dominates the error budget. It was the reason for the second round: after
the first 110 adjudications the bound stood at 2.7%, or ~9 000 words.

### Panel ablation

| panel | engines | accuracy | ties |
|---|---:|---:|---:|
| best 3 + `spa_old+cat+lat` + `abbyy-ia` | 5 | **97.51%** | 16 |
| the six as sampled | 6 | 97.25% | 18 |
| drop `abbyy-bne` | 5 | 96.92% | 25 |
| IA scan only | 3 | 95.69% | 38 |
| BNE scan only | 3 | 94.84% | 37 |
| Vision×2 + Tesseract-IA | 3 | 94.93% | 28 |
| drop both ABBYY | 4 | 94.71% | 36 |

Both scans are needed: either one alone costs about 2 points and doubles the
ties. The weak `abbyy-bne` layer still earns its seat — dropping it *lowers*
accuracy, because its errors are uncorrelated with the others'.

### 3b. The panel that actually builds the edition, scored at last

Everything under `data/text/`, `data/entries/`, `data/jurats/`,
`data/documents/` and `data/sigla/` is built from **`consensus6_swap_swapk`** —
`abbyy-ia`, `tess-ia-300dpi-spa_old-cat-lat`, `vision-bne`, `vision-ia`,
`paddle-ppocrv6`, `kraken-cronicon` — and not from the panel recommended in §8.
Until now that panel had never been scored: `benchmark.py` read one hard-coded
directory, and PaddleOCR and Kraken were drawn after the sample was frozen, so
the sample had no column for them.

It can be scored without re-adjudicating anything. Their readings are already on
disk in the consensus, and a position is identified by its **word box**, which
does not renumber when a leaf's geometry changes — an index does. Joining on the
box recovers 495 of the 550 adjudicated positions; the other 55 are refused
because some engine the two records share reads them differently, which means the
box has been re-tokenised and they are no longer the same word. Every row below
is scored on those same 495, so the ordering is meaningful even though the
absolute values sit above the §3 figures (the 55 excluded positions are the hard
ones).

| panel | engines | accuracy | ties | unanimous and wrong |
|---|---:|---:|---:|---:|
| all eight | 8 | 99.07% | 7 | 0 / 315 |
| **`consensus6_swap_swapk` — production** | **6** | **99.04%** | **4** | **0 / 348** |
| `consensus7` (+kraken) | 7 | 98.87% | 6 | 0 / 333 |
| `consensus7_paddle` | 7 | 98.68% | 7 | 0 / 324 |
| `consensus6_swap` (paddle for tess-bne) | 6 | 98.49% | 11 | 0 / 342 |
| the panel recommended in §8 | 6 | 98.32% | 11 | 0 / 352 |
| IA scan only | 5 | 99.43% | 9 | 0 / 355 |
| BNE scan only | 3 | 95.78% | 22 | **2 / 386** |

**The drift was an improvement, and it is now evidence rather than habit.** The
production panel is the best six, ties four times where the documented panel ties
eleven, and shows no shared error in 348 unanimous positions. The eight-engine
panel matches it to within noise and is not adopted: over the whole book it
*raises* the queue (see §4c), and three more voters buy 0.03 points.

Two rows are worth reading against each other:

- **`BNE scan only` is the one panel in the table with a measured shared error** —
  two positions where all three agreed and all three were wrong. It is the reason
  a three-engine fallback is not an option anywhere in this pipeline, however
  attractive its numbers look on a particular leaf.
- **`IA scan only` scores highest and must not be believed.** Five engines over
  one image vote together; that is unanimity without independence, and §8 already
  warns about it. It is also the configuration that collapses on the leaves where
  that image is defective — see §4d.

A caveat that this exercise turned up: **the sample was drawn with Tesseract
`spa_old`, while every consensus since has been built with `spa_old+cat+lat`.**
The strata, and therefore the weighting, still come from the drawing panel, so
the comparison holds — but a number produced this way is not the 97.25% of §3,
and `benchmark.py` now says so on every run where the two panels differ.

---

## 4. How much human review, and for what gain

The twelve pilot pages deliberately over-sample the hard classes: a third of them
are introduction, appendix or errata, which are together under 5% of the book.
Projecting the pilot's own mix would overstate the work threefold, so the
projection re-weights by the leaf counts the book actually has — taken from
`scripts/inventory.py`, which surveys all 671 leaves, not from an estimate.

| page class | leaves | words/leaf | contested | + two-dissent |
|---|---:|---:|---:|---:|
| body (2 columns) | 471 | 768 | 2.1% | 7.7% |
| body, late (worn type) | 101 | 799 | 7.9% | 14.1% |
| body, multi-column tables | 15 | 542 | 15.0% | 29.6% |
| introduction | 12 | 716 | 10.3% | 22.0% |
| appendices | 8 | 560 | 15.0% | 29.6% |
| advertencias | 3 | 397 | 10.3% | 22.0% |
| front matter | 2 | 181 | 10.3% | 22.0% |
| errata | 2 | 327 | 16.9% | 31.3% |

614 leaves carry running text; the other 57 are engraved plates or blanks.

### The projection has since been superseded by a census

The panel has now been run over every one of those 614 leaves
(`scripts/consensus.py`), so the queue size is counted, not extrapolated:

| | tokens | share |
|---|---:|---:|
| **total** | **473 280** | |
| unanimous | 337 542 | 71.3% |
| one dissenter | 77 820 | 16.4% |
| two dissenters | 31 620 | 6.7% |
| **contested** | **26 298** | **5.6%** |

**Reviewing the contested tier is 26 298 decisions, not the 17 000 projected** —
about 55% more work. The residual error afterwards is 0.46%, one wrong word in
219, essentially as predicted.

The gap is one class. The pilot's five body pages came out at 2.1% contested
where the real body average is **5.4%**; every other class landed close to or
better than predicted (`body_late` 5.1% against 7.9% predicted, `intro` 8.4%
against 10.3%, `errata` 16.9% exactly). Five pages was never enough to pin a
per-class rate, and the class that carries 78% of the book was the one that
missed. The pilot's *accuracy* figures rest on 550 adjudications and are
unaffected; only the volume estimate was wrong.

The tables below are kept as the pre-census projection, for comparison.

The inventory turned up one thing the pilot had missed: **15 leaves inside the
body are three- to six-column tables**, not running prose — further lists of
Jurats for the 14th and 15th centuries (leaves 114 and 225 and their
continuations), set exactly like the appendix name list that scored worst in the
pilot. They are scored here at the appendix's rates rather than the body's.

| policy | words reviewed | residual error |
|---|---:|---:|
| accept the vote everywhere, no review | 0 | ~2.7% — 1 wrong word in 37 |
| **review the contested 5.6%** | **26 298** | **0.46% — 1 wrong word in 219** |
| review contested + two-dissent (12.3%) | 57 918 | ~0.23% — 1 wrong word in 440 |

At a few seconds per decision in a keyboard-driven review tool with the crop on
screen, 26 000 decisions is on the order of 25–30 hours, interruptible and
priority-orderable (proper nouns, dates and figures first). Doubling that buys a
further halving of the error rate.

The recommended target is the middle row: **review the contested words, ship at
~1 error in 200, and let the two-dissent tier be a later refinement.**

### 4c. A seventh engine makes the queue bigger, twice

Each candidate panel has been run over all 614 leaves, so this is counted:

| panel | unanimous | contested | vs. the six |
|---|---:|---:|---:|
| `consensus6_swap_swapk` (production, 6) | 77.7% | **24 607** | −6% |
| the panel of §8 (6) | 71.3% | 26 298 | — |
| `consensus7_paddle` (7) | 70.3% | 32 040 | **+22%** |
| `consensus7` (+kraken, 7) | 69.6% | 35 328 | **+34%** |

Both seventh voters are *more accurate* than several sitting members — Kraken
reads body pages at 96.7%, better than any panel engine, and PaddleOCR gets 73%
of the contested tier where the best panel engine manages 48%. Neither helps.
Accuracy and complementarity are different properties: a seventh voice breaks
agreements that were already right more often than it settles ones that were
wrong.

**The panel is saturated at six.** Adding engines is not the lever, and this is
now the second independent measurement saying so. What did work was *swapping* —
replacing the two weakest readings with Kraken and PaddleOCR keeps six voters and
takes the queue down.

---

## 4b. Can the review be automated away? Mostly no

Three deterministic arbitration rules were tried against the same 550 adjudicated
positions (`scripts/arbitrate.py`), to see how much of the ~17 000-decision queue
they could absorb. The result is largely negative and worth recording as such.

| rule | accuracy | contested right | ties left | invents strings |
|---|---:|---:|---:|---:|
| majority (baseline) | 97.25% | 39/60 | 18 | 0 |
| medoid (closest candidate to all others) | 97.46% | 41/60 | 8 | 0 |
| character-level vote | 97.25% | 39/60 | 0 | **6** |
| lexicon + medoid | 97.09% | 44/60 | 9 | 0 |

- **Medoid** looks like a win — it cuts ties from 18 to 8 — but the positions it
  newly decides are only 65% right, *below* the 71% of the ones plain majority
  already decided. It converts ties into confident wrong answers, which is worse
  than leaving them for a human.
- **Character-level voting** gains nothing and returns six strings no engine ever
  read. That is precisely the failure this project is built to avoid, whatever
  produces it. Rejected.
- **A lexicon built from the book's own unanimous words** (1 544 distinct, from
  the pilot pages) does help on the contested stratum, 73% against 65% — but it
  *loses* on the one- and two-dissent strata (96% and 93%, against 99% and 97%),
  netting worse overall. It pulls toward attested spellings and away from correct
  but rare ones: the modernisation failure mode in miniature, and a larger
  lexicon would pull harder, not less.

All of these differences sit inside the noise of a 60-position stratum. The
honest reading is **no measurable improvement**, not a small one.

What has *not* been tested is the one signal that carries information the vote
does not already contain: **the per-word confidences**. The medoid and lexicon
rules only re-read the same six strings; ABBYY's `x_wconf` and Tesseract's TSV
confidence are independent evidence about how sure each engine was. Wiring them
into a weighted vote is the remaining lever, and the only one worth building
before accepting the 17 000 figure.

On an LLM as arbiter: volume is not the obstacle (17 000 calls is trivial), the
failure mode is. A language model picks the *plausible* reading, and a diplomatic
transcription of an 1881 book is exactly where plausible and printed diverge —
`formacion` without the accent, the author's own typos, Catalan and Latin quotes,
Mallorcan surnames in no lexicon. The lexicon result above is the same effect
measured on a much weaker mechanism, and it already came out negative. If it is
tried at all, the defensible form is a vote **restricted to the candidates the
engines produced**, never free text, weighted by measured accuracy — and measured
by someone who did not produce the ground truth.

## 5. What the errors actually look like

Across all engines and all 300 adjudicated positions (892 individual errors):

| error type | count |
|---|---:|
| character misread | 455 |
| word dropped entirely | 192 |
| accent or diacritic only | 136 |
| merged with the neighbouring word | 65 |
| word split | 44 |

Characteristic failures, with the printed reading on the right:

- `abbyy-bne` — `lÁCateriales` → *Materiales*; `deUmbert` → *de Umbert*;
  `Gastell` → *Castell*; `Lúeas` → *Lúcas*; `6o2` → *602*; `lyor.` → *1701.*
  It also *silently modernises*: it returned `formación` where the book prints
  `formacion`. For a diplomatic transcription that is worse than a misread,
  because it looks correct.
- `abbyy-ia` — reflows columns into running prose, losing the printed lines;
  `Bemardino` → *Bernardino* (the classic rn/m confusion); `Ga$ó` → *Gaçó*; and
  it ingests the Google Books watermark, returning `VIII Google` for a page
  header.
- Tesseract — loses diacritics on the Spanish models (`extraidos`, `biografia`,
  `notabilisima`) and cedillas without the Catalan model; occasionally reads the
  old-style `f` as a long s (`uniſorme`).
- Apple Vision — the cleanest character reader on running prose, but drops whole
  lines without warning, and hallucinates nothing so much as it simply omits.

Two systematic issues are normalisation decisions rather than recognition
failures, and are handled separately: **small capitals** (Campaner sets month
names and table headers in small caps — `JUNIO` vs `Junio`) and **line-end
hyphenation**. Both are deterministic to fix; the benchmark measures them apart
so they neither flatter nor damn any engine. Their effect turns out to be small
(strict and case-insensitive accuracy differ by under half a point).

---

## 6. Method and its limits

- **Sampling.** All 8 252 token positions on the twelve pages were classified by
  panel agreement, then sampled stratified: round 1 drew 110 unanimous, 70
  one-dissent, 60 two-dissent and 60 contested; round 2 drew 250 further
  unanimous positions, disjoint from round 1 by construction. Every reported
  figure re-weights the strata by their true share. Seeds are fixed, so both
  rounds are reproducible.
- **Adjudication rule.** The truth is the whole printed word the sampled box sits
  in, in 1881 orthography, with the author's own spellings preserved. An engine
  that split or merged a word counts as wrong, because it is.
- **The adjudicator is fallible too, and it showed.** Round 2 initially recorded
  one shared error: all fourteen readings gave `así` where the review sheet
  appeared to print `asi`. Re-cropped at native resolution the acute accent is
  unmistakable — the engines were right and the adjudication was wrong. Four other
  positions where the adjudication and the panel differed by a diacritic alone
  (`notabilísima`, `Gamundí.»`, `Gerónimo`, `ínti-`) were re-checked the same way
  and the adjudication held in all four.

  This has a direct consequence for the build: **the review tool must show crops
  at native resolution.** The 78-pixel line height used for these sheets is
  comfortable for reading words but not for telling an acute accent from the dot
  of an `i`, which is precisely the distinction most of the disagreements turn on.
- **Geometry bias.** Word boxes come from Tesseract's TSV, so a word Tesseract
  never detected at all cannot become a sampled position. Such words show up
  indirectly (as a neighbour's merge) but are under-counted. This flatters
  Tesseract slightly relative to the others.
- **Alignment fragility on sparse pages.** Errors concentrate on p14 (43%), p631
  (43%) and p642 (32%). On p14 — the ornate introduction opener, with a drop cap,
  a footnote block and the Google watermark — part of that rate is token
  alignment struggling on a short page rather than genuine misreading. The
  book-weighted projection limits the damage, since these classes are ~4% of the
  leaves, but per-class figures for `intro`, `appendix_list` and `errata` should
  be read as indicative.
- **Sample size.** 550 adjudications support the headline numbers to roughly
  ±2 points overall. The non-unanimous strata still rest on 60–70 adjudications
  each, so the contested row (65%) carries a wide interval; the per-page-class
  rows are indicative only.

## 7. Reproducing this

```sh
nix develop                                   # tesseract with spa_old spa cat lat + uv
uv sync                                       # Python env from uv.lock

python scripts/fetch_ia.py --derivatives
python scripts/align_scans.py                 # BNE page <-> IA leaf
python scripts/fetch_ia.py --leaves 12 15 18 28 32 34 48 198 625 627 629 640
python scripts/render_pages.py --scales 1 2 3
python scripts/prepare_ia_pages.py

python scripts/extract_abbyy_bne.py           # engine A
python scripts/parse_chocr_ia.py              # engine B
python scripts/ocr_tesseract.py --workers 10  # engine C, 8 variants, ~60 s
python scripts/ocr_vision.py --workers 6      # engine D, 4 variants, ~7 s

python scripts/build_ordered.py               # one reading order for all engines
python scripts/sample_loci.py --per-stratum 110 70 60 60          # round 1
python scripts/sample_loci.py --round 2 --per-stratum 250 0 0 0   # round 2, in order
# adjudicate data/adjudication/sample*_sheet_*.png -> data/ground_truth/adjudicated.tsv
python scripts/benchmark.py --by-class        # merges every round it finds
```

Rounds must be drawn in order, since each excludes the positions its predecessors
used. `benchmark.py` verifies a fingerprint of the drawn positions against
`data/ground_truth/sample_fingerprint.txt` and refuses to run on a mismatch — a
renumbered sample would otherwise score every engine against the wrong words and
report a plausible-looking figure. That failure actually occurred during
development (a seed change renumbered round 1 and produced "6.75% accuracy"),
which is why the check exists.

Throughput measured on this M4: Tesseract 96 page-runs in 59 s with 10 workers
(≈ 6–7 min for the whole book, one variant); Apple Vision 48 page-runs in 6.6 s
(≈ 90 s for the whole book). Neither is a constraint. The Internet Archive images
are ~2.4 MB per leaf, so the full set is about 1.6 GB.

---

## 8. Recommendation

Build it, with this configuration:

1. **Images from the Internet Archive scan** (≈630 dpi), downsampled to 300 dpi
   for Tesseract. Keep the BNE PDF as the second, independent source.
2. **Six-engine panel:** ABBYY-IA, ABBYY-BNE, Tesseract `spa_old+cat+lat` @IA
   300, Tesseract `spa_old` @BNE 400, Apple Vision @BNE 400, Apple Vision @IA
   300. Token-level majority vote.

   The five-engine set scoring 97.51% above is *not* the recommendation, despite
   the higher number: it reaches it by running two Tesseract variants over the
   same image. Near-clones vote together, so they inflate unanimity without
   adding evidence — and unanimity is the guarantee the whole design rests on.
   Keep one Tesseract per scan and accept the 97.25%.
3. **Accept unanimous** — 70% of words, bounded at ≤0.83% shared error.
4. **Review the contested 5.6%** in a keyboard-driven tool showing the crop at
   native resolution, priority-ordered by proper nouns, dates and figures.
   26 298 decisions, ~25–30 hours, interruptible.
5. **Ship at ~1 wrong word in 220**, with the two-dissent tier as a later
   refinement path to 1 in 440.
6. **No generative model in the transcription path, ever.** The consensus is the
   guarantee; an LLM would only reintroduce the failure mode this whole design
   exists to avoid.
