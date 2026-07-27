"""Load and align the readings of a page produced by the different engines.

Two things make a naive text-vs-text comparison unfair here, and both are handled
before anything is measured:

* Line breaking is not a property of the text. Internet Archive's ABBYY reflows
  the column into running prose while the others keep the printed lines, so we
  compare token streams, not lines.
* Hyphenation at the line end is likewise typographic, not textual. The engines
  disagree about whether to emit a soft hyphen, a hyphen-minus or nothing at all,
  and counting that as an OCR error would drown the errors we actually care about.
  Line-final hyphens are therefore stitched before comparison, in every reading
  alike -- including the ground truth.

What is deliberately *not* normalised: accents, cedillas, case, and 1881 spelling.
Those are exactly what the benchmark is trying to measure.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"

# Running heads. Stripped from every reading so that a page number ABBYY misread
# as "6o2" is not counted twice -- once as a header error and once as content.
HEADER_RE = re.compile(r"^\s*(\d{1,3}\s*)?(MAYORICENSE\.?|CRONICON|INTRODUCCION\.?)"
                       r"(\s*\d{1,3})?\s*$", re.IGNORECASE)

SOFT_HYPHEN = "­"
HYPHENS = f"[-‐‑{SOFT_HYPHEN}]"
# Stitch a break hyphen whether the engine kept the line break (Tesseract, Apple
# Vision, the BNE ABBYY layer) or reflowed the column into running prose and left
# the hyphen followed by a space (the Internet Archive ABBYY layer does this).
# Em and en dashes are deliberately not in HYPHENS: the Cronicon uses them to
# separate entries, and joining across one would destroy real structure.
LINE_END_HYPHEN = re.compile(rf"{HYPHENS}\s+")


def normalise(text: str) -> str:
    """Canonical form for comparison: NFC, stitched hyphens, collapsed space."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ")
    lines = [ln for ln in text.split("\n") if not HEADER_RE.match(ln)]
    text = "\n".join(lines)
    text = LINE_END_HYPHEN.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def tokens(text: str) -> list[str]:
    return normalise(text).split()


# --- engine catalogue -------------------------------------------------------

def available_readings(pdf_page: int) -> dict[str, str]:
    """All engine readings for this page, keyed by engine id.

    Read from data/ocr/ordered/, i.e. after scripts/build_ordered.py has imposed
    the same column order on every engine. Comparing the engines' own output
    order measures their layout analysis instead of their recognition.
    """
    suffix = f"_p{pdf_page:04d}.txt"
    return {path.name[: -len(suffix)]: path.read_text(encoding="utf-8")
            for path in sorted((OCR / "ordered").glob(f"*{suffix}"))}



# --- alignment --------------------------------------------------------------

def align_to_reference(reference: list[str], other: list[str]) -> list[str | None]:
    """Map `other` onto `reference` positions.

    Returns a list as long as `reference`; each slot holds the token `other` has
    at that position, or None where it has nothing. Tokens `other` has in excess
    are appended to the preceding slot, joined by a space, so nothing is silently
    discarded -- an engine that invents text must be visible as a mismatch, not
    disappear into the alignment.
    """
    out: list[str | None] = [None] * len(reference)
    matcher = SequenceMatcher(a=reference, b=other, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = other[j1 + k]
        elif tag == "replace":
            span = other[j1:j2]
            for k in range(i1, i2):
                idx = k - i1
                out[k] = span[idx] if idx < len(span) else None
            if len(span) > (i2 - i1) and i2 > i1:
                out[i2 - 1] = " ".join(span[i2 - i1 - 1:])
        elif tag == "delete":
            pass  # reference has tokens `other` lacks: leave them None
        elif tag == "insert" and i1 > 0:
            extra = " ".join(other[j1:j2])
            out[i1 - 1] = f"{out[i1 - 1]} {extra}" if out[i1 - 1] else extra
    return out


def alignment_table(readings: dict[str, list[str]], reference_key: str
                    ) -> tuple[list[str], dict[str, list[str | None]]]:
    reference = readings[reference_key]
    table = {key: (list(reference) if key == reference_key
                   else align_to_reference(reference, toks))
             for key, toks in readings.items()}
    return reference, table
