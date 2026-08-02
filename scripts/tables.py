"""Find the tables Campaner sets inside the prose, by where the figures sit.

The book stops now and then and prints a table: the harvest of a year, the dead
of a plague week by week, who lent how much for the armada of 1343, the census
of 1784. The transcription has every word of them and has lost the one thing
that made them readable -- that the figures were in a column. `COSECHA DE ESTE
AÑO. Trigo y candeal.. 237,863 cuarteras. Cebada. 176,780 » Avena. 102,006 »`
is a paragraph, and on the page it is four rows.

**This recovers structure, not text.** No character is added, removed or
changed; what is stored is which word records make up which row of which table.
The signal is geometric and needs no model: on leaf 569 the figures end at
x 0.793, 0.796, 0.797 and 0.796 -- right-aligned to within four thousandths of
the page -- while the labels all start at the column's left edge. Prose does not
do that.

Two things learned by checking a detection against the facsimile, which is the
reason to check:

- **The figure is not always the last token.** Where the panel disagreed about
  where the words end, `spans.py` votes on the whole run and returns one record
  for it, so leaf 591's row arrives as the single string `Solteras . 40.603`.
  Testing the last token dropped that row and the one above it, and the crop
  showed both sitting in the middle of the table.
- **A row is dropped when its own geometry is wrong, and that is right.** Leaf
  569 prints four lines of plague dead and the detector takes three: the panel
  gave `163` a box 0.002 of the page wide, a sliver, so it cannot align with
  anything. Nothing is lost -- the row stays in the prose where it always was --
  and the alternative, absorbing a line because it looks like a row, is guessing
  from the shape after the geometry has already said no.
- **A run of aligned figures is not always a table.** The Jurats lists label
  each year `AÑO 1322.`, `AÑO 1323.`, and those align by construction. They are
  excluded by leaf, since `sections.json` already knows which leaves they are,
  and by requiring the figures in a table to differ from one another.

Usage:
  python scripts/tables.py            # the report
  python scripts/tables.py --show 591
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
TEXT = PROJECT / "data" / "text"
OUT = PROJECT / "data" / "tables"

# A figure as this book writes them: `237,863`, `126.588`, `4 894`, `38`.
FIGURE = re.compile(r"\d[\d.,\s]*\d|\d")
# What may follow the figure and still leave it the end of its cell: the ditto
# mark, the unit, the currency words.
UNIT = re.compile(r"^[»\"'\s.,]*(cuarteras?|id|ls|ss|ds|libs?|»)?[\s.,»]*$",
                  re.IGNORECASE)
# How far apart two right edges may be and still count as one column.
ALIGN = 0.012
# A row needs a label: three letters or more somewhere in it, so that a bare
# figure at the foot of a column cannot open a table.
LABELLED = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
# A table is at least this many rows. Two aligned figures happen by accident in
# ordinary prose; three do not.
MIN_ROWS = 3


def cell_edge(row: list[dict]) -> tuple[str, float] | None:
    """Which edge this row's figure column sits on, and where, or None.

    Campaner sets these two ways and both have to be named, because a rule that
    just looks for a figure somewhere finds prose. Leaf 160 reads `En 26 de Mayo
    als frares del Temple per lur provisio 6 libs.` -- an account in medieval
    Catalan with figures scattered through it -- and walking backwards from the
    end of the line until something matched picked up the `26` and called three
    lines of prose a table.

    Only one of the two is a rule. **Figure last** -- `Cebada. 176,780 »`, the
    label first and nothing after the figure but a unit or a ditto mark -- is 15
    detections and all 15 are tables. **Figure first** -- `24,294 hombres útiles
    para tomar las armas.` on leaves 453 and 593, which really are tables -- was
    tried and declined: it also takes `19 de Febrero, por haber llovido el día
    23 y` and `15 ss. la barcilla; el trigo á 14 ss.`, because prose begins with
    a date or a price often enough, and 9 detections of which 4 or 5 are real is
    not a rule. Those leaves stay prose until something separates them.

    Within a span record the figure's own box is not recorded, so the record's
    right edge stands in for it, which is right exactly when the figure ends the
    record -- which the test has just established.
    """
    last = row[-1]
    found = list(FIGURE.finditer(last["text"]))
    if found and UNIT.match(last["text"][found[-1].end():]):
        return "right", last["bbox"][2]
    # …and the unit may be a record of its own: `176,780` then `»`.
    if len(row) > 1 and UNIT.match(last["text"]):
        found = list(FIGURE.finditer(row[-2]["text"]))
        if found and UNIT.match(row[-2]["text"][found[-1].end():]):
            return "right", row[-2]["bbox"][2]
    return None


def rows_of(leaf: dict) -> list[tuple[float | None, list[dict]]]:
    lines: dict[tuple, list[dict]] = {}
    for word in leaf["words"]:
        lines.setdefault(tuple(word["line"]), []).append(word)
    out = []
    for words in lines.values():
        row = sorted(words, key=lambda w: w["bbox"][0])
        cell = cell_edge(row) if row else None
        # A figure standing alone is a page number, not a row: a row has
        # something to label the figure with. Counted in letters and not in
        # word records, because a whole row can arrive as one record -- leaf
        # 591's `Solteras . 40.603` is a span, and testing for two records
        # dropped it out of its own table.
        if cell and not LABELLED.search(" ".join(w["text"] for w in row)):
            cell = None
        out.append((cell, row))
    return out


def figures(row: list[dict]) -> str:
    return " ".join(m.group(0) for w in row for m in FIGURE.finditer(w["text"]))


def tables_on(leaf: dict) -> list[list[list[dict]]]:
    """Runs of consecutive lines whose figures line up on the right."""
    rows = rows_of(leaf)
    found = []
    n = 0
    while n < len(rows):
        if rows[n][0] is None:
            n += 1
            continue
        side, edge = rows[n][0]
        m = n
        while (m + 1 < len(rows) and rows[m + 1][0] is not None
               and rows[m + 1][0][0] == side
               and abs(rows[m + 1][0][1] - edge) < ALIGN):
            m += 1
        block = [row for _cell, row in rows[n:m + 1]]
        # Every row reading the same figure is a label repeated, not a table.
        if len(block) >= MIN_ROWS and len({figures(r) for r in block}) > 1:
            found.append((side, block))
        n = m + 1
    return found


# The second family, and it is the documents' rather than the chronicle's. A
# payments ledger sets the label across as many printed lines as it needs and
# the figure alone on its own line, right against the measure:
#
#     A Juliá Valera, altre dels sargents majors.
#                                            41 »
#
# `tables_on` cannot see it, because it asks each printed line whether it is a
# row and here the row is four lines. The audit found it the other way round --
# `audit_documents.py` ranked `0311-VI-06` and `0311-XI-11` first and second on
# 40 runts between them, and every runt was one of these figures stranded as a
# paragraph of its own.
#
# Two guards, and the second is what separates this from the genealogical tree.
# Leaf 152 has ten figure-only lines aligned to within 0.012 -- the node numbers
# of the plate -- and they hang in the *left* margin of their column, opening
# the entry they belong to. A ledger's figure closes its row and stands at the
# right. So the figure has to sit in the right-hand part of its own column, and
# the label has to come before it and not after.
# How many printed lines of label a row may carry before the two figures stop
# being one ledger. The longest real one in the book is five.
LEDGER_GAP = 6


def ends_in_a_figure(row: list[dict]) -> bool:
    """Does this printed line close with a figure, as a ledger's row does?"""
    return cell_edge(row) is not None


def ledgers_on(leaf: dict) -> list[list[list[dict]]]:
    """Runs of ledger rows, where the label runs over the lines between them."""
    rows = rows_of(leaf)
    lines = [row for _cell, row in rows]
    if not lines:
        return []
    # Only the lines `layout.join_leaders` put back together. That is the whole
    # guard, and it is what the first version lacked: allowing any line that
    # ends in a figure, with up to six lines of label between two rows, took
    # leaf 74's footnote (`los cuatro importan 538 ls. 8 ss.—130 ls. 10 / ss. 5
    # ds. para execuacion de la transaccion de 1315…`) and five other stretches
    # of prose that merely count money. A joined line is *proof* of the ledger's
    # typography: the engines cut it in two at a gap wide enough to be leader
    # dots, and what stood to the right of that gap was nothing but a figure.
    marks = [n for n, row in enumerate(lines)
             if any(w.get("leader") for w in row)]
    found: list[list[list[dict]]] = []
    run: list[int] = []

    def edge(n: int) -> float:
        return max(w["bbox"][2] for w in lines[n])

    def close() -> None:
        if len(run) < MIN_ROWS:
            return
        block: list[list[dict]] = []
        for i, at in enumerate(run):
            since = run[i - 1] + 1 if i else at
            block.append([w for n in range(since, at) for w in lines[n]]
                         + lines[at])
        if all(LABELLED.search(" ".join(w["text"] for w in r)) for r in block) \
                and len({figures(r) for r in block}) > 1:
            found.append(block)

    for at in marks:
        if (run and at - run[-1] <= LEDGER_GAP
                and abs(edge(at) - edge(run[-1])) < ALIGN):
            run.append(at)
            continue
        close()
        run = [at]
    close()
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, help="print the tables found on one leaf")
    args = ap.parse_args()

    skip = set(json.loads(
        (PROJECT / "data" / "entries" / "sections.json").read_text()
    )["jurats_tables"])

    records, rows_total = [], 0
    for path in sorted(TEXT.glob("p*.json")):
        leaf = json.loads(path.read_text())
        if leaf["pdf_page"] in skip:
            continue
        blocks = [("right", b) for b in ledgers_on(leaf)]
        seen = {id(row) for _s, b in blocks for row in b}
        blocks += [(side, b) for side, b in tables_on(leaf)
                   if not any(id(row) in seen for row in b)]
        for side, block in blocks:
            rows_total += len(block)
            records.append({
                "pdf_page": leaf["pdf_page"],
                "figures": side,
                "rows": [[w["text"] for w in row] for row in block],
                "boxes": [[w["bbox"] for w in row] for row in block],
                "tiers": [max((w["tier"] for w in row),
                              key=lambda t: ("unanimous", "one-dissent",
                                             "two-dissent", "contested",
                                             ).index(t)
                              if t in ("unanimous", "one-dissent",
                                       "two-dissent", "contested") else 0)
                          for row in block],
            })

    if args.show:
        for r in records:
            if r["pdf_page"] == args.show:
                print()
                for row in r["rows"]:
                    print("   ", " ".join(row))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tables.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    leaves = sorted({r["pdf_page"] for r in records})
    print(f"{len(records)} tables, {rows_total} rows, on {len(leaves)} leaves")
    print(f"  {leaves}")
    print(f"\n-> {OUT / 'tables.json'}")


if __name__ == "__main__":
    main()
