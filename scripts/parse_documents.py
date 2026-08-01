"""Delimit the documents Campaner prints in full, between the centuries.

At the close of each century the chronicle stops and an appendix runs for
anything from six to seventy leaves: the Jurats list first, then documents given
whole -- `II. Cartas del gobernador Gilaberto de Centellas á Pedro IV`, `IV.
Relacion (anónima) del tumulto ocurrido en la Iglesia de San Francisco`, `IX.
Relacion (anónima) de la muerte de Jorge San Juan`. They are why the chronology
in `parse_entries.py` keeps meeting years it has already passed: each dates its
own material, so leaf 153 runs 1382, 1384, 1387 in the middle of the 1340s.

Finding the blocks needs care, because leaf count alone does not identify one.
Leaves 253-280 are twenty-eight consecutive leaves of Germanía narrative with no
year heading between 1520 and 1525, and that is chronicle. What every appendix
block does have is a Jurats list at its head, numbered `I`; so a block runs from
a Jurats series to the leaf where the chronicle picks up its next year, and the
sections inside it are numbered from `II` on.

The numerals need care too. Documents quote ordinances that number their own
clauses -- leaf 85 has `III. Item, com sia slat dit al Sr. Rey…` seven times
over -- and the Jurats tables put a bare `I.` above a column. Both are excluded
by requiring the numerals of a block to rise: a section numbered below the one
before it is not a section.

Nothing is transcribed or corrected here; this only says where each document
begins, what it is called, and which leaves it occupies.

Usage:
  python scripts/parse_documents.py --report
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import targets
from parse_entries import OCR, page_lines, year_of_line

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "documents"

ROMAN_RE = r"(X{0,2}(?:IX|IV|V?I{1,3}|V))"
# `IV.` alone on its line, with the title beneath it, or `IV. Relacion…` on one.
# The running head's page number sits on the same line often enough to matter:
# leaf 153 opens `126 IV.` and the numeral was invisible without this.
BARE_NUMERAL = re.compile(rf"^\s*(?:\d{{1,3}}\s+)?{ROMAN_RE}\s*\.?\s*$")
NUMERAL_TITLE = re.compile(rf"^\s*{ROMAN_RE}\s*\.\s+([A-Z«ÁÉÍÓÚ].{{6,}})")
# What a clause of a quoted ordinance opens with, never a section of the book.
CLAUSE = re.compile(r"^(Item|ítem|Ítem)\b")

VALUES = {"I": 1, "V": 5, "X": 10}


def roman_readings(row: list[dict]) -> set[str]:
    """Every numeral the panel offers for a line, not just the winner's.

    The section numerals are set in the heavy display face, and that face is
    what the engines are worst at: leaf 482 prints `II.` and the consensus
    settles on `XX.`, having been offered `zz.`, `LL.`, `IH.`, `TIT.` and one
    correct `II.` from Apple Vision. Reading the numeral off the panel is the
    same move the year headings need, and for the same reason.
    """
    out: set[str] = set()
    for word in row:
        for reading in list(word["variants"].values()) + [word["winner"]]:
            text = (reading or "").strip().upper().rstrip(".-—,")
            if text and BARE_NUMERAL.match(text):
                out.add(BARE_NUMERAL.match(text).group(1))
    return out


def from_roman(text: str) -> int:
    total = 0
    for a, b in zip(text, text[1:] + " "):
        total += -VALUES[a] if VALUES.get(b, 0) > VALUES[a] else VALUES[a]
    return total


def block_bounds(jurats: list[int], chronicle: list[list]) -> list[tuple]:
    """(first leaf, last leaf) of each appendix block.

    A block opens with a Jurats list and closes where the chronicle states its
    next year. That is what tells 114-167 -- fifty-four leaves of appendix -- from
    253-280, which is the same length and is the chronicle itself.
    """
    out = []
    for start in jurats:
        later = [page for page, _year in chronicle if page > start]
        out.append((start, (later[0] - 1) if later else 10 ** 6))
    return out


# How many lines a title may run to. Campaner's longest is three.
TITLE_LINES = 4
# A title line is centred on the measure; a line of body starts at the column's
# left edge. 0.05 of the page is well clear of the paragraph indent, 0.02.
CENTRED = 0.05


def title_after(lines: list[dict], texts: list[str], i: int) -> str:
    """The title under a numeral, however many printed lines it runs to.

    Taking one line truncated a third of them: `Historia de los Reyes de
    Mallorca, que fueron` stopped before `Señores de Montpeller.`, `Fragmentos
    de las Apuntaciones del Notario` before `Mateo Salcet`, and `Relacion
    (anónima) del tumulto ocurrido en la Iglesia de` before `San Francisco de
    Asis`.

    A title is centred and the body is not, which is the same signal the century
    openings and the document paragraphs use. The title runs while the lines
    stay centred on the measure and stops at the first that begins at the
    column's left edge. The line straight after the numeral is taken whatever
    its box says -- it is the title by position -- and only its continuation has
    to prove itself.
    """
    body = [ln for ln in lines if ln["text"].strip()]
    if not body:
        return ""
    left = min(ln["bbox"][0] for ln in body)
    right = max(ln["bbox"][2] for ln in body)
    parts: list[str] = []
    for n in range(i + 1, min(i + 3 + TITLE_LINES, len(lines))):
        text = texts[n]
        if not text:
            continue
        box = lines[n]["bbox"]
        centred = abs((box[0] - left) - (right - box[2])) <= CENTRED
        if parts and not centred:
            break
        # …and it stops at the source note Campaner sets under the title, which
        # is centred too: `«Resúmen recopilado del tomo cuarto de la Historia
        # general del Languedoc…` under section III, and `(pág. 71 del texto.)`
        # under several. Both announce themselves in their first character.
        if parts and text[:1] in "«\"" or text.startswith("(pág"):
            break
        parts.append(text)
        if len(parts) >= TITLE_LINES:
            break
    return " ".join(parts).strip()


def sections(leaves: dict[int, list[dict]], first: int, last: int,
             jurats_until: int) -> list[dict]:
    """The numbered sections inside one block, in order.

    Section I is always the Jurats list and is taken as given rather than looked
    for: its leaves carry a bare `I.` over a column of names, and searching for
    one finds `1406.` or `Antonio Cifre.` as the title of the appendix.
    """
    found: list[dict] = [{"number": 1, "numeral": "I",
                          "title": "Jurados de la c. y r. de Mallorca",
                          "pdf_page": first, "line": 0, "jurats": True}]
    # From the last leaf of the table, not the one after it: the 15th-century
    # list ends on leaf 229 and `II. Fragmentos de las Apuntaciones del Notario`
    # begins ten lines further down the same leaf.
    for page in range(jurats_until, last + 1):
        lines = leaves.get(page)
        if not lines:
            continue
        texts = [ln["text"].strip() for ln in lines]
        for i, text in enumerate(texts):
            readings: set[str] = set()
            match = BARE_NUMERAL.match(text)
            if match:
                title = title_after(lines, texts, i)
                readings.add(match.group(1))
            elif NUMERAL_TITLE.match(text):
                match = NUMERAL_TITLE.match(text)
                title = match.group(2)
                readings.add(match.group(1))
            elif len(text) <= 10 and len(lines[i]["row"]) <= 2:
                # The winner may be no numeral at all -- leaf 482 prints `II.`
                # and the vote returned `XX.` -- so a short line is put to the
                # panel before it is dismissed. The evidence is weaker here, so
                # the prior is stronger: a section found this way has to be the
                # very next one, not merely a later one.
                title = title_after(lines, texts, i)
                readings = {r for r in roman_readings(lines[i]["row"])
                            if from_roman(r) == (found[-1]["number"] + 1
                                                 if found else 1)}
            else:
                continue
            if not readings or CLAUSE.match(title) or len(title) < 8:
                continue
            # Section numbers rise through a block. Anything else is a clause of
            # a document, or the `I.` heading a column of the Jurats table. Among
            # the numerals the panel offers for this line, take the lowest that
            # can still be the next section.
            previous = found[-1]["number"] if found else 0
            options = sorted({(from_roman(r), r) for r in readings},
                             key=lambda x: x[0])
            forward = [o for o in options if o[0] > previous]
            if not forward:
                continue
            number, numeral = forward[0]
            found.append({"number": number, "numeral": numeral,
                          "title": title, "pdf_page": page, "line": i,
                          "read_as": text})
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    entries = PROJECT / "data" / "entries" / "sections.json"
    if not entries.exists():
        raise SystemExit(f"{entries} missing -- run scripts/parse_entries.py")
    series = json.loads((PROJECT / "data" / "jurats" / "series.json").read_text())
    jurats = sorted({s["title_leaf"] for s in series["parsed"]})

    leaves = {p: page_lines(source / f"p{p:04d}.json")
              for p in targets.resolve("all")
              if (source / f"p{p:04d}.json").exists()}

    chronicle = [[page, year] for page, year in
                 json.loads((PROJECT / "data" / "entries" / "headings.json").read_text())] \
        if (PROJECT / "data" / "entries" / "headings.json").exists() else []
    if not chronicle:
        raise SystemExit("data/entries/headings.json missing -- rerun parse_entries.py")

    inventory = {leaf["pdf_page"]: leaf for leaf in
                 json.loads((PROJECT / "data" / "inventory.json").read_text())["leaves"]}
    # Where each Jurats list stops, and so where the numbered sections may start.
    # This used to need patching from `annotated_not_parsed`, because the two
    # annotated series contributed no leaves and the scan for section numerals
    # then began inside the list's own prose -- leaf 58 says «...ejercieron
    # aquella magistratura, siglo XIV», and `XIV` became a section. Now that
    # those leaves are parsed, `leaves` covers them and the patch would undo it.
    jurats_end = {s["title_leaf"]: max(s["leaves"] + [s["title_leaf"]])
                  for s in series["parsed"]}

    blocks = []
    for first, last in block_bounds(jurats, chronicle):
        # The last block has no chronicle after it; it stops where the book's
        # own sectioning does.
        section = inventory[first]["section"]
        last = min(last, max(p for p in leaves
                             if inventory.get(p, {}).get("section") == section))
        found = sections(leaves, first, last, jurats_end.get(first, first))
        for n, item in enumerate(found):
            item["until"] = (found[n + 1]["pdf_page"] - 1
                             if n + 1 < len(found) else last)
            # The years a section dates its own material to. This is the whole
            # reason the chronicle parse has to set these leaves aside, and it
            # is also what makes them findable once they are separated out.
            years = sorted({y for page in range(item["pdf_page"], item["until"] + 1)
                            for line in leaves.get(page, [])
                            for y, votes, _rest in [year_of_line(line)]
                            if y is not None})
            if years:
                item["years"] = [years[0], years[-1]]
                item["years_stated"] = len(years)
        missing = [n for n in range(1, max(i["number"] for i in found))
                   if n not in {i["number"] for i in found}]
        blocks.append({"first_leaf": first, "last_leaf": last,
                       "leaves": last - first + 1, "sections": found,
                       "numerals_not_found": missing})

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "documents.json").write_text(
        json.dumps(blocks, ensure_ascii=False, indent=1), encoding="utf-8")

    total = sum(len(b["sections"]) for b in blocks)
    print(f"{len(blocks)} appendix blocks, {total} numbered sections, "
          f"{sum(b['leaves'] for b in blocks)} leaves\n")
    for block in blocks:
        print(f"leaves {block['first_leaf']}–{block['last_leaf']} "
              f"({block['leaves']} leaves)")
        for item in block["sections"]:
            span = (f"{item['pdf_page']}–{item['until']}"
                    if item["until"] > item["pdf_page"] else f"{item['pdf_page']}")
            print(f"   {item['numeral']:>5}. {span:>9}  {item['title'][:64]}")
        if block["numerals_not_found"]:
            print(f"   not found: {block['numerals_not_found']}")
        print()

    print(f"-> {OUT / 'documents.json'}")


if __name__ == "__main__":
    main()
