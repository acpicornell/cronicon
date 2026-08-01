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

**Campaner's apparatus on those leaves was separated and then thrown away.**
Splitting the notes off is the hard half and the reason the documents read as
prose at all — 62 of them across 22 sections — and they were counted and
dropped, so not one reached a page. They are where he says which manuscript a
passage comes from and where he corrects it. Now stored with the section, loaded
into `footnote` with a `document_id`, and set under the document at the smaller
size the book gives them, each with a link to its own leaf.

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

**A title runs to as many printed lines as it needs**, and taking one truncated
a third of them: `Historia de los Reyes de Mallorca, que fueron` stopped before
`Señores de Montpeller.`, `Fragmentos de las Apuntaciones del Notario` before
`Mateo Salcet`, `Relacion (anónima) del tumulto ocurrido en la Iglesia de`
before `San Francisco de Asis`. A title is centred and the body is not — the
same signal the century openings use — so it runs while the lines stay centred
and stops where one begins at the column's left edge. It also stops at the
source note Campaner sets under it, which is centred too: `«Resúmen recopilado
del tomo cuarto de la Historia general del Languedoc…`, `(pág. 71 del texto.)`.
Both announce themselves in their first character.

**Campaner names the genre himself**, in the first word of each title — `Cartas`,
`Sentencia`, `Relacion`, `Memorial`, `Declaraciones`, `Toma de posesion`,
`Fragmentos`, `Historia`, `Nota`, `Cas nunca vist`. That is surfaced as `genre`
rather than mapped onto categories the book does not use.

**A line break is not a paragraph break**, and treating it as one made these
documents unreadable: `stitch` ended every printed line that did not carry a
hyphen, so a letter of Gilaberto de Centellas arrived as a wall of
forty-character lines. The original's line breaks belong to the measure and to
the facsimile, not to a text meant to be read. What the book *does* mark is the
paragraph, and it marks it with an indent — so lines are joined and a paragraph
opens where the printer indented one. **Two details, both of them bugs first:**
the left edge is the commonest one *per column*, because a heading starts
further left than the body and the minimum makes every ordinary line look
indented; and a line ending in a break hyphen joins the next with **no
separator at all**, which the first attempt got wrong and produced `fe yets`.
**And an indent alone is not enough.** Section III still came out with 266 of
its 395 paragraphs under 60 characters, because a continuation line sits a
little right of the modal edge often enough — an opening quotation mark outside
the measure, a word the panel gave a wide box. A paragraph also *ends*, and it
ends with a **short line**, so an opener must be indented **and** follow a line
that does not fill the measure. Those are 7, 2 and 16 lines on leaves 137, 145
and 153, which is the right order for a page of prose. Section III 395 → 91
paragraphs; the Centellas letters 1 800 lines → 40.

**And the documents get the facsimile marks the chronicle already had.** One
link at the head of a seventeen-leaf section says where it starts and nothing
else, so `stitch` carries out the leaf each paragraph opens on and the page
names it once per run — 16 marks over section III's 91 paragraphs.

**The recovered numeral has to win in the heading.** Display type is the class
the engines read worst: leaf 316 prints `III.` and the vote returned `I XIX.`,
having been offered `zz.`, `LL.` and `TIT.` `parse_documents.py` already reads
the numeral off the panel rather than off the winner — that is how the section
is catalogued as III — and `build_documents.py` was throwing that away, because
the text keeps the winner. The head of the file now takes the recovered reading;
everything below it does not, since the panel's evidence is about the numeral
and nothing else. 22 of the 23 heads agree with the catalogue after it.

And the numeral and title are set as **a heading**, not as the first two
paragraphs. The page used to open with a bare `III.` in reading type with the
title indistinguishable from the first sentence.

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

## The non-Spanish material — measured at last

**Round 3 is adjudicated: 320 positions on 127 document leaves** (ids 551–870,
`data/adjudication/documents.json`), against the facsimile at native resolution
through `review.py --sample`. The book turns out to be two books:

| | today | after reviewing the contested tier |
|---|---:|---:|
| chronicle, 79% of the words | 1 wrong word in 113 | 1 in 706 |
| documents, 21% | 1 in 39 | 1 in 96 |

Per stratum on the document leaves, raw consensus → as published: unanimous
98.5% → **99.5%**, one-dissent 96.0%, two-dissent 90.0% → **96.7%**, contested
62.5% → **70.0%**. The gap between the two columns is `editorial.py`, and this is
the first evidence that it helps rather than merely changes things — the
adjudication did not know the rule existed.

**One shared error in 200 unanimous positions, and it was predicted.** Leaf 358
prints `ſe` in *Vnquam ſi ſe odium Noti remittit* and all six engines read `fe` —
the exact case `docs/EDITORIAL.md` writes down as knowingly left wrong, because
`fe` is also a real word and corrupting a real word is worse than leaving a real
reading unrepaired.

**11 positions (3.4%) had no engine reading the printed form**: the long s, and
two Latin ligatures nobody offers — `prœdo` and `Numidœ` on leaf 351. Seven are
repaired by the editorial rule; the ligatures are a known gap and four examples
are not enough to write a rule from.

Never publish one number for the edition. Publish the tier per word, which
`data/text/p####.json` already carries.

## How that measurement was made

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

## The empty string was winning votes

**5 476 positions, up to 9 668 words, were being deleted by the consensus
itself.** The vote runs one geometric slot at a time, which works while the
engines agree where a word ends and fails completely where they do not --
`cuartos.—J. V.—30.—Mataron` is one printed stretch and every engine cuts it
somewhere else:

```
paddle    cuartos.—J. | V.  | —30.—Mataron | ''  | ''
tess-ia   cuartos.—   | J.  | P.           | —   | 30.—Mataron
abbyy-ia  cuartos.    | ''  | ''           | —   | /. V. — 30. — Mataron
```

At three of those five slots more engines returned `''` than returned any one
word, so `—30.—Mataron` lost 3-2 and vanished. An empty reading is not a
recogniser saying the paper is blank; it is its tokens having landed in the
neighbouring slot. Absence of evidence was counted as evidence of absence.

`scripts/spans.py` votes on the **whole run at once**: each engine's readings
are joined across it and the joined strings compared, so the comparison is
between readings of the same ink. The winner is still a string an engine
produced. 445 spans, **559 words recovered**, 226 leaves.

Three limits, each of them a mistake made first and then measured:

- **A span may only recover text, never remove it.** Over `ABRiL 3.—Marchó`
  three engines skipped the display heading and outvoted the three that read
  it. That is the same error one level up -- reading less is not a vote
  against -- so the result must be strictly longer than what the slots had and
  must still contain every word they had.
- **A span never enters the unanimous stratum.** Agreement is measured after
  folding whitespace and dash shapes, so it is weaker than the slot-level
  unanimity the accept rule rests on. One-dissent is the ceiling.
- **An adjudicated slot stops the merge.** A decision made against the
  facsimile outranks anything computed here.

**The doubling check is the other half.** `JUNIO JuNio`, `Setiembre SETIEMBRE`,
`Te-Deum Te-Deum`, `AÑO 1319. 1319.` are one word the alignment gave two slots;
`etc., etc.` and `Felipe Felipe` are Campaner writing it twice. The panel tells
them apart with no guessing: **if some engine read the word twice over those
two slots the page says it twice, and if none did, the second is the
alignment's.** Two further details, both learned by getting them wrong:

- It runs over the **whole leaf**, not line by line: leaf 430 ends a line with
  `—J. Agosto` and opens the next with `Acosro 3.—De vuelta`.
- **Which copy survives is not arbitrary, and neither is which reading.** A
  month heading belongs to the notice it *opens* and the day follows it, so
  dropping the second copy strands it at the foot of the previous notice; and
  the survivor takes the best-supported reading of the two, preferring a form
  that *is* a month name over one merely close to it (`Acosro 3.` → `Agosto
  3.`, `Mavo 20.` → `Mayo 20.`).

## One book, one assembly

`build_text.py` published the prose and `parse_entries.py` cut it into notices,
and **each joined the winners itself**. They drifted: the entries kept
`Te-Deum Te-Deum` and lacked `—30.—Mataron` after the published text had been
repaired of both. Both now call `spans.layout`, and `page_lines` must rebuild
each group's readings from **all eight** engines, not the panel's six -- the
two outside the panel are what carry leaf 101's `1383.`, and restricting it
silently cost year headings.

## What reading one year found

Reading 1229 — the first year of the book — end to end against the facsimile
turned up five defects, none of them visible in any aggregate. Four of them are
whole classes:

- **Printer's furniture at the foot.** Every eighth leaf ends with the gathering
  signature, a bare `I`, `2`, `13` set alone under the right column, and it
  glues onto whatever the reading order puts last. It landed inside words —
  leaf 562 read `apre68 saron`, leaf 387 `este año 46 fué`. `layout.drop_signature`
  removes it like the running head, and what proves the rule is arithmetic:
  it fires on **61 leaves and every one of them is pdf_page ≡ 4 (mod 8)**, with
  no exception in 614. Dropped at assembly and *not* in `consensus.py`, because
  removing a token there renumbers a leaf and leaf 36 is in the frozen sample.
- **A notice was credited to the leaf its buffer opened on.** The buffer runs
  from one year heading to the next and crosses up to five leaves; every notice
  in it claimed the first. **1 504 of 3 446 notices — 44% — pointed at the wrong
  page of the facsimile.** `split_entries` now returns the offsets it cut at and
  `flush` turns them back into leaves.
- **A footnote's address is (leaf, column, number).** Campaner restarts the
  numbering at the head of every column — leaf 74 prints `(1)` and `(2)` twice —
  and matching the bare number across every leaf the notice spanned sent leaf
  29's «Honores ó féudos.» to 1229 as well as to 1230. **85 of 185 notes reached
  more than one notice; now none does.** Where the number is not in that column
  the note is *not* printed: 22 of 198 chronicle notes reach nothing, because
  `split_notes` missed them, and a note fetched from a neighbouring leaf to fill
  the hole would be a wrong one rather than a missing one.
- **The century front matter was published as chronicle.** `SIGLO XIV. / DE 1301
  Á 1400.` and Campaner's list of every manuscript that reports the next hundred
  years — the closest thing the book has to a bibliography — became a notice of
  **1300**, and the 15th's of 1400, the 16th's of 1500, the 17th's of 1600. Leaf
  28's became an entry with no year, which no page could show; leaf 506's fell
  inside the appendix block and was lost outright. `century_openings` lifts all
  six to `data/entries/centuries.json`, and `parse_sigla.py` now reads that file
  instead of delimiting the same six blocks by its own rule — the two disagreed,
  and the typographic one is right on all six.
- **245 footnotes were parsed, stored and never rendered.** The page printed
  `(1)` pointing at nothing.

Two rules came out of it, both typographic and both general:

- **A line centred on the measure is laid across it, whatever its width.**
  `SPANNING_WIDTH` catches the full-width lines and missed `SIGLO XIV.` at 0.547,
  so three banner lines counted as column text, crossed the gutter, and 3 of 27
  is 11% — just over the 10% a column boundary may be crossed. **Leaf 64 was read
  as one column with its two columns interleaved line by line**, and the whole of
  1301 came out as prose reading `mandó al Gobernador y JuraGa`, dated 1300.
  With the centred test all eight engines read it as two columns.
- **`DE 1301 Á 1400.` is Campaner stating the year the chronicle resumes at.**
  Two centuries never print a heading for their own first year — the 14th opens
  with a drop cap (`EN este año 1301…`) and the 16th's `1501.` came back from the
  vote as `ISOI.` — so both began under the last year of the century before.

And one rule was written and then withdrawn: the century's *preface* (leaf 28's
«PARA que no causen al lector dificultad…») was admitted by "no dated notice in
the block", and the moment leaf 64's columns were repaired that test swallowed
the whole of 1301, which states no month either. **One example is not enough to
write a rule from.** The headnote stands where the book prints it, as the first
notice of the century.

## Working from the sweep: the first rule it produced

`audit_entries.py --check glued` found 35 words the line break split and the vote
never rejoined — `dive rsos`, `bandole ros:`, `Tarrago. na`. **11 of the 35 are
now repaired and the other 24 are declined and listed**, which is the honest
ratio and the same shape as the long s. `docs/EDITORIAL.md` §Rule 2 has the
whole thing; three things are worth carrying in the head:

- **The lexicon comes from the consensus, never from `data/text/`** — that is the
  rule's own output, the same trap the long s fell into once.
- **The left half must not be a word.** Requiring it of both halves let `de` +
  `Ntro.` become `deNtro.` while refusing `Tarrago` + `na`.
- **Excluding tokens that end in a real break hyphen is not an optimisation, it
  is the rule.** Without it the thing fired 2 481 times on 547 leaves, rejoining
  every ordinary hyphenated line break in the book — all of which the assembler
  already stitches correctly one stage later.

And the trap this project keeps re-paying for: **a rule wired into one assembly
is wired into neither.** The joins went into `build_text.py`, the published text
lost `dive rsos`, and the audit went on reporting it because it reads the entries
— which `parse_entries.py` assembles separately. Both now ask
`editorial.joins_for()`, which caches because the lexicon costs a pass over 614
leaves.

## Reading page by page does not scale; the sweep does

`scripts/audit_entries.py` runs every symptom we have ever found over all 3 445
notices at once and returns a ranked list of where to look. **201 findings over
120 years**, which is a worklist rather than 572 pages, and it took one run to
justify itself twice: it found the eighteenth century's source list spilling
onto leaf 507, and it disproved its own biggest check.

**Every check prints its own fire rate, and that is the point.** `split` — a
notice opening in lower case — fired 204 times, 5.9% of the book, and **201 of
the 204 carry their date perfectly well**. Campaner's other date form is a
sentence opener: `…contra el partido de Felipe V.—El 29 llegaron de Barcelona el
Teniente de Rey…`, 149 of those, plus 33 of `—En 31 de Octubre decretó el
Virey…`. The parser lifts `El 29` into the date column exactly as it lifts
`AGOSTO 12.—`, and a verb is left behind. That is the book's convention, not a
broken cut. Narrowed to "lower case **and** no date recovered", the check is 2.
A check that fires on 6% of a book has found a convention; the rate is what says
so, and three checks are marked `informational` because they describe the book
rather than accuse it.

What the sweep says is left, none of it structural:

| | | |
|---|---:|---|
| `orphan-note` | 62 | a note no notice calls — see below |
| `glued` | 35 | `dive rsos`, `Novie mbre`, `ciu dad`, `alo dio` |
| `doubled` | 23 | informational: the book, not the reading — see below |
| `dangling-note` | 18 | a `(n)` whose note was never separated |
| `runt` | 5 | `47 3 •`, `Díjose F.`, `ENERO . 1795-` |
| `stray-tail` | 5 | text ending in a dash — was 13 |
| `bad-day` | 0 | was `31 de junio`, `30 de febrero` |

**A trailing dash is never text**, and eleven of the thirteen were not a broken
siglum at all but the dash that opens the *next* notice, left behind when the
cut fell after it: `…luminarias dos noches.— — 28.—Llegaron 5 galeras…`. The
pattern required whitespace before the dash and the commonest form has none.
13 → 5.

**A day the carried month cannot hold proves the carry wrong, not the day.**
Leaf 454 reads `…de Julio.—Cl. Fl. —31.—El Doctor Vilasalo…`: the `Julio.` is
the tail of the previous notice's own sentence rather than a heading, so June
was still running and the notice came out 31 June. The day is what the book
prints and the month is our inference, so the inference goes — publishing 31
June asserts something the page does not say, and repairing it to July asserts
something else.

`glued` finds broken words with the book as its own dictionary — `formacion` and
`Setiembre` are correct here and wrong in any Spanish word list — by requiring
that the joined form be a word the book uses at least five times and that each
half be rarer than the whole. It has no false positive in the 35.

### The apparatus is found twice, by position and by size

`split_notes` is the **union of two rules**, and the union is the point. The
band knows where notes usually sit — below y 0.55, running to the foot of their
column — and fails on the leaves whose apparatus is so deep it starts in the
upper half: **leaf 86 is eleven lines of chronicle and 122 of a quoted letter**,
opening at y 0.28, and all 122 were published as chronicle. So the opening is
also looked for by the size of the type, after which the band's own rule takes
over. **474 lines on 11 leaves**, and `dangling-note` 35 → 18.

**The threshold is calibrated on the leaf**, between the height of its opening
lines — body by construction, since a note sits at the foot of a column — and
the height of whatever notes the band already found, which are apparatus by
construction. Comparing the two sizes across the book does not work and is the
negative the old docstring recorded: 0.0097 against 0.0127, and they overlap.
Where the band found fewer than three note lines there is nothing to calibrate
against and the body type alone carries it — which is exactly the case on the
leaves that need this most, leaf 86 among them.

Three things had to be got wrong first, and the third is the one worth keeping:

- **A single line's height means very little.** Leaf 66 opens `(1) El pavorde
  Terrassa se equivoca lastimosamen-` at 0.0147 with 0.0177 under it, both wrong
  for note type. An opening counts if it *or the line under it* is small.
- **A line that is nothing but `(2)` is not a note opening**, it is a reference
  the alignment stranded, and its box is small because it is two characters. One
  of them opened an apparatus on leaf 93 that ate the rest of the column.
- **Scanning up from the foot of a column for a note continuing from the one
  before was tried and dropped.** It reads correctly — leaf 105's note really
  does come back at the foot of the second column with no number to announce
  it — and it cost the year headings of 1289, 1339 and 1730, because `1339.`
  alone on a line has no ascender or descender and measures like note type.
  Nine lines of apparatus are not worth a year of the chronicle, and the loss is
  silent where the gain is not.

### The notes nothing calls, and why most of them stay that way

The call in the text is a superscript `(1)`, **two characters wide and the
smallest thing on the leaf**, so it is the likeliest thing in the book to be
misread or missed entirely. Of the leaves carrying an uncalled note: 35 have no
reference in the body at all, 11 have one that already belongs to another note,
and **7 have one misread as `(I)`**. Accepting the letter shapes of 1 is safe —
the match still has to find a note of that number *in that column*, so a stray
`(I)` with nothing behind it resolves to nothing — and it is worth 6 notes:
68 → 62, with 158 → 165 notices carrying one.

The other 55 are not recoverable by any rule, because there is no evidence to
recover them from. **So they are published anyway**, at the foot of the year,
with `entry_id` null and a line saying the call could not be read. 306 footnote
rows against 257 called ones, on 77 year pages. Campaner's notes are half the
scholarship in the book — he corrects Terrassa's dates and quotes the accounts a
notice summarises — and an edition that silently keeps 62 of them to itself is
worse than one that admits it cannot place them.

### Two checks that turned out to describe the book

**`doubled` finds Campaner's page, not our reading of it.** Four of the
doublings were cut from the facsimile and looked at — the one use of an image
this project allows — and **all four are printed twice**: leaf 219 `«En dicho
año año de 1488`, leaf 41 `de dicho año año, á quienes`, leaf 79 `generoso,
Nuñis Nuñis, domicelo` (a man's name in a list of names), and leaf 88
`Falleció el Reformador Felipe` / `Felipe de Boil`, the compositor setting a
word twice across a line break. His errors stand and so do his printer's. The
rest of the 23 are Campaner writing it twice on purpose: `etc., etc.`,
`¡Vergüenza, vergüenza!`, `Aquí, aquí`, `«todos, todos`, `luégo luégo`.

The check stays, because the other kind exists and this is what caught it:
`Te-Deum Te-Deum` and `JUNIO JuNio` were one word the alignment gave two slots,
and `spans.dedupe` drops those — on the evidence that **no** engine read the word
twice. Here every engine did, on both scans.

**`runt` was 16 and is 5.** Eleven were Campaner writing one line: `se levantó
el entredicho.`, `Extraccion de Jurados.`, `Llegó el Obispo de Orihuela.` The
five that are wreckage have 0, 3, 5, 7 and 7 letters against 12 for the shortest
real notice, so the threshold is letters and not length, and nothing in the book
sits in the gap.

Two of those five are one class — `OCTUBRE 7 3 •` before `Octubre i.°`, `ENERO .
1795-` before `Enero i.°` — a display heading the alignment wrote twice, badly
the first time. **Extending `dedupe` to skip the junk between two copies was
measured and refused**: it fires 95 times and nearly all of them are false, since
`month_of` tolerates two wrong letters and turns `moro`, `cuyo`, `judío` into
months. Adjacency is what makes that tolerance safe, and over a gap there is
nothing holding it.

`contested` was written and taken out. The entry text has been hyphen-stitched
and re-joined, so it can only be matched to the leaf's words by the word itself,
and a word doubtful once on a leaf then marks every occurrence: it fired on 58%.
`review.py` does the same thing properly, keyed by word box.

## A siglum is a sequence of initials, not a string

Campaner's source attributions are the reason this book is worth a database,
and 205 notices kept theirs stuck in the prose because the matcher wanted an em
dash and exactly one siglum. What an attribution *is*: one of the sigla the
introduction glosses. So the glossary decides, and the shape only says where to
look -- at the end, after a dash.

Then a sweep for tails that look like attributions and are not lifted found
**130 more**, all one cause: comparing characters when the engines scatter the
stops and the spaces.

| | |
|---|---|
| `—G. G. T.` 66 | a doubled initial |
| `—M M.` 12 | no stop after the first |
| `—G. T` 6 | no final stop |
| `—M. S. B. J.` 4 | two sigla, no dash between |
| `—B. J. .` 3 | a stop too many |
| `— G . T.` 2 | a space inside |

**And the tail is resolved whole before it is split.** A dash *inside* a siglum
is the alignment's and not the book's: `-Jn.—Br.` is Joaquin M. Bover in two
pieces, and splitting on the dash asked whether `Jn.` was a source, which it is
not, so the guard threw the whole attribution away. Resolving the tail whole
still separates a real pair — `—M. S.—B. J.` comes back as two — because the key
is a sequence of initials and the glossary decides where one ends. Sourced
notices 2 945 → 2 948, attributions resolved 92% → **93%**, `unlifted-siglum` 3 → 0.

Matching is on the **key of initials** and the guard is not the pattern but
that the key resolves against the glossary; a chunk that does not resolve lifts
nothing, because half an attribution is worse than none. `G. G. T.` collapses to
`G. T.` while `M. M.` (Matías Mut) stands, and four initials that fail are
retried as a pair. Sourced notices **70% → 85%**; 92% of attributions carry the
name Campaner gives them.

Things that must keep passing: `y su hermano N.`, `de 30 ls. y 4 ds.`, `el
Alcalde Mayor.`, `de D. Pedro de Bellcastell.` -- `ds. ls. ss.` are in the
glossary and abbreviate dineros, libras and sueldos, not manuscripts.

**Do not read the `unglossed` list from `sigla.json` here.** It is built by
counting attributions in `entries.jsonl`, so reading it makes `parse_entries`
depend on its own output. `UNGLOSSED` is written out in the source instead.

## The introduction is dropped, but not thrown away

The scope decision stands — the twelve leaves of introduction are not published
as text — and it was costing far more than the sigla glossary. **Eight of those
leaves are a dossier on every source the book uses**, and the abbreviation list
on leaf 25 is only the index to it. `M. M.—Matías Mut.` is what the list gives;
leaf 18 says he was an **espardenyer from Llucmajor**, that his diary runs 1680
to 1715 in a hand Campaner calls «de muy mala letra y peor redaccion y
ortografía», and that we know he was born in 1639 because on 15 April 1686 he
wrote in it «Dit dia jo vaig fer 47 anys».

`data/sigla/sources.tsv` holds that for **26 sources covering 97% of the 3 373
attributions**: who the man was, his trade, the years his manuscript covers, its
title as printed, and one telling fact. **Every row carries the leaf it comes
from**, which is what makes it checkable rather than asserted, and where
Campaner does not say, the field is empty.

Entered by hand, deliberately. Those leaves run two columns of footnotes under
the text and interleave them, so they are among the worst in the book for
reading order; and there are twenty-six of them, which is an afternoon, not a
parser. It is not transcription — it is metadata about the transcription, and
the prose is Catalan because it is shown on the site.

Two of the entries pay for the whole file on their own: **`L. V.` and `N. F.`
attribute 183 notices between them and are simply not in the book's own
abbreviation list.** They used to render as "font no glossada a la
introducció". They are Luis de Villafranca, the Capuchin librarian who copied
and continued half the diaries the Cronicón empties, and Nicolás Ferrer de Sant
Jordi of Sineu, whose book ends «fonch finit este libre en la vila de Sineu, en
ma casa dita Son Ferrer».

Still open: **`T. A.` is two different people.** Tomás Aguiló in the 16th-century
header and Tomás Amorós in the 18th, which is exactly why `parse_sigla.py`
refuses to guess — and it is a fact the site should state rather than hide.

## The drop caps: adjudicated, because no rule could do it

`ENERO 13.—Por Real Privilegio…` opened 1401 and the edition printed `NERO 13`.

**The letter is not misread; it is outside the geometry.** A crop of leaf 168
cut to the line's own box does not contain the `E` at all — the display initial
sits left of every engine's line box, so the line segmentation excludes it. No
amount of panel work recovers a character no engine was ever asked about, and
that is what makes this the review tool's business rather than `editorial.py`'s.

Finding them is geometric and clean: a drop cap indents the three lines beside
it by its own width and the fourth steps back to the column margin. Leaf 28
reads 0.196, 0.197, 0.196 then 0.129; leaf 64 0.182, 0.182, 0.183 then 0.119.
**15 candidates in the whole book.** Choosing the letter is the half no rule can
do — the lexicon offers `A, B, E, I, O, U, V` for `N este año` — so all fifteen
were cut from the facsimile and looked at:

| | |
|---|---|
| leaf 14 | `E` + `L presente libro` → **EL presente libro** |
| leaf 28 | `P` + `ARA que no cáusen` → **PARA que no cáusen** |
| leaf 64 | `E` + `N este año 1301` → **EN este año 1301** |
| leaf 168 | `E` + `NERO 13.—Por Real Privilegio` → **ENERO 13** |

**Eleven of the fifteen are not drop caps at all**, and the crops are the only
thing that could have said so. Nine are verse indented for scansion — the Latin
of the 1541 reprint on leaves 345–358, Catalan on 280, and a Mallorcan goig on
578 («y del Pare general, / Maria es concebuda / sens pecat original») — and two
are the brace `)` of the notes column on the annotated Jurats leaves 114 and 118.

The four repairs are recorded in `data/review/decisions.jsonl` as `source:
"typed"`, which is exactly what that field is for: the share of the edition
resting on a reading no engine produced should be countable, not assumed. It is
now four positions.

## The tables inside the prose

Campaner stops now and then and prints a table — the harvest of a year, the dead
of a plague, the census of 1784, who lent how much for the armada of 1343 — and
the transcription had every word of them and had lost the one thing that made
them readable, that the figures were in a column. `scripts/tables.py` finds
**16 tables, 78 rows, on 13 leaves**.

**This recovers structure, not text, and that distinction is the whole licence
for doing it.** No character is added, removed or changed; what is stored is
which word records make up which row. The signal is geometric and needs no
model: on leaf 569 the figures end at x 0.793, 0.796, 0.797 and 0.796 —
right-aligned to within four thousandths of the page — while prose does not do
that. A model was used once, the way this project allows: **crops of leaves 591
and 569 were read to check the detections**, and both times the check paid.

- The first crop showed two rows the detector had dropped. **The figure is not
  always the last token**: where the panel disagreed about where words end,
  `spans.py` returns one record for the whole run, so leaf 591's row arrives as
  the single string `Solteras . 40.603`.
- The second showed a row it drops **correctly**: leaf 569's `163` has a box
  0.002 of the page wide, a sliver, so it can align with nothing. It stays in
  the prose, where it always was. Absorbing a line because it *looks* like a row
  after the geometry has said no is guessing.

**Only one of the two families is a rule.** Figure last — `Cebada. 176,780 »` —
is 16 detections and all 16 are tables. Figure first — `24,294 hombres útiles
para tomar las armas.`, which really is one on leaves 453 and 593 — was declined:
it also takes `19 de Febrero, por haber llovido el día 23 y` and `15 ss. la
barcilla; el trigo á 14 ss.`, because prose begins with a date or a price often
enough, and 9 detections of which 4 are real is not a rule.

## The Jurats have a section at last

1 979 names were in the database and in the parquet and **no route showed one of
them**. `/jurats/` is the six series and `/jurats/<century>/` is a year at a
time, six seats to a card, the year linking to its notices where it has any.

Two things it turned up that are worth keeping:

- **`perayre` is not a surname.** Taking the last word of a name makes it the
  commonest family in Mallorca with 70 seats, ahead of Pachs and Zaforteza. It
  is a trade — a wool-carder — and Campaner writes the trade after a comma for
  **341 of the 1 979**: apotecari, forner, doctor en lleis, notari, argenter,
  ferrer, sabater, sastre, teixidor, blanquer. That is the guild sitting beside
  the donzell in the government of the Kingdom, and it is the most interesting
  column in the table. A families-across-the-centuries view needs the trades cut
  out first, which is why there isn't one yet.
- **The page has to say how weak this is.** Only **516 of 1 979 names (26%)** are
  read the same way by all six engines, against 79% for the book. Every doubtful
  name is marked and the index says the figure in words. Some names still carry
  the notes column bleeding into them — `Bernardo Villafranca se encuentran en
  el privi-`, `Jaime de Montsó I mismos` — on the annotated leaves.

## The site must not tidy the book either

**Year pages are ordered by the book, not by date.** November 1644 runs
5, 6, 9, 15, 22, 11, 19 -- checked against the facsimile, Campaner's own
disorder -- and `ORDER BY month, day` silently repaired it. Reordering his
notices is the same correction as respelling his words. It also puts a notice
that states no day back under the date it continues.

**A siglum is meaningless without the introduction, which this edition drops.**
The chips on the year pages expand to the name on click -- a button, not an
`abbr title`, because a title never appears on a touch screen -- and the index
carries the browsable glossary. Where a name is missing the page says which of
the two reasons applies: not in the glossary (`L. V.`, `N. F.`, `T. A.`) or a
truncated siglum whose second initial no engine placed.

## Where we left off (29 Jul 2026)

**Reading year by year is over; `audit_entries.py` replaced it.** 1229 and 1301
were read end to end and were worth it — see §What reading one year found — but
that is because they are the first leaves of their centuries, where every
structural class happens to meet. The sweep now finds the same symptoms
everywhere at once: §Reading page by page does not scale. Work from
`data/audit/findings.json`, not from the next year.

Two things this left open and one it must not do by accident:

- **Both are now done.** The centred-line rule was applied to the whole book:
  17 engine-leaf files on 12 leaves changed their column count (22, 28, 59, 60,
  117, 118, 120, 121, 168, 246, 380, 482), none of them adjudicated, and the
  consensus was rebuilt. Unanimous 367 908 → **368 887**, contested 23 647 →
  23 538, and the leaves needing line alignment 25 → **21**, which takes the
  held-back block from 11 114 positions to 8 391.
- **A leaf that carries adjudications is held page-aligned**, and that rule now
  lives in `layout_health.py` rather than being discovered by hitting
  `consensus.py`'s guard. Leaf 642 is the only one, it holds part of the frozen
  sample, and aligning it by line would renumber it. Lift the hold when
  `adjudicated.tsv` is re-keyed by word box, not before.

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

## Two sample families, and why they must not be merged

- **`sample*.json` — frozen.** Rounds 1 and 2, 550 adjudications, the twelve
  pilot leaves, the panel and geometry of the day. `sample_loci.py` now refuses
  `--from-consensus` or a different `--pages` on this family outright, rather
  than merely discouraging it.
- **`documents.json` — round 3, drawn, not yet adjudicated.** 320 positions
  (200 unanimous, 50 one-dissent, 30 two-dissent, 40 contested) over 127 of the
  164 document leaves, ids 551–870, drawn from the **production** consensus
  because there is no legacy adjudication there to protect. 44 of them fall on
  the 1541 long-s reprint. Adjudicate with
  `python scripts/review.py --sample documents.json`, then
  `--export-truth` to get `id<TAB>text`.

They are separate files with separate populations because their strata shares
differ — 78.7% unanimous on the document leaves against 70.4% on the pilot ones.
`benchmark.py` globs `sample*.json`, so the new family is invisible to it until
it is scored deliberately; merging them would weight medieval Catalan by the
chronicle's proportions and quietly corrupt every figure resting on them.

**The contact sheets are not the adjudication surface any more.** `build_sheets`
scales every crop to a constant 78-pixel line, and the single shared error round 2
recorded turned out to be the *adjudication* being wrong, because at that size the
acute accent on `así` is not there to see. Sheets are now opt-in (`--sheets`) and
exist only so the frozen family stays reproducible.

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

## What the repository holds, and what it must not

**The rendered site is not committed.** It was, and it was 73% of the history:
595 pages regenerated whole on every build, and neither HTML nor an
already-compressed parquet deltas against its previous version, so each rebuild
added about 10 MB that could never be reclaimed. The history was rewritten to
drop it — 72 MB → 22.5 MB, all 28 commits re-signed — and a clone can now
rebuild everything:

```sh
python scripts/build_db.py --from-parquet web/data
python scripts/build_site.py
```

That works because `web/data/*.parquet` **is** committed and is the only copy of
the two tables `data/` cannot produce: `word` needs the per-leaf sidecars, 100 MB
of JSON, and `leaf` needs the consensus itself, ten thousand files, and both are
gitignored. In parquet the same thing is 4.7 MB of zstd, and the site queries it
in the browser anyway. Verified end to end: the database rebuilt from parquet
renders every page byte for byte identical.

So the rule for anything new under `web/`: **if `build_site.py` writes it, it
does not belong in git.** Thirteen files are tracked there — the parquet, and
the hand-written `style.css`, `app.js`, `_headers`, `robots.txt` — which is the
convention the sibling projects already follow.

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
