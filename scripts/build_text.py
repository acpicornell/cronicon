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
import spans
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


BOX_PLACES = 5
DECISIONS = PROJECT / "data" / "review" / "decisions.jsonl"


def decision_key(pdf_page: int, bbox) -> str:
    """The same key `review.py` writes: leaf and word box, never an index."""
    return f"{pdf_page}:" + ",".join(f"{v:.{BOX_PLACES}f}" for v in bbox)


def read_decisions(path: Path = DECISIONS) -> dict[str, str]:
    """What a person settled with the facsimile on screen, by word box.

    These were being recorded and then ignored: 320 adjudications existed and
    not one of them reached the page, because nothing between `review.py` and
    this file ever read them. Twenty-three of the 320 disagree with the panel,
    and those twenty-three were the whole point of making them.

    A decision outranks an editorial rule. `editorial.py` works from the
    panel's readings and knows it can be wrong -- it leaves `fe` for `ſe`
    deliberately -- while a decision was made against the printed page.
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("chose") is not None:
            out[row["key"]] = row["chose"]      # append-only, last one wins
    return out


def assemble(loci: list[dict], panel: list[str],
             repairs: dict | None = None,
             decisions: dict | None = None) -> tuple[str, list[dict]]:
    """Reading-order text, plus one record per word with its tier and box.

    `repairs` carries the editorial rules from `editorial.py`, keyed by (leaf,
    index). Where one applies, the word record keeps what the panel voted for
    under `printed` so that nothing is changed silently. `decisions` carries the
    adjudications, keyed by box, and takes precedence over both.
    """
    lines: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for locus in loci:
        key = tuple(locus["line_bbox"])
        if key not in lines:
            order.append(key)
        lines[key].append(locus)

    repairs = repairs or {}
    decisions = decisions or {}
    words: list[dict] = []
    pieces: list[str] = []
    flat: list[dict] = []
    by_line: dict[tuple, list[str]] = {}
    for key in order:
        row = sorted(lines[key], key=lambda x: x["index"])
        settled = [decisions.get(decision_key(w["pdf_page"], w["bbox"]))
                   for w in row]
        def reading(locus, page=None):
            return repairs.get((locus["pdf_page"], locus["index"]),
                               locus["winner"])

        for group in spans.layout(row, panel, settled, reading):
            group["line"] = key
            flat.append(group)

    # The doubling check runs over the whole leaf: a display heading falls on a
    # line boundary as readily as inside a line.
    spans.dedupe(flat, panel)

    for group in flat:
        record = {"text": group["text"], "tier": group["grade"],
                  "line": list(group["line"]),
                  "bbox": spans.union([x["bbox"] for x in group["loci"]])}
        if len(group["loci"]) > 1:
            record["span"] = len(group["loci"])
        printed = " ".join(x["winner"] for x in group["loci"]
                           if x["winner"]).strip()
        if printed != group["text"]:
            record["printed"] = printed
        # What the engines read here and the edition did not print, so the site
        # can show a doubtful word's rivals rather than a bare question mark.
        if group["grade"] not in ("unanimous", "adjudicated"):
            rivals = spans.alternatives(group["loci"], panel, group["text"])
            if rivals:
                record["variants"] = rivals
        if record["text"]:
            words.append(record)
        by_line.setdefault(group["line"], []).append(group["text"])

    for key in order:
        text = " ".join(c for c in by_line.get(key, ()) if c).strip()
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
    decisions = read_decisions()
    if not args.show:
        OUT.mkdir(parents=True, exist_ok=True)

    total_words = 0
    tiers: dict[str, int] = defaultdict(int)
    written = 0
    for pdf_page in pages:
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        leaf = json.loads(path.read_text())
        prose, words = assemble(leaf["loci"], leaf["panel"], repairs, decisions)
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
    for tier in ("unanimous", "one-dissent", "two-dissent", "contested",
                 "adjudicated"):
        print(f"  {tier:12} {tiers[tier]:8,}  {tiers[tier]/total_words:5.1%}")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
