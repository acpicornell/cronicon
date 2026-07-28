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
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

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
                                 "O": "0", "o": "0", "S": "5"})
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
ENTRY_START = re.compile(
    rf"(?:"
    rf"(?<![a-záéíóúñA-ZÁÉÍÓÚÑ])(?P<month>{MONTH_ALT})\s*(?P<day1>\d{{1,2}})?\s*\.?\s*—"
    rf"|—\s*(?P<day2>\d{{1,2}})(?:\s*[yá]\s*\d{{1,2}})?\s*[.,]?\s*—"
    rf"|—\s*El\s+(?P<day3>\d{{1,2}})\s*,?\s+(?=[a-záéíóúñ])"
    rf"|—\s*En\s+(?P<day5>\d{{1,2}})\s+de\s+(?P<month2>{MONTH_ALT})\b"
    # `Este año` was the assumed form and matches nothing at all: what Campaner
    # writes is `—En este año se sufrió una peste…`, 59 times. The `En` is
    # optional so both spellings pass, and the phrase itself stays in the entry
    # -- it is the text, not a label.
    rf"|—\s*(?=(?:En\s+)?Este\s+(?:año|mes|dia|día))"
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
    r"\s*(?P<day4>\d{1,2})?\s*\.\s*—")

# `—El 14 de Julio otro pregon…` states its own month, and taking the month
# carried forward instead would date it to whatever month was running.
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
    return None

# A year heading the layout missed and left inline, sitting immediately before a
# date marker: `—B. J. 1459. Mayo 2.—`. Anchored to the end of the run so that a
# year mentioned in passing ("la donacion de 1058. Sin embargo…") cannot be
# mistaken for a heading -- only one that directly precedes a date counts.
INLINE_YEAR = re.compile(r"(?<!\d)(1[2-8]\d\d)\s*[.,\-—]\s*$")

# Sigla trailing an entry: —G. T. / —B. J. / —L. V. / —Jn. Br. / —T. A.
SIGLA = re.compile(r"—\s*((?:[A-ZÁÉÍÓÚ][a-z]?\.\s*){1,3})\s*$")


# A footnote opens with its own number on a fresh line: `(1)`, `(2)`, `[3]`.
NOTE_START = re.compile(r"^\s*[\(\[]\s*(\d{1,2})\s*[\)\]]")
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


def split_notes(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separate a leaf's footnotes from its body.

    A note runs from its own number to the foot of the column it is in, so the
    rule follows the reading order rather than the geometry: once a note has
    opened, every following line belongs to it until y jumps back towards the
    top of the leaf, which is the next column beginning.

    Type size does not work as a signal here and was tried: notes are set at
    0.0097 of the leaf against 0.0127 for the body, and the two overlap.
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


def gather_notes(notes: list[dict]) -> list[dict]:
    """The note lines joined into one record per number."""
    out: list[dict] = []
    for line in notes:
        match = NOTE_START.match(line["text"])
        if match:
            out.append({"number": int(match.group(1)),
                        "text": line["text"][match.end():].strip()})
        elif out:
            text = out[-1]["text"]
            out[-1]["text"] = (text[:-1] + line["text"] if text.endswith("-")
                               else (text + " " + line["text"]).strip())
    return out


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def page_lines(path: Path) -> list[dict]:
    """Lines with text, box, column and the worst certainty tier they contain."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for locus in json.loads(path.read_text())["loci"]:
        key = tuple(locus["line_bbox"])
        if key not in grouped:
            order.append(key)
        grouped[key].append(locus)

    rank = {"unanimous": 0, "one-dissent": 1, "two-dissent": 2, "contested": 3}
    lines = []
    for key in order:
        row = sorted(grouped[key], key=lambda x: x["index"])
        lines.append({
            "text": " ".join(w["winner"] for w in row).strip(),
            "bbox": list(key),
            "row": row,
            "worst_tier": max((w["grade"] for w in row),
                              key=lambda g: rank[g], default="unanimous"),
            "tiers": Counter(w["grade"] for w in row),
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
SIGLUM_TAIL = r"\s+(?=[A-ZÁÉÍÓÚ«¿][^.]{25,})"


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
        kept.append({**entry, "edited": edit.get("why", edit["op"])})

    missed = [f"p{leaf}: {edit['op']} {edit['anchor']!r} matched nothing"
              for (leaf, _a), edit in edits.items()
              if (leaf, edit["anchor"]) not in used]
    return kept, missed


def date_marks(text: str) -> list[dict]:
    """Every place an entry opens, from both passes, merged by position.

    A mangled-month candidate is dropped when it overlaps a marker the strict
    pattern already found: `Mayo 2.—` is matched by both, and the strict one
    knows the month for certain.
    """
    marks = [{"start": m.start(), "end": m.end(),
              "month": (MONTHS[strip_accents(
                            m.group("month") or m.group("month2")).lower()]
                        if (m.group("month") or m.group("month2")) else None),
              "day": next((int(d) for d in (m.group("day1"), m.group("day2"),
                                            m.group("day3"), m.group("day5"))
                            if d), None)}
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
                      "day": int(m.group("day4")) if m.group("day4") else None})
    for m in (SIGLA_BREAK.finditer(text) if SIGLA_BREAK else ()):
        # start == end: the siglum stays with the notice it closes, and the new
        # one begins at the capital after it.
        if any(a < m.end() and m.end() < b for a, b in taken):
            continue
        marks.append({"start": m.end(), "end": m.end(),
                      "month": None, "day": None})
    marks.sort(key=lambda m: m["start"])
    return marks


def split_entries(text: str, year: int | None) -> list[dict]:
    """Cut a run of prose into dated entries, carrying the month forward.

    Campaner writes the month once and then gives bare days until it changes, so
    a `—20.—` inherits whatever month was last stated. The year does the same
    when the layout missed its display heading.
    """
    marks = date_marks(text)
    if not marks:
        return ([{"month": None, "day": None, "year": year,
                  "text": text.strip()}] if text.strip() else [])

    entries = []
    preamble = text[:marks[0]["start"]].strip()
    if preamble:
        entries.append({"month": None, "day": None, "year": year,
                        "text": preamble})

    current_month = None
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
        # `—El 14 de Julio…` names its own month; believe it over the one being
        # carried forward.
        if day is None and WHOLE_YEAR.match(body):
            current_month = None
        stated = MONTH_AFTER_DAY.match(body)
        if stated:
            current_month = MONTHS[strip_accents(stated.group("month")).lower()]
        if not body:
            continue
        # An "entry" consisting of nothing but a sigla is the tail of the one
        # before it, orphaned when the split fell between the two.
        if entries and re.fullmatch(r"(?:[A-ZÁÉÍÓÚ][a-z]?\.\s*){1,3}", body):
            entries[-1]["text"] = (entries[-1]["text"] + " —" + body).strip()
            continue
        entries.append({
            "month": current_month,
            "day": int(day) if day else None,
            "year": year,
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


def lift_sigla(text: str) -> tuple[str, list[str]]:
    sigla = []
    while True:
        match = SIGLA.search(text)
        if not match:
            break
        sigla.insert(0, collapse_repeat(
            re.sub(r"\s+", " ", match.group(1)).strip()))
        text = text[:match.start()].rstrip()
    return text, sigla


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
        for ln in buffer:
            if text.endswith("-"):
                text = text[:-1] + ln["text"]
            else:
                text = (text + " " + ln["text"]).strip()
        # An entry belongs to the leaf it *opens* on, and may refer to a note
        # printed on any leaf it runs across.
        spanned = list(dict.fromkeys(ln["leaf"] for ln in buffer))
        opened = spanned[0]
        for entry in split_entries(text, year):
            body, sigla = lift_sigla(entry["text"])
            # The notes this entry refers to, by the number printed in it.
            wanted = {int(m.group(1))
                      for m in re.finditer(r"[\(\[]\s*(\d{1,2})\s*[\)\]]", body)}
            notes = [n for leaf in spanned for n in footnotes.get(leaf, [])
                     if n["number"] in wanted]
            entries.append({**entry, "text": body, "sources": sigla,
                            "pdf_page": opened,
                            "printed": inventory[opened]["printed"],
                            "ia_leaf": inventory[opened]["ia_leaf"],
                            **({"notes": notes} if notes else {})})
        buffer.clear()

    for n, pdf_page in enumerate(chronicle):
        for position, line in enumerate(leaves[pdf_page]):
            if not line["text"]:
                continue
            if CENTURY_LINE.match(line["text"]):
                flush()
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
