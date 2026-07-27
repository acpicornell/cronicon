"""Assemble the consensus decisions into readable text.

The consensus stage produces a verdict per token position. This turns those into
prose: tokens joined in reading order, line-end hyphens stitched, columns
concatenated, running heads already gone.

Every word keeps its certainty tier alongside the text, because that is the whole
point of the pipeline and the edition should not throw it away. `.txt` is for
reading and grepping; `.json` carries the tiers so the site can shade doubtful
words and offer the facsimile crop.

What this deliberately does *not* do: correct anything. 1881 orthography stands as
printed, and so do Campaner's own errors.

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


def assemble(loci: list[dict]) -> tuple[str, list[dict]]:
    """Reading-order text, plus one record per word with its tier and box."""
    lines: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for locus in loci:
        key = tuple(locus["line_bbox"])
        if key not in lines:
            order.append(key)
        lines[key].append(locus)

    words: list[dict] = []
    pieces: list[str] = []
    for key in order:
        row = sorted(lines[key], key=lambda x: x["index"])
        text = " ".join(w["winner"] for w in row).strip()
        for w in row:
            words.append({"text": w["winner"], "tier": w["grade"],
                          "bbox": w["bbox"], "line": list(key)})
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
    if not args.show:
        OUT.mkdir(parents=True, exist_ok=True)

    total_words = 0
    tiers: dict[str, int] = defaultdict(int)
    written = 0
    for pdf_page in pages:
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        prose, words = assemble(json.loads(path.read_text())["loci"])
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
    for tier in ("unanimous", "one-dissent", "two-dissent", "contested"):
        print(f"  {tier:12} {tiers[tier]:8,}  {tiers[tier]/total_words:5.1%}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
