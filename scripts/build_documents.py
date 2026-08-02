"""Assemble each document Campaner prints in full as one text.

`parse_documents.py` says where the sections are; this puts them together. Until
now the letters of Gilaberto de Centellas existed only as fourteen leaf files with
the letters of some other section starting halfway down the last of them, which is
the same as not having them.

Three things need care and none of them is transcription:

  the ends       A section's `until` is the leaf before the next section starts,
                 but a section can start in the middle of a leaf -- section III
                 opens at line 7 of leaf 233 while section II is still running
                 down it. Ending at `until` therefore drops the top of that leaf.
                 The end taken here is the next section's *first line*, so the
                 leaf is split where the book splits it.

  the footnotes  Separated exactly as in the chronicle, and for the same reason:
                 a note runs from its number to the foot of its column and is not
                 part of the sentence it interrupts.

  the certainty  Carried through. These are the leaves nothing has measured -- no
                 adjudicated position falls on one -- so a document that is mostly
                 contested must say so on its face rather than read like the rest.

Nothing here corrects, translates or normalises. The medieval Catalan and Latin
stay as printed, including the long s of the 1541 reprint, which `editorial.py`
handles under its own documented rule.

Usage:
  python scripts/build_documents.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import unicodedata
from collections import Counter
from pathlib import Path

import editorial
from build_text import BREAK_HYPHEN
from parse_entries import (MIN_YEAR_VOTES, OCR, gather_notes, heading_votes,
                           page_lines, split_notes, years_in)

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "documents"
SECTIONS = OUT / "sections"

# Campaner names the genre himself, in the first word of every title: `Cartas`,
# `Sentencia`, `Relacion`, `Memorial`, `Declaraciones`, `Toma de posesion`. That
# is better evidence than any classification of ours, so it is surfaced as it
# stands rather than mapped onto categories the book does not use.
# `IV. ` opening a line, where the numeral and the title share it.
NUMERAL_HEAD = re.compile(r"[IVXLC]{1,6}\.\s+")
ROMAN = re.compile(r"[IVXLCivxlc0-9 .,]{1,10}")
GENRE = re.compile(r"^[«\"'\s]*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)")


def span_of(block: dict, index: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """(first leaf, first line) and the exclusive end of section `index`."""
    sections = block["sections"]
    section = sections[index]
    start = (section["pdf_page"], section.get("line", 0))
    if index + 1 < len(sections):
        nxt = sections[index + 1]
        end = (nxt["pdf_page"], nxt.get("line", 0))
    else:
        end = (section.get("until", section["pdf_page"]) + 1, 0)
    return start, end


# How far past its column's left edge a line has to start before it counts as
# opening a paragraph. Word spaces here are 0.0066 of the page and the printer's
# indent is about 0.02, so 0.012 sits between them with room on both sides.
INDENT = 0.012
# A line this much narrower than the measure is the last line of a paragraph.
SHORT = 0.88
CLEAR = 0.02


# A bare numeral hanging left of its column's text: the node number of the
# genealogical plate, printed in the margin against the entry it belongs to.
HANGING_NUMBER = re.compile(r"^\s*[0-9IilOo]{1,3}\s*$")
HANGS = 0.015


def hanging_numbers(lines: list[dict]) -> set[int]:
    """Lines that are a node number standing in their column's margin.

    Leaf 152 is the `ESPLICACION DEL ÁRBOL` of the genealogical plate on 151,
    and it prints each entry's number out in the margin: `8  Casó con el
    infante de Castilla D. Juan Manuel.` The number is its own line box with a
    y a hair below the entry's first, so the reading order puts it *after* that
    line and it lands in the middle of the sentence -- `Se dice es la que está
    enterrada en la 9 Catedral.`, and once inside a hyphen join, `D. Fer17
    rario`.

    Sorting overlapping lines left to right would fix it and was measured
    first: it reorders 74 of 650 leaves, two of which carry adjudications, so
    it is not a change to make in passing. This is the same fact stated where
    it is safe -- **one leaf in all 23 documents has a hanging numeral at all**
    -- and the number opens its entry, which is what the book does with it.
    """
    out: set[int] = set()
    by_column: dict[int, list[int]] = {}
    # (the caller moves each of these in front of the line it overlaps)
    for n, line in enumerate(lines):
        if line["text"].strip():
            by_column.setdefault(line.get("column", 0), []).append(n)
    for rows in by_column.values():
        base = statistics.median(lines[n]["bbox"][0] for n in rows)
        out |= {n for n in rows
                if HANGING_NUMBER.match(lines[n]["text"])
                and lines[n]["bbox"][0] < base - HANGS}
    return out


# Leaves whose columns must be sorted by *printed line* rather than by the top
# of each box. Two lines that overlap in y are one line of the page and belong
# left to right; sorting by y0 alone puts a marginal number after the line it
# stands against, because its box begins a hair lower.
#
# Leaf 152 -- the `ESPLICACION DEL ÁRBOL` of the genealogical plate -- is the
# only leaf in all 23 documents with a number in its margin, and it came out as
# `Se dice es la que está enterrada en la 9 Catedral.` and `D. Fer17 rario`.
#
# Named leaf by leaf on purpose. Applying it everywhere reorders 74 of the 650
# engine-leaves, two of them carrying adjudications from the frozen sample, and
# that is a measurement to act on with room to verify it -- not a side effect of
# repairing one page.
BY_PRINTED_LINE = {152}


def by_printed_line(lines: list[dict]) -> list[dict]:
    """Sort each column by printed line, then left to right within it."""
    out: list[dict] = []
    for column in sorted({line.get("column", 0) for line in lines}):
        rows = [line for line in lines if line.get("column", 0) == column]
        # From the lines that carry text: an empty line has a degenerate box
        # and a handful of them move the median enough to change every key.
        heights = [line["bbox"][3] - line["bbox"][1] for line in rows
                   if line["text"].strip() and line["bbox"][3] > line["bbox"][1]]
        step = (statistics.median(heights) if heights else 0.01) * 0.7
        rows.sort(key=lambda line: (round(line["bbox"][1] / step),
                                    line["bbox"][0]))
        out += rows
    return out


def paragraph_breaks(lines: list[dict]) -> set[int]:
    """Paragraph openers, computed leaf by leaf and unioned.

    The indent and the short line are facts about **a page**, and this used to
    be asked of a whole section at once: the 17 leaves of `Historia de los Reyes
    de Mallorca` share a column-0 edge of 0.11, and leaf 152's own column sits
    at 0.15, so every ordinary line on it read as indented by 0.04 and the
    breaks fell wherever the short-line test happened to agree.

    A section is not typeset to one measure -- it crosses a table, a plate and a
    change of type -- so the unit is the leaf.
    """
    by_leaf: dict[int, list[int]] = {}
    for n, line in enumerate(lines):
        by_leaf.setdefault(line.get("leaf", 0), []).append(n)
    if len(by_leaf) > 1:
        out: set[int] = set()
        for rows in by_leaf.values():
            here = [lines[n] for n in rows]
            out |= {rows[i] for i in paragraph_breaks(here)}
        return out
    return _breaks_on_one_leaf(lines)


def centred_lines(lines: list[dict]) -> set[int]:
    """Which lines are centred, leaf by leaf and unioned -- see `centred`."""
    by_leaf: dict[int, list[int]] = {}
    for n, line in enumerate(lines):
        by_leaf.setdefault(line.get("leaf", 0), []).append(n)
    out: set[int] = set()
    for rows in by_leaf.values():
        here = [lines[n] for n in rows]
        live = [i for i, line in enumerate(here) if line["text"].strip()]
        out |= {rows[i] for i in centred(here, live)}
    return out


def _breaks_on_one_leaf(lines: list[dict]) -> set[int]:
    """Which lines open a paragraph, by where the printer indented them.

    **A line break is not a paragraph break**, and treating it as one is what
    made these documents unreadable: `stitch` used to end every printed line
    that did not carry a hyphen, so a letter of Gilaberto de Centellas arrived
    as a wall of forty-character lines instead of prose. The original's line
    breaks are an accident of the measure and belong to the facsimile, not to a
    text meant to be read.

    What the book does mark is the paragraph, and it marks it the way books do:
    with an indent. The left edge is taken per column, because a two-column leaf
    has two of them and one median over both makes every line of column one look
    outdented and every line of column two indented.
    """
    # The commonest left edge, not the smallest: a heading or a display line
    # starts further left than the body and would make every ordinary line look
    # indented. Rounded to a hundredth so that near-identical edges count as one.
    edges: dict[int, Counter] = {}
    for line in lines:
        if line["text"].strip():
            edges.setdefault(line.get("column", 0), Counter())[
                round(line["bbox"][0], 2)] += 1
    base = {column: xs.most_common(1)[0][0] for column, xs in edges.items()}
    # An indent alone is not enough, and this document proved it: leaf 137 gave
    # 11 openers in 73 lines and the section still came out with 266 of its 395
    # paragraphs under 60 characters, because continuation lines like `páginas
    # 76 y 77, citando á Gar. ser. præs. Mag.` sit a little right of the modal
    # edge for reasons that are not a paragraph -- a quotation mark that starts
    # outside the measure, a word the panel gave a wide box.
    #
    # A paragraph also *ends*, and it ends with a short line. So an opener has
    # to be indented **and** follow a line that does not fill the measure. Those
    # are 7, 2 and 16 lines on leaves 137, 145 and 153, which is the right order
    # of magnitude for a page of prose.
    live = [n for n, line in enumerate(lines) if line["text"].strip()]
    widths = [lines[n]["bbox"][2] - lines[n]["bbox"][0] for n in live]
    if not widths:
        return set()
    measure = statistics.median(widths)
    ends = {live[i] for i, w in enumerate(widths) if w < measure * SHORT}
    middle = centred(lines, live)
    opens = set()
    for i, n in enumerate(live):
        indented = (lines[n]["bbox"][0]
                    - base.get(lines[n].get("column", 0), 0) > INDENT)
        # A centred line is a heading, and the body resumes under it. Both are
        # paragraph openers whatever the indent says, which matters because the
        # indent is the test the scan's skew defeats: on leaf 484 the left edge
        # of a column slides from 0.133 to 0.127 down the page, so the modal
        # edge sits in the middle and a real indent at the foot measures short.
        #
        # A run of centred lines is **one** heading and not one each: leaf 373
        # sets `Las honrres feren los magnífichs Jurats per dit / Sr. Rey Phelip
        # segon á 27 de Janer / del any 1599.` over three, and the `Historia de
        # los Reyes` heads its chapters `D.a VIOLANTE / REINA VIUDA DE
        # MALLORCA.` So only the first of a run opens, and so does the line that
        # ends it.
        was = live[i - 1] in middle if i else False
        if (n in middle) != was:
            opens.add(n)
        elif indented and (i == 0 or live[i - 1] in ends
                           or lines[n]["bbox"][0]
                           - base.get(lines[n].get("column", 0), 0) > CLEAR):
            opens.add(n)
    return opens


# A line laid centred inside its own column, which in a justified measure no
# line of body text is: the deposition headings of `Declaracions en la causa
# criminal` (`Declaració de Amet, cochero de Berga.`), the chapter headings of
# `Historia de los Reyes de Mallorca` (`D.a VIOLANTE / REINA VIUDA DE
# MALLORCA.`), the numeral over each of Centellas' letters, and the bare years
# in the diaries. This is the same signal `parse_documents.title_after` uses to
# find where a section's title ends, asked one level down.
CENTRED = 0.010      # how unequal the two margins may be
# 0.95 rather than 0.90, and the threshold is not delicate: over the 187
# document leaves, moving it from 0.90 to 0.95 admits **six** further lines --
# `Declaració de Mn. Juan Miquel Pre. sobre lo matex.`, `LO REY DARAGO E DE LES
# DOS`, two lines of the 1541 Latin verse, a ledger row and one line of a
# three-line heading -- and moving it on to 0.97 admits none at all.
NOT_FULL = 0.95      # …and how much narrower than the measure it must be
OFF_MARGIN = 0.015   # …and how far off its column's edge, more than an indent


def centred(lines: list[dict], live: list[int]) -> set[int]:
    """Lines that are centred in their column rather than set to its measure."""
    by_column: dict[int, list[int]] = {}
    for n in live:
        by_column.setdefault(lines[n].get("column", 0), []).append(n)
    out: set[int] = set()
    for rows in by_column.values():
        if len(rows) < 6:            # too few lines to say what the measure is
            continue
        left = statistics.median(lines[n]["bbox"][0] for n in rows)
        right = statistics.median(lines[n]["bbox"][2] for n in rows)
        measure = right - left
        if measure <= 0:
            continue
        for n in rows:
            x0, x1 = lines[n]["bbox"][0], lines[n]["bbox"][2]
            if (x1 - x0 <= measure * NOT_FULL and x0 - left > OFF_MARGIN
                    and abs((x0 - left) - (right - x1)) <= CENTRED):
                out.add(n)
    return out


# A month opening a notice and followed by its day: `MARZO 14.—Publicacion de
# la Real órden`. Campaner sets these in small caps throughout, and the engines
# return the small capital sometimes as a capital and sometimes as a minuscule,
# so the same heading arrives as `MARZO`, `Marzo`, `MARzO` and `MaRzo`. Checked
# against the facsimile on leaves 627 and 605: `MARZO` and `JUNIO` are set the
# same way, and the variation is ours and not the book's.
#
# Rendering small capitals as capitals is the ordinary convention and is what
# 74 of these 115 headings already show. It is a typographic transform like the
# hyphen stitching, not an editorial rule -- no letter is chosen, only its case,
# and the case is what the page prints.
MONTH_HEAD = re.compile(
    r"^(enero|febrero|marzo|abril|mayo|junio|julio|agosto|setiembre"
    r"|septiembre|octubre|noviembre|diciembre)"
    r"(?=\s+(?:[0-9IilJ]|[.,]?\s*[-—–]))", re.IGNORECASE)


# Campaner sets a wavy rule under a section's title, and it comes through as a
# paragraph of its own reading `—` or `——`. Checked against the facsimile on
# both leaves it survives on -- 236 and 632 -- and it is the same squiggle in
# the same place: under the title, above the first year.
#
# The guard is not the count but the predicate. A paragraph with no letter and
# no digit in it carries no reading of anything, so there is nothing to lose by
# dropping it and nothing to recover by keeping it. Two in all 23 documents.
FURNITURE = re.compile(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]*")


# …and the dash that follows the day in the same heading. The page sets it tight
# against the stop -- `MARZO 28.—El Virrey`, checked on leaf 632 -- and 111 of
# the 117 headings in the documents already read that way; the other six carry a
# space the engines put there, five as `— ` and one as a plain hyphen. Same
# category as the case above: no character is chosen, only whether a space the
# printer did not set survives, and the shape of the mark the page prints.
DAY_MARK = re.compile(r"^((?:{})\s+[0-9]{{1,2}}\s*[.,]?)\s*[-—–]\s*"
                      .format("|".join(
                          ("enero", "febrero", "marzo", "abril", "mayo",
                           "junio", "julio", "agosto", "setiembre",
                           "septiembre", "octubre", "noviembre", "diciembre"))),
                      re.IGNORECASE)


# Campaner numbers the pieces inside a document -- each of Gilaberto de
# Centellas' letters to Pedro IV, each of the executions of June 1523 -- and
# sets the number alone and centred over the piece it opens. That numbering is
# the only thing that delimits a letter, and it took the centred-line rule to
# see it: `CLAUDE.md` recorded the section as having "20 salutations against
# only 3 numbered pieces", because the reading order had buried the other
# eighteen inside the prose.
#
# The number is two characters of display type standing alone, which is the
# worst case this book offers a recogniser, and the winner collapses on five of
# Centellas' twenty-one: leaf 125 published `*` for `4.*`, leaf 126 `.*` for
# `5.*`, leaf 128 `*` for `7.*`, and leaf 125's `3.` was swallowed by the
# salutation that follows it. So the number is read off the panel.
#
# **The sequence is the guard, not the vote.** One reading is enough, because a
# candidate has to take its place in a run that rises and rises by no more than
# three -- the same constraint `parse_documents.py` puts on a section numeral,
# which must be the *next* number and not merely a later one. Measured over all
# 23 documents, that separates completely: two documents have a series (19 and
# 20 members) and no other reaches five candidates in a row. Without the step
# cap, leaf 356's `42` -- a figure inside the 1541 reprint, 25 leaves past the
# last execution -- joined the run; without excluding `hanging_numbers`, leaf
# 152's ten marginal node numbers looked like a series of their own.
PIECE_MARK = re.compile(r"^\s*([0-9]{1,2})\s*[.,]?\s*[*°º'’‘]?\s*$")
PIECE_LOOKALIKE = str.maketrans({"I": "1", "i": "1", "l": "1", "|": "1",
                                 "O": "0", "o": "0", "S": "5", "T": "7"})
PIECE_WIDTH = 0.25   # of its column's measure: a numeral standing on its own
PIECE_STEP = 3       # how many lost numbers a run may jump
PIECE_RUN = 5        # how many members before it is a series and not a coincidence
LETTER = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def piece_votes(line: dict) -> Counter:
    """What number, if any, the panel says this line is."""
    votes: Counter = Counter()
    for word in line["row"]:
        for reading in list(word["variants"].values()) + [word["winner"]]:
            found = PIECE_MARK.match((reading or "").translate(PIECE_LOOKALIKE))
            if found:
                votes[int(found.group(1))] += 1
    return votes


def numbered_pieces(lines: list[dict]) -> dict[int, int]:
    """Line index -> the number Campaner prints over the piece it opens."""
    hanging = hanging_numbers(lines)
    candidates: list[tuple[int, int]] = []
    by_leaf: dict[tuple[int, int], list[int]] = {}
    for n, line in enumerate(lines):
        if line["text"].strip():
            by_leaf.setdefault(
                (line.get("leaf", 0), line.get("column", 0)), []).append(n)
    for rows in by_leaf.values():
        if len(rows) < 6:
            continue
        measure = statistics.median(lines[n]["bbox"][2] - lines[n]["bbox"][0]
                                    for n in rows)
        for n in rows:
            width = lines[n]["bbox"][2] - lines[n]["bbox"][0]
            if n in hanging or width > measure * PIECE_WIDTH:
                continue
            votes = piece_votes(lines[n])
            if votes:
                candidates.append((n, votes.most_common(1)[0][0]))
    candidates.sort()
    numbers = [number for _n, number in candidates]
    best = [1] * len(numbers)
    prev = [-1] * len(numbers)
    for i in range(len(numbers)):
        for j in range(i):
            if (numbers[j] < numbers[i] <= numbers[j] + PIECE_STEP
                    and best[j] + 1 > best[i]):
                best[i], prev[i] = best[j] + 1, j
    if not numbers:
        return {}
    end = max(range(len(numbers)), key=lambda i: best[i])
    run = []
    while end != -1:
        run.append(end)
        end = prev[end]
    if len(run) < PIECE_RUN:
        return {}
    return {candidates[i][0]: candidates[i][1] for i in run}


def piece_heading(line: dict, number: int) -> str:
    """The best reading an engine gave of this piece's number."""
    readings = Counter(
        reading
        for word in line["row"]
        for reading in list(word["variants"].values()) + [word["winner"]]
        if reading and PIECE_MARK.match(reading.translate(PIECE_LOOKALIKE))
        and int(PIECE_MARK.match(
            reading.translate(PIECE_LOOKALIKE)).group(1)) == number)
    if not readings:
        return f"{number}."
    digits = str(number)
    return min(readings, key=lambda r: (not r.startswith(digits),
                                        -readings[r], len(r)))


def small_caps(paragraph: str) -> str:
    """A display month heading, set as the page sets it."""
    match = MONTH_HEAD.match(paragraph)
    if match:
        paragraph = (paragraph[:match.start(1)] + match.group(1).upper()
                     + paragraph[match.end(1):])
    return DAY_MARK.sub(lambda m: m.group(1) + "—", paragraph)


# Four of the 23 sections are diaries and set a bare year over each stretch, the
# same display type the chronicle heads its years with -- and it is the type the
# engines read worst, so the winner regularly collapses. Section II of the 18th
# century published `171`, `1`, `1` and `1 781.` for 1711, 1751, 1755 and 1781,
# and `1795` for `1795.`
#
# This is the chronicle's own rule -- *ask the panel, not the winner* -- applied
# where the same typography does the same damage. It recovers from evidence and
# not by substituting characters: the year has to be what three of the eight
# readings state, and the string published has to be one an engine returned.
# `heading_votes` and `years_in` are imported rather than reimplemented, so a
# heading is read one way in this book and not two.
YEAR_ONLY = re.compile(r"^[\s0-9IilOoJ.,·•*'’‘\"«»_\-—–]{1,12}$")


def year_heading(line: dict) -> str | None:
    """The year this line states, in the best reading an engine gave of it."""
    if not YEAR_ONLY.match(line["text"].strip()):
        return None
    votes = heading_votes(line["row"])
    if not votes:
        return None
    year, count = votes.most_common(1)[0]
    if count < MIN_YEAR_VOTES:
        return None
    readings = Counter(reading
                       for word in line["row"]
                       for reading in list(word["variants"].values())
                       + [word["winner"]]
                       if reading and years_in(reading) == {year})
    if not readings:
        return None
    # Of the readings that state this year and nothing else, prefer the one that
    # is the year plainly -- `1711.` over `171 1.` and `I7II.` -- then the one
    # most engines gave. Both are readings; the tie-break is not a repair.
    digits = str(year)
    return min(readings,
               key=lambda r: (r.lstrip("0123456789") != r[len(digits):],
                              -readings[r], len(r)))


# A numeral the reading order dropped into the middle of a word. Leaf 123 sets
# the section's own `II.` centred above the second column, and sorting that
# column by y puts it between `…fo scap-` at the foot of the first and `sat, lo
# qual…` at the head of the second, so the edition published **`fo scapXX.
# sat`**. Leaf 152 did the same with three of the genealogical tree's marginal
# numbers -- `D. Fer17 rario`, `Montfer22 rato` -- and leaf 325 with two of its
# figures: `los ager18 » manats`.
#
# The line is not dropped, only moved past the word it interrupted: it is a
# reading of real ink and belongs in the text, just not inside a word.
#
# What says the join is real is that the line after the numeral **continues the
# word in lower case**. Over the whole book 14 numerals sit inside an apparent
# join and that test splits them 7 and 7 with nothing in between: `sat`,
# `rario`, `rato`, `nio`, `bores`, `manats`, `gents` against `«Los`, `Hasta`,
# `«Part`, `Fragmentos`, `FEBRERO`, `Agosto`, `I.` -- where the hyphen was a
# dash or the word ended at the foot of the column and the numeral is a heading
# in its own right.
WEDGE = re.compile(r"^[0-9IVXLCivxlc\W_]{1,6}$")
CONTINUES = re.compile(r"^[a-zà-öø-ÿ]")


def unwedge(lines: list[dict]) -> list[dict]:
    """Move a numeral out of the middle of a hyphenated word."""
    out = list(lines)
    live = [n for n, line in enumerate(out) if line["text"].strip()]
    for i in range(1, len(live) - 1):
        before, here, after = live[i - 1], live[i], live[i + 1]
        if (BREAK_HYPHEN.search(out[before]["text"].strip())
                and WEDGE.match(out[here]["text"].strip())
                and CONTINUES.match(out[after]["text"].strip())):
            out[here], out[after] = out[after], out[here]
    return out


def stitch(lines: list[dict]) -> tuple[str, list[int], list[int | None],
                                     list[bool]]:
    """Reading-order prose, the leaf each paragraph opens on, and its number.

    The leaf is carried out because a document runs across up to seventeen of
    them and the reader needs the same thing the chronicle gives: a way back to
    the page. One link at the head of a seventeen-leaf section only says where
    it starts. The number is Campaner's own, where the document is a numbered
    series -- the letters of Centellas, the executions of 1523.
    """
    lines = unwedge(lines)
    opens = paragraph_breaks(lines) | hanging_numbers(lines)
    hanging = hanging_numbers(lines)
    pieces = numbered_pieces(lines)
    # A paragraph that opens on a centred line is a heading, and the book has
    # many more of them than the section titles: `D.a VIOLANTE / REINA VIUDA DE
    # MALLORCA.` over a chapter of the `Historia`, `LECTOREM.`, `PROHEMI.` and
    # `LAUS DEO.` in the 1541 reprint, `EL REY.` and `Vt. Claver.` under a royal
    # cédula, `La Prosesó.` and `Autos de Fè.` over a stretch of a diary. They
    # were being set as ordinary paragraphs, which is why `audit_documents.py`
    # reported them as wreckage: 30 of its 47 runts are one of these.
    heads = centred_lines(lines)
    # Built as a list of paragraphs rather than as one string that is split
    # again afterwards: the leaf per paragraph is what the site's facsimile
    # links are keyed on, and joining and re-splitting let the two counts drift.
    paragraphs: list[list[str]] = []
    leaves: list[int] = []
    marks: list[int | None] = []
    titles: list[bool] = []
    hyphen = False          # did the line before end mid-word?
    for n, line in enumerate(lines):
        if n in pieces and not LETTER.search(line["text"]):
            # …but only where the slot holds the numeral and nothing else. On
            # leaf 125 the salutation's first word landed in the numeral's box,
            # so the winner is `«Molt` and one engine read `3*` behind it;
            # replacing the line there would delete a word to print a number.
            # The piece still opens here -- the site sets the number above it.
            text = piece_heading(line, pieces[n])
        else:
            text = year_heading(line) or line["text"].strip()
        if not text:
            continue
        # The number opens its entry, so it never continues the line before it
        # however that line ended -- and a piece's number opens its piece.
        if n in hanging or n in pieces:
            hyphen = False
        if hyphen:
            pass            # the word continues: no separator at all
        elif not paragraphs or n in opens or n in pieces:
            paragraphs.append([])
            leaves.append(line.get("leaf", 0))
            marks.append(pieces.get(n))
            titles.append(n in heads and n not in pieces)
        else:
            paragraphs[-1].append(" ")
        hyphen = bool(BREAK_HYPHEN.search(text))
        paragraphs[-1].append(BREAK_HYPHEN.sub("", text) if hyphen else text)

    kept = [(small_caps(re.sub(r"[ \t]+", " ", unicodedata.normalize(
        "NFC", "".join(parts))).strip()), leaf, mark, head)
        for parts, leaf, mark, head in zip(paragraphs, leaves, marks, titles)]
    kept = [row for row in kept
            if row[0] and not FURNITURE.fullmatch(row[0])]
    return ("\n\n".join(row[0] for row in kept) + "\n",
            [row[1] for row in kept], [row[2] for row in kept],
            [row[3] for row in kept])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    manifest_path = OUT / "documents.json"
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} missing -- run parse_documents.py")
    blocks = json.loads(manifest_path.read_text())

    repairs, _applied, _amb = editorial.long_s_repairs(
        source, editorial.long_s_leaves(source))

    # Leaves are read once; a leaf can carry the end of one section and the start
    # of the next, and re-reading it per section would double the work and the
    # footnote extraction with it.
    cache: dict[int, tuple[list[dict], list[dict]]] = {}

    def leaf(pdf_page: int) -> tuple[list[dict], list[dict]]:
        if pdf_page not in cache:
            path = source / f"p{pdf_page:04d}.json"
            if not path.exists():
                cache[pdf_page] = ([], [])
            else:
                lines = page_lines(path)
                for line in lines:
                    line["leaf"] = pdf_page
                body, notes = split_notes(lines)
                if pdf_page in BY_PRINTED_LINE:
                    body = by_printed_line(body)
                cache[pdf_page] = (body, gather_notes(notes) if notes else [])
        return cache[pdf_page]

    SECTIONS.mkdir(parents=True, exist_ok=True)
    catalogue: list[dict] = []
    for block in blocks:
        for index, section in enumerate(block["sections"]):
            if section.get("jurats"):
                continue                      # parse_jurats.py owns these
            start, end = span_of(block, index)
            lines: list[dict] = []
            notes: list[dict] = []
            for pdf_page in range(start[0], end[0] + 1):
                body, page_notes = leaf(pdf_page)
                first = start[1] if pdf_page == start[0] else 0
                last = end[1] if pdf_page == end[0] else len(body)
                chosen = body[first:last]
                if chosen:
                    lines.extend(chosen)
                    notes.extend(page_notes)

            if not lines:
                continue

            tiers = Counter()
            for line in lines:
                tiers += line["tiers"]
            words = sum(tiers.values())
            text, para_leaves, para_marks, para_heads = stitch(lines)
            # The section's own numeral, as `parse_documents.py` read it off the
            # panel rather than off the vote's winner. Display type is the class
            # the engines read worst -- leaf 316 prints `III.` and the winner
            # was `I XIX.`, having been offered `zz.`, `LL.` and `TIT.` -- and
            # the numeral was recovered there and then thrown away here, because
            # the text keeps the winner. The heading is the one place the
            # recovered reading has to win, since it is what the reader sees
            # first and the panel's own evidence says the winner is wrong.
            # The title is a heading whether or not the line under it was
            # indented, and on two sections it was not: leaf 316's VI ran its
            # title into 1 795 characters of body, and leaf 229's IV put the
            # numeral, the title and the first sentence in one paragraph.
            # `parse_documents.py` knows where the title ends -- it read it --
            # so the break is taken from there, and only the first paragraph is
            # touched, because rewriting the whole text collapses the paragraphs
            # that stitch has just found. All 23 come out with the title
            # standing free.
            #
            # Every edit below moves paragraphs, so `para_leaves` moves with
            # them. It did not: cutting one paragraph into three and prepending
            # the numeral each added a paragraph and no leaf, and **19 of the 23
            # documents were left one out of step**, so every `full N al
            # facsímil` link inside them named the leaf of the paragraph before.
            # A title runs to as many printed lines as it needs, and Campaner
            # indents its continuation -- `Algunas noticias é indicaciones
            # curiosas extraídas / de las que coleccionó el Pavorde Jaume.` --
            # so the paragraph rule now cuts it in two. The catalogue holds the
            # whole title, so the match is made against a run of up to three
            # opening paragraphs joined, and the run is replaced by one heading.
            paras = text.split("\n\n")
            flat = " ".join(section["title"].split())
            found = None
            for i in range(min(2, len(paras))):
                for j in range(i, min(i + 3, len(paras))):
                    one = " ".join(" ".join(paras[i:j + 1]).split())
                    lead = NUMERAL_HEAD.match(one)
                    body = one[lead.end():] if lead else one
                    if flat and body.startswith(flat):
                        found = (i, j, lead, body)
                        break
                if found:
                    break
            if found:
                i, j, lead, body = found
                cut = [lead.group(0).strip()] if lead else []
                # The numeral and the title are headings; whatever the same
                # paragraph carried after the title is the section's first
                # sentence and is not, which marking the whole splice `True`
                # got wrong on five sections -- `Ara oiats y veiats la
                # sentensia…` came out as a heading of 3 000 characters.
                pieces_of = [(x, True) for x in cut + [flat] if x]
                rest = body[len(flat):].lstrip()
                if rest:
                    pieces_of.append((rest, False))
                new = [x for x, _h in pieces_of]
                paras[i:j + 1] = new
                para_leaves[i:j + 1] = [para_leaves[i]] * len(new)
                para_marks[i:j + 1] = [None] * len(new)
                para_heads[i:j + 1] = [h for _x, h in pieces_of]

            head = paras[0] if paras else ""
            if ROMAN.fullmatch(head.strip()) and head.strip(". ") != section["numeral"]:
                paras[0] = f"{section['numeral']}."
            elif " ".join(head.split()) == " ".join(section["title"].split()):
                # The section opens on its title because its numeral sorted
                # elsewhere on the leaf -- leaf 123's `II.` is centred above the
                # title and lands in whichever column edge is nearer. The panel
                # recovered the numeral, so it is put back at the head where the
                # book prints it.
                paras.insert(0, f"{section['numeral']}.")
                para_leaves.insert(0, para_leaves[0] if para_leaves else start[0])
                para_marks.insert(0, None)
                para_heads.insert(0, True)

            # Last, because cutting the title free is what creates the commonest
            # one: the wavy rule under it arrives glued to the end of the title's
            # own paragraph and only becomes a paragraph here.
            kept = [row for row in zip(paras, para_leaves, para_marks,
                                       para_heads)
                    if row[0].strip() and not FURNITURE.fullmatch(row[0].strip())]
            paras = [row[0] for row in kept]
            para_leaves = [row[1] for row in kept]
            para_marks = [row[2] for row in kept]
            para_heads = [row[3] for row in kept]
            text = "\n\n".join(paras) + "\n"
            genre = GENRE.match(section["title"])

            name = (f"{block['first_leaf']:04d}-{section['numeral']}"
                    f"-{section['number']:02d}")
            # The file is what the book prints, from the section's first line to
            # its last, and nothing else -- the printed title stands at the head
            # of it already. Repeating the recorded title above it would put a
            # truncated copy of the same words in front of the real ones.
            (SECTIONS / f"{name}.txt").write_text(text, encoding="utf-8")
            catalogue.append({
                "id": name,
                "block_leaf": block["first_leaf"],
                "numeral": section["numeral"],
                "title": section["title"],
                "genre": genre.group(1) if genre else None,
                # A leaf carrying the end of one section and the start of the
                # next belongs to both, so these counts overlap by design.
                "first_leaf": start[0], "last_leaf": end[0],
                "leaves": end[0] - start[0] + 1,
                "words": words,
                # Which leaf each paragraph opens on, so the reader can get back
                # to the page from anywhere in a seventeen-leaf document.
                "paragraph_leaves": para_leaves,
                # Campaner's own numbering of the pieces inside the section,
                # where it has one: which paragraph opens piece N.
                "pieces": [{"number": m, "paragraph": i, "pdf_page": para_leaves[i]}
                           for i, m in enumerate(para_marks) if m is not None],
                # Paragraphs the book sets centred: a heading, not prose.
                "headings": [i for i, h in enumerate(para_heads) if h],
                "footnotes": len(notes),
                # …and the notes themselves, not only how many. They were being
                # separated from the body -- which is the hard half, and the
                # reason the documents read as prose at all -- and then counted
                # and dropped, so 62 notes came off the leaves and none of them
                # reached a page. Campaner's apparatus is where he says which
                # manuscript a passage is from and where he corrects it.
                "notes": [{"number": n["number"], "text": n["text"],
                           "pdf_page": n.get("leaf", start[0])} for n in notes],
                "certainty": {k: tiers[k] for k in
                              ("unanimous", "one-dissent", "two-dissent",
                               "contested")},
                "contested_share": round(tiers["contested"] / words, 4) if words
                else 0.0,
            })

    (OUT / "sections.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(c["words"] for c in catalogue)
    contested = sum(c["certainty"]["contested"] for c in catalogue)
    print(f"{len(catalogue)} documents assembled, {total:,} words, "
          f"{contested:,} contested ({contested/total:.1%})")
    print(f"{sum(c['footnotes'] for c in catalogue)} footnotes carried with them\n")
    print(f"{'id':16}{'leaves':>7}{'words':>8}{'contested':>11}  title")
    for c in catalogue:
        print(f"{c['id']:16}{c['leaves']:7d}{c['words']:8,}"
              f"{c['contested_share']:10.1%}  {c['title'][:52]}")

    if args.report:
        genres = Counter(c["genre"] for c in catalogue)
        print("\nby the noun Campaner opens the title with:")
        for genre, n in genres.most_common():
            print(f"  {n:2d}  {genre}")
        worst = sorted(catalogue, key=lambda c: -c["contested_share"])[:5]
        print("\nleast certain, and none of them is measured:")
        for c in worst:
            print(f"  {c['contested_share']:6.1%}  {c['id']}  {c['title'][:46]}")

    print(f"\n-> {SECTIONS}")


if __name__ == "__main__":
    main()
