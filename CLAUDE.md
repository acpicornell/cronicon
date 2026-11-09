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

## A column's edge is where its leftmost line starts

`find_columns` took the **mean** of a cluster of left edges, and a mean falls
inside the column whenever anything hangs in its margin. Leaf 152 is the
`ESPLICACION DEL ÁRBOL` of the genealogical plate and prints each entry's node
number out in the margin of its column, so the second column's edges run 0.485
to 0.555 and the mean lands at 0.529. Every number then sat left of the
boundary, was assigned to the *first* column, and sorted by y among its prose:
`…conquistó á Mallorca y Menorca.— IO En 1231 las dá en cambio…`.

The minimum is right and is safe by measurement: **over all 614 leaves it
changes no leaf's column count.** It only moves a boundary within its own
column, which is exactly where a hanging number, an outdent or a display
initial lives. Unanimous 368 887 → **369 566** over the book.

Two remedies were tried first and neither applies, which is worth not repeating:
`--split-gutter` cuts a *line* whose internal gap is too wide and these numbers
are already lines of their own; and `find_columns` was not failing to find two
columns, it was putting the boundary in the wrong place inside one.

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
  **Superseded for the annotated leaves, on the user's decision and with a
  guard** — see §The Jurats, read off the facsimile. The warning was right
  about the risk and it is why every name read is checked against the engines.

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

**Six of the 23 documents run across an engraved plate — 13 of them — and the
plates are now shown.** Section III prints the `ESPLICACION DEL ÁRBOL` on leaf
152 and the tree itself is the plate on 151, so a reader met the explanation of
a diagram the edition never mentioned.

**They are shown without being stored.** The page images are 1.6 GB in
`data/pages/`, gitignored, and committing 13 of them would start undoing the
work that took the history from 72 MB to 22.5. The Internet Archive serves them
over IIIF from the same scan this edition already cites —
`iiif.archive.org/iiif/CroniconMayoricenseCampaner$<ia_leaf>/full/1200,/0/default.jpg`
— so the cost here is a URL. The link to the facsimile stays under each one: if
their service is down the plate does not render and the reader still has a way
to the page.

A plate is a leaf of the section's range that carries **no word at all**, taken
from the text that was actually assembled. Reading `page_class` instead was
tried and is wrong: it counts the appendix leaves as plates, which is how the
first count came out as seven documents rather than six.

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

**The numbered pieces are found, and the numbering was the answer after all.**
This file used to say the Centellas section held "20 salutations against only 3
numbered pieces", so that neither the numbering nor the formula could delimit a
letter. That was a measurement of our reading order, not of the book: **all
twenty-one numbers are on the page**, set alone and centred over the letter they
open, and it took the centred-line rule to see them. The salutation is no use --
`Molt alt e molt poderos princep e Senyor` recurs *inside* a letter as readily
as at its head -- and the number is decisive.

The number is two characters of display type standing alone, the worst case
this book offers a recogniser, so it is read off the panel: leaf 125 published
`*` for `4.*`, leaf 126 `.*` for `5.*`, leaf 128 `*` for `7.*`. **The sequence
is the guard, not the vote.** One reading is enough, because a candidate has to
take its place in a run that rises and rises by no more than three -- the same
constraint `parse_documents.py` puts on a section numeral. Over all 23 documents
that separates completely: **two have a series and no other reaches five
candidates in a row.** Centellas 19 of 21, the `Nota de varias ejecuciones` of
1523 20 of 21, and the gaps are stated on the page rather than papered over --
leaf 134's number is printed and no engine returned it at all.

Two guards, each a wrong answer first: without the step cap, leaf 356's `42` (a
figure inside the 1541 reprint, 25 leaves past the last execution) joined the
run; without excluding `hanging_numbers`, leaf 152's ten marginal node numbers
looked like a series of their own.

**And a numeral was being published inside a word.** Leaf 123 sets the section's
`II.` centred above the second column, and sorting that column by y dropped it
between `…fo scap-` and `sat, lo qual…`: the edition printed **`fo scapXX.
sat`**. Leaf 152 did the same to `D. Fer17 rario` and `Montfer22 rato`, leaf 325
to `los ager18 » manats`. `unwedge` moves the numeral past the word rather than
dropping it -- it is a reading of real ink and belongs in the text, just not
inside a word -- and what says the join is real is that the line after the
numeral **continues the word in lower case**. Over the book 14 numerals sit
inside an apparent join and that test splits them 7 and 7 with nothing between:
`sat`, `rario`, `rato`, `nio`, `bores`, `manats`, `gents` against `«Los`,
`Hasta`, `«Part`, `Fragmentos`, `FEBRERO`, `Agosto`, `I.`

**Section VI of the 16th-century block was 45 leaves and almost none of it was
the section.** It ran 324–368, and the explanation written here — that VII was
the 1541 reprint, so its numeral was never printed — was wrong. **Leaf 325
prints `VII. Documentos y notas relativas á la Germanía, extraidas de los libros
de la Procuracion Real por el Pavorde D. A. Jaume.`**, centred, and Tesseract
never boxed the line, so no engine was asked about it. The line recovery found
it (§"Lines the geometry never boxed"); checked against the facsimile. VI is now
the one leaf of `Nota de varias ejecuciones` and VII runs 325–367, ids
`0311-VI-06` and `0311-VII-07`.

**VII still contains the 1541 reprint**, leaves 335–367: a different work,
reading as part of Jaume's Germanía documents. The boundary needs no new
evidence: `editorial.long_s_leaves` derives 335–367 from the consensus with two
independent signals, leaves 333–334 are blank, and leaf 332 is Campaner
introducing it (*«haber reducido el tamaño de las tres primeras páginas á las
dimensiones del original»*). Measured and not yet applied. VIII and X are still
not found; check for unboxed lines before assuming they are not printed.

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

## The documents were dirty in five different ways, and four were general

Reading `documents/0631-II-02` -- section II of the 18th century, a diary of 52
years -- turned up a page with a stray `605`, years printed as `171` and `1`, a
notice that opened `24.—Se terminó` with no month, attributions loose in the
prose and the same dash set four ways. Every one of them is a class, and none of
them is confined to the documents:

- **The folio number was leaking into the text of 109 leaves.** The running head
  is dropped by content, so where the engines cut it into two line boxes the
  words went and the number stayed. `layout.drop_folio`, and the proof is the
  same shape as the signature's: all 109 state `pdf_page - 27` and each is on the
  side its parity requires. The fifteen other bare numbers in that band are four
  digits and every one is a year heading.
- **A display month was being deleted by the span vote, on a technicality of
  case.** Leaf 632 prints `DICIEMBRE 24.—Se terminó…` and the panel returned
  `DICIEMBRE`, `DICIEMBRE`, `DiciEMBRE` and two empty strings; `spans.fold` did
  not fold case, so that is 2 against 2, `revote` refuses to outvote the blanks,
  and the month vanished. Folding case makes it 3 against 2. Over the whole book
  **438 spans → 472, 1 514 words → 1 667**, and all 34 of the new ones are a
  display month, a siglum or a name in a source list.
- **`Mavo`, `Acosro`, `OcruBRE`, `Jusio`, `FEsRERO`.** The years already got
  *ask the panel, not the winner*; the months never did, though they are the
  same display type failing the same way. `spans.months` fires on **86 slots
  over 76 leaves**. The guard that makes it safe is `strictly_a_month`: the
  winner has to be a misreading of one month **and nothing else**, because 13 of
  the 103 candidates were `Abril.—B.`, `-G. T. OCTUBRE`, `1355. Marzo` -- and
  replacing those deletes a siglum, a year or a footnote reference.
- **Year headings inside the documents.** Four sections are diaries and head
  each stretch with a bare year, which the winner collapses exactly as in the
  chronicle: `171`, `1`, `1 781.` `build_documents.year_heading` counts the year
  across all eight readings and publishes the best reading an engine gave of it.
  Section II went from 5 broken headings to none. One `T`→`7` was added to
  `DIGIT_LOOKALIKE` to reach the last of them, and measured first: over 614
  leaves it changes the panel's verdict on **two** lines, one of which is the fix.
- **The attributions were stuck in the prose**, where the chronicle lifts them
  into chips. 132 document paragraphs end in a siglum the glossary resolves;
  `build_site.sourced` lifts them with `parse_entries.lift_sigla`, which also
  settles the dash the user noticed -- `—`, `-`, `- ` and none were all being
  printed for the same mark, and the chip carries its own separator. The text
  keeps the panel's reading; this is how the page is set, not what it says.

And one defect that was silent and is the worst of them: **`paragraph_leaves`
was one short in 19 of the 23 documents.** Cutting the title free and putting the
recovered numeral back each added a paragraph and no leaf, so every *full N al
facsímil* link inside those documents named the leaf of the paragraph before it.
`stitch` now builds a list of paragraphs instead of joining a string and
splitting it again, and every edit that moves a paragraph moves its leaf.

### The documents have a second signal, and it is centred type

Sweeping all 23 documents rather than reading one showed the paragraph rule
failing in a way the diaries hid. Two fixes, both geometric:

- **A centred line is a heading.** `Declaracions en la causa criminal` set each
  deposition's heading centred in its column (`Declaració de Amet, cochero de
  Berga.`), `Historia de los Reyes de Mallorca` heads its chapters the same way
  (`D.a VIOLANTE / REINA VIUDA DE MALLORCA.`), Centellas numbers each of his
  letters over the measure, and the diaries centre their years. **333 lines on
  91 leaves**, and in a justified measure no line of body text is centred, so
  the signal is clean. Two details: a **run** of centred lines is one heading
  and not one each — leaf 373 sets a heading over three lines — and the width
  threshold sits in a gap, since moving it from 0.90 of the measure to 0.95
  admits six lines in the whole corpus and moving it on to 0.97 admits none.
- **A clear indent needs no short line before it.** The pair *indented **and**
  the line above is short* was written for section III and is right there; it
  fails on the legal documents, where a deposition or a sentence runs a full
  measure to its last line. The indent histogram over the 187 document leaves
  has a valley: 4 400 lines within 10‰ of the modal edge, **149 between 10 and
  15**, and 960 between 15 and 25 — the printer's indent. Above 20‰ the indent
  carries itself. **199 further paragraphs**, and reading every document's
  additions they are quotations opening `«`, operative clauses (`Proveex,
  sentencia y declara…`), and the second line of a title.
- Which is the trap that came with it: **a title runs to as many printed lines
  as it needs and Campaner indents its continuation**, so the new rule cut
  `Algunas noticias é indicaciones curiosas extraídas / de las que coleccionó el
  Pavorde Jaume.` in two and the catalogue no longer recognised its own title.
  The match is now made against up to three opening paragraphs joined.

Also **the running head survives on 12 leaves** and `consensus.py` cannot see
it, because six of them read `MAYORISENCE.` — the engines swapping the C and the
S. `layout.is_running_head` matches the word within two letters instead of the
string. 11 of the 12 go; the twelfth is leaf 98's `MAYORICENSE. sos`, where the
trailing letters are wreckage off the defective scan and are left to review.

Documents: 1 280 → **1 550 paragraphs**, none removed.

### And the documents get their own sweep

`scripts/audit_documents.py`, for the same reason `audit_entries.py` exists:
reading one document works and does not scale. Section II of the 18th century
was worth reading because it is a diary, where the year heading, the display
month, the folio number and the source siglum all meet on one leaf; the next
document is eight paragraphs of narrative and costs the same to read.

**It caught two of its own checks before it caught anything else**, which is
what the fire rate is printed for. `runt` and `bare-dash` fired on 17% of the
corpus each and every one of them was a heading -- a year over a diary's stretch
or a piece's number, which have no letters by construction. And two checks were
accusing defects the assembler already repairs one stage later: `wedged` and
`broken-year` read the raw lines instead of the output, so they reported four
year headings `year_heading` had recovered and six numerals `unwedge` had moved.
A sweep that accuses a fixed defect trains you to ignore it. 275 → 70, 262 → 26,
9 → 2. `bad-month` had a bug of its own: `strictly_a_month` reads `Entre` as two
letters off `enero`, so `Entre las partidas` passed a day-marker test that
accepted a lowercase `l`.

**And the second run said the same thing about `runt`.** Once the centred lines
were being recorded, 20 of the 47 that remained turned out to be headings the
book prints and the edition was setting as prose: `LECTOREM.` and `PROHEMI.` in
the 1541 reprint, `EL REY.` and `Vt. Claver.` under a royal cédula, `Autos de
Fè.` and `La Prosesó.` over a stretch of a diary, `D. FERNANDO` over a chapter
of the `Historia`. `build_documents` now carries them out as `headings` -- **304
paragraphs, 96 of them set as headings on the page** -- and the sweep stops
counting them as wreckage. 47 → **27**.

A trap that came with it: a heading still calls its footnotes, and skipping the
heading paragraphs took `orphan-note` from 2 to 13 before the note references
were collected first.

What it says is left, over 1 508 paragraphs:

| | | |
|---|---:|---|
| `short-para` | 228 | informational: the diaries' notices really are short |
| `wall` | 113 | informational: a deposition really is 3 000 characters |
| `runt` | 27 | 14 stranded ledger figures, 11 display lines of the 1541 reprint |
| `bare-dash` | 7 | the same ledger figures |
| `piece-gap` | 3 | numbers Campaner prints and no engine read; stated on the page |
| `bad-month` | 2 | `MájYO 23.`, `Manzo 6` — no engine read the month |
| `orphan-note` | 2 | |
| `broken-year` | 1 | leaf 152's `16`, 2 of 8 readings |
| `unlifted-siglum` | 1 | `— G. M.—T. A.`, and `G. M.` is not in the glossary |

**Eleven of the 27 runts are the 1541 reprint's own display lines** and are not
this rule's business: `LECTOREM.` is centred on a measure narrower than the
column's, `Ceruello.` and `Caualler.` are set flush left, `XXXXII.` misses the
centring tolerance by two thousandths. Reading a 1541 booklet's typography with
thresholds calibrated on Campaner's 1881 text is the confusion **task #47**
exists to end, and it is the right place to stop rather than loosen a threshold
that was measured.

**And the attribution dash may not follow a letter.** `…se cantó un solemnísimo
Te-Deum. — J. M. — M. M.` matched from the hyphen *inside* `Te-Deum`, so the
tail offered for resolution was `-Deum. — J. M. — M. M.`, `Deum.` is not a
source, and the guard threw the whole attribution away rather than lift half of
one. Seven notices and one document paragraph get their sources back and nothing
loses one; `…dos noches.—G. T.` and `…Te-Deum.-G. F.` are untouched, since both
put a stop before the dash.

**And the class it found is a ledger.** `0311-VI-06` and `0311-XI-11` rank first
and second, and their runts are all the same shape: `A Juliá Valera, altre dels
sargents majors.` then `41 »` on its own. Campaner prints a payments ledger
inside the document and the figure comes out as a paragraph. `tables.py` already
solves exactly this for the chronicle -- the figure-last family, 16 detections
and all 16 real -- and has never been run on a document leaf.

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

**And then it was paid again, for the long s.** `build_text.py` computed the long
s repairs for itself and `parse_entries.page_lines` — which assembles the notices
*and the documents* — passed `None` for them. So the 1 481 repaired tokens of the
1541 reprint were in `data/text/` and in no page a reader opens: the document
carried **10 `ſ` where the published text had 1 681**. Every per-slot repair now
comes from `editorial.repairs_for()`, asked by both. **When adding any rule, grep
for `spans.layout` and check every caller gets it.**

A third tier came with it: **the hyphen the panel read.** `Tarrago. na`,
`pú. blicos`, `compa-, ñías` — the winner made the break hyphen a stop, and three
or more engines (or two, with the joined word attested) read it as a hyphen.
`editorial.hyphen_breaks` restores `Tarrago-` and the ordinary stitch joins it:
15 tokens, `glued` 31 → **25**. Measured in `docs/EDITORIAL.md` §Rule 2.

**The assembly was not deterministic.** `page_lines` collected the engines in a
`set`, whose order follows Python's per-process string hashing, and
`build_documents.year_heading` broke ties by first-seen — so leaf 375's heading
came out `1543.` on one run and `1543•` on the next, and leaf 374's `1525-` won
on some runs and glued the year to the paragraph after it (`1525«A 30 de…`).
Engines are sorted, the tie-break ends on the string, and a reading ending in a
hyphen can no longer be a year heading. **Verified by running the chain under
two `PYTHONHASHSEED`s and diffing: identical.** Do that again after touching
anything that iterates a set.

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

**The note's own number is misread the same way, and that was most of
`dangling-note`.** The call got the `(I)` licence and the note opening did not,
so eleven notes that open `(I) CRIDA. Ara oiats…`, `(I) EXECUCIÓ RARA.`, `(I)
NOU DRET DE ADUANAS.`, `(i) Véanse los apéndices al siglo XIV.` were never split
off and were **published as chronicle**, straight after the `(1)` that called
them — Catalan documents a notice quotes in full, reading as Campaner's prose.
`parse_entries.note_start` accepts the letter shapes of 1 at a note's head when
text follows it, since a bare `(I)` at the start of a line is a stranded call.
Over the whole book twelve lines open that way and every one is a note.
`dangling-note` **18 → 9**; `orphan-note` 62 → 64, because two of the eleven sit
where their call cannot be matched (leaf 224's note is called from leaf 223).
The nine left are leaves where the note is genuinely absent from the panel's
lines or split_notes' bands, not a reading problem.

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

**And the documents print a third kind, which is a line the engines cut in
half.** Campaner's ledgers set the label and the figure on *one* printed line
with leader dots between them — `manats. . . . . . . . 18 »  »` — and the dots
are a wide internal gap, which is exactly what a line segmenter looks for. So
the figure arrived as a line of its own, sorted by its own y, and landed
anywhere from the middle of the label to after it: `A Juliá Valera, altre dels
sargents majors.` and then a paragraph reading `41 »`. That is what
`audit_documents.py` ranked first and second in the whole corpus.

`layout.join_leaders` puts the two boxes back into one line. The join needs
three things at once — they overlap in y, they are in the **same column**, and
the right-hand one is **nothing but a figure** — and the third is what makes it
safe: **25 joins on 7 leaves and every one is a ledger row.** Without the
same-column test it also joins leaf 152's marginal node numbers to the entry
beside them, and every line of column one to the line facing it in column two.
Nothing is dropped or rewritten; `layout.line_order` reads a rejoined line left
to right, because the figure's box begins a hair above the label's and sorted
first — leaf 325 published `41 » gents majors.`

Two consequences, and the second is why it belongs in `layout` rather than in
either assembler. The documents lose 49 stranded paragraphs, so the sweep's
`runt` goes 70 → **47** and `bare-dash` 26 → **7**; and `tables.py` starts
seeing rows it could not see before, because it asks each *printed line* whether
it is a row and the row had been cut in half. **16 tables → 20, 78 rows → 92**,
three of the new leaves being document leaves.

`ledgers_on` is the family that then reads them: a run of rejoined lines whose
figures align, with the label running over the lines between two rows. **The
rejoin is the whole guard.** Allowing any line that ends in a figure, with up to
six lines of label between two rows, took leaf 74's footnote (`los cuatro
importan 538 ls. 8 ss.—130 ls. 10 / ss. 5 ds. para execuacion…`) and five other
stretches of prose that merely count money. A rejoined line is *proof* of the
typography: the engines cut it at a gap wide enough to be leader dots, and what
stood to the right of that gap was nothing but a figure.

**A table aligns two things and the panel loses one or the other**, so a run
continues if *either* the end of the row or the end of its first figure aligns.
Taking only the row's end cost leaves 566, 571 and 612, where `Cebada. . . . •
37.663 »` and `Avena. . . . . 23,038` end 0.05 apart because one keeps its ditto
mark and the other does not; taking only the figure's cost leaf 161, where
`Ingresos… 6 ds.` aligned on the `6` and `Gastos… 11 »` on the `11`, which are
two different columns of the page.

**Leader dots are not a cell**, and treating them as one was worth five leaves:
`Cebada. . . . . 179,000 »` arrives as four records, the walk back swallowed the
dots, and the figure's edge came out as the dots' — 0.226 instead of 0.420.

**And a table puts more than a word space between the label and the figure.**
That is the one guard the two-edge union needed: it let in leaf 241's `com dura
lo divinal offici a raho de 2 ss. 6 ds.`, a sentence in medieval Catalan that
happens to end in money. Measured over every table found, leaf 241's median gap
is **0.0075** — a word space in this book is 0.0066 — and the smallest of the
real ones is 0.0146, so the threshold sits in a gap that is not delicate.

**A row of ditto marks may continue a table but never open one.** Campaner's
household accounts set most cells as `»` — `Una galina. . . . . . . 2 » » » »` —
and the panel keeps the dittos and drops the figure, so a row with no digit in
it is common inside a real table and is also what a closing guillemet looks like
when the panel gives it a record of its own. So such a row joins a run that
figures have already opened, and a run may not end on one either.

**16 tables → 30, 78 rows → 124, 13 leaves → 18**, and leaf 92's list of who
lent what for the armada of 1343 comes out as seven blocks of 32 names.

### The one table the panel could not read, and what it took

The daily household accounts of 1307 on leaf 159, which open `0114-V-05`, are
the worst case in the book for the empty-string problem and no rule reaches
them. The page prints `Una galina. . . . . . . 2 » » » »` and the panel returned
`Una galina. . . . »`: **the vote emptied three to nine cells on every row of
the table.** Leader dots and ditto marks set far apart scatter the tokenisation
completely — on that one row five of eight engines return nothing where the `2`
is, and at the last slot four read `» »`, `» t) »`, `» » »` and `» " "`, no two
alike, so `spans.revote` has no class with two votes and refuses.

There is nothing to recover and nothing to detect. **So it was adjudicated**,
which is what the facsimile is for and the only sanctioned use of reading the
page: **53 positions on leaf 159**, 27 confirming a reading some engine gave and
**26 typed**, recorded in `data/review/decisions.jsonl` with `source` as the
project has always required so that the share of the edition resting on no
engine's reading stays countable — 4 positions before this, 30 now. The cells
were assigned to the boxes by the five money columns the printer set, at x
0.751, 0.772, 0.790, 0.816 and 0.847, and every one of the 15 rows reconstructs
exactly what the page prints.

**A section boundary is a point on the page, not a point in the reading order**,
and on a two-column leaf the two are not the same thing. Section V opens in
column 0 of leaf 159, so everything after it in reading order was taken --
including the top of column 1, which is where section IV finishes. The edition
published `Suma 3 » 2 » com les altres fossen ja arribades, exceptades
alcunes…`: a household account of 1307 run straight into a fleet's storm
damage. Nothing printed *above* a section's first line belongs to it, and the
test is applied only on the leaf the section starts on and only to lines in a
later column, so the ordinary case is untouched.

**A row needs two letters, not three.** `It. vi.`, `It. farina.`, `It. figues y
cogombres.` — the first has no word of three letters, so the block was never a
table. Over the whole book the looser guard admits exactly **two further
tables**, that one and leaf 607's table of coin values, and both are real.
**34 tables, 142 rows, 20 leaves.**

### The two leaves where a table's column is read as the page's

`find_columns` clusters left edges, and on **leaves 161 and 163 the account's
figure column is wide enough and regular enough to look like a column of the
page**. So the leaf reads as three columns, the reading order takes every label
first and every figure after, and the edition published `Dada de dons 65 » » 389
» 451 » 8 » 1 » 1.687 1.913 » 9 » 10» 582» 3» 3» 395 » » I» 17.069 » I5 » 6 »` —
a whole account's figures in one run, with its labels a paragraph away.

`join_leaders` cannot reach them, because it requires the two boxes to be in the
same column and here they are not. **Fixed**: `layout.is_ledger_column` merges a
column back into the one on its left when **half its lines are nothing but
figures and half of those carry a ditto or a unit**. "All figures" was the first
draft and is wrong: measured over every engine-leaf file, OCR noise in the cells
(`17.069 » I$ » 62`, `395 Y » » I»`) puts the real ledger columns anywhere from
0.50 to 0.94, the geometry engine's at 0.62 on leaf 161. The mark is what keeps
leaf 152 out — its genealogical node numbers are 0.82 figures for Apple Vision
and carry no mark — and it fires on **161, 163 and 325** and nowhere else. 325 is
the same defect: its payments ledger set `18 »` far enough right to be a column.

Three things came with it, each a wrong answer first:

- **The figure has to follow its label.** Merged into the label's column, a
  figure whose box tops a hair higher sorted *first*, and under line alignment
  the readings are matched to slots in that order — Apple Vision's `• 2103` was
  given to the `18`'s slot and `2103` lost its vote. `layout.side_by_side` moves
  a ledger figure (one carrying a mark) right of whatever shares its row. Applied
  to any two boxes on a row it reordered ~350 leaves, the frozen sample among
  them; restricted to marked figures it touches **15 leaves, every one a ledger**.
- **A label can lead to more than one figure box.** `2103 » 18 »` arrives as
  `. 2103` and `18 »`, and `join_leaders` gave each figure its own union with the
  label, so the printed line came back in two pieces. Every box of the row now
  takes one union.
- **Asking the column question of the consensus needs the panel for the mark and
  the winner for the figure.** The vote strips dittos (`785 » 17 »` → `785`,
  `17`), so winners alone no longer look like a ledger; but joining every
  reading lets one engine that glued the label on (`conipanya.......2103`) turn
  a figure into prose. `layout.panel_text` takes the winners and adds the mark
  if any engine read one. `join_leaders` and `parse_entries` used to pass no text
  at all, so neither could ever see this rule.

Consensus rebuilt for the 15 leaves; every box identical, all 7 round-3
positions on them found with their grade, every review decision still keyed.
Tables **34 → 39, rows 142 → 165, leaves 20 → 22**; no leaf publishes fewer
figures than before and 160, 162, 164 publish more (`Gastos… 14.271 » 9 » 11 »`
for 1334, checked against the facsimile). What it does not fix, and is now
visible rather than buried in a run of figures:

- **Tesseract never segmented the last line of several labels** on 161 and 163 —
  `rella. . . .`, `ça. . . .`, `pitals. . . .`, `tre. . . .`, `armat. . . .` have
  no box at all — so the hyphen stitch joins the label's `Tor-` to the figure:
  `Tor65 » »`, `Ebi582» 3» 3»`, `des122 » 10 » 8»`, `prebe296 » 17 » 7 »`. A word
  never continues in a digit, and four stitchers would need the guard; and the
  missing line is a geometry problem the guard would only hide.
- On 325 the vote still empties the `18 »` of `agermanats. . . 18 »`: with the
  label first, the engines' leader dots fill the figure's slots. The document
  shows it as a paragraph of its own. Six new `runt`s in `0114-V-05` are rows of
  this kind plus the account's total and its `Gastos.` heading.

### Leaves 159–164: adjudicated as lines, because the defect was the line

The accounts of 1307, 1318 and 1343 never came right by rule: every fix above
moved figures nearer their labels and left a page a reader could not follow --
rows as prose, a table printed twice, `Dimecres á 5 Juriol. Pa Vi. I s. + ds.`
What was wrong was not any one word box but **the line**: which boxes are one
printed row, in what order the rows run, which rows are a table and where a
row's label stops. `review.py` settles a box at a time and cannot say that.

So those leaves were read from the facsimile at native resolution, line by
line, into **region files**:

```
data/adjudication/regions/p0161-a.txt
leaf: 161
box: 0.13 0.098 0.52 0.895
---
0.414 A | Id. de les de Ebi-
0.431 A | ça.. | 582 » 3 » 3 »
0.518 | Gastos.
```

`y [table] | text`, or `y table | label | cells` for a row; a table line with
no cells is the label continuing onto the next. **Nine regions, 226 printed
lines.** `scripts/adjudicate_region.py --show LEAF --box …` lists the rows it
finds with their centres; `--apply` does three things, and the file is the
record of all three:

- **Text.** Every box in the region gets a decision in `decisions.jsonl`, keyed
  by box as always: 1 314 written, **148 typed** -- no engine had read them --
  the rest confirming a reading some engine gave. Typed positions in the
  edition: 167, of which 152 are on these six leaves. That number is the
  condition this is allowed on, so it is printed by the tool and kept here.
- **Lines.** `layout.apply_regions` makes the boxes of one printed line one
  line, in the order the file gives, in the place the region's first box had.
  Both assemblers call it. Nothing outside the box moves and no index changes.
- **Tables.** `tables.py` takes the rows as written and detects nothing inside
  the box. A row that starts at the foot of one column and ends at the head of
  the next -- or of the next leaf -- is carried over and belongs where it ends.

Three things that came with it:

- **Leader dots are not transcribed.** `Carn y tocino.. . . . . . .` is the
  printer's fill between a label and its figure; counting dots off a scan is
  neither reliable nor information. The label keeps the stops set against it
  (`Pa..`, `blat..`), which are the book's. `docs/EDITORIAL.md` §Not rules.
- **Tables are set row by row** (`build_site.InlineTables`). They were set
  first-row-to-last, so when the assembler broke a paragraph inside a table the
  last row was not in that paragraph, only the first was replaced -- by the
  whole table -- and the other rows came again as prose. Adjacent tables are
  joined, and a leaf mark that falls inside a table goes under it.
- **A ledger's cells are separate cells.** `2 » 4 » »` is five table cells, so
  libras, sueldos and dineros stand under one another as the page sets them.

`0114-V-05` went from 3 tables and 27 flagged runts to 10 tables and 107 rows,
every one found in the text. **Do this again rather than write another rule**
when a table's cells are being emptied and its order is wrong: read the crop,
write the lines. And check the name is free first -- `scripts/adjudicate.py`
already existed (the pilot's review sheets) and was overwritten and restored.

### Lines the geometry never boxed

The first of those residues was not a stitching problem. **Kraken and PaddleOCR
do not segment the page: they are handed Tesseract's line boxes and recognise
inside them.** So a line Tesseract did not find is a line three of the six
engines were never asked about, and the alignment, which projects every engine
onto the geometry's slots, dropped the text the other three did read. Only two
engines segment the IA scan for themselves, ABBYY and Apple Vision.

`consensus.uncovered_lines` takes every line **both** of them read that no
geometry box covers and that is not furniture (running head, folio, the Google
watermark), and `insert_lines` puts ABBYY's word boxes into the reading order
after the last line of their column that starts above them — inserted, never
re-sorted, so nothing that was right moves. **43 lines on 26 leaves**, and they
are not trivia: the account labels of 161 and 163 (`Torrella 65 » »`,
`despitals.... 122`, `preberes 296`, `Alaro`, `Santueri`), `Pa` and `Vi` in the
accounts of 1307, `B. J. (1)` on 218 and 220 and `J. P. (1)` on 401 — a source
and its note's call — the year heading `1538.` on 312, and **the numeral of a
section nobody knew was missing** (above, §The appendix blocks).

On a recovered slot the three line-bound engines vote `None`, not `''`: their
silence is not a reading. With three of six possible votes a recovered word can
never be better than `contested`, so every one of them is published *and* goes
to review — the same ceiling `spans.py` puts on what it recovers.

Measured on the 26 leaves: every existing word box kept, every round-3
position and review decision still found, 8 existing winners changed (most of
them a siglum that had been squeezed into a neighbour's slot and now has its
own). Years with a heading 524 → 525, tables 39 → 41, rows 165 → 176. Line-
aligned leaves reshuffle grades when a reference line is added — leaf 159
moved 50 positions up a tier and 37 down — because the vertical offset to the
BNE scan is fitted on the reference lines; those leaves are held for review
anyway.

**And the generous rule it fed had to be tightened.** `parse_documents` asks the
panel for a section numeral on any short line, and the recovered `Vi` (wine) of
leaf 159 became section VI. A numeral is centred and never starts at the
column's text edge; measuring the indent from the column's *leftmost* line was
tried first and rejected leaf 123's numeral, which is centred over the gutter
and is its own column's leftmost line.

**What is still not right on leaf 159 and is honest to say so:**
`Disapte 1.er de Juliol` runs `It. vi.`, `It. farina.`, `It. peix y ous` — and
`rows_of` requires a row to carry three consecutive letters somewhere, so that a
bare figure at the foot of a column cannot open a table. `It. vi. 1 s. 2 ds.`
has no such word. The guard is right in general and wrong here, and loosening it
is a measurement to make deliberately rather than in passing.

**And it exposed the drift this repository keeps paying for.** An adjudicated
position reached `build_text.py` and neither `parse_entries.py` nor
`build_documents.py`, because only the first read `decisions.jsonl` — so the 53
cells appeared in the published text and the document came back as prose the
moment it was rebuilt. `page_lines` now applies them too. Leaf 159 is a table:
32 tables, 135 rows, and four of them set on `0114-V-05`.

**A ledger's right-hand cell is a row of cells, not one figure.** The account of
1318 on leaf 160 reads `2.594 » 7 » IO »` — libras, sueldos and dineros with a
ditto mark wherever a column repeats — and matching one figure and one unit read
`2.594 »` and stopped, so the whole account stayed in pieces. The test is now
*every token is a figure, a ditto or a unit, and at least one carries a real
digit*: the digit is what stops a line of ditto marks alone from opening a row,
and the digit lookalikes are folded first because `IO` for 10 is constant in this
column. **28 joins → 38, tables 20 → 22, rows 92 → 101**, and the same cut had
to be made again in `build_db.split_row`, which was cutting `28 » 16` into a
label of `ga doble.. 28 »` and a figure of `16`.

Leaf 374's ledger is **declined and that is right**: its figures end at 0.398,
0.436, 0.465 and 0.364, because the number of trailing ditto marks varies and
the panel drops some. The geometry says no, so those rows stay in the prose.

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

## The Jurats, read off the facsimile — and what that showed

The user asked whether the lists were as bad as the tiers said and suggested
reading them with vision. **They were worse, and not in the way the tiers
measured.** Leaf 114 prints six Jurats for 1302; the edition had two, and both
belong to 1303. Of 344 parsed names for the 13th and 14th centuries one was
unanimous, but the damage was structural: names missing four in six and filed
under the wrong year, because on these leaves the engines do not agree what
order the page is read in.

So leaves 58–60 and 114–121 were read at native resolution into
`data/adjudication/jurats/p####.txt` (year, then `seat | name`, or `* | remark`
where Campaner prints a sentence instead of names). `parse_jurats.py` calls
`jurats_facsimile.override`: the years a file covers come from the file.
**382 names over 80 years where the parse had 202**; `Los del año anterior.`
and `Villafranca no pone ninguno.` are kept as remarks; a seat he numbers and
leaves blank is absent, and the seat number is the one he prints.

**The guard is the comparison with the engines, and it is the finding too.**
This file says, of exactly these leaves, that a model must not read them: a
1300s surname is where it normalises and invents. So every name read is
compared with each engine's text of that leaf (`jurats_facsimile.py --check`):

- **381 of 382 were read letter for letter by at least one engine, nearly all
  by three or more.** The engines read these names well. What failed was never
  recognition; it was the alignment and the parse built on it.
- **The one that differed was the model's error.** `Guillermo Delfi` on leaf 59
  had been written `Delfí`, by analogy with leaf 58 where the accent is
  printed. Five engines had `Delfi`; a 3× crop shows an fi ligature and no
  accent. That is the normalisation the rule warns of, caught by the check the
  rule's own logic suggests. No name on these leaves now rests on the model
  alone (`source: "typed"` is 0).
- **Nothing is corrected**: `Francisco de Vilanona` (leaf 115, though the note
  beside it says Vilanova) and `Beruardo Bonet` (leaf 120, a turned letter)
  stand as printed, and every engine reads them so.

**Then the compact lists were read the same way, on the user's decision**
("léelo directamente como hasta ahora, es lo más fiable"): leaf 121 from 1371,
122, 225–229, 311–315, 478–482 and 631. **All six series now come from the
facsimile: 28 leaves, 2 436 names, 12 remarks, 423 year headings, and no row
of the parse is kept.** A whole leaf at ~1 000 px wide is legible enough to
read three columns in order; the check is what makes that safe.

- **2 431 of 2 436 names match some engine letter for letter**; the other five
  carry a superior letter no engine renders (`Juan B.ª Bordils y Sureda` ×3,
  `Juan B.ª de Bordils`, `Juan Mig.l Ballester de Togores`) and are the only
  `typed` ones. Twenty matched a single engine, nearly all over an accent, and
  each was re-read from a 3–6× crop: the acute is a slanted stroke where the
  dot of an `i` is round.
- **The check caught the model a second time**: leaf 478 prints `uan Vivot.`
  for 1614 — the `J` never inked — all eight engines read `uan`, and the model
  had written `Juan`. Restored. Two for two, both normalisations, both the
  failure this file predicted.
- **What the parse had got wrong beyond the names**: the 16th-century list does
  not end on leaf 314 — the last two seats of 1599 and the whole of 1600 are at
  the head of leaf **315**, above section II, and were never read (the parse
  stopped at 1598). Two years are printed twice and are two elections: `1401.`
  then `1401 (EN 7 DE JULIO.)`, `1444.` then `1444 EN 23 JUNIO.` A year runs
  across a column or a leaf break as often as not (1545, 1554, 1563, 1572,
  1581, 1590, 1599, 1606, 1612, 1618, 1627, 1636, 1671, 1680, 1689).
- Rows keep the leaf's order (`order`, then `id` in the database), because
  (year, seat) no longer orders a year printed twice; the site renders a year
  in that order, remarks where they stand. `jurat` gained `source` and
  `engines`. `Pedro AndrésRossinyolde Defla` (leaf 481, set squeezed) is
  matched ignoring spaces only.

Still not published: the notes column of the annotated leaves (which codex
gives which name). And `jurats_facsimile.py --check` should be run whenever a
file under `data/adjudication/jurats/` is touched.

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
does not belong in git.** What is tracked there is the parquet and what a
person wrote: `style.css`, `app.js`, `search.js`, `home.js`, `theme.js`,
`favicon.svg`, `_headers`, `robots.txt` and `vendor/` (the fonts) — the
convention the sibling projects already follow. `web/jurats/` was tracked by
mistake for months, seven generated pages, and is out.

## The site: a book to be read, under its own security policy

Redesigned on 9 Nov 2026 after an audit. The look follows the sibling
`mapes/mut` — paper and ink, EB Garamond and Cinzel **served from this origin**
(`web/vendor/fonts/`, OFL; the long s was checked in the font before it was
adopted) — because this is the one site of the family that is read for pages at
a time. Light and dark, the measure held at 66 characters, `hyphens: manual` so
a browser never adds a hyphen that looks like the book's.

**The deployed site would have been broken, and nothing local showed it.** The
Content-Security-Policy is `style-src 'self'` with no `'unsafe-inline'`, and the
year index drew its 572 bars with `style="height:…"`: 627 inline styles, every
one blocked, plus the plates from an origin `img-src` did not admit. A plain
`python -m http.server` ignores `_headers`, so it all looked fine. Three things
keep that from recurring, and all three are to be used:

```sh
python scripts/build_site.py     # ~5 s
python scripts/check_site.py     # fails on any style=, on*=, inline script,
                                 # foreign origin, dead link or duplicate id
python scripts/dev_server.py     # serves web/ with the real _headers, :8788
```

- **Nothing writes a `style` attribute.** What varies with the data is an SVG
  attribute (`height` is geometry, not style) or a class; chart colours are
  `--band-0…11` in `style.css`, once per theme; axis labels are equal flex
  cells, one per decade, so no position is written into the markup.
- **One foreign origin, for one thing**: `https://iiif.archive.org` under
  `img-src`. A leaf of the facsimile opens in a `<dialog>` when the reader
  clicks a `full N` link; the `<img>` is created on that click and not before,
  so a reader who opens none makes no request to the Archive. Every such link
  is a real link to the Archive's reader and works with scripts off.
- **`theme.js` is a file, loaded synchronously in `<head>`**, because an inline
  script is forbidden and a deferred one flashes light before turning dark.

**Doubt is marked by position, in `scripts/doubt.py`.** It was marked by word
*form* — underlined wherever the form had been disputed anywhere on those
leaves — so `/anys/1715/` carried 4 161 dotted words, 40% of the page, mostly
`de` and `la`; and those spans were 70% of the bytes of the heavy pages. A
notice does not record its word records (`word_from`/`word_to` are NULL), so
the text is **aligned** against the leaves' word stream with
`difflib.SequenceMatcher`: 99.9% of 430 676 text tokens placed, in about a
second. 1715 now carries **576 marks**; the heaviest page went 615 KB → 188 KB.
Four things, each a wrong answer first:

- **Tokens are runs of letters and digits; punctuation is not a token.** The
  engines dispute a dash far more than a word, and the published text has moved
  both — `21.--Rogativas` is one record on the leaf and `Rogativas` in the
  notice.
- **A multi-token record's tier is the run's, not each word's.** `1.°—Refriega`
  is contested because of the day; marking `Refriega` for it put a dotted line
  under the first word of four notices in ten. Each token of a run is graded
  from the record's own rival readings: disputed if two or more lack it — the
  line the tiers draw. Where no rivals are recorded the whole run stays marked.
- **An unaligned stretch is disputed if its side of the stream was.** A failed
  alignment must never present a disputed reading as settled.
- **A stray match of one or two tokens far off its neighbours' diagonal is
  dropped** — it is `de` matching some other `de`.

The build prints the coverage and **exits non-zero under 95%**. The rival
readings shown are those of *that* position (`data-v`), reachable by tapping
the word or by the "amb les variants" mode — a `title` tooltip does not exist
on a phone or from a keyboard. Jurats alone get a second, fainter grade for one
dissenter, because a name is what a reader copies into a genealogy.

**Wayfinding.** Every notice has an address, `anys/<y>/#n<id>`; the id is its
position in the book, so it is stable as long as the parse is and no longer —
nothing outside a build stores one. Search is a page (`/cerca/`) reachable from
a form in every header, with state in the URL, filters by century, source and
scope, AND between words, and hits that land on the notice. The index is in
shards (`web/search/c13…c18.json`, `docs.json`, `jurats.json`), fetched on the
first search and only the century asked for. The 44 years with no news keep
their page, are `noindex`, and prev/next steps over them.

**Thematic routes are searches, and say so** (`scripts/themes.py`,
`/temes/<slug>/`). A pattern over the folded text of every notice, the terms
printed on the page, the notices in the book's order: nobody chose them and
nobody wrote about them. `build_site.py --themes-report` prints counts and a
random sample, and **a route is kept only after its sample is read** — which
narrowed three on the first reading: `bando` is an edict far more often than a
faction, `temporal` is the Church's *porción temporal*, and `Colom` is
Porto-Colom before it is the leader of the Germania.

A fourth was narrowed by the user reading the site, and it is the instructive
one: **`inquisi` is not the Inquisition.** `inquisiciones ocultas` (1279),
`haciendo inquisicion del estado` (1304) and `declaracion inquisitiva` (1619)
are inquiries. Folding destroys the one thing that tells them apart, the
capital, so a route may also carry an `exact` pattern run on the text as
printed: the tribunal is `Inquisicion` capitalised, `inquisidor`, and `Santo
Oficio` -- which the first pattern had not thought to look for and is worth
nine notices. 119 → 125, three out. A random sample of eight does not find
three wrong in 119; a reader who knows the word does.

**"Tal dia com avui"** on the home page reads `web/dies/MM.json` — dated
notices short enough to show whole, and only those that open the way a notice
opens, because one that starts in lower case is the tail of a sentence the
parse cut and the home page is the wrong place to show the edition's seams.

**`lang` is set where the language changes.** The interface is Catalan; the
chronicle is `lang="es"`; ten documents are `lang="ca"` (`DOC_LANG`, a judgment
by title and to be reviewed); everything transcribed is `translate="no"`.

**A page must not depend on its stylesheet to be legible, and must never be
paired with an old one.** The first review of the redesign came back as "you
have removed the spaces between words and destroyed every bar chart". Neither
was in the HTML: the browser had kept August's `style.css`, cached under a
server that sent no cache headers, and was showing the new markup with it.
Reproduced by rendering a new page against the old stylesheet — the bars one
black block, `AnysTemesDocuments`, `12301123111232`. Three fixes, because the
cache was only the trigger:

- **Asset URLs carry a fingerprint** (`style.css?v=92b95b32`, `asset()` in
  `build_site.py`), so a rebuilt page cannot load a stylesheet from before it.
- **Adjacent inline elements are separated by real spaces**, not by CSS
  margins: links in a nav, a year and its count, the fields of a card. The
  page reads correctly with no stylesheet at all, which is also what a screen
  reader gets.
- **SVG bars carry `fill` as an attribute.** A shape with no fill is black, and
  572 full-height hit areas with no stylesheet are one black rectangle.

`_headers` now sets `Cache-Control` on directory URLs too (`/` and `/*/`): a
page is requested as `/anys/1521/`, which `/*.html` never matched.

**The build is deterministic and that is checked the same way as the
assemblers**: four runs under different `PYTHONHASHSEED`s, `diff -r`. Five
queries had no total order — a tie in `ORDER BY n` — and each showed up as one
page differing between runs.

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
