"""Leaves where the engines do not agree how the page is laid out.

The panel's whole design rests on every engine being asked about the same
position, and that in turn rests on them agreeing where the columns are. Usually
they do -- `layout.py` imposes one column-finding algorithm on all of them, and
on 589 of 614 leaves it returns the same answer for every engine.

On the other 25 it does not, and those leaves are the worst in the book: the
contested rate there averages **21.96%** against **4.70%** everywhere else. The
cause is circular and cannot be broken from inside the column finder.
`layout.find_columns` refuses a boundary that more than a tenth of the lines
cross, so a line that Tesseract merged across the gutter -- leaf 312 opens
`Pedro Descatlar. Alfonso`, one box from x 0.10 to 0.81 -- hides the very
boundary that would have separated it. Whether the finder sees two columns then
depends on how badly each engine merged, and the engines disagree.

Disagreeing about the layout is worse than getting it wrong, because a shared
mistake still leaves every engine answering the same question. This file names
the leaves where they are answering different ones, which is where
`consensus.py --align line` earns its keep: matching a printed line against the
engine text that overlaps it removes reading order from the question entirely.

**It does not license accepting those leaves unread.** The 550 adjudications say
what unanimity is worth under the page-wide alignment; nothing says what it is
worth under this one, and no adjudicated position falls on any of these leaves.
`consensus.py` therefore marks them `accept_unanimous: false`, and everything on
them goes to review whatever tier it lands in, until a round of adjudication
covers them.

Usage:
  python scripts/layout_health.py --report
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import targets

PROJECT = Path(__file__).resolve().parent.parent
ORDERED = PROJECT / "data" / "ocr" / "ordered"
OUT = PROJECT / "data" / "layout_health.json"

# The production panel. Column counts are compared among the engines that
# actually vote: a disagreement between two readings nobody consults is not a
# problem with the leaf.
PANEL = [
    "abbyy-ia",
    "tess-ia-300dpi-spa_old-cat-lat-psm3",
    "vision-bne-400dpi-corr",
    "vision-ia-300dpi-corr",
    "paddle-ppocrv6",
    "kraken-cronicon",
]
MIN_ENGINES = 4


def columns_on(pdf_page: int) -> dict[str, int]:
    out: dict[str, int] = {}
    for engine in PANEL:
        path = ORDERED / f"{engine}_p{pdf_page:04d}.json"
        if path.exists():
            out[engine] = json.loads(path.read_text())["columns"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="all")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    measured, disputed = 0, {}
    for page in targets.resolve(args.pages):
        counts = columns_on(page)
        if len(counts) < MIN_ENGINES:
            continue
        measured += 1
        tally = Counter(counts.values())
        if len(tally) > 1:
            disputed[page] = {"pdf_page": page, "columns": dict(sorted(tally.items())),
                              "agreed": tally.most_common(1)[0][1],
                              "engines": len(counts)}

    # A leaf that carries adjudications is left page-aligned whatever its
    # engines disagree about. Aligning by line renumbers the leaf, and the
    # ground truth is keyed by index as well as by box, so switching leaf 642 --
    # which holds part of the frozen sample -- would orphan its decisions.
    # `consensus.py` refuses such a leaf outright; naming them here is the same
    # rule stated where it can be read. Lift this when `adjudicated.tsv` is
    # re-keyed by word box, not before.
    from consensus import adjudicated_leaves
    held = sorted(set(disputed) & adjudicated_leaves())
    for page in held:
        disputed[page]["held_for_adjudications"] = True

    OUT.write_text(json.dumps({
        "panel": PANEL,
        "leaves_measured": measured,
        "align_by_line": sorted(set(disputed) - set(held)),
        "held_for_adjudications": held,
        "detail": [disputed[p] for p in sorted(disputed)],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{measured} leaves measured, {len(disputed)} where the panel disagrees "
          f"how many columns the page has")
    for page in sorted(disputed):
        d = disputed[page]
        spread = "  ".join(f"{c}col×{n}" for c, n in d["columns"].items())
        print(f"  p{page:4d}  {spread}")

    if args.report:
        consensus = PROJECT / "data" / "ocr" / "consensus6_swap_swapk"
        if consensus.exists():
            rates = {}
            for page in targets.resolve(args.pages):
                path = consensus / f"p{page:04d}.json"
                if not path.exists():
                    continue
                grades = Counter(json.loads(path.read_text())["grades"])
                total = sum(grades.values())
                if total:
                    rates[page] = (grades["contested"], total)
            def mean(pages):
                c = sum(rates[p][0] for p in pages if p in rates)
                t = sum(rates[p][1] for p in pages if p in rates)
                return c / t if t else 0.0
            bad = set(disputed)
            good = [p for p in rates if p not in bad]
            print(f"\ncontested rate where the panel disagrees: {mean(bad):.2%}")
            print(f"contested rate where it agrees:           {mean(good):.2%}")

    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
