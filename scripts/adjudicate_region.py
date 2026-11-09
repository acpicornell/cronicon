"""Adjudicate a region of a leaf against the facsimile, line by line.

Some regions defeat the panel in a way no rule reaches. A ledger sets a label,
a run of leader dots and three or five narrow cells of figures and ditto marks
on one line; every engine cuts that line somewhere else, the vote empties the
cells, the segmenter loses whole lines, and the reading order comes out as all
the labels and then all the figures. `review.py` settles one word box at a time
and cannot say what is wrong here, which is the *line*: which boxes are one
printed row, in what order the rows run, and which of them are a table.

So a region is adjudicated as lines. Someone with the facsimile on screen -- a
person, or a model reading the crop at native resolution, which is the one use
of a model this project allows -- writes down what each printed line says:

    data/adjudication/regions/p0159-a.txt

    leaf: 159
    box: 0.50 0.42 0.95 0.86        # the region, in page fractions
    by: claude (facsímil, resolució nativa)
    ---
    0.455 | Dimecres á 5 Juriol.
    0.468 A | Pa.. . . . . . . . . . |
    0.481 A | Vi.. . . . . . . . . . | 1 s. 4 ds.

A line is `y [table] | text` or `y table | label | cells`, where `y` is the
vertical centre of the printed line (`--show` prints the rows it finds, with
their centres). That file is the record, it is committed, and it does three
things when applied:

  text    every word box in the region gets a decision in
          `data/review/decisions.jsonl`, keyed by leaf and box like any other,
          with `source: "variant"` where an engine read it and `"typed"` where
          none did -- so the share of the edition resting on no engine's
          reading stays countable, which is the condition this is allowed on.
  lines   `layout.apply_regions` makes the boxes of one printed line one line,
          and puts the lines in the order the file gives them. Nothing else
          about the leaf moves.
  tables  the rows that carry a table letter are the table, label and cells
          apart as written; `tables.py` takes them instead of detecting.

Nothing here writes a word into the transcription that is not in this file,
and this file says only what the page prints.

Usage:
  python scripts/adjudicate_region.py --show 159 --box 0.50,0.42,0.95,0.86
  python scripts/adjudicate_region.py --apply            # every region file
  python scripts/adjudicate_region.py --apply p0159-a    # one
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import layout
from build_text import DECISIONS, decision_key, read_decisions

PROJECT = Path(__file__).resolve().parent.parent
CONSENSUS = PROJECT / "data" / "ocr" / "consensus6_swap_swapk"
REGIONS = layout.REGIONS


def slots_in(pdf_page: int, box: list[float]) -> list[dict]:
    leaf = json.loads((CONSENSUS / f"p{pdf_page:04d}.json").read_text())
    return [x for x in leaf["loci"] if layout.inside(x["bbox"], box)]


def rows_of(slots: list[dict]) -> list[list[dict]]:
    """Slots clustered into printed rows by vertical centre, left to right."""
    rows: list[list[dict]] = []
    for slot in sorted(slots, key=lambda x: layout.centre_y(x["bbox"])):
        y = layout.centre_y(slot["bbox"])
        if rows and abs(y - sum(layout.centre_y(s["bbox"]) for s in rows[-1])
                        / len(rows[-1])) <= layout.REGION_ROW:
            rows[-1].append(slot)
        else:
            rows.append([slot])
    return [sorted(row, key=lambda x: x["bbox"][0]) for row in rows]


def show(pdf_page: int, box: list[float]) -> None:
    settled = read_decisions()
    for row in rows_of(slots_in(pdf_page, box)):
        y = sum(layout.centre_y(s["bbox"]) for s in row) / len(row)
        cells = []
        for s in row:
            text = settled.get(decision_key(pdf_page, s["bbox"]), s["winner"])
            cells.append(f"{text!r}@{s['bbox'][0]:.3f}")
        print(f"{y:.3f}  " + "  ".join(cells))


def norm(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def distribute(tokens: list[str], row: list[dict]) -> list[str]:
    """The line's tokens shared out among its boxes, left to right.

    A token goes to the box where an engine read it, when one did; what lies
    between two such anchors is shared out in order. More tokens than boxes and
    the surplus joins its left neighbour; more boxes than tokens and the spare
    boxes are empty -- they were never a word.
    """
    out = [""] * len(row)
    if not row:
        return out
    read = [{norm(v) for v in list((s.get("variants") or {}).values())
             + [s.get("winner") or ""] if v} for s in row]
    anchors = []          # (token index, slot index), both rising
    last = -1
    for i, tok in enumerate(tokens):
        for j in range(last + 1, len(row)):
            if norm(tok) and norm(tok) in read[j]:
                anchors.append((i, j))
                last = j
                break
    for i, j in anchors:
        out[j] = tokens[i]
    anchors = [(-1, -1)] + anchors + [(len(tokens), len(row))]
    for (i0, j0), (i1, j1) in zip(anchors, anchors[1:]):
        between, free = tokens[i0 + 1:i1], list(range(j0 + 1, j1))
        spare: list[str] = []
        for k, tok in enumerate(between):
            if k < len(free):
                out[free[k]] = tok
            else:
                spare.append(tok)
        if not spare:
            continue
        # No box of their own: the tokens join the box on their left, or, at
        # the head of the line, lead the first box that has text -- so the
        # line still reads in order.
        if free:
            out[free[-1]] = " ".join([out[free[-1]], *spare])
        elif j0 >= 0:
            out[j0] = " ".join([out[j0], *spare])
        else:
            out[j1] = " ".join([*spare, out[j1]]) if j1 < len(row) else " ".join(spare)
    return out


def apply(name: str, now: str) -> tuple[int, int, int]:
    region = layout.read_region(REGIONS / f"{name}.txt")
    page = region["pdf_page"]
    slots = slots_in(page, region["box"])
    lines = region["lines"]
    by_line: dict[int, list[dict]] = {n: [] for n in range(len(lines))}
    stray = []
    for slot in slots:
        n = layout.line_of(slot["bbox"], lines)
        (by_line[n] if n is not None else stray).append(slot)

    settled = read_decisions()
    written = typed = 0
    with DECISIONS.open("a", encoding="utf-8") as out:
        def decide(slot: dict, text: str) -> None:
            nonlocal written, typed
            key = decision_key(page, slot["bbox"])
            if settled.get(key) == text:
                return
            variants = {v for v in (slot.get("variants") or {}).values() if v}
            source = "variant" if text in variants | {slot["winner"]} else "typed"
            typed += source == "typed" and bool(text)
            written += 1
            out.write(json.dumps({
                "key": key, "pdf_page": page, "index": slot["index"],
                "bbox": slot["bbox"], "grade": slot["grade"], "held": False,
                "winner": slot["winner"], "chose": text, "source": source,
                "engines": sorted(e for e, v in (slot.get("variants") or {}).items()
                                  if v == text),
                "context": f"regió {name}", "by": region["by"], "at": now,
            }, ensure_ascii=False) + "\n")

        for n, line in enumerate(lines):
            row = sorted(by_line[n], key=lambda x: x["bbox"][0])
            if not row:
                print(f"  {name}: no word box for line y={line['y']:.3f} "
                      f"{line['text']!r}")
                continue
            for slot, text in zip(row, distribute(line["text"].split(), row)):
                decide(slot, text)
        # A box inside the region that belongs to no printed line is not a
        # word: a speck, a rule, the tail of a ditto mark read as a letter.
        for slot in stray:
            decide(slot, "")
    return written, typed, len(stray)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, metavar="LEAF")
    ap.add_argument("--box", help="x0,y0,x1,y1 in page fractions")
    ap.add_argument("--apply", nargs="*", metavar="REGION")
    args = ap.parse_args()

    if args.show:
        box = [float(v) for v in (args.box or "0,0,1,1").split(",")]
        show(args.show, box)
        return
    if args.apply is not None:
        names = args.apply or sorted(p.stem for p in REGIONS.glob("p*.txt"))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for name in names:
            written, typed, stray = apply(name, now)
            print(f"{name}: {written} decisions written, {typed} typed, "
                  f"{stray} stray boxes emptied")


if __name__ == "__main__":
    main()
