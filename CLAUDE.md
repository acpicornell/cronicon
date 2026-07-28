# CLAUDE.md — cronicon (Cronicón Mayoricense, Palma 1881)

OCR pilot for Campaner's chronicle of Mallorca, 1229–1800. Part of the Corpus
Balear family; same conventions as the sibling projects in `../`.

## Golden rules

- **Repo content in English** (code, comments, docs, commits). Any UI copy is
  Catalan. The transcribed text stays in Campaner's 1881 Spanish, verbatim.
- **No generative model in the transcription path.** Ever. Not to read a page, not
  to "clean up" OCR, not to break a tie. The consensus of independent recognisers
  is the entire guarantee; an LLM writing text into the transcription voids it.
  `../nomenclators/madoz/README.md` §Difficulties documents what happens
  otherwise. LLMs may read facsimile crops to *adjudicate* between engine
  readings — verification with the evidence on screen — and nothing more.
- **Never modernise.** `formacion`, `dia`, `Setiembre`, `mallorquin`, `á`, `ó`
  stand as printed, and so do Campaner's own typos. The BNE ABBYY layer silently
  writes `formación`; that is an error, not a fix.
- **Nix for tools, uv for Python, both locked.** `flake.nix` pins Tesseract *and*
  its language set (`spa_old spa cat lat eng osd`) inside the project rather than
  touching `~/Setups/macos`. Never `brew`.

## Toolchain

```sh
nix develop     # tesseract + uv + openjpeg, pinned by flake.lock
uv sync         # .venv from uv.lock (uv-managed CPython, not conda/miniforge)
```

Scripts are run as `python scripts/<name>.py` (they import their siblings; Python
puts `scripts/` on the path automatically). All are idempotent and skip existing
output, so re-running is safe and cheap.

## What is established

Measured, not assumed — see `docs/OCR_BENCHMARK.md`:

- Two independent scans exist: BNE (200 dpi, in `data/raw/`) and Internet
  Archive/Google (~630 dpi). **IA leaf = BNE PDF page − 2.**
- Best single engine: Tesseract `spa_old+cat+lat` on the IA scan at 300 dpi,
  94.5%. `cat`+`lat` are worth ~1.5 points — the book quotes Catalan and Latin,
  and the cedilla in Mallorcan surnames needs the Catalan model.
- Six-engine majority vote: 97.25%. Where all six agree (70% of tokens) they were
  right 360/360, bounding shared errors at ≤0.83% (95%, one-sided).
- **The panel that builds the edition is `consensus6_swap_swapk`** — `abbyy-ia`,
  `tess-ia-300dpi-spa_old-cat-lat`, `vision-bne`, `vision-ia`, `paddle-ppocrv6`,
  `kraken-cronicon` — and it is the default of every parser. It is the best six
  measured (99.04% on the 495 positions all panels can be scored on, 4 ties
  against 11, no shared error in 348 unanimous positions), and 23 647 contested
  against 26 298. `benchmark.py --consensus <dir>` scores any panel; it recovers
  the engines the sample predates **by word box**, because an index renumbers
  when a leaf's geometry changes and a box does not.
- **A seventh engine has been tried twice and made the queue worse both times**:
  Kraken 26 298 → 35 328 (+34%), PaddleOCR → 32 040 (+22%), despite both being
  more accurate than several sitting members. Accuracy and complementarity are
  not the same thing. What worked was *swapping*, not adding.
- **Do not stack two Tesseract variants on the same image in the panel.** It
  scores higher (97.51%) but only by voting with itself; unanimity is the
  guarantee and near-clones corrupt it. One engine per scan.
- **A three-engine fallback is not available.** The BNE-only trio is the one
  panel with a *measured* shared error — 2 wrong in 386 unanimous positions —
  so however good it looks on a particular leaf, it cannot carry the accept rule.
- Upscaling is not resolution: Tesseract on the BNE scan interpolated to 600 dpi
  scores *worse* than the same engine at native 200 dpi.
- Reviewing the contested 5.0% of words — **23 647 decisions**, counted over all
  614 leaves, not projected — leaves no residual the sample can measure (95% upper
  bound 0.65%). The pilot's projection of ~17 000 was wrong by 55%, because five
  body pages showed 2.1% contested where the real body average is 5.4%.
- **Plus 11 114 positions held back**, not doubtful: they sit on the 25 leaves
  aligned line by line, which no adjudication covers. A stratified round on those
  leaves discharges the block. `accept_unanimous: false` in the leaf JSON marks
  them.
- **Review crops must be at native resolution.** Adjudicating from 78-px-tall
  crops produced one wrong call (`asi` for `así`); at full resolution the accent
  is obvious. Accent-vs-dot is exactly what most disagreements turn on.
- **A drawn sample is data. Never regenerate it.** `data/adjudication/sample*.json`
  are committed and `sample_loci.py` now refuses to overwrite them without
  `--force`. The strata depend on every engine's output, so *any* engine
  improvement changes which positions get drawn — repairing the ABBYY-IA parser
  renumbered the sample and orphaned all 550 adjudications. `benchmark.py`
  verifies a fingerprint of `(id, page, index, box)` and hard-fails on a mismatch;
  when it fires, restore the sample from git rather than re-drawing.

## Structure of the book

Surveyed by `scripts/inventory.py` over all 671 leaves → `data/inventory.json`:

| section | PDF leaves | notes |
|---|---|---|
| front matter | 0–13 | covers, title |
| introduction | 14–27 | describes each manuscript source; the sigla glossary lives here |
| body | 28–630 | the chronicle |
| appendices | 631–638 | I: Jurats of the 18th c. II: noticias curiosas |
| advertencias | 639–641 | notes on the plates |
| errata + plates | 642–670 | |

614 leaves carry running text; 57 are plates or blanks.

Body is a chronicle by year: a bare year heading (`1229.`), then entries of the
form `Mes día.—texto…—SIGLA`, where the sigla name the manuscript source
(`B. J.` Bartolomé Jaume, `G. T.` Guillermo Terrassa, `L. V.` Luis de
Villafranca, `Jn. Br.`, `T. A.`…).

Layout, detected by `scripts/layout.py` clustering line left edges — not by
looking for an empty gutter, which fails because ABBYY's line boxes overrun it:
body is 2-column (519 leaves), but **15 body leaves are 3–6 column tables** —
further Jurats lists for the 14th and 15th centuries at leaves 114 and 225 and
their continuations. Same hard class as the appendix name list, which scored
worst in the pilot. Introduction and errata are 1-column.

**The body is not all chronicle**, and counting columns does not find the parts
that are not. `parse_entries.py` classifies the 614 leaves into three kinds and
writes the split to `data/entries/sections.json`:

- **519 chronicle leaves** — the dated entries.
- **27 Jurats name lists.** `inventory.py` finds the ones that print in 3–6
  columns and misses the ones typeset as two: leaves 58–60 (13th c.) and 114–121
  (14th, headed `APÉNDICES. I.`) read as ordinary body. They are found instead by
  content — numbered names, `AÑO 1332.` labels — and a table run also **spills
  onto the leaf after it** (229, 242, 482, 502 open with the last names of the
  table before them).
- **160 leaves of documents printed in full** — `II. Cartas del gobernador
  Gilaberto de Centellas`, `IV. Fragmentos de las Apuntaciones del Notario Mateo
  Salcet`, and a dozen more.

  Two rules find them and **only together**. Some date their own material, so
  leaf 153 runs 1382, 1384, 1387 in the middle of the 1340s, and no year they
  state can be true where they sit: that catches 41 leaves. The rest state no
  year at all — the letters of Centellas are 14 leaves of medieval Catalan that
  name no date — so nothing fires, and they came through as chronicle entries
  glued to whatever heading preceded them, dated 1400. **96 leaves, 60 303 words,
  one word in six of what this file called the chronicle.**

  They are found by reading `data/documents/documents.json`, which
  `parse_documents.py` had delimited correctly all along. The two scripts knew
  different things and did not talk. Because that file is built *from*
  `headings.json`, the build is a second pass:

  ```sh
  python scripts/parse_entries.py --bootstrap   # first build only
  python scripts/parse_documents.py
  python scripts/parse_entries.py               # converges here
  ```

  Without `--bootstrap` a missing document list is a hard stop, not a fallback:
  the failure it guards against is silent, and ran for weeks.

**The shape of an entry cannot be used to find them, and it was measured before
being believed.** A document printed in full runs ten times longer than an entry,
states no month, names no source and is the only "entry" on its leaf — all true
of the averages and useless as a test:

| | inside a document | elsewhere |
|---|---:|---:|
| ≥300 words, no month, no siglum | 81 | **123** |
| the same, and the sole entry on its leaf | 80 | **66** |

There are more of them *outside* the documents than inside, at every threshold.
Leaves 253–280 are twenty-eight leaves of continuous Germanía narrative and are
chronicle; by shape they are indistinguishable from Centellas' letters. The
separation has to come from Campaner's own numbering, and it does.

Beware the inverse: a long stretch with no year heading is **not** evidence of an
appendix. Leaves 253–280 are 28 leaves of continuous Germanía narrative, real
chronicle, with no heading between 1520 and 1525.

**ABBYY does not read the large display headings at all** — the letterspaced
`APÉNDICES` on leaf 631 and `INTRODUCCION.` on leaf 14 are simply absent from the
embedded layer. Section boundaries are therefore anchored on ordinary body text
(`SECTION_ANCHORS` in `inventory.py`), and each anchor must match exactly one
leaf or the script fails rather than guessing.

**BNE↔IA alignment is a constant offset of −2** across the whole book: 377 leaves
confirm it, spanning pdf 16–635. The 60 that appear to contradict it are ABBYY
dropping the leading digit of the running head (`5^ CRONICON` for 54). Never
drive the mapping off the per-leaf printed number — an earlier version did and
mapped leaf 211 to IA leaf 29.

## Finding year headings

Measured, after geometry was tried and dropped. A display heading is **not**
identifiable by its box: real ones sit anywhere from the centre of their column
to 47% off it, and one at the top of a column occupies the same vertical band
(y 0.088–0.123) as the running head's page number (0.080–0.099). Three rules that
do work, in the order they matter:

1. **Ask the panel, not the winner.** A heading is five characters wide, so the
   vote has almost nothing to work with and the winner is often the worst reading
   on the line: `I3II.` won a three-way tie on leaf 66 while PaddleOCR had
   plainly read `1311.`. Count the year across all eight readings and require
   three of them. This is recovery from evidence, not character substitution —
   the same rule that forbids an LLM rewriting a word allows counting what the
   recognisers actually returned. It is also why lines whose winner collapsed to
   `1`, `I`, `r.` or `M.` are still readable: leaves 178, 203, 302, 470 and 516
   were checked against the facsimile and all five are real headings.
2. **The line must say nothing but a year** — otherwise `1700 lbs.`, `1,259
   carros`, `hasta 1343.`, `Any 1522` and `á 1558.)` all become years. The one
   exception is the heading the line finder glued to the start of its own entry
   (`1460. Marzo`, 16 readings; `1776. MARZO`), admitted only when the panel
   reads a month or an opening quote after the year. That single case was worth
   26 years on its own.
3. **The chronicle only moves forward.** Keep the longest non-decreasing run of
   candidates and report the rest. This is the guard that lets rules 1 and 2 be
   generous, and it is what exposed the two real oddities in the whole book.

493 → 521 distinct years of 572, and the 51 still missing are mostly genuine:
29 have no trace of a heading anywhere between the years that bracket them —
Campaner simply had no news. Only two candidates in the book break the
chronology, and neither is an OCR error:

- **leaf 39 prints `1449.`** and the entry beneath it reads «año de 1249,
  perseverando…». Campaner's own error; by this edition's rules it stays.
- **leaf 74 `1336.»`** is the last line of a footnote quotation, wrapped alone.

## The Jurats lists

Six series, one per century, printed as appendices inside the body:
XIII at leaf 58, XIV at 114, XV at 225, XVI at 311, XVII at 478, XVIII at 631.
`scripts/parse_jurats.py` finds them by their own title line and gives
`data/jurats/jurats.jsonl` — **1 670 names over 282 years**, one row per
(year, seat, name) with its certainty tier.

Two typographies, and **neither difficulty is in the parser**. What the six
engines share is a reading order, and it comes from Tesseract's line
segmentation, which is wrong on these leaves in two different ways.

- **Compact form** (a bare `1418.` and six names, three columns to the leaf) —
  Tesseract joins a line of column one to a line of column two across the
  gutter: leaf 312 opens `Pedro Descatlar. Alfonso`, one box from x 0.10 to
  0.81, and every year heading caught in such a line vanishes. Circular, too:
  `layout.find_columns` refuses a boundary more than a tenth of the lines cross,
  so the merged lines hide the boundary that would separate them.
  **Fixed** by `consensus.py --split-gutter`, which cuts a line where the gap in
  it exceeds 0.025 of the page width — word spaces here are 0.0066, and leaf 312
  had 34 gaps over 0.03 against 3 on a clean table leaf. Worth 12 years and 77
  names. It writes to `consensus…_gutter`, never over the book's consensus:
  changing geometry changes every stratum and would orphan the frozen sample.
- **Annotated form** (`AÑO 1312.` centred over the pair of columns,
  `1.—Guillermo de Montsó` with a dot leader to a brace, and a column of notes on
  which manuscript gives which name, leaves 58–60 and 114–121) — **fixed, and it
  took two changes at once.** Tesseract returns nothing at all right of x 0.47 on
  leaf 115, so the notes column is absent from the panel entirely; ABBYY on the
  BNE scan reads all three regions, but under the page-wide token alignment the
  engines' readings land in the notes column's slots and **the names come back
  empty**, because each engine walks the leaf in a different order. The pair that
  works is

  ```sh
  consensus.py --pages 58,59,60,114,115,116,117,118,119,120,121 \
      --swap-paddle --swap-kraken --geometry abbyy-bne --align line \
      --out data/ocr/consensus6_swap_swapk_annotated
  ```

  the geometry so the boxes exist, `--align line` so the reading order stops
  mattering. It recovered the **entire 13th-century series**, which was empty,
  and took the 14th back from 1375 to 1302: 1 747 → 1 949 names, 297 → 356 years,
  0 leaves left unread. The new names are mostly one-dissent or worse and go to
  review as such; `AÑO 1240.` really is what leaf 58 prints, four years before
  the Jurats were instituted, and under it five rows of leader dots and
  `6.—Pedro Ferrer.` — checked against the facsimile.
- Not by having a model read the page. Family names of 1300s Mallorca are
  exactly where a language model silently normalises `Za-flor` to `Zaflor` and
  invents a plausible surname, with no consensus left to catch it.

**`--align line` is the general form of that fix and is not the default.**
`project()` matches two flat token streams over the whole leaf, which works only
while the engines agree what order the leaf is read in. Aligning by geometry
instead — a printed line competes only with the engine text overlapping it —
is dramatically better where the layout is contested (leaf 453 36.1% → 6.4%
contested, leaf 312 38.7% → 11.1%) and **worse on ordinary prose**, where the
page-wide match already works and this one costs unanimity (leaf 200: 86.1% →
7.4% unanimous). Unanimity is the accept rule, so it stays opt-in until a round
of adjudication on those leaves says what unanimity is worth under it. A fitted
vertical *scale* was tried first and was ten times worse than doing nothing: the
two scans differ by where the page was cropped, not by how much it was
stretched, so the offset is a constant and fitting a slope turns it into an
error that grows down the leaf.

Bounding each series: it ends at the next series' title, at a roman-numeral
section head (`II. Noticias é indicaciones curiosas` starts at 1702 on the leaf
right after the 18th-century list, rising years, so nothing else stops it), or at
the first leaf that adds no year beyond those already collected. Within a series
the same non-decreasing-subsequence rule as the chronicle: one heading misread
high on leaf 479 was locking out twenty consecutive years.

## The appendix blocks

At the close of each century the chronicle stops and an appendix runs for six to
sixty-nine leaves. `scripts/parse_documents.py` delimits them →
`data/documents/documents.json`: **6 blocks, 29 numbered sections, 187 leaves.**

A block is *not* identifiable by length: leaves 253–280 are twenty-eight leaves
of continuous Germanía narrative and are chronicle. What every block does have is
the Jurats list at its head, numbered `I`; so a block runs from a Jurats series
to the leaf where the chronicle states its next year, and sections run `II`
onward. Three traps, all measured:

- **Quoted ordinances number their own clauses** — leaf 85 has `III. Item, com
  sia slat dit al Sr. Rey…` seven times. Excluded by requiring a block's
  numerals to rise, and by rejecting a title beginning `Item`.
- **The numeral shares a line with the running head**: leaf 153 opens `126 IV.`.
- **The numerals are display type, which is the class the engines read worst.**
  Leaf 482 prints `II.` and the vote returned `XX.`, having been offered `zz.`,
  `LL.`, `IH.`, `TIT.` and one correct `II.` from Apple Vision. Read the numeral
  off the panel, exactly as with the year headings. Because that evidence is
  weaker, a section found that way must be the *next* number, not merely a later
  one — without that constraint a chronicle entry on leaf 632 became section V.

`scripts/build_documents.py` then assembles each one as a text →
`data/documents/sections/*.txt` and `sections.json`: **23 documents, 97 595
words, 3.3% contested**, footnotes separated as in the chronicle and the
certainty tiers carried through, because these are the leaves nothing has
measured and a mostly-contested document must say so on its face.

Two details that are not obvious:

- **A section can start in the middle of a leaf.** `until` is the leaf *before*
  the next section, so ending there drops the top of the shared leaf — section
  III opens at line 7 of leaf 137 while II is still running down it. The end
  taken is the next section's first line, so the leaf is split where the book
  splits it: II closes `…anno. Dni. m.ccc.xl.ix »` and III opens `Historia de los
  Reyes de Mallorca`.
- **The `.txt` is what the book prints and nothing else.** No title is prepended:
  the printed title already stands at the head, and the recorded one is a
  truncation of it.

**Campaner names the genre himself**, in the first word of each title — `Cartas`,
`Sentencia`, `Relacion`, `Memorial`, `Declaraciones`, `Toma de posesion`,
`Fragmentos`, `Historia`, `Nota`, `Cas nunca vist`. That is surfaced as `genre`
rather than mapped onto categories the book does not use.

**Splitting a section into its individual pieces is still open, and it is
philology rather than parsing.** The Centellas section holds 20 salutations
`«Molt alt e molt poderos princep e Senyor»` against only 3 numbered pieces and 3
`Dat.` closings, so neither the numbering nor the formula alone delimits a
letter. It wants the same treatment the year headings got: a rule, measured,
with the exceptions counted.

Three numerals in the 16th-century block are still not found (VII, VIII, X).
Leaves 333–334 are blank and leaf 332 ends *«haber reducido el tamaño de las tres
primeras páginas á las dimensiones del original»*: section VII is a **facsimile
reprint of a 1541 booklet**, leaves 335–367, carrying its own title page in its
own typography. The gap is explained, not mysterious.

## The non-Spanish material — measured coverage is zero

The book embeds letters, edicts and relations in medieval Catalan and Latin. Two
things are true and must not be confused:

- The panel is *equipped* for it: Tesseract runs `spa_old+cat+lat`, worth ~1.5
  points precisely because of these quotations, and the arbitration lexicon is
  built from this book rather than from a Spanish dictionary.
- **Nothing on those leaves has ever been measured.** All 550 adjudicated
  positions fall on twelve leaves — 14, 17, 20, 30, 34, 36, 50, 200, 627, 629,
  631, 642 — and **none of them is a document leaf**. The 97.6% figure covers
  chronicle prose, the introduction, one Jurats table and the errata. The 159
  document leaves are unmeasured.

## The long s — fixed, and the shape of the fix

Leaves 335–367 reproduce a 1541 booklet in its own typography, which uses `ſ`.
Five of six engines read it as `f`. `scripts/editorial.py` repairs **1 481
tokens**; the rule is written up in `docs/EDITORIAL.md` and applied in
`build_text.py`, and every word it touches keeps the panel's reading under
`printed`.

The lesson worth keeping is the veto. Tesseract `spa_old` does read the long s —
`coſa`, `moſſen`, `boſſer`, `eſtigueſſen` — and is outvoted, so preferring its
reading recovers most of it. **But an engine reading `ſ` is evidence, not
proof:** leaf 342 prints `fonch` and leaf 362 `fins` with a full crossbar (real
`f`, both real Catalan words) and Tesseract offers `ſonch` and `ſins` anyway.
Repairing on the panel alone would have corrupted 47 tokens of good text. So a
repair is refused whenever the printed form is a word the book uses elsewhere,
outside the reprint:

| outcome | tokens |
|---|---|
| repaired, an engine read it | 1 292 |
| repaired, attested on the reprint | 189 |
| ambiguous — real word, `f` stands, sent to review | 465 |
| untouched — no engine ever read `ſ` | 542 |

`fe`, `fa` and `fi` are knowingly left wrong: they are `ſe`, `ſa`, `ſi` on the
page *and* real words. Leaving a real reading unrepaired is recoverable;
corrupting a real word is not.

Also: **derive the affected leaves from the consensus, never from
`data/text/`** — that is the rule's own output, and reading the signal from it
made the detection vanish the moment the repair had run once.

## Where we left off (28 Jul 2026)

The panel is closed at six, ratified against the adjudications, and the engine
question is settled: **the marginal engine is not the lever.** Kraken and
PaddleOCR are *in* the panel, having replaced the two weakest readings; adding
either as a seventh was measured and rejected. See §Toolchain above and
`docs/OCR_BENCHMARK.md` §3b and §4c.

What the ratification exposed, and what was done about it. The book's consensus is
now built with **both per-leaf corrections**, and this is the command that makes it:

```sh
python scripts/scan_health.py            # -> data/scan_health.json
python scripts/layout_health.py          # -> data/layout_health.json
python scripts/consensus.py --pages all --swap-paddle --swap-kraken \
       --per-leaf-scan --per-leaf-align
```

- **The IA scan is defective on a short run of leaves, and the panel put five of
  its six votes there.** Comparing each recogniser against itself on the two
  scans isolates leaves **93, 94, 97, 98**: the IA-reading engines' malformed-token
  rate jumps 5–13 points while the BNE ones stay at 0.6–2%. The facsimile confirms
  it — IA leaf 96 is smeared, BNE p98 is pristine. Those four carried **1 909
  contested positions**. Changing the *geometry* does not help; changing the
  *scan* does. `scan_health.py` also finds the other direction: the BNE copy of
  leaf 122 has the facing page set off across it in mirror image.
- **Two thirds of the review queue was a segmentation artefact.** Of the 24 607
  contested positions as they then stood, 46.6% had some engine returning an empty
  string and 27.8% a multi-word variant; only 34.8% were a genuine disagreement
  about characters. On **25 leaves the engines do not even agree how many columns
  there are** (`layout_health.py`), and there the contested rate is 21.96% against
  4.70% everywhere else. Those leaves are now aligned line by line — and marked
  `accept_unanimous: false`, because no adjudication covers that alignment.
- Net: **24 607 → 23 647 contested**, and leaf 98 goes from `sos torras grano y y'
  que` to `frumentarios en grano y especie, sin que`. Only the 29 affected leaves
  changed; the other 585 are byte-identical.
- **Scope decision:** the introduction (12 leaves) is dropped from the edition, but
  its glossary of manuscript sigla must still be extracted by hand — the body's
  source attributions are meaningless without it.

### Negative results worth not repeating

- Anchoring the token alignment on a folded key (lowercase, accents and
  punctuation stripped) instead of exact equality: **no gain** (leaf 98
  66.7% → 61.9%, leaf 163 worse). The alignment is not failing for want of
  anchors; the readings genuinely diverge.
- Swapping the geometry engine on the blurred leaves (`tess-bne`, `abbyy-ia` as
  the box source): **no gain**. The boxes were never the problem there.
- **A layout detector for the column boundaries** (`scripts/layout_paddle.py`,
  PP-DocLayout_plus-L): 12/12 on the pilot control, including leaf 631's
  three-column list — and **no use on the 25 disputed leaves**, where it returns
  one `content` region spanning x 0.148–0.895. That is correct behaviour: a table
  is one region and decomposing it is a different model's job. That model,
  `TableCellsDetection`, ships the **wired** variant and Campaner's tables have no
  rules, so it finds one cell on leaf 631. The script is kept and nothing consumes
  it; it would serve as an independent check on `find_columns` for prose.

## The review tool

`scripts/review.py` serves a page at `127.0.0.1:8000`; decisions append to
`data/review/decisions.jsonl`. **34 761 positions** — the 23 647 contested plus
the 11 114 held back on the line-aligned leaves — ordered figures first (8 986),
then capitalised words (10 474), then the rest. `--stats` reports without serving.

Four properties, each of them a lesson rather than a preference:

- **Crops are never resized.** They are cut from the largest scan held of that
  leaf and shown at native resolution, because the pilot's one recorded shared
  error was `asi` for `así` and it was the *adjudication* that was wrong: at 78
  pixels the accent is not there to see. `c` widens to three lines of context.
- **The readings are numbered choices**, with the engines that gave each one, so
  that four engines agreeing is visible — and so is the fact that all four read
  the same scan.
- **Typing what is printed is allowed**, and recorded as `source: "typed"`. A
  person with the facsimile on screen outranks the panel; the point of recording
  it is that the share of the edition resting on a reading no engine produced
  can be counted instead of assumed.
- **Keyed by `(leaf, word box)`, never by index.** An index renumbers whenever a
  leaf's geometry changes — which happened four times this week — and the queue
  is re-filtered against the decisions on every request, so reloading the page
  does not bring back settled work.

## Backlog

- [x] Tighten the shared-error bound — 360 unanimous positions adjudicated, none
      wrong, bound ≤0.83%. `scripts/sample_loci.py --round N` draws disjoint
      further rounds (draw them **in order**; each excludes its predecessors);
      `benchmark.py` merges every `sample*.json` it finds and refuses to run if
      the sample fingerprint no longer matches the adjudicated one.
- [x] Inventory and classify all 671 leaves (`scripts/inventory.py`), align
      BNE↔IA for every one. Surfaced the 15 multi-column body tables the pilot
      had missed; the review projection now derives from it.
- [ ] Fetch the full IA image set (`fetch_ia.py --images`, 1.6 GB, 667 leaves) and
      convert (`prepare_ia_pages.py`). Archive.org drops the transfer regularly,
      hence the resume loop.
- [ ] Full-book run of the six-engine panel (~10 min), then consensus + conflict
      queue. Recompute the review projection: changing the panel changes the
      strata, so the ~16 000 figure has to be re-derived.
- [ ] Keyboard-driven review tool: native-resolution crop on screen, variants as
      numbered choices, decisions to an append-only file keyed so re-runs replay
      them.
- [x] Deterministic normalisation with the rules written down — `docs/EDITORIAL.md`.
      One rule so far (the long s), plus the two typographic transforms that were
      already happening (hyphen stitching, running heads).
- [ ] Parse into the chronicle structure; sigla glossary from the introduction.
- [ ] Static SPA on Cloudflare Workers, Catalan UI, `cronicon.corpusbalear.org`,
      plus a card in `../portal/web/index.html` and its JSON-LD `hasPart`.
