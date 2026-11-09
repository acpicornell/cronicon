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
import statistics
from pathlib import Path

import layout

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
# A row needs a label -- two letters or more somewhere in it -- so that a bare
# figure at the foot of a column cannot open a table. Three was too many: leaf
# 159's household account of 1307 runs `It. vi.`, `It. farina.`, `It. figues y
# cogombres.` and the first of those has no word of three letters, so the block
# was never a table. Over the whole book, dropping to two admits exactly **two
# further tables** -- that one, and leaf 607's table of coin values (`Dobla de
# 20 pesos ú onza . . 24 lbs. 3 ss. 8 ds.`) -- and both are real.
LABELLED = re.compile(r"[A-Za-zÀ-ÿ]{2,}")
# A table is at least this many rows. Two aligned figures happen by accident in
# ordinary prose; three do not.
MIN_ROWS = 3
# A table puts white space between the label and the figure -- leader dots, or
# the blank the printer leaves. Prose puts a word space, which in this book is
# 0.0066 of the page. That is the whole difference between `Cebada. . . . .
# 179,000 »` and leaf 241's `com dura lo divinal offici a raho de 2 ss. 6 ds.`,
# which is a sentence in medieval Catalan that happens to end in money and was
# the one false detection among 29. Measured over every table found: leaf 241's
# median gap is 0.0075 and the smallest of the real ones is 0.0146, so 0.010
# sits in the gap and above a word space.
MIN_GUTTER = 0.010
# A record that is nothing but a ditto mark or a unit: the tail of a row's
# figures often arrives as several records, and `»` alone carries no digit.
# **Leader dots are not a cell.** `Cebada. . . . . 179,000 »` arrives as four
# records and the run of dots matched a pattern that allowed only punctuation,
# so the walk back swallowed it and the figure's edge came out as the dots' --
# 0.226 instead of 0.420, which is why leaves 566, 571, 609, 612 and 625 lost
# their harvests. A cell has to carry a ditto mark or a unit.
CELL_ONLY = re.compile(r"^[\s.,·•]*(?:[»\"'*]+|(?:cuarteras?|id|ls|ss|ds|lbs?"
                       r"|libs?)\.?)[\s.,»]*$", re.IGNORECASE)


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

    **The edge returned is the row's, not the figure's**, and that was wrong
    before: where the last record is a unit the figure's own edge is the
    *penultimate* record's, so `Ingresos. . . . . 17.069 libs. 15 ss. 6 ds.`
    aligned on the `6` and `Gastos.. . . . . 8.435 » 16 » 11 »` on the `11`,
    which are two different columns of the page. The three closing rows of the
    account of 1318 therefore never formed a table. What the printer aligns is
    the end of the row.
    """
    at = len(row)
    while at and (layout.only_a_figure(row[at - 1]["text"])
                  or CELL_ONLY.match(row[at - 1]["text"].strip())):
        at -= 1
    if at == len(row):
        return None
    if at == 0:
        # The whole row arrived as one record, which happens where the panel
        # disagreed about the leader dots: leaf 159's `It. peix y ous 1 » 6 »`
        # is a single span. Then the split is made inside its text, and the
        # edge is the record's own, which is what the alignment uses anyway.
        tokens = row[0]["text"].split()
        cut = len(tokens)
        while cut and (layout.only_a_figure(tokens[cut - 1])
                       or CELL_ONLY.match(tokens[cut - 1])):
            cut -= 1
        if not cut or cut == len(tokens):
            return None
        if not any(c.isdigit() for c in " ".join(tokens[cut:])):
            return None
        return "right", (row[0]["bbox"][2], row[0]["bbox"][2])
    tail = " ".join(w["text"] for w in row[at:])
    if not any(c.isdigit() for c in tail):
        # A row whose cells are all ditto marks. On the household accounts of
        # 1307 (leaf 159) most of them are: `Una galina. . . . . . . 2 » » » »`
        # is four ditto marks and one figure, set far apart, and the panel keeps
        # the dittos and drops the figure. Such a row may *continue* a table but
        # never open one, so it is returned marked and `tables_on` decides.
        return "ditto", (max(w["bbox"][2] for w in row), row[at]["bbox"][2])
    # Two edges, because the printer aligns two things and the panel loses one
    # or the other: the end of the row, and the end of the figure that opens the
    # cell run. Taking only the row's end cost leaves 566, 571 and 612, where
    # `Cebada. . . . • 37.663 »` and `Avena. . . . . 23,038` end 0.05 apart
    # because one keeps its ditto mark and the other does not; taking only the
    # figure's cost leaf 161, where `Ingresos… 6 ds.` aligned on the `6` and
    # `Gastos… 11 »` on the `11`. A run continues if **either** holds.
    return "right", (max(w["bbox"][2] for w in row), row[at]["bbox"][2])


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


def gutter(block: list[list[dict]]) -> float:
    """The median white space between a row's label and its figures."""
    gaps = []
    for row in block:
        at = len(row)
        while at and (layout.only_a_figure(row[at - 1]["text"])
                      or CELL_ONLY.match(row[at - 1]["text"].strip())):
            at -= 1
        if 0 < at < len(row):
            gaps.append(row[at]["bbox"][0] - row[at - 1]["bbox"][2])
    return statistics.median(gaps) if gaps else 0.0


def tables_on(leaf: dict) -> list[list[list[dict]]]:
    """Runs of consecutive lines whose figures line up on the right."""
    rows = rows_of(leaf)
    found = []
    n = 0
    while n < len(rows):
        if rows[n][0] is None or rows[n][0][0] == "ditto":
            n += 1
            continue
        side, edge = rows[n][0]
        m = n
        while (m + 1 < len(rows) and rows[m + 1][0] is not None
               and rows[m + 1][0][0] in (side, "ditto")
               and any(abs(a - b) < ALIGN
                       for a, b in zip(rows[m + 1][0][1], edge))):
            m += 1
        # A run may not *end* on a ditto row either: what closes a table is a
        # figure, and trailing dittos are as likely to be a closing guillemet
        # the panel gave a record of its own.
        while m > n and rows[m][0][0] == "ditto":
            m -= 1
        block = [row for _cell, row in rows[n:m + 1]]
        # Every row reading the same figure is a label repeated, not a table.
        if (len(block) >= MIN_ROWS and len({figures(r) for r in block}) > 1
                and gutter(block) > MIN_GUTTER):
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
