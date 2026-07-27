"""Impose one reading order on every engine's output.

Each engine is asked only for *positioned lines*; the column split and the
top-to-bottom order come from scripts/layout.py, identically for all of them.
Without this, comparing the engines measures their layout analysis rather than
their character recognition -- on these two-column leaves the first disagreement
survey came out at 40% of tokens, almost all of it column interleaving rather
than misread characters.

Writes data/ocr/ordered/<engine>_p<page>.txt, which is what the benchmark reads.

Usage:
  python scripts/build_ordered.py
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from PIL import Image

import argparse

import layout
import targets

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
PAGES = PROJECT / "data" / "pages"
OUT = OCR / "ordered"

IA_OFFSET = -2
MIN_WORD_CONF = 0  # keep everything; the consensus stage weighs confidence later


def from_abbyy_bne(pdf_page: int) -> tuple[list[dict], float, float, str] | None:
    path = OCR / "abbyy_bne" / f"bne_p{pdf_page:04d}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    return d["lines"], d["page_width"], d["page_height"], "top-left"


def from_abbyy_ia(pdf_page: int) -> tuple[list[dict], float, float, str] | None:
    path = OCR / "abbyy_ia" / f"ia_p{pdf_page:04d}.json"
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    lines = [{"text": " ".join(w["text"] for w in ln["words"]), "bbox": ln["bbox"]}
             for ln in d["lines"] if ln["words"]]
    return lines, d["page_width"], d["page_height"], "top-left"


def from_tesseract(path: Path) -> tuple[list[dict], float, float, str] | None:
    """Rebuild lines from the TSV, which carries one row per word with its box."""
    tsv = path.with_suffix(".tsv")
    if not tsv.exists():
        return None
    grouped: dict[tuple, list] = defaultdict(list)
    with tsv.open(encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row.get("level") != "5":
                continue
            text = (row.get("text") or "").strip()
            if not text:
                continue
            key = (row["block_num"], row["par_num"], row["line_num"])
            left, top = int(row["left"]), int(row["top"])
            grouped[key].append((left, top, left + int(row["width"]),
                                 top + int(row["height"]), text))

    lines = []
    for words in grouped.values():
        words.sort(key=lambda w: w[0])
        lines.append({
            "text": " ".join(w[4] for w in words),
            "bbox": [min(w[0] for w in words), min(w[1] for w in words),
                     max(w[2] for w in words), max(w[3] for w in words)],
        })

    image = image_for_tesseract(path)
    if image is None:
        return None
    with Image.open(image) as im:
        width, height = im.size
    return lines, width, height, "top-left"


def image_for_tesseract(path: Path) -> Path | None:
    scan, page, rest = path.stem.split("_", 2)
    dpi = rest.split("_", 1)[0]
    pdf_page = int(page[1:])
    if scan == "bne":
        candidate = PAGES / "bne" / f"p{pdf_page:04d}_{dpi}.png"
    else:
        candidate = PAGES / "ia" / f"leaf{pdf_page + IA_OFFSET:04d}_{dpi}.png"
    return candidate if candidate.exists() else None


def from_kraken(pdf_page: int) -> tuple[list[dict], float, float, str] | None:
    """The book-specific Kraken model, read at the panel's own line boxes.

    Its boxes are already normalised -- it was handed the geometry rather than
    segmenting for itself -- so the page size is unity.
    """
    path = OCR / "kraken" / f"ia_p{pdf_page:04d}.json"
    if not path.exists():
        return None
    lines = json.loads(path.read_text())["lines"]
    return lines, 1.0, 1.0, "top-left"


def from_vision(path: Path) -> tuple[list[dict], float, float, str] | None:
    d = json.loads(path.read_text())
    lines = [{"text": ln["text"],
              "bbox": [ln["x"], ln["y"], ln["x"] + ln["w"], ln["y"] + ln["h"]]}
             for ln in d]
    # Vision reports normalised boxes with the origin at the bottom left
    return lines, 1.0, 1.0, "bottom-left"


def engines_for(pdf_page: int) -> dict[str, tuple]:
    out: dict[str, tuple] = {}
    got = from_abbyy_bne(pdf_page)
    if got:
        out["abbyy-bne"] = got
    got = from_abbyy_ia(pdf_page)
    if got:
        out["abbyy-ia"] = got

    for path in sorted((OCR / "tesseract").glob(f"*_p{pdf_page:04d}_*.txt")):
        scan, _page, rest = path.stem.split("_", 2)
        dpi, tail = rest.split("_", 1)
        lang, psm = tail.rsplit("_", 1)
        got = from_tesseract(path)
        if got:
            out[f"tess-{scan}-{dpi}-{lang}-{psm}"] = got

    for path in sorted((OCR / "vision").glob(f"*_p{pdf_page:04d}_*.json")):
        scan, _page, dpi, mode = path.stem.split("_")
        got = from_vision(path)
        if got:
            out[f"vision-{scan}-{dpi}-{mode}"] = got

    got = from_kraken(pdf_page)
    if got:
        out["kraken-cronicon"] = got

    # already normalised: these were handed the panel's own line boxes
    for folder, name in (("paddle", "paddle-ppocrv6"),
                         ("paddle_latin", "paddle-latin")):
        path = OCR / folder / f"ia_p{pdf_page:04d}.json"
        if path.exists():
            out[name] = (json.loads(path.read_text())["lines"],
                         1.0, 1.0, "top-left")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="pilot",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    pages = targets.resolve(args.pages)
    for n, pdf_page in enumerate(pages, 1):
        report = []
        for name, (lines, w, h, origin) in engines_for(pdf_page).items():
            body, _furniture = layout.order(
                layout.normalise_boxes(lines, w, h, origin))
            text = "\n".join(ln.text for ln in body)
            ncols = len({ln.column for ln in body}) if body else 0
            stem = OUT / f"{name}_p{pdf_page:04d}"
            stem.with_suffix(".txt").write_text(text, encoding="utf-8")
            # boxes are kept alongside the text so the adjudication step can crop
            # the facsimile at the line it is asking about
            stem.with_suffix(".json").write_text(json.dumps({
                "engine": name, "pdf_page": pdf_page, "columns": ncols,
                "lines": [{"text": ln.text, "column": ln.column,
                           "bbox": [ln.x0, ln.y0, ln.x1, ln.y1]} for ln in body],
            }, ensure_ascii=False, indent=1))
            report.append(f"{name}:{ncols}c")
        if args.quiet:
            if n % 100 == 0 or n == len(pages):
                print(f"  [{n:4d}/{len(pages)}]  {len(report)} engines")
            continue
        print(f"  p{pdf_page:04d} " + "  ".join(report))


if __name__ == "__main__":
    main()
