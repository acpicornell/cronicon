"""Shared reading order: turn a bag of positioned lines into ordered text.

Every engine reports where on the leaf it found each line, but each one orders
its output differently -- Tesseract and ABBYY follow their own layout analysis,
Apple Vision returns observations in no guaranteed order at all. Comparing those
raw outputs measures layout analysis, not character recognition, and on these
two-column leaves that difference swamps everything else.

So the same algorithm is applied to all of them: cluster line left edges into
columns, then read each column top to bottom. Coordinates are normalised to
[0,1] with a top-left origin first, so PDF points, image pixels and Vision's
bottom-left normalised boxes all go through the same code.

The column finder is the one developed in extract_abbyy_bne.py: cluster the left
edges, then reject any candidate boundary that the text actually crosses, which
is what separates a real column break from a paragraph indent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Tolerances in normalised page-width units (a two-column body leaf is ~567 pt
# wide, so 0.021 is the ~12 pt used when this was developed on PDF coordinates).
COLUMN_EDGE_TOLERANCE = 0.021
MIN_COLUMN_LINES = 8
MAX_BOUNDARY_CROSSING = 0.10
# A line this wide is laid *across* the columns rather than sitting in one --
# `SIGLO XIII. / DE 1229 Á 1300.` and the source note beneath it, which open
# every century. Such a line crosses every boundary by definition, and counting
# it as text that crosses meant four heading lines could veto a gutter the
# other thirty lines respected. Leaf 28 -- the first leaf of the chronicle --
# was read as one column and its two columns interleaved line by line.
SPANNING_WIDTH = 0.55
# Width alone does not catch all of them, and leaf 64 is the proof: `SIGLO XIV.`
# is 0.547 wide, `DE 1301 Á 1400.` 0.476 and the last line of the century's
# source list 0.396, so all three counted as column text, all three crossed the
# gutter, and 3 of 27 is 11% -- just over the 10% a boundary is allowed. Leaf 64
# was read as one column, its two columns interleaved line by line, and the
# whole of 1301 was published under 1300 in prose reading `mandó al Gobernador y
# JuraGa`. A line centred on the measure is laid across it whatever its width.
CENTRED_TOLERANCE = 0.06
# But on a single wide column almost every line is that wide, and discounting
# them all leaves a handful of short ones to invent a boundary that is not
# there. Only discount the wide lines when the narrow ones carry the page.
NARROW_SHARE = 0.6
HEADER_BAND = 0.09   # top of the leaf: running head
FOOTER_BAND = 0.965  # bottom: the BNE watermark strip

# The foot of every eighth leaf carries the gathering signature: a bare `I`,
# `2`, `13`, set alone under the right column so the binder can order the
# quires. It is printer's furniture like the running head, and because it is the
# last thing in the reading order it glues onto whatever ends the leaf -- the
# footnote on leaf 28, the first leaf of the chronicle, came out
# `…el adjetivo «otros» ó «varios.» I`.
#
# What proves these are signatures rather than stray readings is arithmetic: the
# rule fires on 61 leaves and every one of them is at pdf_page ≡ 4 (mod 8), the
# quire boundary, with no exception anywhere in the 614 leaves of text.
#
# Dropped at assembly and deliberately not in `consensus.py`: removing a token
# there renumbers the leaf, and the frozen adjudication sample is keyed by index
# as well as by box. Leaf 36 carries a signature and is one of its twelve.
SIGNATURE_BAND = 0.895
SIGNATURE_LEFT = 0.70
SIGNATURE = re.compile(r"^[IVXLl0-9]{1,4}\s*[.,]?$")


def is_signature(text: str, line_bbox) -> bool:
    """Is this line the gathering signature? Ask only of a leaf's last line."""
    return bool(line_bbox[1] > SIGNATURE_BAND and line_bbox[0] > SIGNATURE_LEFT
                and SIGNATURE.match(text.strip()))


# The head of the leaf carries the folio number, and `consensus.py` drops the
# running head *by content* -- the line has to say `CRONICON` or `MAYORICENSE.`
# So where the engines cut the head into two line boxes, the words are dropped
# and **the number survives**, and being first in the reading order it glues
# onto whatever opens the leaf: leaf 43 published `16 que el estado de la
# iglesia de…`. The appendices are worse, because there Campaner prints the
# number and nothing else, so no rule anywhere had ever seen them.
#
# What proves these are folios and not text is the same kind of arithmetic that
# proves the signatures: **all 109 of them state `pdf_page - 27`, and each sits
# on the side of the leaf its parity requires** -- an even printed page at the
# left, an odd one at the right -- with no exception in the 614 leaves of text.
# The fifteen other bare numbers in the band are all four digits and all year
# headings at the top of a column (`1497.`, `1700.`, `1788.`), which is why the
# rule is written for one to three digits and checks the number it reads.
#
# Dropped at assembly, like the signature and for the same reason: removing a
# token in `consensus.py` renumbers the leaf and the frozen sample is keyed by
# index as well as by box.
FOLIO_BAND = 0.10
FOLIO_OFFSET = 27          # printed page = pdf_page - 27, over leaves 43-637
FOLIO = re.compile(r"^\s*([0-9IilOo]{1,3})\s*[.,]?\s*$")
FOLIO_LOOKALIKE = str.maketrans({"I": "1", "i": "1", "l": "1",
                                 "O": "0", "o": "0"})


def is_folio(text: str, line_bbox, pdf_page: int) -> bool:
    """Is this line the printed page number at the head of the leaf?"""
    match = FOLIO.match(text.strip())
    if not match or line_bbox[1] >= FOLIO_BAND:
        return False
    digits = match.group(1).translate(FOLIO_LOOKALIKE)
    printed = pdf_page - FOLIO_OFFSET
    if not digits.isdigit() or int(digits) != printed:
        return False
    # A verso's number stands at the left of the measure and a recto's at the
    # right. Requiring it costs nothing -- all 109 agree -- and it is what keeps
    # a stray figure at the top of a table column from being read as a folio.
    return (line_bbox[0] < 0.5) == (printed % 2 == 0)


# The other half of the head, for the leaves where `consensus.py`'s
# content-based drop does not recognise it. It matches on the word and not on
# the string, because six of the twelve survivors are `MAYORISENCE.` -- the
# engines swapping the `C` and the `S` -- and one is `MAYORISENCE.121` with the
# folio run into it. 12 leaves in the book, 11 of which this removes; the
# twelfth is leaf 98's `MAYORICENSE. sos`, where the trailing letters are wreck-
# age off the defective scan rather than part of the head, and are left to the
# review queue rather than guessed at.
HEAD_WORDS = ("MAYORICENSE", "CRONICON", "INTRODUCCION")
HEAD_SLACK = 2


def is_running_head(text: str) -> bool:
    """Is this line the running head, however the engines spelt it?"""
    letters = "".join(
        c for c in unicodedata.normalize("NFD", text.upper())
        if "A" <= c <= "Z")
    if len(letters) < 6:
        return False
    return any(len(letters) == len(word)
               and sum(a != b for a, b in zip(letters, word)) <= HEAD_SLACK
               for word in HEAD_WORDS)


def drop_folio(loci: list[dict]) -> list[dict]:
    """`loci` without the head of the leaf: its folio number and its title."""
    if not loci:
        return loci
    pdf_page = loci[0]["pdf_page"]
    drop: set[tuple] = set()
    for locus in loci:
        box = tuple(locus["line_bbox"])
        if box[1] >= FOLIO_BAND or box in drop:
            continue
        line = [x for x in loci if tuple(x["line_bbox"]) == box]
        text = " ".join(x["winner"] for x in line if x["winner"]).strip()
        if is_folio(text, box, pdf_page) or is_running_head(text):
            drop.add(box)
    return [x for x in loci if tuple(x["line_bbox"]) not in drop]


# Campaner's ledgers set the label and the figure on **one printed line**, with
# leader dots between them: `manats. . . . . . . . 18 »  »`. The engines cut
# that line in two -- the dots are a wide gap, which is exactly what a line
# segmenter looks for -- so the figure arrives as a line of its own, sorts by
# its own y, and lands anywhere from the middle of the label to after it. Read
# as prose the ledger came out as `A Juliá Valera, altre dels sargents majors.`
# followed by a paragraph reading `41 »`, which is what `audit_documents.py`
# ranked first and second in the whole corpus.
#
# The join is between two line boxes that **overlap in y, sit in the same
# column, and where the right-hand one is nothing but a figure**. All three are
# needed and the third is what makes it safe: over the 614 leaves it fires 25
# times on 7 leaves and every one is a ledger row. Without the same-column test
# it also joins leaf 152's marginal node numbers to the entry beside them and
# every line of column one to the line facing it in column two.
#
# Nothing is dropped, reordered or rewritten: the two boxes become one line, so
# the words that were printed on one line are on one line again. That is also
# what lets `tables.py` see these at all -- it asks each printed line whether it
# is a row, and here the row had been cut in half.
LEDGER_FIGURE = re.compile(
    r"^[\s.,·•]*\d[\d.,\s]*\d?[\s.,]*"
    r"(?:»|\"|ls\.?|ss\.?|ds\.?|libs?\.?|lbs?\.?|id\.?|cuarteras?)?[\s.,»]*$",
    re.IGNORECASE)
LEDGER_YEAR = re.compile(r"\s*1[2-8]\d\d\s*[.,]?\s*")
LEDGER_OVERLAP = 0.6      # of the shorter box's height


def only_a_figure(text: str) -> bool:
    """Is this line a figure and nothing else -- a ledger's right-hand cell?"""
    text = text.strip()
    return (bool(text) and bool(LEDGER_FIGURE.match(text))
            and not LEDGER_YEAR.fullmatch(text))


def join_leaders(loci: list[dict]) -> list[dict]:
    """Put a ledger's figure back on the printed line that leads to it."""
    if not loci:
        return loci
    lines: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for locus in loci:
        key = tuple(locus["line_bbox"])
        if key not in lines:
            order.append(key)
            lines[key] = []
        lines[key].append(locus)

    lefts = find_columns([Line(text="", x0=k[0], y0=k[1], x1=k[2], y1=k[3])
                          for k in order])

    def column_of(key) -> int:
        return max((n for n, left in enumerate(lefts)
                    if key[0] >= left - COLUMN_EDGE_TOLERANCE), default=0)

    def text_of(key) -> str:
        return " ".join(x["winner"] for x in lines[key] if x["winner"]).strip()

    merged: dict[tuple, tuple] = {}
    for key in order:
        if not only_a_figure(text_of(key)):
            continue
        column, best, most = column_of(key), None, 0.0
        for other in order:
            if other == key or column_of(other) != column:
                continue
            if other[2] > key[0] or only_a_figure(text_of(other)):
                continue          # must be to its left, and be the label
            share = min(other[3], key[3]) - max(other[1], key[1])
            height = min(other[3] - other[1], key[3] - key[1])
            if height > 0 and share > most and share >= LEDGER_OVERLAP * height:
                best, most = other, share
        if best is not None:
            merged[key] = best

    if not merged:
        return loci
    labels = {label: key for key, label in merged.items()}
    out = []
    for locus in loci:
        key = tuple(locus["line_bbox"])
        other = merged.get(key) or labels.get(key)
        if other is None:
            out.append(locus)
            continue
        locus = dict(locus)
        locus["line_bbox"] = [min(other[0], key[0]), min(other[1], key[1]),
                              max(other[2], key[2]), max(other[3], key[3])]
        # The two boxes are one printed line again, so the words on it read
        # left to right -- and in the stream they often do not, because the
        # figure's box begins a hair above the label's and sorts before it:
        # leaf 325 published `41 » gents majors.` and `18 manats.` The index is
        # left alone, since `build_text` keys its editorial repairs on it and
        # `review.py` its decisions on the box.
        locus["leader"] = True
        out.append(locus)
    return out


def line_order(row: list[dict]) -> list[dict]:
    """A line's loci in reading order: by index, or by x on a rejoined line."""
    if any(x.get("leader") for x in row):
        return sorted(row, key=lambda x: (x["bbox"][0], x["index"]))
    return sorted(row, key=lambda x: x["index"])


def drop_signature(loci: list[dict]) -> list[dict]:
    """`loci` without the gathering signature, if the leaf ends in one.

    The loci arrive in reading order, so the signature is the last line: it sits
    at the foot of the right-hand column, which is where the leaf ends.
    """
    if not loci:
        return loci
    last = tuple(loci[-1]["line_bbox"])
    tail = [x for x in loci if tuple(x["line_bbox"]) == last]
    text = " ".join(x["winner"] for x in tail if x["winner"]).strip()
    if not is_signature(text, last):
        return loci
    return [x for x in loci if tuple(x["line_bbox"]) != last]


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    column: int = 0


def normalise_boxes(lines: list[dict], page_width: float, page_height: float,
                    origin: str = "top-left") -> list[Line]:
    """Convert engine-native line boxes into normalised top-left coordinates.

    `origin` is "top-left" for PDF/image pixel coordinates and "bottom-left" for
    Apple Vision, which reports normalised boxes measured up from the foot.
    """
    out: list[Line] = []
    for ln in lines:
        x0, y0, x1, y1 = ln["bbox"]
        if origin == "bottom-left":
            y0, y1 = 1.0 - y1, 1.0 - y0
        else:
            x0, x1 = x0 / page_width, x1 / page_width
            y0, y1 = y0 / page_height, y1 / page_height
        if ln["text"].strip():
            out.append(Line(ln["text"], x0, y0, x1, y1))
    return out


def across_measure(line: Line, left: float, right: float) -> bool:
    """Is this line laid across the page rather than sitting inside a column?

    True for a full-width line and for a centred one -- the century banners, the
    short last line of a paragraph set across the measure -- and false as soon
    as the text is in a column, which has a wide margin on one side and none on
    the other.
    """
    if line.x1 - line.x0 >= SPANNING_WIDTH:
        return True
    return abs((line.x0 - left) - (right - line.x1)) <= CENTRED_TOLERANCE


def find_columns(lines: list[Line]) -> list[float]:
    """Left edge of each column, left to right. One entry means single-column."""
    if not lines:
        return [0.0]

    left_edge = min(ln.x0 for ln in lines)
    right_edge = max(ln.x1 for ln in lines)
    edges = sorted(ln.x0 for ln in lines)
    clusters: list[list[float]] = [[edges[0]]]
    for x in edges[1:]:
        if x - clusters[-1][-1] <= COLUMN_EDGE_TOLERANCE:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    # The column's edge is where its leftmost line starts, not the mean of its
    # cluster. Leaf 152 -- the `ESPLICACION DEL ÁRBOL` of the genealogical
    # plate -- prints each entry's node number hanging in the margin of its
    # column, so the second column's edges run 0.485 to 0.555 and the mean falls
    # at 0.529, *inside* the column. Every number then sat left of the boundary,
    # was assigned to the first column, and sorted by y among its prose:
    # `…conquistó á Mallorca y Menorca.— IO En 1231 las dá en cambio…`.
    #
    # Safe by measurement: over all 614 leaves the minimum changes no leaf's
    # column *count*. It only moves a boundary within its own column, which is
    # where a hanging number, a paragraph's outdent or a display initial lives.
    candidates = [min(c) for c in clusters if len(c) >= MIN_COLUMN_LINES]
    if not candidates:
        return [0.0]

    lefts = [candidates[0]]
    for left in candidates[1:]:
        before = [ln for ln in lines if ln.x0 < left - COLUMN_EDGE_TOLERANCE]
        if not before:
            continue
        narrow = [ln for ln in before
                  if not across_measure(ln, left_edge, right_edge)]
        body = narrow if len(narrow) >= NARROW_SHARE * len(before) else before
        if not body:
            continue
        crossing = sum(1 for ln in body if ln.x1 > left + COLUMN_EDGE_TOLERANCE)
        if crossing / len(body) <= MAX_BOUNDARY_CROSSING:
            lefts.append(left)
    return lefts


def order(lines: list[Line], strip_furniture: bool = True,
          single_column: bool = False) -> tuple[list[Line], list[Line]]:
    """Sort into reading order. Returns (body lines, stripped furniture lines).

    `single_column` reads straight down the page instead of column by column.
    That is wrong for prose and right for the annotated Jurats lists, where the
    year label `AÑO 1282.` is centred *between* the column of names and the
    column of notes: splitting the leaf into columns puts every label after
    every name it heads, and the names are then filed under no year at all.
    """
    furniture: list[Line] = []
    body = lines
    if strip_furniture:
        furniture = [ln for ln in lines
                     if ln.y1 <= HEADER_BAND or ln.y0 >= FOOTER_BAND]
        body = [ln for ln in lines
                if ln.y1 > HEADER_BAND and ln.y0 < FOOTER_BAND]

    if single_column:
        for ln in body:
            ln.column = 0
        body.sort(key=lambda ln: (ln.y0, ln.x0))
        return body, furniture

    lefts = find_columns(body)
    for ln in body:
        ln.column = max((i for i, left in enumerate(lefts)
                         if ln.x0 >= left - COLUMN_EDGE_TOLERANCE), default=0)
    body.sort(key=lambda ln: (ln.column, ln.y0, ln.x0))
    return body, furniture


def ordered_text(lines: list[dict], page_width: float, page_height: float,
                 origin: str = "top-left") -> tuple[str, int]:
    """Convenience wrapper: engine-native lines in, ordered text + column count."""
    body, _ = order(normalise_boxes(lines, page_width, page_height, origin))
    ncols = len({ln.column for ln in body}) if body else 0
    return "\n".join(ln.text for ln in body), ncols
