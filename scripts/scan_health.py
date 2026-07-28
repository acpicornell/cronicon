"""Which of the two scans is legible on each leaf.

The benchmark's headline finding was that the scan matters more than the engine
and that the Internet Archive one (~630 dpi) beats the BNE one (200 dpi) on every
comparison. That is true *on average* and false on a short run of leaves, and the
panel that builds the edition reads five of its six votes on the IA scan -- so
where that scan is bad, five sixths of the evidence is noise.

Leaf 98 is the clear case. The IA image is out of focus; the BNE one is pristine.
Apple Vision on the BNE scan reads `frumentarios en grano y especie, sin que`
while Tesseract on the IA scan returns `sos.fnímentarios en' grano y.cspecig,
:$in- que` and ABBYY-IA returns `sosüfriímeh torras ai grano’ y' . es’p cci p,`.
Those four leaves alone carry 1 909 of the 24 607 contested positions.

**How the defect is found.** Not by an image statistic -- sharpness measures are
confounded by how much ink is on the leaf, and a threshold tuned on a handful of
pages is a threshold tuned on a handful of pages. It is found by asking each
recogniser to read *both* scans and comparing it against itself:

    abbyy-ia   vs  abbyy-bne
    tess-ia    vs  tess-bne
    vision-ia  vs  vision-bne

Same recogniser, same leaf, different image. Whatever makes the text hard --
dense type, a table of figures, worn plates -- makes it hard on both, and cancels
in the difference. What does not cancel is a defect in one scan.

The quantity compared is the share of tokens that are **malformed**: a token
whose core, once leading and trailing punctuation is stripped, still contains
something that is not a letter, a digit, an apostrophe, a hyphen or an ordinal
mark. `sos.fnímentarios`, `y.cspecig,` and `:$in-` are malformed; `frumentarios`,
`Sr.`, `1.º` and `B. J.` are not. It needs no lexicon and no language, which
matters on a book that quotes Catalan and Latin.

Usage:
  python scripts/scan_health.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

import targets

PROJECT = Path(__file__).resolve().parent.parent
ORDERED = PROJECT / "data" / "ocr" / "ordered"
OUT = PROJECT / "data" / "scan_health.json"

# One pair per recogniser family, each reading the same leaf off a different scan.
PAIRS = [
    ("abbyy-ia", "abbyy-bne"),
    ("tess-ia-300dpi-spa_old-cat-lat-psm3", "tess-bne-400dpi-spa_old-psm3"),
    ("vision-ia-300dpi-corr", "vision-bne-400dpi-corr"),
]

LETTERS = "A-Za-zÁÉÍÓÚÜÑáéíóúüñÇçÀÈÒàèòïÏſ"
EDGE = re.compile(rf"^[^{LETTERS}0-9]+|[^{LETTERS}0-9]+$")
MALFORMED = re.compile(rf"[^{LETTERS}0-9'’\-ºª]")

# Below this a leaf is a plate, a blank or a title page: the rate is noise.
MIN_TOKENS = 50
# How far apart the two scans must read before the difference is a defect rather
# than the ordinary few tenths of a point between two images of the same page.
# Measured: 607 of 611 leaves sit inside ±1 point.
THRESHOLD = 0.03


def malformed_rate(engine: str, pdf_page: int) -> float | None:
    path = ORDERED / f"{engine}_p{pdf_page:04d}.txt"
    if not path.exists():
        return None
    tokens = path.read_text(encoding="utf-8").split()
    if len(tokens) < MIN_TOKENS:
        return None
    bad = 0
    for token in tokens:
        core = EDGE.sub("", token)
        if core and MALFORMED.search(core):
            bad += 1
    return bad / len(tokens)


def leaf_health(pdf_page: int) -> dict | None:
    """The paired difference on one leaf, and which scan it says to trust.

    A pair only counts when both its engines produced enough text; a leaf needs
    two of the three pairs, so one engine dropping the leaf entirely cannot
    decide the question on its own.
    """
    deltas: list[float] = []
    per_pair: dict[str, float] = {}
    for ia, bne in PAIRS:
        a, b = malformed_rate(ia, pdf_page), malformed_rate(bne, pdf_page)
        if a is None or b is None:
            continue
        per_pair[ia.split("-")[0]] = round(a - b, 4)
        deltas.append(a - b)
    if len(deltas) < 2:
        return None

    delta = statistics.median(deltas)
    prefer = "bne" if delta > THRESHOLD else "ia" if delta < -THRESHOLD else None
    return {"pdf_page": pdf_page, "delta": round(delta, 4),
            "per_pair": per_pair, "prefer": prefer}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="all",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    leaves = [h for h in (leaf_health(p) for p in targets.resolve(args.pages))
              if h is not None]
    flipped = {h["pdf_page"]: h for h in leaves if h["prefer"]}

    OUT.write_text(json.dumps({
        "threshold": THRESHOLD,
        "pairs": [list(p) for p in PAIRS],
        "leaves_measured": len(leaves),
        # Only the leaves that fail the test are listed. A file naming every leaf
        # would invite reading a preference into the 99% that show no difference,
        # and there is none to read: the two scans are equivalent there.
        "prefer": {str(p): h["prefer"] for p, h in sorted(flipped.items())},
        "detail": [h for h in leaves if h["prefer"]],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{len(leaves)} leaves measured, {len(flipped)} where the scans differ "
          f"by more than {THRESHOLD:.0%}")
    for page, health in sorted(flipped.items()):
        worse = "IA" if health["prefer"] == "bne" else "BNE"
        print(f"  p{page:4d}  {worse} scan worse by {abs(health['delta']):5.1%}"
              f"   -> read the {health['prefer'].upper()} scan"
              f"   {health['per_pair']}")

    if args.report:
        ranked = sorted(leaves, key=lambda h: -abs(h["delta"]))
        print("\nlargest differences, whether or not they cross the threshold:")
        for health in ranked[:20]:
            print(f"  p{health['pdf_page']:4d}  {health['delta']:+7.2%}"
                  f"   {health['per_pair']}")
        inside = sum(1 for h in leaves if abs(h["delta"]) <= 0.01)
        print(f"\n{inside} of {len(leaves)} leaves read within 1 point on both "
              f"scans, which is what makes the outliers outliers.")

    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
