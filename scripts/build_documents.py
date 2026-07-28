"""Assemble each document Campaner prints in full as one text.

`parse_documents.py` says where the sections are; this puts them together. Until
now the letters of Gilaberto de Centellas existed only as fourteen leaf files with
the letters of some other section starting halfway down the last of them, which is
the same as not having them.

Three things need care and none of them is transcription:

  the ends       A section's `until` is the leaf before the next section starts,
                 but a section can start in the middle of a leaf -- section III
                 opens at line 7 of leaf 233 while section II is still running
                 down it. Ending at `until` therefore drops the top of that leaf.
                 The end taken here is the next section's *first line*, so the
                 leaf is split where the book splits it.

  the footnotes  Separated exactly as in the chronicle, and for the same reason:
                 a note runs from its number to the foot of its column and is not
                 part of the sentence it interrupts.

  the certainty  Carried through. These are the leaves nothing has measured -- no
                 adjudicated position falls on one -- so a document that is mostly
                 contested must say so on its face rather than read like the rest.

Nothing here corrects, translates or normalises. The medieval Catalan and Latin
stay as printed, including the long s of the 1541 reprint, which `editorial.py`
handles under its own documented rule.

Usage:
  python scripts/build_documents.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import editorial
from build_text import BREAK_HYPHEN
from parse_entries import OCR, gather_notes, page_lines, split_notes

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "documents"
SECTIONS = OUT / "sections"

# Campaner names the genre himself, in the first word of every title: `Cartas`,
# `Sentencia`, `Relacion`, `Memorial`, `Declaraciones`, `Toma de posesion`. That
# is better evidence than any classification of ours, so it is surfaced as it
# stands rather than mapped onto categories the book does not use.
GENRE = re.compile(r"^[«\"'\s]*([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)")


def span_of(block: dict, index: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """(first leaf, first line) and the exclusive end of section `index`."""
    sections = block["sections"]
    section = sections[index]
    start = (section["pdf_page"], section.get("line", 0))
    if index + 1 < len(sections):
        nxt = sections[index + 1]
        end = (nxt["pdf_page"], nxt.get("line", 0))
    else:
        end = (section.get("until", section["pdf_page"]) + 1, 0)
    return start, end


def stitch(lines: list[dict]) -> str:
    """Reading-order prose, line-end hyphens joined, as in build_text.py."""
    pieces: list[str] = []
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue
        if BREAK_HYPHEN.search(text):
            pieces.append(BREAK_HYPHEN.sub("", text))
        else:
            pieces.append(text + "\n")
    prose = unicodedata.normalize("NFC", "".join(pieces))
    return re.sub(r"[ \t]+", " ", prose)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    manifest_path = OUT / "documents.json"
    if not manifest_path.exists():
        raise SystemExit(f"{manifest_path} missing -- run parse_documents.py")
    blocks = json.loads(manifest_path.read_text())

    repairs, _applied, _amb = editorial.long_s_repairs(
        source, editorial.long_s_leaves(source))

    # Leaves are read once; a leaf can carry the end of one section and the start
    # of the next, and re-reading it per section would double the work and the
    # footnote extraction with it.
    cache: dict[int, tuple[list[dict], list[dict]]] = {}

    def leaf(pdf_page: int) -> tuple[list[dict], list[dict]]:
        if pdf_page not in cache:
            path = source / f"p{pdf_page:04d}.json"
            if not path.exists():
                cache[pdf_page] = ([], [])
            else:
                body, notes = split_notes(page_lines(path))
                cache[pdf_page] = (body, gather_notes(notes) if notes else [])
        return cache[pdf_page]

    SECTIONS.mkdir(parents=True, exist_ok=True)
    catalogue: list[dict] = []
    for block in blocks:
        for index, section in enumerate(block["sections"]):
            if section.get("jurats"):
                continue                      # parse_jurats.py owns these
            start, end = span_of(block, index)
            lines: list[dict] = []
            notes: list[dict] = []
            for pdf_page in range(start[0], end[0] + 1):
                body, page_notes = leaf(pdf_page)
                first = start[1] if pdf_page == start[0] else 0
                last = end[1] if pdf_page == end[0] else len(body)
                chosen = body[first:last]
                if chosen:
                    lines.extend(chosen)
                    notes.extend(page_notes)

            if not lines:
                continue

            tiers = Counter()
            for line in lines:
                tiers += line["tiers"]
            words = sum(tiers.values())
            text = stitch(lines)
            genre = GENRE.match(section["title"])

            name = (f"{block['first_leaf']:04d}-{section['numeral']}"
                    f"-{section['number']:02d}")
            # The file is what the book prints, from the section's first line to
            # its last, and nothing else -- the printed title stands at the head
            # of it already. Repeating the recorded title above it would put a
            # truncated copy of the same words in front of the real ones.
            (SECTIONS / f"{name}.txt").write_text(text, encoding="utf-8")
            catalogue.append({
                "id": name,
                "block_leaf": block["first_leaf"],
                "numeral": section["numeral"],
                "title": section["title"],
                "genre": genre.group(1) if genre else None,
                # A leaf carrying the end of one section and the start of the
                # next belongs to both, so these counts overlap by design.
                "first_leaf": start[0], "last_leaf": end[0],
                "leaves": end[0] - start[0] + 1,
                "words": words,
                "footnotes": len(notes),
                "certainty": {k: tiers[k] for k in
                              ("unanimous", "one-dissent", "two-dissent",
                               "contested")},
                "contested_share": round(tiers["contested"] / words, 4) if words
                else 0.0,
            })

    (OUT / "sections.json").write_text(
        json.dumps(catalogue, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(c["words"] for c in catalogue)
    contested = sum(c["certainty"]["contested"] for c in catalogue)
    print(f"{len(catalogue)} documents assembled, {total:,} words, "
          f"{contested:,} contested ({contested/total:.1%})")
    print(f"{sum(c['footnotes'] for c in catalogue)} footnotes carried with them\n")
    print(f"{'id':16}{'leaves':>7}{'words':>8}{'contested':>11}  title")
    for c in catalogue:
        print(f"{c['id']:16}{c['leaves']:7d}{c['words']:8,}"
              f"{c['contested_share']:10.1%}  {c['title'][:52]}")

    if args.report:
        genres = Counter(c["genre"] for c in catalogue)
        print("\nby the noun Campaner opens the title with:")
        for genre, n in genres.most_common():
            print(f"  {n:2d}  {genre}")
        worst = sorted(catalogue, key=lambda c: -c["contested_share"])[:5]
        print("\nleast certain, and none of them is measured:")
        for c in worst:
            print(f"  {c['contested_share']:6.1%}  {c['id']}  {c['title'][:46]}")

    print(f"\n-> {SECTIONS}")


if __name__ == "__main__":
    main()
