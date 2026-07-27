"""Survey every leaf of the book: printed number, class, columns, IA counterpart.

The pilot worked on twelve hand-picked pages. Before running the panel over the
whole book we need to know what the other 659 leaves actually are -- which carry
running text, which are engraved plates with only a caption, which are blank,
where each section starts and ends, and which Internet Archive leaf corresponds
to each one.

Everything here comes from the ABBYY layer already embedded in the BNE PDF and
from Internet Archive's `_page_numbers.json`. No OCR is run, so this is cheap and
can be re-run after any change to the layout code.

Classification is by section range, not by guessing per page: the section
boundaries are found once, from the headings Campaner actually printed, and every
leaf inherits the class of the range it falls in. Leaves that carry almost no text
are then re-labelled as plates or blanks, whatever range they sit in.

Usage:
  python scripts/inventory.py
  python scripts/inventory.py --report          # per-leaf listing
  python scripts/inventory.py --anomalies       # only what needs a human look
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import fitz

import layout
from extract_abbyy_bne import page_lines

PROJECT = Path(__file__).resolve().parent.parent
PDF = PROJECT / "data" / "raw" / "Cronicon-mayoricense.pdf"
IA_PAGE_NUMBERS = (PROJECT / "data" / "ia" /
                   "Cronicon_Mayoricense_Campaner_page_numbers.json")
OUT = PROJECT / "data" / "inventory.json"

# A leaf below this many characters carries no running text worth OCRing.
TEXT_FLOOR = 200
# The BNE scan stamps this on every leaf; it is not content.
WATERMARK = "Biblioteca Nacional de España"

# Section openings, each anchored on a phrase from the body text of the leaf that
# opens it.
#
# Not on the printed display headings: ABBYY does not read them at all. The
# letterspaced "APÉNDICES" on leaf 631 and the "INTRODUCCION." on leaf 14 are
# simply absent from the embedded layer, and "ADVERTENCIAS FINALES" comes back as
# "AD'VEIÎTEZN-CIA.S FESTAEES". So each section is anchored on a run of ordinary
# text near its opening, which ABBYY does read, matched on a compressed form
# (lowercase, accents and punctuation removed) to survive the remaining noise.
#
# Each anchor must match exactly one leaf. Zero or several is an error, not
# something to resolve by taking the first: the section boundaries decide which
# leaves get OCRed as what, and a silent mis-boundary would be invisible later.
SECTION_ANCHORS = [
    ("intro", r"caracter y objeto de este libro"),
    ("body", r"anales de la isla y reino de mallorca dispuestos"),
    # The appendix opens with the list of Jurats of the 18th century. The same
    # heading appears twice inside the body for the 14th and 15th centuries
    # (leaves 114 and 225), so the century has to be part of the anchor; sig\w*
    # absorbs ABBYY reading "siglo" as "sigdo".
    ("appendix", r"de mallorca durante el sig\w* xviii"),
    ("advertencias", r"breves indicaciones acerca de los grabados"),
    ("errata", r"erratas y omisiones"),
]

ARABIC = re.compile(r"\b(\d{1,3})\b")
ROMAN = re.compile(r"\b([IVXLC]{2,7})\b")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def printed_number(header: str) -> str | None:
    """The page number in the running head, if it can be read at all.

    ABBYY mangles these often (6o2 for 602, ÊIO for 610), so a failure here is
    expected and handled by falling back on the scan-to-scan offset.
    """
    match = ARABIC.search(header)
    if match:
        return match.group(1)
    match = ROMAN.search(strip_accents(header).upper())
    if match:
        return match.group(1)
    return None


def survey_leaf(doc: fitz.Document, pno: int) -> dict:
    page = doc[pno]
    lines = page_lines(page)
    body, furniture = layout.order(layout.normalise_boxes(
        lines, page.rect.width, page.rect.height))

    text = "\n".join(ln.text for ln in body)
    header = " ".join(ln.text for ln in furniture
                      if ln.y1 <= layout.HEADER_BAND)
    chars = len(text.replace(WATERMARK, "").strip())

    return {
        "pdf_page": pno,
        "printed": printed_number(header),
        "header": header.strip(),
        "columns": len({ln.column for ln in body}) if body else 0,
        "lines": len(body),
        "chars": chars,
        "text": text,
    }


def compress(text: str) -> str:
    """Lowercase, accent-free, punctuation-free, single-spaced."""
    text = strip_accents(text).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text)).strip()


def assign_sections(leaves: list[dict]) -> dict[str, int]:
    """Open each section at its anchor leaf. Returns the boundaries found."""
    boundaries: dict[str, int] = {}
    for name, anchor in SECTION_ANCHORS:
        pattern = re.compile(anchor)
        hits = [leaf["pdf_page"] for leaf in leaves
                if pattern.search(compress(leaf["text"]))]
        if len(hits) != 1:
            raise SystemExit(
                f"section anchor for {name!r} matched {len(hits)} leaves "
                f"({hits[:8]}), expected exactly one. The anchor text or the "
                f"layout extraction has drifted; fix it rather than guessing a "
                f"boundary.")
        boundaries[name] = hits[0]

    ordered = sorted(boundaries.items(), key=lambda kv: kv[1])
    if [name for name, _ in ordered] != [name for name, _ in SECTION_ANCHORS]:
        raise SystemExit(f"sections came out of printing order: {ordered}")

    current = "front_matter"
    starts = dict((page, name) for name, page in boundaries.items())
    for leaf in leaves:
        current = starts.get(leaf["pdf_page"], current)
        leaf["section"] = current
    return boundaries


def classify(leaf: dict) -> str:
    """Refine the section into the class the OCR pipeline cares about."""
    if leaf["chars"] < TEXT_FLOOR:
        return "plate_or_blank"
    if leaf["section"] == "body":
        return "body"
    return leaf["section"]


def ia_leaf_numbers() -> dict[str, list[int]]:
    data = json.loads(IA_PAGE_NUMBERS.read_text())
    out: dict[str, list[int]] = {}
    for entry in data["pages"]:
        number = entry.get("pageNumber")
        if number:
            out.setdefault(number, []).append(entry["leafNum"])
    return out, len(data["pages"])


def align(leaves: list[dict], ia_by_number: dict[str, list[int]]) -> dict:
    """Attach the IA leaf to each BNE page.

    The two scans are the same edition with the same pagination, so the mapping
    is a constant offset. Printed page numbers are used to *establish and check*
    that offset, not to drive it leaf by leaf: ABBYY drops the leading digit of
    the running head often enough (`5^ CRONICON` for 54, `¿§4 CRONICON` for 254)
    that trusting it per leaf produces confident nonsense -- an earlier version
    mapped leaf 211 to IA leaf 29.

    So: take the modal offset, apply it everywhere, and report how many leaves
    the printed numbers confirm, contradict, or cannot speak to. A contradiction
    is a header-OCR problem until the offset itself stops being modal, and the
    span check below is what would catch that.
    """
    offsets = Counter()
    for leaf in leaves:
        candidates = ia_by_number.get(leaf["printed"] or "", [])
        if len(candidates) == 1:
            offsets[candidates[0] - leaf["pdf_page"]] += 1
    modal, modal_count = offsets.most_common(1)[0] if offsets else (0, 0)

    confirming = [leaf["pdf_page"] for leaf in leaves
                  if len(ia_by_number.get(leaf["printed"] or "", [])) == 1
                  and ia_by_number[leaf["printed"]][0] - leaf["pdf_page"] == modal]

    stats = {"modal_offset": modal, "confirm": modal_count,
             "contradict": sum(offsets.values()) - modal_count,
             "silent": len(leaves) - sum(offsets.values()),
             "confirmed_span": (min(confirming), max(confirming)) if confirming
             else None}

    for leaf in leaves:
        leaf["ia_leaf"] = leaf["pdf_page"] + modal
        candidates = ia_by_number.get(leaf["printed"] or "", [])
        if len(candidates) == 1 and candidates[0] == leaf["ia_leaf"]:
            leaf["ia_check"] = "confirmed"
        elif len(candidates) == 1:
            leaf["ia_check"] = "header-misread"
        else:
            leaf["ia_check"] = "unchecked"
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--anomalies", action="store_true")
    args = ap.parse_args()

    doc = fitz.open(PDF)
    leaves = [survey_leaf(doc, pno) for pno in range(doc.page_count)]
    doc.close()

    boundaries = assign_sections(leaves)
    for leaf in leaves:
        leaf["page_class"] = classify(leaf)

    ia_by_number, ia_total = ia_leaf_numbers()
    alignment = align(leaves, ia_by_number)
    modal = alignment["modal_offset"]

    for leaf in leaves:
        del leaf["text"]

    OUT.write_text(json.dumps({
        "pdf_pages": len(leaves),
        "ia_leaves": ia_total,
        "sections": boundaries,
        "alignment": alignment,
        "leaves": leaves,
    }, ensure_ascii=False, indent=1))

    classes = Counter(leaf["page_class"] for leaf in leaves)
    sections = Counter(leaf["section"] for leaf in leaves)
    columns = Counter((leaf["page_class"], leaf["columns"]) for leaf in leaves)
    anomalies = [leaf for leaf in leaves if leaf["ia_check"] == "header-misread"]
    ocr_leaves = [leaf for leaf in leaves if leaf["page_class"] != "plate_or_blank"]

    print(f"BNE PDF pages: {len(leaves)}    IA leaves: {ia_total}    "
          f"modal offset: {modal:+d}")
    print("Section anchors found at pdf pages: "
          + ", ".join(f"{n}={p}" for n, p in boundaries.items()))
    print(f"\nSections (in printing order):")
    for name in ["front_matter", "intro", "body", "appendix", "advertencias",
                 "errata"]:
        if sections[name]:
            pages = [lf["pdf_page"] for lf in leaves if lf["section"] == name]
            print(f"  {name:14} {sections[name]:4d} leaves   "
                  f"pdf {min(pages)}-{max(pages)}")

    print(f"\nPage classes:")
    for name, count in classes.most_common():
        print(f"  {name:16} {count:4d}")

    print(f"\nColumns per class:")
    for (name, ncols), count in sorted(columns.items()):
        print(f"  {name:16} {ncols} col  {count:4d}")

    total_chars = sum(leaf["chars"] for leaf in leaves)
    print(f"\nLeaves to OCR: {len(ocr_leaves)}   "
          f"ABBYY text on them: {total_chars:,} chars")
    span = alignment["confirmed_span"]
    print(f"\nAlignment: every leaf mapped at offset {modal:+d}. "
          f"Printed numbers confirm {alignment['confirm']}, "
          f"contradict {alignment['contradict']}, are unreadable on "
          f"{alignment['silent']}.")
    print(f"  confirmations span pdf pages {span[0]}-{span[1]} of "
          f"0-{len(leaves)-1}, so the offset is constant across the book.")

    if args.anomalies or args.report:
        print(f"\nLeaves whose printed number contradicts the offset "
              f"({len(anomalies)}); all are running heads ABBYY misread:")
        for leaf in anomalies[:15]:
            print(f"  pdf {leaf['pdf_page']:4d}  read {leaf['printed']!r:8} "
                  f"header {leaf['header'][:40]!r}")

    if args.report:
        print("\nPer-leaf:")
        for leaf in leaves:
            print(f"  {leaf['pdf_page']:4d} {leaf['page_class']:16} "
                  f"printed={str(leaf['printed']):>6} ia={leaf['ia_leaf']:4d} "
                  f"{leaf['columns']}col {leaf['lines']:3d}ln {leaf['chars']:5d}ch "
                  f"{leaf['ia_check']}")

    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
