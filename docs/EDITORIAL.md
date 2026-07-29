# Editorial rules

What this edition changes, and what it refuses to change.

The transcription is produced by six independent recognisers voting token by
token. Every word in `data/text/` is a string some engine actually read off the
page; nothing is generated. These rules are the only exceptions to *the vote
stands*, and each one is applied by `scripts/editorial.py` — never by hand, never
by eye, and never anywhere else in the pipeline.

Every rule here must satisfy three conditions:

1. **It repairs an error, not a habit of the book.** Campaner's spelling is not
   an error. His own mistakes are not errors of ours.
2. **It is decided by evidence**, either a reading some engine produced or an
   attestation elsewhere in this book — not by a language model, and not by a
   dictionary of modern Spanish.
3. **It is reversible.** Every word it touches keeps what the panel voted for
   under `printed` in `data/text/p####.json`.

---

## What is never changed

- **1881 orthography.** `formacion`, `dia`, `Setiembre`, `mallorquin`, `á`, `ó`
  stand as printed. The BNE's own ABBYY layer silently writes `formación`; that
  is an error introduced by a tool, and this edition does not repeat it.
- **Campaner's errors.** Leaf 39 prints the year heading `1449.` above an entry
  that reads *«año de 1249, perseverando…»*. The heading is wrong and it stays
  wrong; the chronology index records 1249 and the page records `1449.`
- **Accents, cedillas, case.** `Gaçó`, `Sa Torre`, `Des-Lladó` as set.
- **The book's own typos in titles.** Leaf 311 heads its table *Jurados de la c.
  y r. de Mallorca durante el silgo XVI*. `silgo` stays.

---

## Rule 1 — the long s (`ſ`)

**Where.** Leaves 335–367, derived and not listed: a leaf qualifies when both
signals fire — some engine reads `ſ` on more than 3% of its positions, *and* more
than 4% of its words match `[aeiou]ff?[aeioutlrn]` — and the run between the
first and last such leaf is then closed. Leaves 347 and 356 are mostly woodcut
and reach neither threshold on their own.

Both signals are read from the consensus, never from `data/text/`, which is this
rule's own output. Taking one from the assembled text made the detection vanish
the moment the repair had been applied once.

**Why.** Those leaves reproduce a booklet printed in Barcelona in 1541 — *LA
FELICISSIMA VINGUda de Don Carlos cinque Emperador de Romans* — in its own
typography, which uses the long s. Five of the six engines read that letter as
`f`, so the vote returns `cofa`, `moffen`, `eftat`, `boffer` where the page says
`coſa`, `moſſen`, `eſtat`, `boſſer`.

This is a transcription error, not orthography to be preserved: `ſ` and `f` are
different letters, and the page shows the difference plainly. In this face a real
`f` carries a full crossbar; the long s carries only a nub on the left.

**How.** Not by guessing. The distinction cannot be recovered from the text —
16th-century Catalan has `fer`, `fet`, `fos`, `fins`, `foren`, `fonch`, and also
`ser`, `set`, `sos`. A lexicon on its own settles 29% of cases and mangles some
of the rest.

What settles most of it is the panel. Tesseract with `spa_old` reads the long s
correctly — `eſteril`, `coſa`, `moſſen`, `boſſer`, `eſtigueſſen`, `prouiſio` —
and is simply outvoted five to one. So the repair prefers a reading the engines
produced, under a veto:

| outcome | condition | tokens |
|---|---|---|
| repaired, panel | an engine read this token with `ſ`, agreeing with the winner in every other character, and the printed form is **not** a word this book uses elsewhere | 1 292 |
| repaired, attested | no engine did, but the same word was confirmed that way elsewhere on the reprint | 189 |
| ambiguous | an engine read `ſ`, but the printed form is a real word of this book (≥3 attestations outside the reprint). The `f` stands. | 465 |
| untouched | no engine ever read a `ſ` there | 542 |

The veto is not decoration. Checked against the facsimile, leaf 342 prints
`fonch` and leaf 362 `fins` with a full crossbar — real `f`, both real Catalan
words — and Tesseract offers `ſonch` and `ſins` for them anyway. Without the veto
the rule would have corrupted 29 and 18 tokens of perfectly good text.

The reading has to match the winner character for character apart from the
substitution. Without that, the rule accepts an engine's collapse of
`Villafranca,` into `Villaﬁ"ſifﬁca` on the strength of the `ſ` in it.

**What is knowingly left wrong.** `fe` (115), `fa` (93) and `fi` (19) are `ſe`,
`ſa`, `ſi` on the page and are also real words, so the veto leaves them as `f`.
`Cæfar` should be `Cæſar` and no engine read it. These go to the review queue.
Leaving a real reading unrepaired is recoverable; corrupting a real word is not.

**Measured, afterwards.** Round 3 adjudicated 320 positions on the document
leaves against the facsimile, knowing nothing of this rule. Of 200 unanimous
positions the published text is wrong exactly **once** — leaf 358, the Latin
*Vnquam ſi ſe odium Noti remittit*, where all six engines read `fe` — which is
the case named in the paragraph above. The rule's only measured failure is the
one it declared in advance and accepted for a stated reason.

The same round shows what the repair is worth, on tiers it was never tuned
against: unanimous 98.5% → **99.5%**, two-dissent 90.0% → **96.7%**, contested
62.5% → **70.0%**.

**A gap the round found.** Seven of the eleven positions where no engine had the
printed form are long s and are repaired. The other four are not: the Latin
ligatures `prœdo` and `Numidœ` (leaf 351), which every engine renders as `prodo`,
`prcedo`, `Numido`, `Numidce` and so on. No rule addresses them yet, and none
should be written from four examples.

---

## Rule 2 — a word the line break split in two

`calamidades públic as`, `los dive rsos`, `bandole ros:`, `Tarrago. na,`. The
word is one word on the page and two tokens in the transcription. Three
different causes:

| | |
|---|---|
| the panel disagreed | Leaf 107: three engines read `diversos` and five read `dive` + `rsos`, and the vote is slot by slot, so the majority wins. The span re-vote in `spans.py` cannot help — `fold()` strips whitespace, so both readings are the same class to it and neither is longer. |
| the hyphen was misread | Leaf 95 prints `Tarrago-/na,` and the panel offers `Tarrago-`, `Tarrago.`, `Tarrago,` and `Tarrago_` for the same mark. The winner was `Tarrago.`, which the hyphen stitch does not touch. |
| nobody joined it | Leaf 429: all eight engines read `bandole` + `ros:`. There is no reading to recover, only the fact that the book uses `bandoleros` and uses neither half. |

**The book is the dictionary.** `formacion`, `Setiembre` and `mallorquin` are
correct here and wrong in any Spanish word list, and the medieval Catalan of the
documents is in no word list at all, so the lexicon is built from the consensus's
own unanimous winners — 31 168 words — and never from `data/text/`, which is this
rule's output.

Two tiers of evidence, as with the long s, and a veto on each:

| outcome | | tokens |
|---|---|---:|
| repaired, panel | some engine read the joined form, and the left half is not a word the book uses | 6 |
| repaired, attested | none did, but the book uses the joined form five times or more and **neither half** is a word of the book | 5 |
| declined | one of the halves is a word the book uses: 692 occurrences of 180 distinct pairs | — |

**The left half must not be a word.** Requiring it of both halves was tried and
is wrong on both sides at once: it let `de` + `Ntro.` become `deNtro.` and `des`
+ `Portell` become `desPortell`, because the second half of each is rare, while
refusing `Tarrago` + `na`, whose second half is an ordinary Catalan word. A
broken word's *first* half is never a word — `dive`, `bandole`, `Tarrago`,
`capítu` are not — and a common word on the left is overwhelmingly just a word.

**The attested tier needs the stricter veto**, because nothing read it that way.
Leaf 105 gave `despes` + `es` → `despeses`, and read as the Catalan it is, `lo
dit Jordi despès és bestrach del seu propi` is two words. The looser veto
corrupted a good reading; requiring the right half to be a non-word as well
declines it.

Three further guards, each of them a mistake made first:

- **A token ending in a real break hyphen is not this rule's business.** Without
  that exclusion the rule fired **2 481 times on 547 leaves**, rejoining
  `patronato`, `construir` and `necesario` — every ordinary hyphenated line break
  in the book, all of which the assembler already stitches correctly one stage
  later.
- **A clitic is not half a word.** Leaves 123, 149 and 155 are medieval Catalan
  and gave `qu'` + `ell`, `qu'` + `il`, `qu'` + `es`, which fold to `qu` — not a
  word the book uses — and were joined on that technicality.
- **Never leave a dash inside the word just made.** `costea-` + `ron` produced
  `costea-ron`.

The repair is applied as a **span**, not as two substitutions, so the word record
keeps its evidence: the pair reports `printed` as `dive rsos`, its box as the
union of both, and its grade as the worse of the two and never `unanimous` — the
panel was unanimous about two slots, not about the one word this makes.

`audit_entries.py --check glued` still reports **31 pairs the rule declines**,
including `alo dio`, `ciu dad,` and `Pala-. cio`. They go to review rather than
being repaired on a hunch, which is the same place the long s leaves its 465
ambiguous tokens and for the same reason.

---

## The reading form

Separate from the repair, and not a correction: `editorial.reading_form()` folds
`ſ` to `s`, so that a search for `cosa` finds `coſa`. The verbatim text in
`data/text/` keeps the long s. Consumers that index or search apply the fold;
consumers that display the text do not.

---

## Not rules

Two transformations happen in `build_text.py` and are typographic rather than
editorial, but they are recorded here because they do change the string:

- **Line-end hyphens are stitched.** A word broken across two lines is rejoined
  and the hyphen dropped. Only word-break hyphens: em and en dashes are
  structural in this book — they separate entries and introduce the source
  sigla — so joining across one would destroy the chronicle's own punctuation.
- **Running heads are dropped**, by content and not by position. The two scans
  crop their margins differently (the head sits at y≈0.082 on the BNE leaves and
  0.094 on the Internet Archive ones), so no single band separates head from body
  on both, and a band would leave the panel voting on whether `MAYORICENSE.` is
  there at all.

---

## Adding a rule

Put it in `scripts/editorial.py`, document it here with its measured counts, and
make sure `data/text/p####.json` keeps the `printed` form of every word it
touches. If a proposed rule cannot state how many tokens it changes and cannot be
checked against the facsimile, it is not a rule — it is a guess, and this project
already has a queue for those.
