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

from dataclasses import dataclass

# Tolerances in normalised page-width units (a two-column body leaf is ~567 pt
# wide, so 0.021 is the ~12 pt used when this was developed on PDF coordinates).
COLUMN_EDGE_TOLERANCE = 0.021
MIN_COLUMN_LINES = 8
MAX_BOUNDARY_CROSSING = 0.10
HEADER_BAND = 0.09   # top of the leaf: running head
FOOTER_BAND = 0.965  # bottom: the BNE watermark strip


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


def find_columns(lines: list[Line]) -> list[float]:
    """Left edge of each column, left to right. One entry means single-column."""
    if not lines:
        return [0.0]

    edges = sorted(ln.x0 for ln in lines)
    clusters: list[list[float]] = [[edges[0]]]
    for x in edges[1:]:
        if x - clusters[-1][-1] <= COLUMN_EDGE_TOLERANCE:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    candidates = [sum(c) / len(c) for c in clusters if len(c) >= MIN_COLUMN_LINES]
    if not candidates:
        return [0.0]

    lefts = [candidates[0]]
    for left in candidates[1:]:
        before = [ln for ln in lines if ln.x0 < left - COLUMN_EDGE_TOLERANCE]
        if not before:
            continue
        crossing = sum(1 for ln in before if ln.x1 > left + COLUMN_EDGE_TOLERANCE)
        if crossing / len(before) <= MAX_BOUNDARY_CROSSING:
            lefts.append(left)
    return lefts


def order(lines: list[Line], strip_furniture: bool = True
          ) -> tuple[list[Line], list[Line]]:
    """Sort into reading order. Returns (body lines, stripped furniture lines)."""
    furniture: list[Line] = []
    body = lines
    if strip_furniture:
        furniture = [ln for ln in lines
                     if ln.y1 <= HEADER_BAND or ln.y0 >= FOOTER_BAND]
        body = [ln for ln in lines
                if ln.y1 > HEADER_BAND and ln.y0 < FOOTER_BAND]

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
