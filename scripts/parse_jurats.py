"""Turn the Jurats lists into rows of (year, seat, name).

Six times over, Campaner interrupts the chronicle to print the governing body of
the city and kingdom year by year -- `Jurados de la c. y r. de Mallorca durante
el siglo XV.` and its five siblings. Six seats a year, five centuries: it is the
single most queryable thing in the book, and as running text it is unusable.

The lists come in two typographies and only one of them is tractable here.

  compact     a bare `1418.` and six names under it, three such columns to the
              leaf. Regular enough to parse outright, and this is what the
              script does.

  annotated   `AÑO 1312.`, then `1.—Guillermo de Montsó` with a dot leader
              running to a brace, and beside it a column of notes on which
              manuscript gives which name. Leaves 58-60 and 114-121.

Neither difficulty is in the parsing. What the six engines are made to share is a
reading order, and it comes from Tesseract's line segmentation; on these leaves
that segmentation is wrong, in two different ways.

On the compact leaves it fails quietly. Tesseract joins a line of column one to a
line of column two across the gutter -- leaf 312 opens with `Pedro Descatlar.
Alfonso`, one box from x 0.10 to 0.81 -- and every year heading caught in such a
line disappears. Worse, `layout.find_columns` refuses a boundary that more than a
tenth of the lines cross, so the merged lines hide the very boundary that would
have separated them. `consensus.py --split-gutter` cuts a line where the gap in
it is four times a word space, which breaks the circle; this script reads those
leaves from the result. It is worth twelve years and seventy-seven names, most of
them in the 16th-century list.

On the annotated leaves it fails outright: Tesseract returns nothing at all right
of x 0.47 on leaf 115, so the whole column of notes is absent from the panel, and
what it does return of the names is broken (`Domingo.` where the page reads
`3.—Berenguer Domingo`). `--geometry abbyy-ia` recovers the notes column in full
-- `Limitase Villafranca á decir que no están en` and the rest, out to x 0.89 --
but leaves the name column no better. Those eleven leaves are therefore still not
parsed, and this script counts what it is leaving behind rather than guessing at
it.

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

# The annotated form, which this script does not attempt.
ANNOTATED = re.compile(r"^\s*(A[ÑN]O|ANO)[ .]*1[2-8]")

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--tables", default="consensus6_swap_swapk_gutter",
                    help="consensus built with --split-gutter, used for the "
                         "leaves it covers")
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
    leaves = {}
    regeometried = []
    for page in targets.resolve("all"):
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
            if any(ANNOTATED.match(ln["text"]) for ln in leaves[page]):
                annotated.append(page)
                if blocks:
                    break
                continue
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
        summary.append({"century": century, "leaves": pages,
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
    print(f"\nannotated form, not parsed: {len(left)} leaves {left}")
    print("  the panel's line boxes lose their text; they need re-detecting")

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
