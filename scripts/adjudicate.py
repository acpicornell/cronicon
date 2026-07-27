"""Build the adjudication material for a pilot page.

For every printed line, collect what each engine read and mark the line as
contested if they do not all agree. Contested lines get a crop of the facsimile
at the highest resolution we hold, so the reading can be settled by looking at
the page rather than by reasoning about which engine is usually right.

Crops are laid out in review sheets of a few lines each, big enough to read the
diacritics that most of the disagreements turn on.

The reference engine supplies the line grid, so it must be one that preserves the
printed lines -- the Internet Archive ABBYY layer reflows the column into running
prose and cannot play this role.

Usage:
  python scripts/adjudicate.py --page 50
  python scripts/adjudicate.py --page 50 --sheet-lines 6
"""
from __future__ import annotations

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageDraw

from pilot_pages import CLASS_OF
from readings import available_readings

PROJECT = Path(__file__).resolve().parent.parent
ORDERED = PROJECT / "data" / "ocr" / "ordered"
PAGES = PROJECT / "data" / "pages"
OUT = PROJECT / "data" / "adjudication"

IA_OFFSET = -2
REFERENCE = "vision-ia-300dpi-corr"

PANEL = [
    "abbyy-bne",
    "abbyy-ia",
    "tess-bne-400dpi-spa_old-psm3",
    "tess-ia-300dpi-spa_old-psm3",
    "vision-bne-400dpi-corr",
    "vision-ia-300dpi-corr",
]

CROP_PAD_X = 0.004   # normalised padding around the line box
CROP_PAD_Y = 0.0035
SHEET_WIDTH = 1500   # px; crops are scaled to this width in the review sheet
LABEL_HEIGHT = 26


def reference_lines(pdf_page: int) -> list[dict]:
    path = ORDERED / f"{REFERENCE}_p{pdf_page:04d}.json"
    return json.loads(path.read_text())["lines"]


def line_spans(lines: list[dict]) -> list[tuple[int, int]]:
    """Token index range [start, end) of each reference line."""
    spans, cursor = [], 0
    for ln in lines:
        n = len(ln["text"].split())
        spans.append((cursor, cursor + n))
        cursor += n
    return spans


def project(reference: list[str], other: list[str]) -> list[list[str]]:
    """For each reference token position, the tokens `other` aligns to it."""
    out: list[list[str]] = [[] for _ in reference]
    matcher = SequenceMatcher(a=reference, b=other, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k].append(other[j1 + k])
        elif tag == "replace":
            span = other[j1:j2]
            width = max(1, i2 - i1)
            for k, token in enumerate(span):
                out[min(i1 + k, i1 + width - 1)].append(token)
        elif tag == "insert" and i1 > 0:
            out[i1 - 1].extend(other[j1:j2])
    return out


def source_image(pdf_page: int) -> Path:
    """The most detailed scan we hold of this leaf."""
    leaf = pdf_page + IA_OFFSET
    candidates = sorted((PAGES / "ia").glob(f"leaf{leaf:04d}_*dpi.png"),
                        key=lambda p: int(p.stem.split("_")[-1][:-3]), reverse=True)
    if candidates:
        return candidates[0]
    return sorted((PAGES / "bne").glob(f"p{pdf_page:04d}_*dpi.png"))[-1]


def crop_line(image: Image.Image, bbox: list[float]) -> Image.Image:
    x0, y0, x1, y1 = bbox
    w, h = image.size
    box = (max(0, int((x0 - CROP_PAD_X) * w)),
           max(0, int((y0 - CROP_PAD_Y) * h)),
           min(w, int((x1 + CROP_PAD_X) * w)),
           min(h, int((y1 + CROP_PAD_Y) * h)))
    return image.crop(box)


def build_sheets(pdf_page: int, contested: list[dict], sheet_lines: int) -> list[Path]:
    image = Image.open(source_image(pdf_page)).convert("L")
    sheets: list[Path] = []
    sheet_dir = OUT / f"p{pdf_page:04d}"
    sheet_dir.mkdir(parents=True, exist_ok=True)

    for start in range(0, len(contested), sheet_lines):
        chunk = contested[start:start + sheet_lines]
        crops = []
        for item in chunk:
            crop = crop_line(image, item["bbox"])
            scale = SHEET_WIDTH / crop.width
            crop = crop.resize((SHEET_WIDTH, max(1, round(crop.height * scale))),
                               Image.LANCZOS)
            crops.append(crop)

        height = sum(c.height + LABEL_HEIGHT for c in crops) + 10
        sheet = Image.new("L", (SHEET_WIDTH, height), 255)
        draw = ImageDraw.Draw(sheet)
        y = 5
        for item, crop in zip(chunk, crops):
            draw.text((6, y + 6), f"L{item['line']:03d}", fill=0)
            y += LABEL_HEIGHT
            sheet.paste(crop, (0, y))
            y += crop.height
            draw.line([(0, y - 1), (SHEET_WIDTH, y - 1)], fill=200)

        path = sheet_dir / f"sheet_{start // sheet_lines:02d}.png"
        sheet.save(path)
        sheets.append(path)
    return sheets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--sheet-lines", type=int, default=8)
    args = ap.parse_args()

    pdf_page = args.page
    lines = reference_lines(pdf_page)
    spans = line_spans(lines)

    readings = {k: v for k, v in available_readings(pdf_page).items() if k in PANEL}
    ref_tokens = " ".join(ln["text"] for ln in lines).split()
    projected = {k: project(ref_tokens, text.split())
                 for k, text in readings.items() if k != REFERENCE}

    contested: list[dict] = []
    agreed = 0
    for idx, (ln, (start, end)) in enumerate(zip(lines, spans)):
        variants = {REFERENCE: ln["text"]}
        for engine, cells in projected.items():
            variants[engine] = " ".join(
                tok for cell in cells[start:end] for tok in cell)
        distinct = {v.strip() for v in variants.values() if v.strip()}
        if len(distinct) <= 1:
            agreed += 1
            continue
        contested.append({"line": idx, "bbox": ln["bbox"], "column": ln["column"],
                          "variants": variants})

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "pdf_page": pdf_page,
        "page_class": CLASS_OF.get(pdf_page),
        "reference": REFERENCE,
        "panel": sorted(readings),
        "source_image": source_image(pdf_page).name,
        "lines_total": len(lines),
        "lines_agreed": agreed,
        "lines_contested": len(contested),
        "contested": contested,
    }
    (OUT / f"p{pdf_page:04d}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1))

    sheets = build_sheets(pdf_page, contested, args.sheet_lines)
    print(f"page {pdf_page} [{CLASS_OF.get(pdf_page)}]: {len(lines)} lines, "
          f"{agreed} unanimous, {len(contested)} contested "
          f"({len(contested)/max(1,len(lines)):.0%}) -> {len(sheets)} sheets")


if __name__ == "__main__":
    main()
