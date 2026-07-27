"""Align the BNE PDF pages with the Internet Archive leaves.

Both digitisations are of the same 1881 edition but have different leaf counts
(671 vs 667 images), so nothing can be assumed about a fixed offset. We match on
the *printed* page number: the BNE side reads it out of the running header in the
embedded ABBYY layer, the IA side takes it from `_page_numbers.json`.

The result is a mapping plus, for reporting, the offset distribution -- if the two
scans really are the same book with a constant lead-in difference, the offsets
collapse to one value and any page that disagrees is worth a look.

Usage:
  python scripts/align_scans.py                # build data/ia/leaf_map.json
  python scripts/align_scans.py --report
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import fitz

PROJECT = Path(__file__).resolve().parent.parent
PDF = PROJECT / "data" / "raw" / "Cronicon-mayoricense.pdf"
IA = PROJECT / "data" / "ia"
PAGE_NUMBERS = IA / "Cronicon_Mayoricense_Campaner_page_numbers.json"
OUT = IA / "leaf_map.json"

# The running header is "<page> CRONICON" on versos and "MAYORICENSE. <page>" on
# rectos, in the top ~7% of the page. ABBYY mangles the digits often enough
# (6oi for 601) that we only trust a header we can read cleanly.
HEADER_FRACTION = 0.09
ARABIC = re.compile(r"\b(\d{1,3})\b")
ROMAN = re.compile(r"\b([IVXLC]{1,7})\b")


def bne_printed_numbers() -> dict[int, str]:
    doc = fitz.open(PDF)
    out: dict[int, str] = {}
    for pno in range(doc.page_count):
        page = doc[pno]
        band = fitz.Rect(0, 0, page.rect.width, page.rect.height * HEADER_FRACTION)
        text = page.get_textbox(band)
        m = ARABIC.search(text)
        if m:
            out[pno] = m.group(1)
            continue
        m = ROMAN.search(text)
        if m and m.group(1) not in {"I", "C"}:  # too easily a stray initial
            out[pno] = m.group(1)
    doc.close()
    return out


def ia_printed_numbers() -> dict[int, str]:
    data = json.loads(PAGE_NUMBERS.read_text())
    return {p["leafNum"]: p["pageNumber"]
            for p in data["pages"] if p.get("pageNumber")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    bne = bne_printed_numbers()
    ia = ia_printed_numbers()
    ia_by_number: dict[str, list[int]] = {}
    for leaf, num in ia.items():
        ia_by_number.setdefault(num, []).append(leaf)

    mapping: dict[str, int] = {}
    offsets = Counter()
    ambiguous: list[tuple[int, str]] = []
    for pno, num in sorted(bne.items()):
        leaves = ia_by_number.get(num, [])
        if len(leaves) != 1:
            ambiguous.append((pno, num))
            continue
        mapping[str(pno)] = leaves[0]
        offsets[leaves[0] - pno] += 1

    OUT.write_text(json.dumps({
        "note": "BNE pdf page index (0-based) -> Internet Archive leaf number",
        "matched_on": "printed page number",
        "offsets": dict(offsets),
        "map": mapping,
    }, indent=1))

    print(f"BNE pages with a readable printed number: {len(bne)}")
    print(f"IA leaves with a printed number:          {len(ia)}")
    print(f"Matched one-to-one:                       {len(mapping)}")
    print(f"Ambiguous / unmatched:                    {len(ambiguous)}")
    print(f"Offset distribution (leaf - pdf_page):    {dict(offsets.most_common(8))}")
    if args.report and ambiguous:
        print("\nUnmatched BNE pages (page, printed number read):")
        for pno, num in ambiguous[:40]:
            print(f"  {pno:4d}  {num!r}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
