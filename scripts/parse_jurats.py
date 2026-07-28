"""Turn the Jurats lists into rows of (year, seat, name).

Six times over, Campaner interrupts the chronicle to print the governing body of
the city and kingdom year by year -- `Jurados de la c. y r. de Mallorca durante
el siglo XV.` and its five siblings. Six seats a year, five centuries: it is the
single most queryable thing in the book, and as running text it is unusable.

The lists come in two typographies, and the difficulty in both is the reading
order rather than the parsing.

  compact     a bare `1418.` and six names under it, three such columns to the
              leaf.

  annotated   `AÑO 1312.` centred over the pair of columns, then
              `1.—Guillermo de Montsó` with a dot leader running to a brace, and
              beside it a column of notes on which manuscript gives which name.
              Leaves 58-60 and 114-121.

What the six engines are made to share is a reading order, and it comes from
Tesseract's line segmentation. On these leaves that segmentation is wrong, in two
different ways, and each needed its own consensus.

On the compact leaves it fails quietly. Tesseract joins a line of column one to a
line of column two across the gutter -- leaf 312 opens with `Pedro Descatlar.
Alfonso`, one box from x 0.10 to 0.81 -- and every year heading caught in such a
line disappears. Worse, `layout.find_columns` refuses a boundary that more than a
tenth of the lines cross, so the merged lines hide the very boundary that would
have separated them. `consensus.py --split-gutter` cuts a line where the gap in
it is four times a word space, which breaks the circle. Worth twelve years and
seventy-seven names, most of them in the 16th-century list.

On the annotated leaves it fails outright, and no single change fixes it.
Tesseract returns nothing at all right of x 0.47 on leaf 115, so the notes column
is absent from the panel; ABBYY on the BNE scan reads all three regions, but
under a page-wide token alignment the engines' readings land in the wrong slots
and the names come back *empty*, because each engine walks the leaf in a
different order. Two changes together make it legible:

    consensus.py --geometry abbyy-bne --align line

the first so the boxes exist, the second so the reading order stops mattering --
a printed line competes only with the engine text that overlaps it on the page.
Leaf 115 then reads `AÑO 1312.`, `2.—Guillermo de Montsó`, and the note
`Limítase Villafranca á decir que no están en...`, all off the same leaf.

That recovered the whole 13th-century series, which was empty, and took the 14th
back from 1375 to 1302: **+279 names, +59 years**. The names arrive at low
certainty -- these are the hardest leaves in the book -- and go to review as
such.

Usage:
  python scripts/parse_jurats.py
  python scripts/parse_jurats.py --report
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import targets
from parse_entries import (OCR, monotone_subsequence, page_lines,
                           year_of_line)

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "jurats"

# Every series opens with its own title. `silgo` is not a typo of mine: it is
# what leaf 311 prints, and it stays.
SERIES = re.compile(
    r"Jurados\s+de\s+la\s+c\b.{0,60}?\b(XVIII|XVII|XVI|XV|XIV|XIII)\b",
    re.IGNORECASE)
ROMAN = {"XIII": 13, "XIV": 14, "XV": 15, "XVI": 16, "XVII": 17, "XVIII": 18}

# The annotated form: `AÑO 1312.` centred over the pair of columns.
ANNOTATED = re.compile(r"^\s*(A[ÑN]O|ANO)[ .]*(1[2-8]\d\d)")

# `2.—Guillermo de Montsó. . . .` -- the seat number is printed, so it is read
# rather than counted, and a year that names only its 1st and 4th seats keeps
# them in the right places. `I` and `l` for 1 are the usual misreads of the
# figure in this face.
NUMBERED_SEAT = re.compile(r"^\s*([1-6IilJ])\s*[.,]\s*[—–\-]+\s*(.*)$")
SEAT_DIGIT = {"I": 1, "i": 1, "l": 1, "J": 1}
# The brace sits about here; everything to its right is the notes column, which
# is commentary on the sources rather than the list itself.
NAME_COLUMN = 0.50

# The numeral that opens the next appendix. The 18th-century list ends when the
# Jurats themselves did, and `II. Noticias é indicaciones curiosas` starts on the
# very next leaf at 1702 -- rising years, so nothing else stops the series there.
SECTION_HEAD = re.compile(r"^\s*[IVXL]{1,5}\s*\.?\s*$")

# A row of leader dots standing in for a seat the sources do not name.
LEADERS = re.compile(r"^[\s.·•]*$")
# Six seats to a year, and a name is a name -- anything longer is the prose that
# follows the last table on a leaf.
SEATS = 6
NAME_MAX = 55


def series_starts(leaves: dict[int, list[dict]]) -> list[tuple[int, int]]:
    """(leaf, century) for each list, in the order they are printed."""
    out = []
    for page in sorted(leaves):
        for line in leaves[page][:6]:
            match = SERIES.search(line["text"])
            if match and match.group(1).upper() in ROMAN:
                out.append((page, ROMAN[match.group(1).upper()]))
                break
    return out


def read_leaf(page: int, lines: list[dict], century: int) -> list[dict]:
    """The year blocks a compact leaf holds, in reading order."""
    blocks: list[dict] = []
    current: dict | None = None
    for line in lines:
        text = line["text"].strip()
        if not text or SERIES.search(text):
            continue

        year, votes, rest = year_of_line(line)
        # A year outside its own century is a page number or a misreading, and
        # the century is stated at the head of the list rather than inferred.
        if year is not None and (year - 1) // 100 + 1 == century:
            current = {"year": year, "note": rest.strip(" .,"), "seats": [],
                       "readings": votes, "pdf_page": page}
            blocks.append(current)
            continue
        if current is None or len(current["seats"]) >= SEATS:
            continue
        if LEADERS.match(text):
            current["seats"].append(None)
            continue
        if len(text) > NAME_MAX:
            # prose has started; this leaf's table is over
            current = None
            continue
        # a name broken across two lines is stitched back, as everywhere else
        if current["seats"] and isinstance(current["seats"][-1], dict) \
                and current["seats"][-1]["name"].endswith("-"):
            previous = current["seats"][-1]
            previous["name"] = previous["name"][:-1] + text
            continue
        current["seats"].append({"name": text, "tier": line["worst_tier"]})
    return blocks


def read_annotated_leaf(page: int, lines: list[dict], century: int) -> list[dict]:
    """The year blocks an annotated leaf holds.

    Different from the compact form in three ways, all of them helpful once the
    leaf can be read at all: the year is labelled (`AÑO 1312.`) rather than bare,
    the seat number is printed beside each name, and a column of notes on the
    manuscript sources runs alongside. The notes are skipped here -- they are
    commentary on where a name comes from, not the list -- and the printed seat
    number is trusted over counting, so a year that names only its 1st and 4th
    keeps them in the right seats instead of sliding them up.
    """
    blocks: list[dict] = []
    current: dict | None = None
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue

        label = ANNOTATED.match(text)
        if label:
            year = int(label.group(2))
            if (year - 1) // 100 + 1 != century:
                continue
            current = {"year": year, "note": "", "seats": [None] * SEATS,
                       "readings": 0, "pdf_page": page}
            blocks.append(current)
            continue

        if current is None or line["bbox"][0] >= NAME_COLUMN:
            continue                    # the notes column, or text before a year
        seat = NUMBERED_SEAT.match(text)
        if not seat:
            continue
        n = SEAT_DIGIT.get(seat.group(1), None)
        if n is None:
            n = int(seat.group(1))
        name = seat.group(2).strip(" .·•")
        if not name or len(name) > NAME_MAX:
            continue
        current["seats"][n - 1] = {"name": name, "tier": line["worst_tier"]}
    return blocks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--tables", default="consensus6_swap_swapk_gutter",
                    help="consensus built with --split-gutter, used for the "
                         "leaves it covers")
    ap.add_argument("--annotated", default="consensus6_swap_swapk_annotated",
                    help="consensus for the annotated leaves, built with "
                         "--geometry abbyy-bne --align line; it is the only "
                         "combination that reads the names, the year labels and "
                         "the notes column off the same leaf")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    if not source.exists():
        raise SystemExit(f"{source} missing -- run scripts/consensus.py first")

    inventory = {leaf["pdf_page"]: leaf for leaf in
                 json.loads((PROJECT / "data" / "inventory.json").read_text())["leaves"]}
    # The table leaves are read from a consensus built with the gutter split, so
    # that the columns are separate lines. It covers only those leaves, and it
    # is a separate directory on purpose: changing the geometry changes every
    # stratum, and the frozen sample is keyed to the book's own consensus.
    tables = OCR / args.tables
    annotated_dir = OCR / args.annotated
    leaves = {}
    regeometried = []
    annotated_leaves: set[int] = set()
    for page in targets.resolve("all"):
        special = annotated_dir / f"p{page:04d}.json"
        if special.exists():
            leaves[page] = page_lines(special)
            annotated_leaves.add(page)
            continue
        special = tables / f"p{page:04d}.json"
        plain = source / f"p{page:04d}.json"
        if special.exists():
            leaves[page] = page_lines(special)
            regeometried.append(page)
        elif plain.exists():
            leaves[page] = page_lines(plain)

    rows: list[dict] = []
    summary: list[dict] = []
    annotated: list[int] = []
    dropped: list[tuple] = []
    order = sorted(leaves)
    starts = series_starts(leaves)
    for n, (start, century) in enumerate(starts):
        # A series cannot run past the beginning of the next one.
        stop = starts[n + 1][0] if n + 1 < len(starts) else order[-1] + 1
        blocks: list[dict] = []
        pages: list[int] = []
        for page in order[order.index(start):]:
            if page >= stop:
                break
            if blocks and any(SECTION_HEAD.match(ln["text"])
                              for ln in leaves[page][:4]):
                break
            if page in annotated_leaves:
                found = read_annotated_leaf(page, leaves[page], century)
            elif any(ANNOTATED.match(ln["text"]) for ln in leaves[page]):
                # Annotated, but no consensus was built for it in the geometry
                # that can read it. Counted, not guessed at.
                annotated.append(page)
                if blocks:
                    break
                continue
            else:
                found = read_leaf(page, leaves[page], century)
            # A list runs forwards. A leaf that adds no year beyond the ones
            # already collected is not the next leaf of it: leaf 230 continues a
            # document dated 1403 while the list above has reached 1500, and
            # leaf 483 does the same at 1612 against 1700.
            reached = max((b["year"] for b in blocks), default=0)
            if blocks and max((b["year"] for b in found), default=0) <= reached:
                break
            if found:
                blocks.extend(found)
                pages.append(page)

        # Inside the series, keep the years that can all be true together. A
        # single heading misread high -- 1653 among the 1620s on leaf 479 --
        # otherwise locks out every real year behind it, and that alone cost
        # twenty consecutive years of the 17th-century list.
        keep = set(monotone_subsequence([b["year"] for b in blocks]))
        dropped.extend((century, blocks[n]["pdf_page"], blocks[n]["year"])
                       for n in range(len(blocks)) if n not in keep)
        blocks = [b for n, b in enumerate(blocks) if n in keep]

        filled = 0
        for block in blocks:
            for seat, name in enumerate(block["seats"], start=1):
                if name is None:
                    continue
                filled += 1
                rows.append({"century": century, "year": block["year"],
                             "seat": seat, "name": name["name"],
                             "tier": name["tier"], "pdf_page": block["pdf_page"],
                             "printed": inventory[block["pdf_page"]]["printed"],
                             **({"note": block["note"]} if block["note"] else {})})
        years = [b["year"] for b in blocks]
        summary.append({"century": century, "title_leaf": start,
                        "leaves": pages,
                        "years": len(set(years)), "names": filled,
                        "span": [min(years), max(years)] if years else None,
                        "backwards": sum(1 for a, b in zip(years, years[1:])
                                         if b < a)})

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "jurats.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (OUT / "series.json").write_text(json.dumps(
        {"parsed": summary, "annotated_not_parsed": sorted(set(annotated))},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{len(rows):,} names over {len({(r['century'], r['year']) for r in rows})} years\n")
    print(f"{'century':>9}{'leaves':>9}{'years':>7}{'names':>7}{'span':>14}"
          f"{'out of order':>14}")
    for s in summary:
        span = f"{s['span'][0]}–{s['span'][1]}" if s["span"] else "-"
        print(f"{s['century']:>9}{len(s['leaves']):>9}{s['years']:>7}"
              f"{s['names']:>7}{span:>14}{s['backwards']:>14}")

    seats = Counter(r["seat"] for r in rows)
    print(f"\nseats filled: " + "  ".join(f"{n}:{seats[n]}" for n in range(1, 7)))
    tiers = Counter(r["tier"] for r in rows)
    print("certainty:    " + "  ".join(
        f"{t} {tiers[t]:,} ({tiers[t]/len(rows):.0%})"
        for t in ("unanimous", "one-dissent", "two-dissent", "contested")))

    left = sorted(set(annotated))
    print(f"\n{len(regeometried)} leaves read from the gutter-split consensus")
    print(f"{len(annotated_leaves)} leaves read from the annotated consensus "
          f"(--geometry abbyy-bne --align line)")
    if left:
        print(f"\nannotated form, still not parsed: {len(left)} leaves {left}")
        print(f"  build them with: python scripts/consensus.py --pages "
              f"{','.join(str(p) for p in left)} --swap-paddle --swap-kraken "
              f"--geometry abbyy-bne --align line --out data/ocr/{args.annotated}")

    if args.report:
        by_year: Counter = Counter((r["century"], r["year"]) for r in rows)
        odd = [k for k, n in sorted(by_year.items()) if n != SEATS]
        print(f"\nyears not holding six names ({len(odd)} of {len(by_year)}):")
        for century, year in odd[:20]:
            print(f"  {year}: {by_year[(century, year)]}")
        print("\nyears the list should cover and does not:")
        for s in summary:
            if not s["span"]:
                continue
            have = {y for c, y in by_year if c == s["century"]}
            gone = [y for y in range(s["span"][0], s["span"][1] + 1)
                    if y not in have]
            print(f"  s. {s['century']}: {len(gone):3d} missing  {gone[:24]}"
                  f"{' …' if len(gone) > 24 else ''}")

    print(f"\n-> {OUT / 'jurats.jsonl'}")


if __name__ == "__main__":
    main()
