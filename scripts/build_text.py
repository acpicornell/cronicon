"""Assemble the consensus decisions into readable text.

The consensus stage produces a verdict per token position. This turns those into
prose: tokens joined in reading order, line-end hyphens stitched, columns
concatenated, running heads already gone.

Every word keeps its certainty tier alongside the text, because that is the whole
point of the pipeline and the edition should not throw it away. `.txt` is for
reading and grepping; `.json` carries the tiers so the site can shade doubtful
words and offer the facsimile crop.

What this deliberately does *not* do: tidy the book. 1881 orthography stands as
printed, and so do Campaner's own errors. The one thing it does change is the
long s of the 1541 facsimile on leaves 335-367, which five of the six engines
read as `f`; the rule lives in `editorial.py`, is documented in
`docs/EDITORIAL.md`, and every word it touches keeps what the panel voted for
under `printed`.

Usage:
  python scripts/build_text.py --consensus consensus6_swap_swapk
  python scripts/build_text.py --pages 50 --show
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import editorial
import targets

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
OUT = PROJECT / "data" / "text"

SOFT_HYPHEN = "­"
# Word-break hyphens only. Em and en dashes are structural in this book -- they
# separate entries and introduce the source sigla -- so joining across one would
# destroy the chronicle's own punctuation.
BREAK_HYPHEN = re.compile(rf"[-‐‑{SOFT_HYPHEN}]$")

TIER_MARK = {"unanimous": " ", "one-dissent": "·", "two-dissent": ":",
             "contested": "?"}


def assemble(loci: list[dict], repairs: dict | None = None
             ) -> tuple[str, list[dict]]:
    """Reading-order text, plus one record per word with its tier and box.

    `repairs` carries the editorial rules from `editorial.py`, keyed by (leaf,
    index). Where one applies, the word record keeps what the panel voted for
    under `printed` so that nothing is changed silently.
    """
    lines: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for locus in loci:
        key = tuple(locus["line_bbox"])
        if key not in lines:
            order.append(key)
        lines[key].append(locus)

    repairs = repairs or {}
    words: list[dict] = []
    pieces: list[str] = []
    for key in order:
        row = sorted(lines[key], key=lambda x: x["index"])
        chosen = [repairs.get((w["pdf_page"], w["index"]), w["winner"])
                  for w in row]
        text = " ".join(chosen).strip()
        for w, reading in zip(row, chosen):
            record = {"text": reading, "tier": w["grade"],
                      "bbox": w["bbox"], "line": list(key)}
            if reading != w["winner"]:
                record["printed"] = w["winner"]
            words.append(record)
        if not text:
            continue
        if BREAK_HYPHEN.search(text):
            # the word continues on the next line: drop the hyphen and glue
            pieces.append(BREAK_HYPHEN.sub("", text))
        else:
            pieces.append(text + "\n")

    prose = unicodedata.normalize("NFC", "".join(pieces))
    return re.sub(r"[ \t]+", " ", prose), words


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk",
                    help="which consensus directory to assemble from")
    ap.add_argument("--pages", default="all")
    ap.add_argument("--show", action="store_true",
                    help="print the assembled text instead of writing files")
    args = ap.parse_args()

    source = OCR / args.consensus
    if not source.exists():
        raise SystemExit(f"{source} missing -- run scripts/consensus.py first")

    pages = targets.resolve(args.pages)
    # The editorial rules, applied here and nowhere else, and reported.
    repairs, applied, _ambiguous = editorial.long_s_repairs(
        source, editorial.long_s_leaves(source))
    if not args.show:
        OUT.mkdir(parents=True, exist_ok=True)

    total_words = 0
    tiers: dict[str, int] = defaultdict(int)
    written = 0
    for pdf_page in pages:
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        prose, words = assemble(json.loads(path.read_text())["loci"], repairs)
        total_words += len(words)
        for w in words:
            tiers[w["tier"]] += 1

        if args.show:
            print(f"{'='*70}\npágina PDF {pdf_page}\n{'='*70}")
            print(prose)
            continue

        (OUT / f"p{pdf_page:04d}.txt").write_text(prose, encoding="utf-8")
        (OUT / f"p{pdf_page:04d}.json").write_text(json.dumps(
            {"pdf_page": pdf_page, "consensus": args.consensus, "words": words},
            ensure_ascii=False), encoding="utf-8")
        written += 1

    if args.show:
        return
    print(f"{written} leaves assembled, {total_words:,} words")
    print(f"  long s repaired  {len(repairs):,}  "
          f"({applied['panel']:,} from the panel, {applied['attested']:,} by "
          f"attestation; {applied['ambiguous']:,} ambiguous left as printed)")
    for tier in ("unanimous", "one-dissent", "two-dissent", "contested"):
        print(f"  {tier:12} {tiers[tier]:8,}  {tiers[tier]/total_words:5.1%}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
