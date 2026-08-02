"""Turn the consensus into the chronicle's own structure: year, date, entry, source.

Campaner wrote a chronicle, so the structure is already in the book and this only
has to recognise it rather than impose one:

    1459.                          <- a centred display line
    Mayo 2.—Real Pragmática de D. Juan II, ordenando que…—G. T.
    —25.—Este dia (víspera de su marcha) «con instrumento…»—B. J.

Year headings are *not* found by geometry. That was tried and measured: real
headings sit anywhere from dead centre of their column to 47% off it, and a
heading at the top of a column occupies the same band as the running head's page
number. What identifies one is that the line says a year and nothing else, that
several of the eight readings agree on which year, and that the year fits a
chronicle which only ever moves forward.

One candidate survives all of that and is still wrong, and it was settled against
the facsimile rather than argued about: leaf 39 really does print `1449.`, and
the entry beneath it reads «año de 1249, perseverando…». Campaner's own error,
and by the rules of this edition it stays on the page.

Footnotes come off before any of this. They carry their own years -- the second
surviving candidate used to be `1336.»` on leaf 74, the tail of the note `…a 13
dias dagost de 1336.»` wrapped onto a line of its own -- and their text is not
chronicle. Each is attached to the entry that prints its number.

Entries are then split on the date markers, and the trailing sigla — `—G. T.`,
`—B. J.`, `—L. V.` — are lifted out as the source attribution, which is what makes
this book worth reading in a database: you can ask which manuscript reports what.

Nothing is corrected here. Where the parse cannot see a structure it says so, and
the anomalies are reported rather than smoothed over.

Usage:
  python scripts/parse_entries.py --consensus consensus6_swap_swapk
  python scripts/parse_entries.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import editorial
import layout
import spans
import targets

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
OUT = PROJECT / "data" / "entries"

FIRST_YEAR, LAST_YEAR = 1229, 1800

# A year heading is a line that says nothing but a year. Geometry was tried first
# and does not work: real headings sit anywhere from the exact centre of their
# column to 47% off it, and the running head's page number occupies the same band
# (y 0.080-0.099) as a heading at the top of a column (0.088-0.123). What does
# separate them is the *text* and the *panel*, which is what the rest of this
# pipeline runs on anyway.
#
# Digits the engines habitually return as letters. Restoring them is not guessing:
# the reading is only accepted when the panel independently supports the year.
DIGIT_LOOKALIKE = str.maketrans({"I": "1", "l": "1", "i": "1", "|": "1", "/": "1",
                                 "J": "1", "Í": "1", "¡": "1", "!": "1",
                                 "O": "0", "o": "0", "S": "5", "T": "7"})
# `T` for `7` is the newest of these and was measured before being added, the
# way `S` for `5` should have been: over all 614 leaves it changes the panel's
# verdict on exactly **two** lines. One is the fix -- leaf 634's heading, whose
# winner collapsed to `1` while three engines read `1751.`, `I75I.` and `ITSI.`
# -- and the other is a single stray vote on `Pedro Vidal.` which never comes
# near the three the rule requires. A lookalike table is only admissible while
# it can show it opens no door but the one it was written for.
# Punctuation the printer or the engines hang off a heading: `1282.»`, `1337-`,
# `1353•`, `i 501 .`.
HEADING_NOISE = re.compile(r"[\s.,;:\-—‐–_•*'’‘\"«»()\[\]ºª]")
YEAR_IN = re.compile(r"\d{4}")
# How many of the eight readings must contain the year before it counts. One
# engine hallucinating digits inside a sigla (`G. T.` -> 1232) is common; three
# agreeing on the same four digits, on a line that says nothing else, is not.
MIN_YEAR_VOTES = 3
# The century banners, in both forms the book uses: `SIGLO XIV.` and
# `DE 1301 Á 1400.`. The second one states two years and would otherwise be read
# as a heading for the first of them.
CENTURY_LINE = re.compile(r"^\s*(SIGLO\s+[IVXLC]+|DE\s+1[2-8]\d\d\s*[ÁA]\s*1[2-8]\d\d)",
                          re.IGNORECASE)

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

# How an entry actually opens, read off the text rather than assumed. The date
# comes *before* the em dash, not after it:
#
#   —B. J. JUNIO.—Por Bula dada en Roma…        month, no day
#   —G. T. JULIO 21.—Llegó la noticia…          month and day
#   —B. J. —20.—Murió el Obispo…                day alone, month carried over
#   —G. T. —Este año, sin indicarse la fecha…   no date at all
#
# An earlier version required the dash before the month and matched almost
# nothing: 16% of entries came out dated where it should be most of them.
# `—20.—` was wrong about the punctuation and cost 410 splits. The form the
# book actually prints is `—20—`, with no full stop, and the one this pattern
# required occurs **zero** times in 2 499 entries: every bare-day marker in the
# chronicle was being swallowed into the entry above it. The period is optional
# now, and a range (`—28 y 29—`, 4 of them) takes the first day.
#
# `—El 24 se publicó un edicto…` is Campaner's other way of opening a day, 153
# of them, and was not a marker at all. A digit is required after `El` so that
# `—El Marqués de Rubí` and `—El mismo dia` stay where they belong.
# The em dash comes back as `--` from some engines on some leaves -- 11
# markers -- and a day can be a range Campaner writes two ways, `17 al 21` and
# `28 y 29`, 27 of them. Neither was accepted and each one cost a split.
DASH = r"(?:—|--)"
# `Marzo 20, 21 y 22.—` and `FEBRERO 14, 15 y 16.—`: the book lists the days of
# a three-day feast, and the entry takes the first.
RANGE = r"(?:\s*,\s*\d{1,2})*(?:\s*(?:y|al|á)\s*\d{1,2})?"
# The day of a month heading is display type, and the engines read it as
# letters: `ENERO IS.`, `ABRIL II.`, `Mayo II.`, `Marzo i i.`, `ENERO i.°`.
# Same glyph confusion `DIGIT_LOOKALIKE` already resolves for the years, and
# admissible for the same reason: it is only accepted where a month name stands
# immediately before it and a dash immediately after, so there is no doubt that
# a heading is what is being read. `1.°` is how the book writes the first of the
# month.
DAY_GLYPH = r"[0-9IilJ|/SO]"
DAY_TOKEN = rf"(?:\d{{1,2}}|{DAY_GLYPH}\s?{DAY_GLYPH}?)"
ENTRY_START = re.compile(
    rf"(?:"
    rf"(?<![a-záéíóúñA-ZÁÉÍÓÚÑ])(?P<month>{MONTH_ALT})\s*(?P<day1>{DAY_TOKEN})?"
    rf"{RANGE}\s*[.,]?\s*[°ºo]?\s*[.,]?\s*{DASH}"
    rf"|{DASH}\s*(?P<day2>\d{{1,2}}){RANGE}\s*[.,]?\s*{DASH}"
    rf"|—\s*El\s+(?P<day3>\d{{1,2}})\s*,?\s+(?=[a-záéíóúñ])"
    rf"|—\s*En\s+(?P<day5>\d{{1,2}})\s+de\s+(?P<month2>{MONTH_ALT})\b"
    # `Este año` was the assumed form and matches nothing at all: what Campaner
    # writes is `—En este año se sufrió una peste…`, 59 times. The `En` is
    # optional so both spellings pass, and the phrase itself stays in the entry
    # -- it is the text, not a label.
    rf"|—\s*(?=(?:En\s+)?Este\s+(?:año|mes|dia|día))"
    # `…no produjo ningun resultado.—J. V. —El mismo día se recibieron cartas
    # de Don Fr. Tomás de Rocamora…` is two notices of the same day, 60 of them,
    # and nothing but the phrase says so. The date carries over untouched --
    # the book itself says it is the same day -- and the phrase stays in the
    # text, because it is what Campaner wrote and not a label.
    rf"|—\s*(?=E(?:l|ste)\s+mismo\s+(?:d[ií]a|mes))"
    rf")",
    re.IGNORECASE)

# The mangled months are matched *separately*, and that is not a stylistic
# choice. Folded into the alternation above, this pattern matches any word
# before a dash -- which is most sentence ends in the book -- and `re` consumes
# what it matches even when the result is later discarded. `…de la isla.—El 24
# se publicó…` matched as `isla.—`, ate the dash that `—El 24` needed, and 140
# genuine splits disappeared. Two passes, merged by position, cannot interfere.
NEAR_MONTH = re.compile(
    r"(?<![a-záéíóúñA-ZÁÉÍÓÚÑ])(?P<near>[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,11})"
    rf"\s*(?P<day4>{DAY_TOKEN})?\s*[.,]?\s*[°ºo]?\s*\.?\s*—")

# `—El 14 de Julio otro pregon…` states its own month, and taking the month
# carried forward instead would date it to whatever month was running.
# February gets 29: this is a chronicle of leap years too, and the check is for
# the impossible rather than for the calendar.
DAYS_IN = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
           7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

SAME_DAY = re.compile(r"E(?:l|ste)\s+mismo\s+d[ií]a", re.IGNORECASE)

MONTH_AFTER_DAY = re.compile(rf"^\s*de\s+(?P<month>{MONTH_ALT})\b", re.IGNORECASE)

# A month name after one of these belongs to the sentence running into it, not
# to a heading: `…desde el 25 de Abril hasta el 7 de Julio.—Sucedió que…` opens
# a new notice at the dash, and `Julio` is the last word of the old one. Taking
# it as the marker ate the word and left 59 entries ending on a dangling
# preposition, `…llegaron á Mallorca en 3 de`. A real heading follows a full
# stop or a siglum, never a preposition.
FUNCTION_WORD = re.compile(
    r"(?:^|\s)(?:de|del|en|á|a|hasta|desde|para|entre|sobre|y|e|ó|o)\s+$",
    re.IGNORECASE)


def edit_distance_1(a: str, b: str) -> bool:
    """True if one substitution, insertion or deletion turns `a` into `b`."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long)):
        if long[:i] + long[i + 1:] == short:
            return True
    return short == long[:-1]


def near_month(token: str, day: str | None, before: str = "") -> int | None:
    """The month a mangled heading was printing, or None.

    `Mavo 9.—` is `Mayo`, misread 38 times; `Juxio`, `Manzo`, `DICIEMBEE`,
    `FNERO` and eighteen more are the same accident on display type, which is
    the class the engines read worst. Recovering the month is a *parsing*
    decision and changes nothing in the text -- the entry still prints `Mavo`,
    exactly as the book's scan gives it. Only the date deduced from that
    position is recovered, which is what the year headings already do.

    Being one letter from a month name is not enough on its own: `Raimundo
    Lulio.—`, `el Alcalde Mayor.—` and `fondos de dicho género.—` are ordinary
    words ending a sentence, one edit from `Julio`, `Mayo` and `Enero`. What
    separates them is position, and there are two ways to be in one:

    * a day number follows -- `Mavo 9.—`. Of 71 near-miss tokens the 58 with a
      day are all genuine, and none of the false positives has one.
    * nothing follows, but a full stop or a dash comes *before* it, so the token
      opens rather than closes a sentence: `…el dia 27.—G. F. Mavo.—A
      principios de este mes…`. The three false positives are all mid-phrase --
      `Raimundo Lulio`, `Alcalde Mayor`, `dicho género` -- and fail it. So does
      `—Fr. ABRIL y Mavo`, which is prose naming two months and not a heading
      at all.
    """
    folded = strip_accents(token).lower()
    if not day:
        tail = before.rstrip()
        if not (tail[-1:] in (".", "—") and token[:1].isupper()):
            return None
    if folded in MONTHS:
        return MONTHS[folded]
    for name, number in MONTHS.items():
        if edit_distance_1(folded, name):
            return number
    # Two wrong letters, and only where a day follows. `Acosro 3.—` is August
    # on leaf 430 and `Agosto` sits in the slot before it, on the previous
    # line, so neither the doubling check nor a one-letter distance reaches it.
    # The licence comes from this function's own measurement quoted above: of
    # the 71 near-miss tokens, the 58 that are followed by a day are genuine
    # without exception, so position is doing the work and the distance is only
    # naming which month.
    if day:
        for name, number in MONTHS.items():
            if (len(folded) == len(name)
                    and sum(x != y for x, y in zip(folded, name)) == 2):
                return number
    return None

# A year heading the layout missed and left inline, sitting immediately before a
# date marker: `—B. J. 1459. Mayo 2.—`. Anchored to the end of the run so that a
# year mentioned in passing ("la donacion de 1058. Sin embargo…") cannot be
# mistaken for a heading -- only one that directly precedes a date counts.
INLINE_YEAR = re.compile(r"(?<!\d)(1[2-8]\d\d)\s*[.,\-—]\s*$")

# Sigla trailing an entry: —G. T. / —B. J. / —L. V. / —Jn. Br. / —T. A.
#
# This used to be a *shape* -- a dash, then one to three capital-and-full-stop
# groups -- and the shape is wrong twice over. It insists on an em dash, when
# the engines read the book's em dash as `-` about as often (`»-J. V.`), and it
# takes only one siglum, when Campaner routinely credits two or three
# (`—J. V.-J. P.—CI. Fl.`). 205 entries book-wide kept their attribution stuck
# in the prose because of it.
#
# What a source attribution actually is: one of the sigla Campaner declares in
# his introduction. So the glossary does the work here too, and the shape only
# says where to look -- at the end, after a dash.
#
# Excluded from the list: `ds.`, `ls.`, `ss.` and `MS. y MSS.` are in the
# glossary but abbreviate dineros, libras and sueldos. An entry ending `…y 30
# ls.` is a sum of money, not an attribution.
NOT_A_SOURCE = {"ds.", "ls.", "ss.", "MS. y MSS."}
# Sources Campaner cites but forgot to gloss, named in his own text: Luis de
# Villafranca (49 attributions), `N. F.` (34) and `T. A.` (28). Deliberately
# *not* the single letters the counts also throw up -- `J.`, `T.`, `M.`, `G.` --
# which are two-part sigla the alignment truncated, and admitting them would
# match the last initial of any name at the foot of an entry.
UNGLOSSED = ("L. V.", "N. F.", "T. A.", "Jn. Bs.",
             # Two-part sigla the alignment truncated to their first initial.
             # They are recorded as printed rather than guessed at: `—J.` at
             # the foot of a notice on leaf 430 is a source whose second
             # initial no engine placed, and calling it prose leaves visible
             # rubbish at the end of the entry. Admissible only because the
             # tail has to be dashes and sigla all the way to the end, so an
             # ordinary sentence cannot end in one.
             "J.", "T.", "M.", "G.", "Fl.", "Br.")
# Glyphs this typeface's engines swap freely. Folding them lets `CI. Fl.` and
# `/. V.` be recognised as `Cl. Fl.` and `J. V.` -- an identification of which
# manuscript is being credited, not a rewrite: the transcription keeps whatever
# was printed, and only the `sources` index gets the canonical form.
SIGLUM_GLYPH = str.maketrans({"l": "I", "1": "I", "|": "I", "/": "J", ",": "."})


def fold_siglum(text: str) -> str:
    return re.sub(r"\s+", "", text).translate(SIGLUM_GLYPH).upper()


# A footnote opens with its own number on a fresh line: `(1)`, `(2)`, `[3]`.
# `(1)`, and once `(1.)` -- leaf 429, where missing it cost more than a note:
# the line above ends `…y el 24 falle-`, so the hyphen stitch joined the word to
# the note instead of to its own tail at the top of the next column, and the
# entry read `el 24 falle(1.) «A hora de vespres…» ció.`
NOTE_START = re.compile(r"^\s*[\(\[]\s*(\d{1,2})\s*[.,]?\s*[\)\]]")
# The call in the text is a superscript `(1)` two characters wide, which is the
# smallest thing on the leaf and the likeliest to be misread: seven of the notes
# nothing calls are called by `(I)`. Accepting the letter shapes of 1 is safe
# because the match still has to find a note of that number *in that column* --
# a stray `(I)` with no note behind it resolves to nothing and prints nothing.
NOTE_REF = re.compile(r"[\(\[]\s*([0-9IiLl|]{1,2})\s*[\)\]]")
ONE = {"I", "i", "L", "l", "|"}


def ref_number(text: str) -> int | None:
    digits = "".join("1" if c in ONE else c for c in text)
    return int(digits) if digits.isdigit() else None
# and never in the upper half of the leaf. The same `(1)` appears inside an entry
# as the reference to it, mid-sentence, and that one is not a note.
NOTE_BAND = 0.55
# A column break: y jumps back towards the head of the leaf.
COLUMN_BREAK = 0.2


def known_documents(path: Path | None) -> set[int]:
    """Leaves inside a numbered document section, as parse_documents delimited them.

    The Jurats lists are excluded: they open every block as section `I`, have
    their own parser, and `is_table_leaf` already sets them aside here.
    """
    if path is None or not path.exists():
        return set()
    pages: set[int] = set()
    for block in json.loads(path.read_text()):
        for section in block["sections"]:
            if section.get("jurats"):
                continue
            pages.update(range(section["pdf_page"],
                               section.get("until", section["pdf_page"]) + 1))
    return pages


# A document printed in full does not look like a chronicle entry -- it runs ten
# times longer, states no month, names no manuscript source and is the only
# "entry" on its leaf. That is all true of the averages and **useless as a test**,
# which was measured rather than assumed:
#
#   >=300 words, no month, no siglum      inside a document  81   elsewhere 123
#   the same, and the sole entry on its leaf                 80   elsewhere  66
#
# There are more of them outside the documents than inside, at every threshold.
# Leaves 253-280 are twenty-eight leaves of continuous Germanía narrative with no
# year heading between 1520 and 1525, and they are chronicle; by shape they are
# indistinguishable from the letters of Gilaberto de Centellas. So the separation
# cannot come from what an entry looks like. It comes from Campaner's own
# numbering, via parse_documents.py, and the check below is that the two files
# agree rather than that the text has a particular shape.


def banded_notes(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate a leaf's footnotes from its body, by where they sit.

    A note runs from its own number to the foot of the column it is in, so the
    rule follows the reading order rather than the geometry: once a note has
    opened, every following line belongs to it until y jumps back towards the
    top of the leaf, which is the next column beginning.

    The band is what keeps a reference `(1)` that happens to fall at the start
    of a line from opening a note. It also means a leaf whose apparatus is deep
    -- and some carry more note than text -- has its notes read as chronicle:
    that is what `small_type_notes` is for, and the two are unioned.
    """
    body: list[dict] = []
    notes: list[dict] = []
    in_note = False
    previous = 0.0
    for line in lines:
        top = line["bbox"][1]
        if in_note and top < previous - COLUMN_BREAK:
            in_note = False
        if not in_note and top > NOTE_BAND and NOTE_START.match(line["text"]):
            in_note = True
        (notes if in_note else body).append(line)
        previous = top
    return body, notes


# A leaf opens in body type. Always: a note sits at the foot of its column, so
# the first lines of the first column cannot be apparatus.
OPENING_LINES = 8
# …and how much smaller the note type has to be before this is worth trying.
# Both sizes are measured on the leaf itself, never fixed for the book: the
# earlier attempt compared them globally -- 0.0097 against 0.0127 -- and the
# distributions overlap because the leaves differ.
NOTE_TYPE = 0.90
# A continuation is at least this many lines. Leaf 92 ends `desembar-` / `có en
# las riberas de Morviedro.»-G. T.`, and one short last line is not a note.
MIN_CONTINUATION = 2
# `1339.` alone on a line is a year heading, and a four-digit line has no
# ascender or descender in it, so its box measures like note type and the scan
# walked straight through it. Leaves 74 and 547 lost their year that way.
BARE_YEAR = re.compile(r"^\s*1[2-8]\d\d\s*[.,]?\s*$")


def height(line: dict) -> float:
    return line["bbox"][3] - line["bbox"][1]


def small_type_notes(lines: list[dict]) -> list[dict]:
    """Notes that open above the band, recognised by the size of their type.

    The band is a good rule that fails on one kind of leaf: where the apparatus
    is so deep that it starts in the upper half. Leaf 86 is eleven lines of
    chronicle and 122 of a quoted letter, opening at y 0.28; leaf 92's list of
    subscribers to the armada opens at 0.15. Those notes were read as chronicle.

    So the opening is found by type instead of by position, and then the
    existing rule takes over: a note runs to the foot of its column. **The
    threshold is calibrated on the leaf itself**, between the height of its
    opening lines -- body by construction, since a note sits at the foot of a
    column -- and the height of whatever notes the band already found, which are
    apparatus by construction. Comparing the two sizes across the book does not
    work and was tried: 0.0097 against 0.0127, and they overlap.

    Two things had to be got wrong first:

    - **A single line's height means very little.** Leaf 66's note opens `(1) El
      pavorde Terrassa se equivoca lastimosamen-` at 0.0147 with 0.0177 under
      it, both wrong for note type. An opening counts if it *or the line under
      it* is small.
    - **A line that is nothing but `(2)` is not a note opening.** It is a
      reference the alignment stranded, and its box is small for the obvious
      reason: it is two characters. One of them opened an apparatus on leaf 93
      that swallowed the rest of the column.

    Scanning up from the foot of a column for a note continuing from the one
    before was tried and dropped. It reads well -- leaf 105's note really does
    come back at the foot of the second column with no number to announce it --
    and it cost year headings on leaves 74, 547 and 1289, because `1339.` alone
    on a line has no ascender or descender and measures like note type.
    Recovering nine lines of apparatus is not worth losing a year of the
    chronicle, and the loss is silent while the gain is not.
    """
    live = [line for line in lines if line["text"]]
    banded = [line for line in banded_notes(lines)[1] if line["text"]]
    if len(live) < OPENING_LINES:
        return []
    body_type = statistics.median(height(line) for line in live[:OPENING_LINES])
    if len(banded) >= 3:
        note_type = statistics.median(height(line) for line in banded)
        if note_type >= NOTE_TYPE * body_type:
            return []           # this leaf does not set its notes smaller
        cut = (body_type + note_type) / 2
    else:
        # The leaves that need this most are the ones that cannot calibrate:
        # leaf 86 is eleven lines of chronicle and 122 of a quoted letter, and
        # the band sees two of the 122. With no sample of the note type to
        # measure, the body type alone has to carry it.
        cut = NOTE_TYPE * body_type

    columns: list[list[dict]] = []
    seen: list[int] = []
    for line in lines:
        if not seen or line["column"] != seen[-1]:
            seen.append(line["column"])
            columns.append([])
        columns[-1].append(line)

    notes: list[dict] = []
    for group in columns:
        for n, line in enumerate(group):
            match = NOTE_START.match(line["text"])
            if not match or len(line["text"][match.end():].strip()) < 4:
                continue
            if (height(line) < cut
                    or (n + 1 < len(group) and height(group[n + 1]) < cut)):
                notes += group[n:]
                break
    return notes


def split_notes(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """A leaf's body and its footnotes.

    The union of the two rules, and the union is the point: the band knows
    where notes usually sit and the type test knows what they look like, and
    each finds apparatus the other cannot. Adding the second recovered **829
    lines on 40 leaves** -- leaf 86 is eleven lines of chronicle and 122 of a
    quoted letter, and all 122 were being published as chronicle.
    """
    _body, banded = banded_notes(lines)
    keep = {id(line) for line in banded} | {
        id(line) for line in small_type_notes(lines)}
    return ([line for line in lines if id(line) not in keep],
            [line for line in lines if id(line) in keep])


def gather_notes(notes: list[dict]) -> list[dict]:
    """The note lines joined into one record per number.

    The number is only unique within its **column**: leaf 74 prints `(1)` and
    `(2)` at the foot of the left column and `(1)` and `(2)` again at the foot
    of the right, and so do a dozen other leaves. Keeping the column is what
    stops a notice in the second column being given the first column's note --
    which is not a missing note but a wrong one, and worse.
    """
    out: list[dict] = []
    for line in notes:
        match = NOTE_START.match(line["text"])
        if match:
            out.append({"number": int(match.group(1)),
                        "column": line.get("column", 0),
                        "leaf": line.get("leaf"),
                        "text": line["text"][match.end():].strip()})
        elif out:
            text = out[-1]["text"]
            out[-1]["text"] = (text[:-1] + line["text"] if text.endswith("-")
                               else (text + " " + line["text"]).strip())
    return out


CENTURY_NUMERAL = re.compile(r"SIGLO\s+([IVXLC]+)", re.IGNORECASE)
CENTURY_RANGE = re.compile(r"(1[2-8]\d\d)\s*[ÁA]\s*(1[2-8]\d\d)", re.IGNORECASE)


def century_openings(leaves: dict[int, list[dict]], accepted: dict,
                     body_pages: list[int]
                     ) -> tuple[list[dict], set[tuple[int, int]]]:
    """The six century openings: the banner and Campaner's list of sources.

    Each century starts `SIGLO XIV. / DE 1301 Á 1400.` and then names, in one
    long parenthesis, every manuscript that reports the hundred years to come --
    `Anales etc. por Terrassa.—Notas sacadas de los libros de la Procuracion
    Real, por D. B. Jaume.—Historia etc. por Binimelis…`. It is the closest
    thing the book has to a bibliography, and it is not a chronicle entry.

    It was being read as one. `CENTURY_LINE` skipped the banner and let the
    source list fall through to the buffer, where it became a notice of the year
    the buffer was carrying -- the *previous* century's last, so the list of the
    sources of the 14th century was published as news of 1300, and the 15th's as
    news of 1400. On leaf 28 it became an entry with no year at all, which no
    page of the site can show; leaf 506's belongs to a leaf the document parser
    had already claimed, so it was lost outright.

    The banner and the list are set **across the measure**, and that is what
    bounds them: the block runs while its lines either fill the full width or
    stand centred on it, and stops at the first line that begins a column. The
    year heading cannot be used for this. On leaf 64 the column finder fails and
    the two columns interleave line by line, so the first heading it accepts is
    `1302.` sixteen lines down -- and bounding on it swallowed a real notice of
    March 1301 into the front matter.

    What follows the list is left to the chronicle, including Terrassa's
    headnote on leaf 28 -- the tithes of Urban II, which dates itself to no
    year. Taking it as a preface of the century was tried and abandoned: the
    only test that admitted it was "no dated notice in the block", and when leaf
    64's columns were repaired that test swallowed the whole of 1301, which
    states no month either. One example is not enough to write a rule from, and
    the headnote loses nothing by standing where the book prints it, under the
    century's opening and above the first notice.

    Read from `body_pages` rather than from the chronicle, because leaf 506 sits
    inside the eighteenth century's appendix block and would otherwise be
    invisible here too.
    """
    def across(lines: list[dict], n: int) -> bool:
        left = min(line["bbox"][0] for line in lines)
        right = max(line["bbox"][2] for line in lines)
        box = lines[n]["bbox"]
        return layout.across_measure(
            layout.Line(text="", x0=box[0], y0=box[1], x1=box[2], y1=box[3]),
            left, right)

    records: list[dict] = []
    skip: set[tuple[int, int]] = set()
    for pdf_page in body_pages:
        lines = leaves[pdf_page]
        opening = next((n for n, line in enumerate(lines[:4])
                        if CENTURY_LINE.match(line["text"])), None)
        if opening is None:
            continue
        end = opening
        while end < len(lines) and across(lines, end):
            end += 1
        block = [line for line in lines[opening:end] if line["text"]]
        if not block:
            continue
        skip |= {(pdf_page, n) for n in range(opening, end)}

        # …and onto the next leaf, if the list filled this one. Five of the six
        # openings fit on their leaf and the eighteenth's does not: leaf 506
        # ends mid-sentence in the middle of Amorós and four more full-measure
        # lines run across the head of 507 before `1701.`. The audit found it by
        # the notice that opened `va. (i)— Noticias y relaciones anónimas…`.
        after = next((p for p in body_pages if p > pdf_page), None)
        if end == len(lines) and after is not None and after in leaves:
            spill = leaves[after]
            over = 0
            while over < len(spill) and across(spill, over):
                over += 1
            if over:
                block += [line for line in spill[:over] if line["text"]]
                skip |= {(after, n) for n in range(over)}

        banner = " ".join(line["text"] for line in block[:2])
        numeral = CENTURY_NUMERAL.search(banner)
        span = CENTURY_RANGE.search(banner)
        # The banner is one line or two depending on where it broke -- leaf 246
        # prints `SIGLO XVI. DE` and then `1501 Á 1600.` -- so the source list
        # is whatever follows the lines the banner used.
        used = 1 if CENTURY_RANGE.search(block[0]["text"]) else 2
        records.append({
            "pdf_page": pdf_page,
            "numeral": numeral.group(1).upper() if numeral else None,
            "from_year": int(span.group(1)) if span else None,
            "to_year": int(span.group(2)) if span else None,
            "banner": banner.strip(),
            "text": stitch_lines(block[used:]),
        })
    return records, skip



def stitch_lines(lines: list[dict]) -> str:
    """Line texts joined with the book's word-break hyphens closed up."""
    text = ""
    for line in lines:
        text = (text[:-1] + line["text"] if text.endswith("-")
                else (text + " " + line["text"]).strip())
    return text


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def page_lines(path: Path) -> list[dict]:
    """Lines with text, box, column and the worst certainty tier they contain.

    The text is assembled by `spans.layout`, the same call `build_text.py`
    publishes with, so the notices are cut out of exactly the prose the edition
    shows. Joining the winners here independently is what let the two drift:
    the entries kept `Te-Deum Te-Deum` and lost `—30.—Mataron` for as long as
    the published text had been repaired of both.

    `row` therefore holds the assembled *groups*, not raw loci, and each carries
    the loci it covers so `month_votes` can still ask the whole panel.
    """
    leaf = json.loads(path.read_text())
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for locus in layout.join_leaders(
            layout.drop_folio(layout.drop_signature(leaf["loci"]))):
        key = tuple(locus["line_bbox"])
        if key not in grouped:
            order.append(key)
        grouped[key].append(locus)

    rank = {"unanimous": 0, "one-dissent": 1, "two-dissent": 2, "contested": 3,
            "adjudicated": 0}
    # Assemble every line first, then run the doubling check over the leaf as a
    # whole -- the same order `build_text.py` uses, and necessary because a
    # doubled display heading straddles the line break as often as not.
    joins = editorial.joins_for(path.parent)
    per_line = {key: spans.layout(layout.line_order(grouped[key]),
                                  leaf["panel"], [None] * len(grouped[key]),
                                  None, joins)
                for key in order}
    spans.months(spans.dedupe([g for key in order for g in per_line[key]],
                              leaf["panel"]), leaf["panel"])

    # Which column each line is in, by the same clustering the whole project
    # reads leaves with. Only the footnotes need it -- their numbering restarts
    # at the head of every column -- but it is a property of the line, so it is
    # attached here rather than recomputed by whoever wants it.
    lefts = layout.find_columns([layout.Line(text="", x0=key[0], y0=key[1],
                                             x1=key[2], y1=key[3])
                                 for key in order])

    def column_of(key) -> int:
        return max((n for n, left in enumerate(lefts)
                    if key[0] >= left - layout.COLUMN_EDGE_TOLERANCE),
                   default=0)

    lines = []
    for key in order:
        groups = per_line[key]
        # Every reading, not just the panel's six. `heading_votes` counts a
        # year across all eight -- the two engines outside the panel are what
        # carry leaf 101's `1383.`, which the winner lost -- so restricting
        # this to the panel silently cost year headings.
        engines = {e for g in groups for x in g["loci"] for e in x["variants"]}
        parts = [{"winner": g["text"], "grade": g["grade"],
                  "loci": g["loci"],
                  "variants": {engine: spans.joined(g["loci"], engine)
                               for engine in engines}}
                 for g in groups if g["text"]]
        lines.append({
            "text": " ".join(p["winner"] for p in parts).strip(),
            "bbox": list(key),
            "column": column_of(key),
            "row": parts,
            "worst_tier": max((p["grade"] for p in parts),
                              key=lambda g: rank[g], default="unanimous"),
            "tiers": Counter(p["grade"] for p in parts),
        })
    return lines


# A Jurats table announces itself: numbered names one per line (`3.—Bernardo de
# Font.`) and year labels written out (`AÑO 1332.`), on leaves whose lines are
# half the length of prose.
NUMBERED_NAME = re.compile(r"^\s*[1-6IJl]\s*[.,]\s*[—\-]")
YEAR_LABEL = re.compile(r"^\s*(A[ÑN]O|ANO)[ .]*1[2-8]")


def is_table_leaf(lines: list[dict], columns: int) -> bool:
    """Whether this leaf is a Jurats name list rather than chronicle.

    `inventory.py` finds the tables that print in three or more columns, and
    misses the ones typeset as two: leaves 58-60 (13th century) and 114-121
    (14th, headed `APÉNDICES. I.`) are name lists that read as two columns and
    slipped through. Their year labels run 1302, 1303, 1304 down the page and
    dragged the chronology back a century every time the parser met one.
    """
    if columns >= 3:
        return True
    body = [ln["text"] for ln in lines if ln["text"].strip()]
    if not body:
        return False
    numbered = sum(1 for t in body if NUMBERED_NAME.match(t))
    labels = sum(1 for t in body if YEAR_LABEL.match(t))
    return numbered / len(body) >= 0.15 or labels >= 2


def fill_table_runs(tables: set[int], body: list[int]) -> set[int]:
    """Close single-leaf gaps inside a table run.

    Leaf 117 sits in the middle of the 114-121 list but carries so much
    explanatory note-text that it reads as prose. A leaf with a table on either
    side of it is part of the table.
    """
    index = {page: n for n, page in enumerate(body)}
    filled = set(tables)
    for page in tables:
        n = index.get(page)
        if n is None or n + 2 >= len(body):
            continue
        if body[n + 2] in tables:
            filled.add(body[n + 1])
    return filled


def spillover(candidates: list[dict], accepted: dict, body: list[int],
              aside: set[int]) -> set[int]:
    """Leaves where a table or an excursus runs on past the end of its leaf.

    The Jurats lists do not stop neatly: leaf 229 opens with `1498. 1499.` and
    the last dozen names of the table on 225-228, and leaf 482 does the same for
    the table on 478-481. That stray `1500.` is monotone, so the chronology
    accepts it, and having accepted it the chronicle cannot then climb back to
    the 1487 that really does begin on leaf 242.

    A leaf directly after material already set aside, every year on which the
    chronicle has already passed, is the tail of that material.
    """
    years: dict[int, list[int]] = defaultdict(list)
    for c in candidates:
        years[c["page"]].append(c["year"])
    reached: dict[int, int] = {}
    high = 0
    for page in body:
        reached[page] = high
        if page in aside:
            continue
        for (p, _pos), c in accepted.items():
            if p == page:
                high = max(high, c["year"])

    out: set[int] = set()
    for n, page in enumerate(body):
        if n == 0 or page in aside or page not in years:
            continue
        if body[n - 1] in aside | out and max(years[page]) <= reached[page]:
            out.add(page)
    return out


def says_only_a_number(text: str) -> bool:
    """True if the line carries digits and nothing else.

    This is what keeps sums of money and dates in prose out: `1,259 carros`,
    `1700 lbs.`, `hasta 1343.`, `Any 1522`, `á 1558.)` all read as years to a
    naive scan and all still have letters in them. A display heading does not.

    Up to eight digits, because a heading is sometimes recognised twice over --
    `1507. I507.`, `1576. . IS76.` -- and the vote then settles which it is.
    """
    stripped = HEADING_NOISE.sub("", text).translate(DIGIT_LOOKALIKE)
    return bool(stripped) and stripped.isdigit() and len(stripped) <= 8


# A heading and the first words of its entry, caught in one line box.
GLUED_HEADING = re.compile(r"^\s*([\dIilJ|/Í¡!Oo]{3,6})\s*[.,\-—:]\s*(\S.*)$")


def glued_entry(line: dict) -> str | None:
    """The entry text a display heading is stuck to, if it is stuck to one.

    The commonest way a year goes missing is not a misread digit: it is the line
    finder taking `1460.` and `Marzo 3.—Se pregonó…` for one line. Sixteen
    readings agree the year is there and every rule above still throws it away
    because the line has letters in it.

    Telling that apart from a year inside prose (`1700 lbs.`, `de 1721.»`) needs
    to know that what follows the year opens an entry: an opening quote, or a
    month. The month is read off the panel rather than the winner, because the
    winner is exactly what tends to be damaged here -- leaf 595 prints `Febrero`
    and the consensus returned `Fbbrbro`, while three engines read it plainly.
    """
    match = GLUED_HEADING.match(line["text"])
    if not match:
        return None
    rest = match.group(2)
    if rest.startswith("«"):
        return rest
    for word in line["row"][1:]:
        for reading in list(word["variants"].values()) + [word["winner"]]:
            plain = strip_accents(re.sub(r"[^\w]", "", reading or "")).lower()
            if plain in MONTHS:
                return rest
    return None


def years_in(text: str) -> set[int]:
    """Every in-range year these characters could be stating."""
    digits = HEADING_NOISE.sub("", text or "").translate(DIGIT_LOOKALIKE)
    return {int(m.group()) for m in YEAR_IN.finditer(digits)
            if FIRST_YEAR <= int(m.group()) <= LAST_YEAR}


def heading_votes(row: list[dict]) -> Counter:
    """What year, if any, the panel says this line states -- and how loudly.

    The consensus winner is often the *worst* reading of a year heading, because
    a line of five characters gives the vote almost nothing to work with:
    `I3II.` won a three-way tie on leaf 66 while PaddleOCR had plainly read
    `1311.`. Counting the year across all eight readings recovers it from
    evidence rather than from a character-substitution guess.
    """
    votes: Counter = Counter()
    for word in row:
        readings = list(word["variants"].values()) + [word["winner"]]
        for reading in readings:
            for year in years_in(reading):
                votes[year] += 1
    return votes


def year_of_line(line: dict) -> tuple[int | None, int, str]:
    """The year a line announces, the readings backing it, and any entry text."""
    text = line["text"]
    # A heading five characters wide gives the vote almost nothing to work with,
    # and the winner regularly collapses to a single character -- `1`, `I`, `r.`,
    # `M.` -- while most of the panel read the year plainly. When the whole line
    # is one short token, what the panel says outweighs what the vote returned.
    if says_only_a_number(text) or (len(line["row"]) == 1 and len(text) <= 6):
        remainder = ""
    elif len(text) > 14:
        return None, 0, ""
    else:
        remainder = glued_entry(line)
        if remainder is None:
            return None, 0, ""
    votes = heading_votes(line["row"])
    if not votes:
        return None, 0, ""
    year, count = votes.most_common(1)[0]
    if count < MIN_YEAR_VOTES:
        return None, count, ""
    return year, count, remainder


def monotone_subsequence(years: list[int]) -> list[int]:
    """Indices of the longest non-decreasing run through the candidates.

    The chronicle only moves forward, so a heading that goes backwards is a
    misreading -- of itself or of the one before it. Rather than trusting
    whichever came first, keep the largest set of headings that can all be true
    together and report the rest. This is what caught `1249.` on leaf 39 being
    read as `1449.`: one candidate contradicted forty of its neighbours.
    """
    if not years:
        return []
    best = [1] * len(years)
    prev = [-1] * len(years)
    for i in range(len(years)):
        for j in range(i):
            if years[j] <= years[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end = max(range(len(years)), key=lambda i: best[i])
    out = []
    while end != -1:
        out.append(end)
        end = prev[end]
    return out[::-1]


EDITS = OUT / "edits.jsonl"
ANCHOR = 48

SIGLA_FILE = PROJECT / "data" / "sigla" / "sigla.json"
# Prose after the closing siglum, long enough to be a notice rather than a
# second siglum or a stray fragment.
# The dash the book puts between the attribution and the next notice --
# `…hubo 7000 bajas entre muertos y prisioneros.—J. V. —Llegó la noticia de
# que Lorenzo Bareno…` is two notices, and requiring the prose to follow the
# siglum across nothing but whitespace missed 103 of them.
SIGLUM_TAIL = r"(?:\s*[\-—–]+\s*|\s+)(?=[A-ZÁÉÍÓÚ«¿][^.]{25,})"


def sigla_pattern(path: Path = SIGLA_FILE) -> re.Pattern | None:
    """A siglum in the middle of an entry ends it -- that is what a siglum is.

    `…mandando anular cuántas se hubiesen instituido.»— G. T. En este año de
    1305, empezó á ser Lugarteniente…` is two notices, and only the source
    attribution says so: nothing about the second one's shape distinguishes it
    from a continuation.

    The discriminator is the glossary Campaner prints in his introduction, and
    it has to be: `— D. Pedro de Bellcastell` has exactly the same shape as
    `— G. T. Este mismo año`, and only one of the two is a source. No cycle is
    created by reading it -- the glossary comes off the introduction leaf, and
    `parse_sigla.py` reads `entries.jsonl` only to count attributions.

    The mark is placed *after* the siglum so the notice above keeps it: it is
    that notice's attribution, and `lift_sigla` still has to find it there.
    """
    if not path.exists():
        return None
    glossary = json.loads(path.read_text(encoding="utf-8"))["glossary"]
    # Longest first, so `Jn. Br.` is not matched as `J.` with a tail.
    names = sorted((s["siglum"] for s in glossary), key=len, reverse=True)
    if not names:
        return None
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(rf"[—-]\s*(?:{alternation}){SIGLUM_TAIL}")


SIGLA_BREAK = sigla_pattern()

# A notice that opens by saying *which year* it belongs to is not dated to a
# month, and inheriting the running one invents a precision the book does not
# offer: `En este año de 1305, empezó á ser Lugarteniente…` was coming out as
# July because the notice above it was. Only the inherited month is dropped --
# where a marker printed a day, the book's own figures stand.
WHOLE_YEAR = re.compile(
    r"^\s*[«\"]?\s*(?:en\s+|por\s+)?est[ea]\s+"
    r"(?:mismo\s+|propio\s+)?(?:año|ano|tiempo|época|epoca)\b",
    re.IGNORECASE)


def anchor_of(text: str) -> str:
    """The key an edit is filed under: the opening of the entry, folded.

    Not the entry's index, which renumbers the moment any rule above changes --
    that is the mistake `review.py` already avoids by keying on the word box.
    A box is not available here (an entry is a span of prose, not a token), so
    the anchor is its first characters with accents and case removed.

    It is deliberately sensitive to the text: if the consensus improves and the
    words at the head of an entry change, the edit stops matching and is
    *reported*, not silently dropped. An edit that no longer knows what it was
    editing must be looked at again.
    """
    return " ".join(strip_accents(text).lower().split())[:ANCHOR]


def read_edits(path: Path) -> dict[tuple[int, str], dict]:
    """The hand edits, append-only, last one wins for a given anchor."""
    if not path.exists():
        return {}
    out: dict[tuple[int, str], dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        edit = json.loads(line)
        out[(edit["leaf"], edit["anchor"])] = edit
    return out


def split_by_hand(entry: dict, edit: dict) -> list[dict]:
    """Cut one entry into several where the marker the parser needed was lost.

    `Mavo I.°—Tiraron un arcabuzazo…` is 1 May and opens a notice, but the day
    is printed `I.°` and no rule can see a digit there. Each cut names the
    literal string it follows, so the marker is consumed exactly as a parsed one
    would be, and carries the date the panel supports.

    The sigla are lifted again per piece: the attribution the parser found
    belongs to whichever notice actually ends the entry, and after a cut that is
    no longer the same notice.
    """
    pieces, dates, rest = [], [(entry["month"], entry["day"])], entry["text"]
    for cut in edit["cuts"]:
        at = rest.find(cut["after"])
        if at < 0:
            return [{**entry, "edited": f"split failed: {cut['after']!r} absent"}]
        pieces.append(rest[:at + len(cut["after"])])
        rest = rest[at + len(cut["after"]):]
        dates.append((cut.get("month"), cut.get("day")))
    pieces.append(rest)

    out = []
    for n, (piece, (month, day)) in enumerate(zip(pieces, dates)):
        body, sigla = lift_sigla(piece.strip().strip("—-").strip())
        if not sigla and n == len(pieces) - 1:
            sigla = entry["sources"]
        out.append({**entry, "text": body, "sources": sigla,
                    "month": month, "day": day,
                    "edited": edit.get("why", "split")})
    return [e for e in out if e["text"]]


def apply_edits(entries: list[dict], edits: dict) -> tuple[list[dict], list[str]]:
    """Apply the hand edits and say what happened to every one of them.

    Only decisions a parser cannot reach belong here -- a stray heading the year
    finder rejected, a date the book states in prose. Anything that generalises
    belongs in a rule, where it can be measured; anything that changes what a
    *word says* belongs in the adjudication, with the facsimile on screen.
    """
    used: set[tuple[int, str]] = set()
    kept: list[dict] = []
    for entry in entries:
        key = (entry["pdf_page"], anchor_of(entry["text"]))
        edit = edits.get(key)
        if edit is None:
            kept.append(entry)
            continue
        used.add(key)
        if edit["op"] == "drop":
            continue
        if edit["op"] == "date":
            entry = {**entry, "month": edit.get("month"), "day": edit.get("day")}
        elif edit["op"] == "split":
            kept.extend(split_by_hand(entry, edit))
            continue
        kept.append({**entry, "edited": edit.get("why", edit["op"])})

    missed = [f"p{leaf}: {edit['op']} {edit['anchor']!r} matched nothing"
              for (leaf, _a), edit in edits.items()
              if (leaf, edit["anchor"]) not in used]
    return kept, missed


# How many of the eight readings must name the month. Same threshold, and the
# same reasoning, as MIN_YEAR_VOTES.
MIN_MONTH_VOTES = 3
# What follows the month word in a heading the winner mangled: an optional day,
# then the dash that opens the notice. `M. 6.—Díjose` -- where `M.` is what the
# vote made of `JULIO`.
AFTER_MONTH = re.compile(r"\S+\s*(?:(?P<day>\d{1,2})(?:\s*(?:y|al|á)\s*\d{1,2})?\s*[.,]?\s*)?(?:—|--)")


def month_votes(word: dict) -> int | None:
    """The month this token prints, counted across the panel rather than taken
    from the winner.

    A month heading is five or six characters of display type, which is the
    class the engines read worst, and the vote has almost nothing to work with:
    on leaf 465 `JULIO` won as `M.` -- voting with the siglum `M. M.` beside it
    -- while kraken read `Jutxo`, paddle `JuLIo`, tess `JuLio` and vision
    `JULIO`. Leaf 69 has a heading whose winner is a bare `.` and which six of
    the eight readings call June.

    This is the rule `heading_votes` already applies to years, which
    CLAUDE.md states as "ask the panel, not the winner", applied to the months,
    where it had never been. It recovers what the recognisers actually returned;
    it does not substitute characters, and it does not change the published
    text -- the winner still prints as the consensus gave it.
    """
    votes: Counter = Counter()
    for reading in list(word["variants"].values()) + [word["winner"]]:
        folded = strip_accents(str(reading)).lower()
        for name, number in MONTHS.items():
            if name in folded:
                votes[number] += 1
                break
    if not votes:
        return None
    month, count = votes.most_common(1)[0]
    if count < MIN_MONTH_VOTES:
        return None
    # Nothing to recover when the winner already says it.
    winner = strip_accents(str(word["winner"])).lower()
    if any(n in winner for n, v in MONTHS.items() if v == month):
        return None
    return month


def as_day(token: str | None) -> int | None:
    """A day of the month, whether the engines printed it in digits or in the
    letters they mistake for digits: `IS.` is 15, `II.` is 11, `i i.` is 11.

    Only reached from a heading -- a month name immediately before, a dash
    immediately after -- so there is no other thing this could be reading.
    """
    if not token:
        return None
    digits = re.sub(r"\D", "", token.translate(DIGIT_LOOKALIKE))
    if not digits:
        return None
    day = int(digits)
    return day if 1 <= day <= 31 else None


def line_months(line: dict) -> list[tuple[int, int]]:
    """(offset within this line's text, month) for headings the winner lost.

    Skipped where the line's text is not the plain join of its tokens -- a year
    heading that came glued to its entry is rewritten before it gets here, and
    the offsets would no longer mean anything.
    """
    row = line.get("row") or []
    parts = [str(w["winner"]) for w in row]
    raw = " ".join(parts)
    if raw.strip() != line["text"]:
        return []
    lead = len(raw) - len(raw.lstrip())
    out, at = [], 0
    for part, word in zip(parts, row):
        month = month_votes(word)
        if month is not None:
            out.append((at - lead, month))
        at += len(part) + 1
    return [(o, m) for o, m in out if o >= 0]


def date_marks(text: str, months: list[tuple[int, int]] = ()) -> list[dict]:
    """Every place an entry opens, from both passes, merged by position.

    A mangled-month candidate is dropped when it overlaps a marker the strict
    pattern already found: `Mayo 2.—` is matched by both, and the strict one
    knows the month for certain.
    """
    marks = [{"start": m.start(), "end": m.end(),
              "month": (MONTHS[strip_accents(
                            m.group("month") or m.group("month2")).lower()]
                        if (m.group("month") or m.group("month2")) else None),
              "day": next((n for n in (as_day(m.group("day1")),
                                       as_day(m.group("day2")),
                                       as_day(m.group("day3")),
                                       as_day(m.group("day5")))
                            if n), None)}
             for m in ENTRY_START.finditer(text)
             if not (m.group("month") and FUNCTION_WORD.search(text[:m.start()]))]
    taken = [(m["start"], m["end"]) for m in marks]
    for m in NEAR_MONTH.finditer(text):
        month = near_month(m.group("near"), m.group("day4"), text[:m.start()])
        if month is None:
            continue
        if any(a < m.end() and m.start() < b for a, b in taken):
            continue
        marks.append({"start": m.start(), "end": m.end(), "month": month,
                      "day": as_day(m.group("day4"))})
    for m in (SIGLA_BREAK.finditer(text) if SIGLA_BREAK else ()):
        # start == end: the siglum stays with the notice it closes, and the new
        # one begins at the capital after it.
        if any(a < m.end() and m.end() < b for a, b in taken):
            continue
        marks.append({"start": m.end(), "end": m.end(),
                      "month": None, "day": None})
    for at, month in months:
        found = AFTER_MONTH.match(text, at)
        if not found:
            continue
        if any(a < found.end() and at < b for a, b in taken):
            continue
        day = found.group("day")
        marks.append({"start": at, "end": found.end(), "month": month,
                      "day": int(day) if day else None})
        taken.append((at, found.end()))
    marks.sort(key=lambda m: m["start"])
    return marks


def split_entries(text: str, year: int | None,
                  months: list[tuple[int, int]] = ()) -> list[dict]:
    """Cut a run of prose into dated entries, carrying the month forward.

    Campaner writes the month once and then gives bare days until it changes, so
    a `—20.—` inherits whatever month was last stated. The year does the same
    when the layout missed its display heading.
    """
    marks = date_marks(text, months)
    if not marks:
        return ([{"month": None, "day": None, "year": year, "at": 0,
                  "to": len(text), "text": text.strip()}] if text.strip()
                else [])

    entries = []
    preamble = text[:marks[0]["start"]].strip()
    if preamble:
        entries.append({"month": None, "day": None, "year": year, "at": 0,
                        "to": marks[0]["start"], "text": preamble})

    # `El mismo día` states its own date by referring to the one before it, so
    # the day carries forward as well as the month -- but only for that phrase.
    # Everywhere else a notice with no day printed has no day, and inventing one
    # would claim a precision the book does not give.
    current_month = None
    current_day = None
    for n, mark in enumerate(marks):
        end = marks[n + 1]["start"] if n + 1 < len(marks) else len(text)
        body = text[mark["end"]:end].strip()

        # a year heading the layout missed, sitting just before this marker
        head = text[marks[n - 1]["end"] if n else 0:mark["start"]]
        found = INLINE_YEAR.search(head.rstrip())
        if found and FIRST_YEAR <= int(found.group(1)) <= LAST_YEAR:
            year = int(found.group(1))

        if mark["month"]:
            current_month = mark["month"]
        day = mark["day"]
        if day is None and SAME_DAY.match(text[mark["end"]:end].lstrip()):
            day = current_day
        elif day is not None:
            current_day = day
        # `—El 14 de Julio…` names its own month; believe it over the one being
        # carried forward.
        if day is None and WHOLE_YEAR.match(body):
            current_month = None
        stated = MONTH_AFTER_DAY.match(body)
        if stated:
            current_month = MONTHS[strip_accents(stated.group("month")).lower()]
        # A day the carried month cannot hold proves the carry wrong, not the
        # day. Leaf 454 reads `…de Julio.—Cl. Fl. —31.—El Doctor Vilasalo…`:
        # the `Julio.` is the tail of the previous notice's own sentence, not a
        # heading, so June was still running and the notice came out 31 June.
        # The day is what the book prints and the month is our inference, so the
        # inference goes. Publishing 31 June asserts something the page does not
        # say, and guessing July asserts something else.
        month = current_month
        if month and day and int(day) > DAYS_IN[month]:
            month = None
        if not body:
            continue
        # An "entry" consisting of nothing but a sigla is the tail of the one
        # before it, orphaned when the split fell between the two.
        if entries and re.fullmatch(r"(?:[A-ZÁÉÍÓÚ][a-z]?\.\s*){1,3}", body):
            entries[-1]["text"] = (entries[-1]["text"] + " —" + body).strip()
            entries[-1]["to"] = end
            continue
        entries.append({
            "month": month,
            "day": int(day) if day else None,
            "year": year,
            # Where this notice sits in the run of prose it was cut from. The
            # caller turns that back into a leaf: an entry belongs to the leaf
            # it opens on, and a footnote to the leaf its reference is printed
            # on, and neither is knowable once the text has been cut up.
            "at": mark["start"],
            "to": end,
            "text": body,
        })
    return entries


def collapse_repeat(siglum: str) -> str:
    """`G. G. T.` is `G. T.` counted twice, not a siglum of three initials.

    The engines disagree about where the token after the dash ends: some read
    `reos.»—G.` and `T.`, others `reos.»—` and `G.` and `T.`. The alignment keeps
    both, so the `G.` appears at two positions and the vote accepts it at each.
    Leaf 65 prints `—G. T.`, checked against the facsimile, and the same doubling
    produced `B. B. J.`, `M. M. M.`, `Cl. Fl. Fl.` and `J. J. F.` elsewhere.

    Only a three-part siglum is collapsed, and only where two neighbours are
    equal: `M. M.` is Matías Mut and must survive intact.
    """
    parts = siglum.split()
    if len(parts) != 3:
        return siglum
    for n in (0, 1):
        if parts[n] == parts[n + 1]:
            return " ".join(parts[:n] + parts[n + 1:])
    return siglum


def siglum_key(text: str) -> tuple[str, ...]:
    """A siglum reduced to its initials, which is all a siglum really is.

    Matching the literal string was too strict by a wide margin: 130 notices
    kept their attribution in the prose because the engines scatter the stops
    and spaces. `G. G. T.` doubles an initial, `M M.` drops a stop, `G. T`
    drops the last one, `G . T.` inserts a space, `B. J. .` adds a stop. All
    five are the same two or three letters, and comparing letters instead of
    characters resolves every one of them.
    """
    groups = re.findall(r"[A-Za-zÁÉÍÓÚÑ]{1,2}", text.translate(SIGLUM_GLYPH))
    return tuple(g.upper() for g in groups)


def collapse_key(key: tuple[str, ...]) -> tuple[str, ...]:
    """`G. G. T.` is `G. T.` counted twice; `M. M.` is Matías Mut and stands."""
    if len(key) == 3:
        for n in (0, 1):
            if key[n] == key[n + 1]:
                return key[:n] + key[n + 1:]
    return key


def source_sigla(path: Path = SIGLA_FILE) -> dict[tuple[str, ...], str]:
    """Initials -> the canonical form Campaner prints.

    `UNGLOSSED` is written out here rather than read from the `unglossed` list
    `parse_sigla.py` produces, and that is not laziness. That list is built by
    counting attributions in `entries.jsonl`, so reading it would make this file
    depend on its own output -- the cycle CLAUDE.md says the glossary route
    avoids. The glossary comes off the introduction leaf and depends on nothing.
    """
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    names = [s["siglum"] for s in data["glossary"]] + list(UNGLOSSED)
    out: dict[tuple[str, ...], str] = {}
    for name in sorted(set(names) - NOT_A_SOURCE, key=len, reverse=True):
        out.setdefault(siglum_key(name), name)
    return out


SOURCES = source_sigla()
# The *shape* of an attribution: a dash, then one to four groups of one or two
# letters, each optionally followed by a stop. Deliberately loose, because the
# guard is not the pattern -- it is that every group of initials it captures
# has to resolve against Campaner's glossary before anything is lifted.
_GROUP = r"[A-Za-zÁÉÍÓÚÑ]{1,2}\s*[.,]?\s*"
# The dash may not be preceded by a letter, and that is not decoration. `…se
# cantó un solemnísimo Te-Deum. — J. M. — M. M.` matched from the hyphen inside
# `Te-Deum`, so the tail offered for resolution was `-Deum. — J. M. — M. M.`,
# `Deum.` is not a source, and the guard threw the whole attribution away rather
# than lift half of one. Seven notices and one document paragraph recover their
# sources; nothing loses one. The other forms the book uses are untouched, since
# `…dos noches.—G. T.` and `…Te-Deum.-G. F.` both put a stop before the dash.
SIGLA = re.compile(
    rf"(?:(?<![A-Za-zÀ-ÿ])\s*[-—–]+\s*[.,]?\s*(?:{_GROUP}){{1,4}})+[\s.,]*$")


def resolve(chunk: str) -> list[str] | None:
    """The sources named in one dash-separated chunk, or None if it is prose.

    A chunk of four initials with no dash between them is two sigla the engines
    ran together -- `—M. S. B. J.` -- so a failed lookup is retried as a pair
    before it is given up on.
    """
    key = collapse_key(siglum_key(chunk))
    if not key:
        return None
    if key in SOURCES:
        return [SOURCES[key]]
    if len(key) == 4 and key[:2] in SOURCES and key[2:] in SOURCES:
        return [SOURCES[key[:2]], SOURCES[key[2:]]]
    return None


# A dash left hanging at the end of a notice is the residue of the marker that
# opened the next one, or of a siglum the engines lost: `…embarcado en dos naves
# inglesas. —`. It is punctuation belonging to something else, and 17 notices
# ended on one.
# A dash at the very end of a notice is never text. It is either the dash that
# would have introduced a siglum nobody read, or -- 11 of the 13 cases -- the
# one that opens the *next* notice, left behind when the cut fell after it:
# `…luminarias dos noches.— — 28.—Llegaron 5 galeras…`. Whitespace before it is
# not required, because the commonest form has none: `…dos noches.—`.
TRAILING_DASH = re.compile(r"\s*[-—–]+\s*$")


# `…las corts en Inca.—J. V. (2)`: the reference to the footnote is printed
# after the attribution, and it kept 73 sigla stuck in the prose. It is put
# back into the text afterwards, because `parse_entries` finds a notice's notes
# by the numbers printed in it.
FOOTNOTE_REF = re.compile(r"\s*([\(\[]\s*[\dIil]{1,2}\s*[\)\]])\s*$")


def lift_sigla(text: str) -> tuple[str, list[str]]:
    """Split an entry into its prose and the sources credited at its foot."""
    text = TRAILING_DASH.sub("", text).rstrip()
    ref = FOOTNOTE_REF.search(text)
    if ref:
        text = text[:ref.start()].rstrip()
    if SIGLA is None:
        return (text + (" " + ref.group(1) if ref else "")), []
    match = SIGLA.search(text)
    if not match:
        return (text + (" " + ref.group(1) if ref else "")), []
    tail = match.group(0)
    # The whole tail first, because a dash *inside* a siglum is the alignment's
    # and not the book's: `-Jn.—Br.` is Joaquin M. Bover in two pieces, and
    # splitting on the dash asks whether `Jn.` is a source, which it is not, so
    # the guard below threw the whole attribution away. Resolving the tail whole
    # still separates a real pair -- `—M. S.—B. J.` comes back as two -- because
    # the key is a sequence of initials and the glossary decides where it ends.
    whole = resolve(tail)
    if whole is not None:
        kept = [x for n, x in enumerate(whole) if n == 0 or x != whole[n - 1]]
        body = text[:match.start()].rstrip()
        return (body + (" " + ref.group(1) if ref else "")), kept
    sigla: list[str] = []
    for part in re.split(r"[-—–]+", tail):
        if not part.strip():
            continue
        found = resolve(part)
        if found is None:
            # One chunk that is not a source means the tail is prose that
            # merely looks like one. Nothing is lifted rather than half of it.
            return (text + (" " + ref.group(1) if ref else "")), []
        sigla += found
    # `—J. — J.` is one attribution the alignment split in two, the same
    # doubling a repeated initial gets inside a siglum. Campaner never credits
    # the same manuscript twice in a row.
    kept = [x for n, x in enumerate(sigla) if n == 0 or x != sigla[n - 1]]
    body = text[:match.start()].rstrip()
    return (body + (" " + ref.group(1) if ref else "")), kept


def report_gaps(missing: list[int], headings: list[tuple[int, int]],
                leaves: dict[int, list[dict]], aside: set[int]) -> None:
    """For each year with no heading, whether the book looks like it has one.

    A year can be absent for two quite different reasons and they need telling
    apart before anyone goes hunting: Campaner may simply have had no news to
    report -- 1355 to 1361 is seven consecutive silent years -- or the heading
    may be there and unreadable. The test is whether any line on the leaves that
    bracket the year carries that year in *any* engine's reading, at any vote
    count. If nothing anywhere says 1233, the book does not say 1233.
    """
    print(f"\nyears with no heading, and whether one seems to be on the page:")
    silent, suspect = [], []
    for year in missing:
        before = [p for p, y in headings if y < year]
        after = [p for p, y in headings if y > year]
        span = range(before[-1] if before else 0, (after[0] if after else 10**6) + 1)
        traces = []
        for page in (p for p in span if p in leaves and p not in aside):
            for line in leaves[page]:
                if len(line["text"]) <= 16 and year in heading_votes(line["row"]):
                    traces.append((page, line["text"],
                                   heading_votes(line["row"])[year]))
        (suspect if traces else silent).append((year, traces))

    print(f"  {len(silent)} with no trace anywhere in their span "
          f"-- the chronicle is silent on them: {[y for y, _ in silent]}")
    print(f"  {len(suspect)} with a damaged line that may be the heading:")
    for year, traces in suspect:
        page, text, votes = traces[0]
        print(f"    {year}  p{page} {text!r} ({votes} readings)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--documents",
                    default=str(PROJECT / "data" / "documents" / "documents.json"),
                    help="the numbered document sections, from parse_documents.py; "
                         "their leaves are excluded from the chronicle")
    ap.add_argument("--bootstrap", action="store_true",
                    help="run without the document list. Only for the first pass "
                         "of a fresh build, since parse_documents.py reads this "
                         "script's output and so cannot exist yet")
    ap.add_argument("--edits", default=str(EDITS),
                    help="hand edits to apply after parsing (append-only)")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    if not source.exists():
        raise SystemExit(f"{source} missing -- run scripts/consensus.py first")

    # Without this list the chronicle silently swallows 160 leaves of letters,
    # edicts and the 1541 reprint -- 60 303 words, one in six of the text, dated
    # to whatever year heading happened to precede them. It went unnoticed for a
    # long time precisely because it is silent, so a missing file is a hard stop
    # rather than a fallback.
    documents = Path(args.documents)
    if args.bootstrap:
        documents = None
        print("bootstrap: no document list, so the documents Campaner prints in "
              "full will be\n  parsed as chronicle. Run parse_documents.py and "
              "then this script again.\n")
    elif not documents.exists():
        raise SystemExit(
            f"{documents} not found.\nThe chronicle cannot be separated from the "
            f"documents without it. Run:\n"
            f"  python scripts/parse_entries.py --bootstrap\n"
            f"  python scripts/parse_documents.py\n"
            f"  python scripts/parse_entries.py")

    inventory = {leaf["pdf_page"]: leaf for leaf in
                 json.loads((PROJECT / "data" / "inventory.json").read_text())["leaves"]}

    # ---- pass 1: read every body leaf, separate the footnotes from the body,
    # and the name lists from the chronicle. The notes come off first because
    # they are not chronicle in any sense: they carry their own years, and one of
    # them -- `…a 13 dias dagost de 1336.»` wrapped alone on leaf 74 -- was one
    # of only two candidates in the book that broke the chronology.
    leaves: dict[int, list[dict]] = {}
    footnotes: dict[int, list[dict]] = {}
    body_pages: list[int] = []
    for pdf_page in targets.resolve("all"):
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists() or inventory[pdf_page]["page_class"] != "body":
            continue
        body, notes = split_notes(page_lines(path))
        leaves[pdf_page] = body
        if notes:
            footnotes[pdf_page] = gather_notes(notes)
        body_pages.append(pdf_page)

    tables = fill_table_runs(
        {p for p in body_pages
         if is_table_leaf(leaves[p], inventory[p]["columns"])}, body_pages)
    chronicle = [p for p in body_pages if p not in tables]

    # ---- pass 2: collect every line that announces a year, then keep the
    # largest set of them that can all be true at once. Deciding leaf by leaf
    # cannot tell a misread heading from a real jump; the whole sequence can.
    #
    # Then the excursuses. Campaner interrupts the chronicle to print documents
    # in full -- `II. Cartas del gobernador Gilaberto de Centellas`, `IV.
    # Fragmentos de las Apuntaciones del Notario Mateo Salcet` -- and each dates
    # its own material, so leaf 153 runs 1382, 1384, 1387 in the middle of the
    # 1340s. They are not chronicle, and they are what the chronology rejects. A
    # leaf that states years, none of which can be true where it sits, is inside
    # one; leaves between two such leaves are inside the same one.
    #
    # Removing them changes the sequence, so the chronology is recomputed until
    # it stops moving: an excursus twelve leaves long can otherwise outvote the
    # chronicle around it and get itself accepted instead.
    # `parse_documents.py` has already delimited these blocks by their own
    # numerals, and it finds what the chronology test cannot. The test asks
    # whether a leaf states a year that can be true where it sits; the letters of
    # Gilaberto de Centellas state no year at all, so nothing fires and fourteen
    # leaves of medieval Catalan came through as chronicle entries dated 1400.
    # Ninety-six leaves arrived that way -- 60 303 words, one word in six of what
    # this file called the chronicle.
    #
    # The dependency runs both ways (parse_documents reads headings.json, which
    # this script writes), so it is a second pass: run this, run that, run this
    # again. Idempotent from the second pass on, and the first pass simply has no
    # document list to read.
    excursus: set[int] = set(known_documents(documents))
    chronicle = [p for p in chronicle if p not in excursus]
    for _round in range(4):
        candidates = [
            {"page": pdf_page, "position": position, "year": year,
             "votes": votes, "text": line["text"], "rest": rest}
            for pdf_page in chronicle
            for position, line in enumerate(leaves[pdf_page])
            for year, votes, rest in [year_of_line(line)] if year is not None]

        keep = set(monotone_subsequence([c["year"] for c in candidates]))
        rejected = [c for n, c in enumerate(candidates) if n not in keep]
        accepted = {(c["page"], c["position"]): c
                    for n, c in enumerate(candidates) if n in keep}

        found = fill_table_runs(
            {c["page"] for c in rejected} - {p for p, _ in accepted}, chronicle)
        found = fill_table_runs(found, chronicle)
        found |= spillover(candidates, accepted, body_pages,
                           tables | excursus | found)
        if not found - excursus:
            break
        excursus |= found
        chronicle = [p for p in chronicle if p not in excursus]

    year = None
    entries: list[dict] = []
    headings: list[tuple[int, int]] = []
    anomalies = [f"p{c['page']}: {c['text']!r} reads {c['year']} "
                 f"({c['votes']} readings) but breaks the chronology"
                 for c in rejected]
    skipped_tables = sorted(tables)

    # The buffer lives outside the leaf loop, and that is the whole of the fix
    # for entries cut in half by a page turn. Flushing at the end of every leaf
    # made 285 of them: a notice that ran over the foot of leaf 595 came out as
    # two entries, the second undated and opening mid-word -- `juró-` on one and
    # `el Obispo en manos del Comandante General` on the next. The hyphen
    # stitching was already there; it only ever saw one leaf at a time.
    #
    # It is carried only to the *consecutive* leaf. `chronicle` has holes in it
    # where the Jurats tables and the documents were lifted out, and running the
    # buffer across one of those would weld the text on either side of an
    # appendix sixty leaves long.
    buffer: list[dict] = []

    def flush():
        if not buffer:
            return
        text = ""
        # Offsets of the month headings the vote lost, carried into the joined
        # text so `date_marks` can cut at them.
        months: list[tuple[int, int]] = []
        # …and of the leaves themselves, which is what turns an offset in the
        # joined run back into a leaf of the book.
        bounds: list[tuple[int, int, int]] = []
        for ln in buffer:
            if text.endswith("-"):
                base = len(text) - 1
                text = text[:-1] + ln["text"]
            else:
                base = len(text) + 1 if text else 0
                text = (text + " " + ln["text"]).strip()
            months += [(base + at, m) for at, m in line_months(ln)]
            bounds.append((base, base + len(ln["text"]), ln["leaf"],
                           ln.get("column", 0)))

        spanned = list(dict.fromkeys(ln["leaf"] for ln in buffer))

        def where(offset: int) -> tuple[int, int]:
            """The leaf and column that carry this position in the joined run."""
            found = [(leaf, column) for start, _e, leaf, column in bounds
                     if start <= offset]
            return found[-1] if found else (spanned[0], 0)

        def leaf_at(offset: int) -> int:
            return where(offset)[0]

        for entry in split_entries(text, year, months):
            at, to = entry.pop("at"), entry.pop("to")
            body, sigla = lift_sigla(entry["text"])
            # An entry belongs to the leaf it *opens* on -- which is the leaf
            # its own date marker is printed on, not the leaf the buffer began
            # on. The buffer runs from one year heading to the next and can
            # cross five leaves, so crediting all of them to its first leaf sent
            # the facsimile link, the printed page number and the leafmark on
            # the year page to the wrong page of the book.
            opened = leaf_at(at)
            # A footnote belongs where its *reference* is printed, and the
            # address is (leaf, column, number) -- the numbering restarts at the
            # head of every column. Matching the bare number across every leaf
            # the entry ran over put leaf 29's «Honores ó féudos.» under 1229 as
            # well as under 1230, which is where it is called: 85 of the book's
            # 185 notes were reaching more than one notice.
            notes = []
            for m in NOTE_REF.finditer(text[at:to]):
                number = ref_number(m.group(1))
                if number is None:
                    continue
                leaf, column = where(at + m.start())
                # Nothing of that number in that column means the note was not
                # separated, not that it is elsewhere: leaf 105 opens its `(1)`
                # at y 0.545 and `split_notes` only looks below 0.55, so the
                # note stayed in the prose. Reaching to a neighbour for a
                # number that happens to match would print leaf 104's note
                # under a notice of leaf 105 -- an attribution invented to fill
                # a hole. Print nothing instead.
                hit = [n for n in footnotes.get(leaf, ())
                       if n["number"] == number and n["column"] == column
                       and n not in notes]
                notes += hit[:1]
            entries.append({**entry, "text": body, "sources": sigla,
                            "pdf_page": opened,
                            "printed": inventory[opened]["printed"],
                            "ia_leaf": inventory[opened]["ia_leaf"],
                            **({"notes": notes} if notes else {})})
        buffer.clear()

    # The six century openings, lifted before the entry loop so that neither
    # their banner nor the source list under them can be read as chronicle.
    centuries, front_lines = century_openings(leaves, accepted, body_pages)
    # `DE 1301 Á 1400.` is Campaner stating the year the chronicle resumes at,
    # and it has to be believed, because two centuries never print a heading for
    # their own first year. The 14th opens with a drop cap -- `EN este año 1301
    # fueron Lugartenientes…` -- and the 16th's `1501.` came back from the vote
    # as `ISOI.`, so both centuries began under the last year of the one before.
    opens_at = {c["pdf_page"]: c["from_year"] for c in centuries
                if c["from_year"]}

    for n, pdf_page in enumerate(chronicle):
        for position, line in enumerate(leaves[pdf_page]):
            if not line["text"]:
                continue
            if (pdf_page, position) in front_lines:
                flush()
                if pdf_page in opens_at:
                    year = opens_at.pop(pdf_page)
                    headings.append((pdf_page, year))
                continue
            candidate = accepted.get((pdf_page, position))
            if candidate is not None:
                flush()
                year = candidate["year"]
                headings.append((pdf_page, year))
                # …and if the heading came glued to its entry, the entry stays.
                if candidate["rest"]:
                    buffer.append({**line, "text": candidate["rest"],
                                   "leaf": pdf_page})
                continue
            # A rejected candidate is still not prose: dropping it keeps a stray
            # `1449.` out of the middle of an entry.
            if year_of_line(line)[0] is not None:
                continue
            buffer.append({**line, "leaf": pdf_page})
        following = chronicle[n + 1] if n + 1 < len(chronicle) else None
        if following != pdf_page + 1:
            flush()
    flush()

    # A leaf inside a numbered document section is a document leaf, whatever its
    # typography: leaves 161-163 are 4- and 6-column tables and also sit inside
    # section V of the second block, and Campaner's own numbering is the better
    # authority on what they are. Stated as a precedence so the three sets really
    # are a partition, rather than leaving three leaves in two of them.
    known = known_documents(documents)
    skipped_tables = sorted(tables - known)

    entries, orphans = apply_edits(entries, read_edits(Path(args.edits)))

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "entries.jsonl").open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # What the chronicle parse set aside is not rubbish -- it is the Jurats
    # lists and the documents Campaner prints in full, both of which want their
    # own parser. Writing the classification down keeps them from being quietly
    # lost between one script and the next.
    # Where each year of the chronicle is stated. Downstream this is what says
    # where an appendix block ends and the chronicle resumes.
    (OUT / "headings.json").write_text(
        json.dumps(headings, ensure_ascii=False), encoding="utf-8")
    (OUT / "centuries.json").write_text(
        json.dumps(centuries, ensure_ascii=False, indent=1), encoding="utf-8")
    # Every note the leaves print, whether or not a notice calls it. The
    # entries carry only the ones that were called; the difference between the
    # two is a defect, and it cannot be seen from either file alone.
    (OUT / "footnotes.json").write_text(json.dumps(
        {str(page): notes for page, notes in sorted(footnotes.items())},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "sections.json").write_text(json.dumps({
        "chronicle": chronicle,
        "jurats_tables": skipped_tables,
        "document_excursus": sorted(excursus),
        "rejected_headings": [
            {"pdf_page": c["page"], "text": c["text"], "reads": c["year"],
             "readings": c["votes"]} for c in rejected],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    years = [y for _p, y in headings]
    dated = sum(1 for e in entries if e["month"])
    sourced = sum(1 for e in entries if e["sources"])
    print(f"{len(headings)} year headings, {len(set(years))} distinct "
          f"({min(years)}–{max(years)})")
    attached = sum(1 for e in entries if e.get("notes"))
    print(f"{len(entries):,} entries")
    print(f"  footnotes         {sum(len(v) for v in footnotes.values()):,} on "
          f"{len(footnotes)} leaves, {attached} entries carry one")
    print(f"  century openings  {len(centuries)}, "
          f"{sum(len(c['text'].split()) for c in centuries):,} words of "
          "front matter no longer read as chronicle")
    print(f"  with a month      {dated:,}  ({dated/len(entries):.0%})")
    print(f"  with a source     {sourced:,}  ({sourced/len(entries):.0%})")
    print(f"  median length     {sorted(len(e['text']) for e in entries)[len(entries)//2]} chars")
    edited = sum(1 for e in entries if e.get("edited"))
    applied = len(read_edits(Path(args.edits))) - len(orphans)
    if applied or orphans:
        print(f"  hand edits        {applied} applied, {edited} entries marked")
    # Loud, and last, because an edit that matches nothing means the text under
    # it moved: the decision has to be made again rather than assumed to hold.
    for line in orphans:
        print(f"  !! EDIT ORPHANED  {line}")

    missing = [y for y in range(min(years), max(years) + 1) if y not in set(years)]
    print(f"\n{len(skipped_tables)} Jurats-table leaves skipped: {skipped_tables}")
    print(f"{len(excursus)} document-excursus leaves set aside: {sorted(excursus)}")
    print(f"years with no heading at all: {len(missing)}")
    if args.report:
        print(f"  {missing[:40]}{' …' if len(missing) > 40 else ''}")
        print(f"\ncandidates rejected by the chronology ({len(anomalies)}):")
        for line in anomalies[:25]:
            print(f"  {line}")
        report_gaps(missing, headings, leaves, tables | excursus)
        top = Counter(s for e in entries for s in e["sources"])
        print(f"\ntop sigla: {dict(top.most_common(12))}")

    print(f"\n-> {OUT / 'entries.jsonl'}")


if __name__ == "__main__":
    main()
