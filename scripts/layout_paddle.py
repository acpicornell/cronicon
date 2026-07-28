"""Ask a layout detector where the columns are, on the leaves that defeat ours.

`layout.find_columns` clusters line left edges and rejects a boundary the text
crosses. That works on 589 of 614 leaves and is circular on the other 25: a line
Tesseract merged across the gutter hides the boundary that would have separated
it, so whether the finder sees two columns depends on how badly each engine
merged, and the engines disagree. Nothing inside the column finder can break that
circle, because the evidence it needs is the evidence that is missing.

PP-DocLayout is a region detector run on the *image*. It has no idea what any
engine read, so it is independent evidence about the geometry in exactly the sense
the panel is independent evidence about the characters. That is the whole argument
for trying it, and it is why this is not a generative step: the model draws boxes,
it does not write text, and the six recognisers still vote on what is inside them.

**The test was fixed before it was run**, because a layout that looks plausible on
a leaf nobody has checked is not a result:

  1. On the twelve pilot leaves, whose column counts are known and agreed by every
     engine, it must get all twelve right. A detector that cannot do the easy
     cases cannot be trusted on the hard ones.
  2. On leaves 115-121 it must separate the column of names from the column of
     notes, which is the specific thing our finder cannot see.

## The verdict: passes the first test, fails the second, not adopted

**12/12 on the control**, including leaf 631's three-column name list, which is
the case our own finder gets right only by accident. It is a competent detector
and it is genuinely independent of what the engines read.

**And it does not answer the question we have.** On 7 of the 25 disputed leaves --
59, 60, 115, 117, 118, 120 and the rest of the annotated Jurats -- it returns a
single `content` region spanning x 0.148 to 0.895, and on 119 and 163 a single
`table` doing the same. That is not a failure of the model. A table *is* one
region, and saying so is a region detector's job; decomposing it into columns is
a different model's. Ours needs the decomposition.

`TableCellsDetection` is that other model and does not help either: it ships the
*wired* detector, trained on tables drawn with rules, and Campaner's tables are
set typographically with no rules at all. It finds one cell on leaf 631 and
sixteen on 115, most of them the braces.

What it does get right is the prose: two columns on ten of the disputed body
leaves, and three on leaf 312 exactly where they are. That makes it usable as an
**independent check** on `layout.find_columns` for running text, which is worth
having and is not what it was tried for. Nothing in the pipeline consumes it
today.

Usage:
  .venv-paddle/bin/python scripts/layout_paddle.py --pages pilot
  .venv-paddle/bin/python scripts/layout_paddle.py --pages disputed
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

PROJECT = Path(__file__).resolve().parent.parent
PAGES = PROJECT / "data" / "pages" / "ia"
LAYOUT_HEALTH = PROJECT / "data" / "layout_health.json"
OUT = PROJECT / "data" / "ocr" / "layout_paddle"

IA_OFFSET = -2
DPI = "300dpi"

# The twelve leaves the adjudications sit on: known column counts, agreed by
# every engine. The control group.
PILOT = [14, 17, 20, 30, 34, 36, 50, 200, 627, 629, 631, 642]
PILOT_COLUMNS = {14: 1, 17: 1, 20: 1, 30: 2, 34: 2, 36: 2, 50: 2, 200: 2,
                 627: 2, 629: 2, 631: 3, 642: 1}

# Regions that carry running text. Headers, footers, figures and the like are
# detected too and are not part of the column structure.
TEXT_LABELS = {"text", "table", "list", "paragraph_title", "abstract"}
# Two regions belong to the same column when their horizontal spans overlap by
# this fraction of the narrower one. A gutter is ~0.02 of the page; a paragraph
# indent is far less, so this does not have to be delicate.
OVERLAP = 0.5
# A region wider than this *may* be laid across the columns rather than being one
# -- a centred heading, a rule, a caption. Leaf 631 has one such line and it fused
# all three columns of the Jurats table into one; the detector had found them
# correctly and the merge threw it away.
#
# But on a single-column leaf the text region is legitimately that wide, so width
# alone cannot decide it. What separates the two cases is how much of the leaf the
# *narrow* regions account for: on leaf 631 they are the whole table, on leaf 14
# they are a drop cap and a footnote marker. Discard the wide ones only when the
# narrow ones carry the page.
SPANNING = 0.6
NARROW_SHARE = 0.6


def leaf_image(pdf_page: int) -> Path:
    return PAGES / f"leaf{pdf_page + IA_OFFSET:04d}_{DPI}.png"


def columns_from(boxes: list[dict], width: float) -> list[tuple[float, float]]:
    """Merge the text regions' horizontal spans into columns, left to right.

    Counting columns by projecting the spans and taking connected components,
    rather than by clustering left edges: a heading centred over two columns has
    a left edge belonging to neither, and this book puts one over every year of
    the annotated Jurats lists.
    """
    text = [b for b in boxes if b["label"] in TEXT_LABELS]
    if not text:
        return []

    def area(b) -> float:
        x0, y0, x1, y1 = b["coordinate"]
        return abs(x1 - x0) * abs(y1 - y0)

    narrow = [b for b in text if (b["coordinate"][2] - b["coordinate"][0])
              / width <= SPANNING]
    total = sum(area(b) for b in text)
    if narrow and total and sum(area(b) for b in narrow) >= NARROW_SHARE * total:
        text = narrow

    spans = sorted((b["coordinate"][0] / width, b["coordinate"][2] / width)
                   for b in text)
    merged = [list(spans[0])]
    for x0, x1 in spans[1:]:
        last = merged[-1]
        overlap = min(x1, last[1]) - max(x0, last[0])
        if overlap > OVERLAP * min(x1 - x0, last[1] - last[0]):
            last[1] = max(last[1], x1)
            last[0] = min(last[0], x0)
        else:
            merged.append([x0, x1])
    return [(round(a, 4), round(b, 4)) for a, b in merged]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="disputed",
                    help="disputed | pilot | both | comma-separated page numbers")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    disputed = (json.loads(LAYOUT_HEALTH.read_text())["align_by_line"]
                if LAYOUT_HEALTH.exists() else [])
    if args.pages == "disputed":
        pages = list(disputed)
    elif args.pages == "pilot":
        pages = list(PILOT)
    elif args.pages == "both":
        pages = sorted(set(disputed) | set(PILOT))
    else:
        pages = [int(p) for p in args.pages.split(",")]

    from PIL import Image
    from paddleocr import LayoutDetection
    model = LayoutDetection()

    OUT.mkdir(parents=True, exist_ok=True)
    results: dict[int, list] = {}
    for page in pages:
        image = leaf_image(page)
        if not image.exists():
            print(f"  p{page:4d}  no image")
            continue
        with Image.open(image) as im:
            width, height = im.size
        boxes = []
        for res in model.predict(str(image), batch_size=1):
            data = res.json if hasattr(res, "json") else res
            data = data.get("res", data)
            boxes = data.get("boxes") or []
        columns = columns_from(boxes, width)
        results[page] = columns
        (OUT / f"p{page:04d}.json").write_text(json.dumps({
            "pdf_page": page, "columns": len(columns), "spans": columns,
            "regions": [{"label": b["label"], "score": round(b["score"], 3),
                         "bbox": [b["coordinate"][0] / width,
                                  b["coordinate"][1] / height,
                                  b["coordinate"][2] / width,
                                  b["coordinate"][3] / height]}
                        for b in boxes],
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    control = [p for p in results if p in PILOT_COLUMNS]
    right = [p for p in control if len(results[p]) == PILOT_COLUMNS[p]]
    if control:
        print(f"\nControl -- the twelve pilot leaves, whose column count is known:")
        for page in sorted(control):
            mark = "ok " if page in right else "NO "
            print(f"  {mark} p{page:4d}  detector says {len(results[page])}, "
                  f"the book has {PILOT_COLUMNS[page]}   {results[page]}")
        print(f"  {len(right)}/{len(control)} correct"
              + ("" if len(right) == len(control) else
                 "  -- fails the precondition, do not trust the rest"))

    hard = [p for p in results if p in disputed]
    if hard:
        print(f"\nThe {len(hard)} leaves our column finder cannot settle:")
        for page in sorted(hard):
            print(f"  p{page:4d}  {len(results[page])} columns  {results[page]}")

    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
