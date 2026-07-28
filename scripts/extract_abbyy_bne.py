"""Extract the ABBYY reading embedded in the BNE PDF for the pilot pages.

The PDF was produced by ABBYY FineReader Server and carries a full text layer with
word boxes, so this reading costs nothing to obtain. It has no per-word confidence
-- that information was not kept when the layer was written into the PDF -- which
is precisely why the consensus stage cannot rely on this engine alone.

Only the positioned lines are produced here. Reading order is imposed later, by
scripts/layout.py, using the same algorithm for every engine.

Usage:
  python scripts/extract_abbyy_bne.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz

import targets
from pilot_pages import CLASS_OF

PROJECT = Path(__file__).resolve().parent.parent
PDF = PROJECT / "data" / "raw" / "Cronicon-mayoricense.pdf"
OUT = PROJECT / "data" / "ocr" / "abbyy_bne"


def page_lines(page: fitz.Page) -> list[dict]:
    """Lines with their boxes, in PDF points, unordered.

    The per-word boxes are kept as well as the line they compose. They cost
    nothing -- PyMuPDF returns them and an earlier version threw them away when
    grouping -- and they make this engine usable as a source of *geometry*, not
    only of text. That matters on the annotated Jurats leaves, where Tesseract
    returns nothing at all right of x 0.47 and the whole column of notes on which
    manuscript gives which name is absent from the panel; ABBYY read it.
    """
    words = page.get_text("words")  # x0, y0, x1, y1, word, block, line, word_no
    grouped: dict[tuple[int, int], list] = {}
    for w in words:
        grouped.setdefault((w[5], w[6]), []).append(w)

    lines = []
    for ws in grouped.values():
        ws.sort(key=lambda w: w[0])
        lines.append({
            "text": " ".join(w[4] for w in ws),
            "bbox": [min(w[0] for w in ws), min(w[1] for w in ws),
                     max(w[2] for w in ws), max(w[3] for w in ws)],
            "words": [{"text": w[4], "bbox": [w[0], w[1], w[2], w[3]]}
                      for w in ws],
        })
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="pilot",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(PDF)
    pages = targets.resolve(args.pages)
    for n, pdf_page in enumerate(pages, 1):
        page_class = CLASS_OF.get(pdf_page, "")
        page = doc[pdf_page]
        lines = page_lines(page)
        name = f"bne_p{pdf_page:04d}"
        (OUT / f"{name}.json").write_text(json.dumps({
            "pdf_page": pdf_page,
            "page_class": page_class,
            "page_width": page.rect.width,
            "page_height": page.rect.height,
            "lines": lines,
        }, ensure_ascii=False, indent=1))
        if args.quiet:
            if n % 100 == 0 or n == len(pages):
                print(f"  [{n:4d}/{len(pages)}]")
            continue
        print(f"  p{pdf_page:04d} [{page_class:14s}] {len(lines):3d} lines")
    doc.close()


if __name__ == "__main__":
    main()
