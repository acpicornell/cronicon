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
import statistics
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
# `IV. ` opening a line, where the numeral and the title share it.
NUMERAL_HEAD = re.compile(r"[IVXLC]{1,6}\.\s+")
ROMAN = re.compile(r"[IVXLCivxlc0-9 .,]{1,10}")
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


# How far past its column's left edge a line has to start before it counts as
# opening a paragraph. Word spaces here are 0.0066 of the page and the printer's
# indent is about 0.02, so 0.012 sits between them with room on both sides.
INDENT = 0.012
# A line this much narrower than the measure is the last line of a paragraph.
SHORT = 0.88


# A bare numeral hanging left of its column's text: the node number of the
# genealogical plate, printed in the margin against the entry it belongs to.
HANGING_NUMBER = re.compile(r"^\s*[0-9IilOo]{1,3}\s*$")
HANGS = 0.015


def hanging_numbers(lines: list[dict]) -> set[int]:
    """Lines that are a node number standing in their column's margin.

    Leaf 152 is the `ESPLICACION DEL ÁRBOL` of the genealogical plate on 151,
    and it prints each entry's number out in the margin: `8  Casó con el
    infante de Castilla D. Juan Manuel.` The number is its own line box with a
    y a hair below the entry's first, so the reading order puts it *after* that
    line and it lands in the middle of the sentence -- `Se dice es la que está
    enterrada en la 9 Catedral.`, and once inside a hyphen join, `D. Fer17
    rario`.

    Sorting overlapping lines left to right would fix it and was measured
    first: it reorders 74 of 650 leaves, two of which carry adjudications, so
    it is not a change to make in passing. This is the same fact stated where
    it is safe -- **one leaf in all 23 documents has a hanging numeral at all**
    -- and the number opens its entry, which is what the book does with it.
    """
    out: set[int] = set()
    by_column: dict[int, list[int]] = {}
    # (the caller moves each of these in front of the line it overlaps)
    for n, line in enumerate(lines):
        if line["text"].strip():
            by_column.setdefault(line.get("column", 0), []).append(n)
    for rows in by_column.values():
        base = statistics.median(lines[n]["bbox"][0] for n in rows)
        out |= {n for n in rows
                if HANGING_NUMBER.match(lines[n]["text"])
                and lines[n]["bbox"][0] < base - HANGS}
    return out


# Leaves whose columns must be sorted by *printed line* rather than by the top
# of each box. Two lines that overlap in y are one line of the page and belong
# left to right; sorting by y0 alone puts a marginal number after the line it
# stands against, because its box begins a hair lower.
#
# Leaf 152 -- the `ESPLICACION DEL ÁRBOL` of the genealogical plate -- is the
# only leaf in all 23 documents with a number in its margin, and it came out as
# `Se dice es la que está enterrada en la 9 Catedral.` and `D. Fer17 rario`.
#
# Named leaf by leaf on purpose. Applying it everywhere reorders 74 of the 650
# engine-leaves, two of them carrying adjudications from the frozen sample, and
# that is a measurement to act on with room to verify it -- not a side effect of
# repairing one page.
BY_PRINTED_LINE = {152}


def by_printed_line(lines: list[dict]) -> list[dict]:
    """Sort each column by printed line, then left to right within it."""
    out: list[dict] = []
    for column in sorted({line.get("column", 0) for line in lines}):
        rows = [line for line in lines if line.get("column", 0) == column]
        # From the lines that carry text: an empty line has a degenerate box
        # and a handful of them move the median enough to change every key.
        heights = [line["bbox"][3] - line["bbox"][1] for line in rows
                   if line["text"].strip() and line["bbox"][3] > line["bbox"][1]]
        step = (statistics.median(heights) if heights else 0.01) * 0.7
        rows.sort(key=lambda line: (round(line["bbox"][1] / step),
                                    line["bbox"][0]))
        out += rows
    return out


def paragraph_breaks(lines: list[dict]) -> set[int]:
    """Which lines open a paragraph, by where the printer indented them.

    **A line break is not a paragraph break**, and treating it as one is what
    made these documents unreadable: `stitch` used to end every printed line
    that did not carry a hyphen, so a letter of Gilaberto de Centellas arrived
    as a wall of forty-character lines instead of prose. The original's line
    breaks are an accident of the measure and belong to the facsimile, not to a
    text meant to be read.

    What the book does mark is the paragraph, and it marks it the way books do:
    with an indent. The left edge is taken per column, because a two-column leaf
    has two of them and one median over both makes every line of column one look
    outdented and every line of column two indented.
    """
    # The commonest left edge, not the smallest: a heading or a display line
    # starts further left than the body and would make every ordinary line look
    # indented. Rounded to a hundredth so that near-identical edges count as one.
    edges: dict[int, Counter] = {}
    for line in lines:
        if line["text"].strip():
            edges.setdefault(line.get("column", 0), Counter())[
                round(line["bbox"][0], 2)] += 1
    base = {column: xs.most_common(1)[0][0] for column, xs in edges.items()}
    # An indent alone is not enough, and this document proved it: leaf 137 gave
    # 11 openers in 73 lines and the section still came out with 266 of its 395
    # paragraphs under 60 characters, because continuation lines like `páginas
    # 76 y 77, citando á Gar. ser. præs. Mag.` sit a little right of the modal
    # edge for reasons that are not a paragraph -- a quotation mark that starts
    # outside the measure, a word the panel gave a wide box.
    #
    # A paragraph also *ends*, and it ends with a short line. So an opener has
    # to be indented **and** follow a line that does not fill the measure. Those
    # are 7, 2 and 16 lines on leaves 137, 145 and 153, which is the right order
    # of magnitude for a page of prose.
    live = [n for n, line in enumerate(lines) if line["text"].strip()]
    widths = [lines[n]["bbox"][2] - lines[n]["bbox"][0] for n in live]
    if not widths:
        return set()
    measure = statistics.median(widths)
    ends = {live[i] for i, w in enumerate(widths) if w < measure * SHORT}
    opens = set()
    for i, n in enumerate(live):
        indented = (lines[n]["bbox"][0]
                    - base.get(lines[n].get("column", 0), 0) > INDENT)
        if indented and (i == 0 or live[i - 1] in ends):
            opens.add(n)
    return opens


def stitch(lines: list[dict]) -> tuple[str, list[int]]:
    """Reading-order prose, and the leaf each paragraph opens on.

    The leaf is carried out because a document runs across up to seventeen of
    them and the reader needs the same thing the chronicle gives: a way back to
    the page. One link at the head of a seventeen-leaf section only says where
    it starts.
    """
    opens = paragraph_breaks(lines) | hanging_numbers(lines)
    hanging = hanging_numbers(lines)
    pieces: list[str] = []
    leaves: list[int] = []
    hyphen = False          # did the line before end mid-word?
    for n, line in enumerate(lines):
        text = line["text"].strip()
        if not text:
            continue
        # The number opens its entry, so it never continues the line before it
        # however that line ended.
        if n in hanging:
            hyphen = False
        if hyphen:
            pass            # the word continues: no separator at all
        elif n in opens and pieces:
            pieces.append("\n\n")
            leaves.append(line.get("leaf", 0))
        elif pieces:
            pieces.append(" ")
        else:
            leaves.append(line.get("leaf", 0))
        hyphen = bool(BREAK_HYPHEN.search(text))
        pieces.append(BREAK_HYPHEN.sub("", text) if hyphen else text)
    prose = unicodedata.normalize("NFC", "".join(pieces))
    return re.sub(r"[ \t]+", " ", prose).strip() + "\n", leaves


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
                lines = page_lines(path)
                for line in lines:
                    line["leaf"] = pdf_page
                body, notes = split_notes(lines)
                if pdf_page in BY_PRINTED_LINE:
                    body = by_printed_line(body)
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
            text, para_leaves = stitch(lines)
            # The section's own numeral, as `parse_documents.py` read it off the
            # panel rather than off the vote's winner. Display type is the class
            # the engines read worst -- leaf 316 prints `III.` and the winner
            # was `I XIX.`, having been offered `zz.`, `LL.` and `TIT.` -- and
            # the numeral was recovered there and then thrown away here, because
            # the text keeps the winner. The heading is the one place the
            # recovered reading has to win, since it is what the reader sees
            # first and the panel's own evidence says the winner is wrong.
            # The title is a heading whether or not the line under it was
            # indented, and on two sections it was not: leaf 316's VI ran its
            # title into 1 795 characters of body, and leaf 229's IV put the
            # numeral, the title and the first sentence in one paragraph.
            # `parse_documents.py` knows where the title ends -- it read it --
            # so the break is taken from there, and only the first paragraph is
            # touched, because rewriting the whole text collapses the paragraphs
            # that stitch has just found. All 23 come out with the title
            # standing free.
            paras = text.split("\n\n")
            flat = " ".join(section["title"].split())
            for i, para in enumerate(paras[:2]):
                one = " ".join(para.split())
                lead = NUMERAL_HEAD.match(one)
                body = one[lead.end():] if lead else one
                if not flat or not body.startswith(flat):
                    continue
                cut = [lead.group(0).strip()] if lead else []
                paras[i:i + 1] = [x for x in
                                  cut + [flat, body[len(flat):].lstrip()] if x]
                break
            text = "\n\n".join(x for x in paras if x.strip()) + "\n"

            head, _, rest = text.partition("\n\n")
            if ROMAN.fullmatch(head.strip()) and head.strip("." ) != section["numeral"]:
                text = f"{section['numeral']}.\n\n{rest}"
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
                # Which leaf each paragraph opens on, so the reader can get back
                # to the page from anywhere in a seventeen-leaf document.
                "paragraph_leaves": para_leaves,
                "footnotes": len(notes),
                # …and the notes themselves, not only how many. They were being
                # separated from the body -- which is the hard half, and the
                # reason the documents read as prose at all -- and then counted
                # and dropped, so 62 notes came off the leaves and none of them
                # reached a page. Campaner's apparatus is where he says which
                # manuscript a passage is from and where he corrects it.
                "notes": [{"number": n["number"], "text": n["text"],
                           "pdf_page": n.get("leaf", start[0])} for n in notes],
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
