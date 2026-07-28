"""Turn the consensus into the chronicle's own structure: year, date, entry, source.

Campaner wrote a chronicle, so the structure is already in the book and this only
has to recognise it rather than impose one:

    1459.                          <- a centred display line
    Mayo 2.—Real Pragmática de D. Juan II, ordenando que…—G. T.
    —25.—Este dia (víspera de su marcha) «con instrumento…»—B. J.

Year headings are *not* found by geometry. That was tried and measured: real
headings sit anywhere from dead centre of their column to 47% off it, and a
heading at the top of a column occupies the same band as the running head's page
number. What identifies one is that the line says a year and nothing else, that
several of the eight readings agree on which year, and that the year fits a
chronicle which only ever moves forward.

Two candidates survive all of that and are still wrong; both were settled against
the facsimile rather than argued about:

  leaf 39  `1449.`  the page really does print 1449, and the entry beneath it
                    reads «año de 1249, perseverando…». Campaner's own error,
                    and by the rules of this edition it stays on the page.
  leaf 74  `1336.»` the last line of a footnote quotation, `…a 13 dias dagost
                    de 1336.»`, wrapped onto a line of its own.

Entries are then split on the date markers, and the trailing sigla — `—G. T.`,
`—B. J.`, `—L. V.` — are lifted out as the source attribution, which is what makes
this book worth reading in a database: you can ask which manuscript reports what.

Nothing is corrected here. Where the parse cannot see a structure it says so, and
the anomalies are reported rather than smoothed over.

Usage:
  python scripts/parse_entries.py --consensus consensus6_swap_swapk
  python scripts/parse_entries.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import targets

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
OUT = PROJECT / "data" / "entries"

FIRST_YEAR, LAST_YEAR = 1229, 1800

# A year heading is a line that says nothing but a year. Geometry was tried first
# and does not work: real headings sit anywhere from the exact centre of their
# column to 47% off it, and the running head's page number occupies the same band
# (y 0.080-0.099) as a heading at the top of a column (0.088-0.123). What does
# separate them is the *text* and the *panel*, which is what the rest of this
# pipeline runs on anyway.
#
# Digits the engines habitually return as letters. Restoring them is not guessing:
# the reading is only accepted when the panel independently supports the year.
DIGIT_LOOKALIKE = str.maketrans({"I": "1", "l": "1", "i": "1", "|": "1", "/": "1",
                                 "J": "1", "Í": "1", "¡": "1", "!": "1",
                                 "O": "0", "o": "0", "S": "5"})
# Punctuation the printer or the engines hang off a heading: `1282.»`, `1337-`,
# `1353•`, `i 501 .`.
HEADING_NOISE = re.compile(r"[\s.,;:\-—‐–_•*'’‘\"«»()\[\]ºª]")
YEAR_IN = re.compile(r"\d{4}")
# How many of the eight readings must contain the year before it counts. One
# engine hallucinating digits inside a sigla (`G. T.` -> 1232) is common; three
# agreeing on the same four digits, on a line that says nothing else, is not.
MIN_YEAR_VOTES = 3
# The century banners, in both forms the book uses: `SIGLO XIV.` and
# `DE 1301 Á 1400.`. The second one states two years and would otherwise be read
# as a heading for the first of them.
CENTURY_LINE = re.compile(r"^\s*(SIGLO\s+[IVXLC]+|DE\s+1[2-8]\d\d\s*[ÁA]\s*1[2-8]\d\d)",
                          re.IGNORECASE)

MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "setiembre": 9, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

# How an entry actually opens, read off the text rather than assumed. The date
# comes *before* the em dash, not after it:
#
#   —B. J. JUNIO.—Por Bula dada en Roma…        month, no day
#   —G. T. JULIO 21.—Llegó la noticia…          month and day
#   —B. J. —20.—Murió el Obispo…                day alone, month carried over
#   —G. T. —Este año, sin indicarse la fecha…   no date at all
#
# An earlier version required the dash before the month and matched almost
# nothing: 16% of entries came out dated where it should be most of them.
ENTRY_START = re.compile(
    rf"(?:"
    rf"(?<![a-záéíóúñA-ZÁÉÍÓÚÑ])(?P<month>{MONTH_ALT})\s*(?P<day1>\d{{1,2}})?\s*\.?\s*—"
    rf"|—\s*(?P<day2>\d{{1,2}})\s*\.\s*—"
    rf"|—\s*(?=Este\s+(?:año|mes|dia|día))"
    rf")",
    re.IGNORECASE)

# A year heading the layout missed and left inline, sitting immediately before a
# date marker: `—B. J. 1459. Mayo 2.—`. Anchored to the end of the run so that a
# year mentioned in passing ("la donacion de 1058. Sin embargo…") cannot be
# mistaken for a heading -- only one that directly precedes a date counts.
INLINE_YEAR = re.compile(r"(?<!\d)(1[2-8]\d\d)\s*[.,\-—]\s*$")

# Sigla trailing an entry: —G. T. / —B. J. / —L. V. / —Jn. Br. / —T. A.
SIGLA = re.compile(r"—\s*((?:[A-ZÁÉÍÓÚ][a-z]?\.\s*){1,3})\s*$")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def page_lines(path: Path) -> list[dict]:
    """Lines with text, box, column and the worst certainty tier they contain."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for locus in json.loads(path.read_text())["loci"]:
        key = tuple(locus["line_bbox"])
        if key not in grouped:
            order.append(key)
        grouped[key].append(locus)

    rank = {"unanimous": 0, "one-dissent": 1, "two-dissent": 2, "contested": 3}
    lines = []
    for key in order:
        row = sorted(grouped[key], key=lambda x: x["index"])
        lines.append({
            "text": " ".join(w["winner"] for w in row).strip(),
            "bbox": list(key),
            "row": row,
            "worst_tier": max((w["grade"] for w in row),
                              key=lambda g: rank[g], default="unanimous"),
            "tiers": Counter(w["grade"] for w in row),
        })
    return lines


# A Jurats table announces itself: numbered names one per line (`3.—Bernardo de
# Font.`) and year labels written out (`AÑO 1332.`), on leaves whose lines are
# half the length of prose.
NUMBERED_NAME = re.compile(r"^\s*[1-6IJl]\s*[.,]\s*[—\-]")
YEAR_LABEL = re.compile(r"^\s*(A[ÑN]O|ANO)[ .]*1[2-8]")


def is_table_leaf(lines: list[dict], columns: int) -> bool:
    """Whether this leaf is a Jurats name list rather than chronicle.

    `inventory.py` finds the tables that print in three or more columns, and
    misses the ones typeset as two: leaves 58-60 (13th century) and 114-121
    (14th, headed `APÉNDICES. I.`) are name lists that read as two columns and
    slipped through. Their year labels run 1302, 1303, 1304 down the page and
    dragged the chronology back a century every time the parser met one.
    """
    if columns >= 3:
        return True
    body = [ln["text"] for ln in lines if ln["text"].strip()]
    if not body:
        return False
    numbered = sum(1 for t in body if NUMBERED_NAME.match(t))
    labels = sum(1 for t in body if YEAR_LABEL.match(t))
    return numbered / len(body) >= 0.15 or labels >= 2


def fill_table_runs(tables: set[int], body: list[int]) -> set[int]:
    """Close single-leaf gaps inside a table run.

    Leaf 117 sits in the middle of the 114-121 list but carries so much
    explanatory note-text that it reads as prose. A leaf with a table on either
    side of it is part of the table.
    """
    index = {page: n for n, page in enumerate(body)}
    filled = set(tables)
    for page in tables:
        n = index.get(page)
        if n is None or n + 2 >= len(body):
            continue
        if body[n + 2] in tables:
            filled.add(body[n + 1])
    return filled


def spillover(candidates: list[dict], accepted: dict, body: list[int],
              aside: set[int]) -> set[int]:
    """Leaves where a table or an excursus runs on past the end of its leaf.

    The Jurats lists do not stop neatly: leaf 229 opens with `1498. 1499.` and
    the last dozen names of the table on 225-228, and leaf 482 does the same for
    the table on 478-481. That stray `1500.` is monotone, so the chronology
    accepts it, and having accepted it the chronicle cannot then climb back to
    the 1487 that really does begin on leaf 242.

    A leaf directly after material already set aside, every year on which the
    chronicle has already passed, is the tail of that material.
    """
    years: dict[int, list[int]] = defaultdict(list)
    for c in candidates:
        years[c["page"]].append(c["year"])
    reached: dict[int, int] = {}
    high = 0
    for page in body:
        reached[page] = high
        if page in aside:
            continue
        for (p, _pos), c in accepted.items():
            if p == page:
                high = max(high, c["year"])

    out: set[int] = set()
    for n, page in enumerate(body):
        if n == 0 or page in aside or page not in years:
            continue
        if body[n - 1] in aside | out and max(years[page]) <= reached[page]:
            out.add(page)
    return out


def says_only_a_number(text: str) -> bool:
    """True if the line carries digits and nothing else.

    This is what keeps sums of money and dates in prose out: `1,259 carros`,
    `1700 lbs.`, `hasta 1343.`, `Any 1522`, `á 1558.)` all read as years to a
    naive scan and all still have letters in them. A display heading does not.

    Up to eight digits, because a heading is sometimes recognised twice over --
    `1507. I507.`, `1576. . IS76.` -- and the vote then settles which it is.
    """
    stripped = HEADING_NOISE.sub("", text).translate(DIGIT_LOOKALIKE)
    return bool(stripped) and stripped.isdigit() and len(stripped) <= 8


# A heading and the first words of its entry, caught in one line box.
GLUED_HEADING = re.compile(r"^\s*([\dIilJ|/Í¡!Oo]{3,6})\s*[.,\-—:]\s*(\S.*)$")


def glued_entry(line: dict) -> str | None:
    """The entry text a display heading is stuck to, if it is stuck to one.

    The commonest way a year goes missing is not a misread digit: it is the line
    finder taking `1460.` and `Marzo 3.—Se pregonó…` for one line. Sixteen
    readings agree the year is there and every rule above still throws it away
    because the line has letters in it.

    Telling that apart from a year inside prose (`1700 lbs.`, `de 1721.»`) needs
    to know that what follows the year opens an entry: an opening quote, or a
    month. The month is read off the panel rather than the winner, because the
    winner is exactly what tends to be damaged here -- leaf 595 prints `Febrero`
    and the consensus returned `Fbbrbro`, while three engines read it plainly.
    """
    match = GLUED_HEADING.match(line["text"])
    if not match:
        return None
    rest = match.group(2)
    if rest.startswith("«"):
        return rest
    for word in line["row"][1:]:
        for reading in list(word["variants"].values()) + [word["winner"]]:
            plain = strip_accents(re.sub(r"[^\w]", "", reading or "")).lower()
            if plain in MONTHS:
                return rest
    return None


def years_in(text: str) -> set[int]:
    """Every in-range year these characters could be stating."""
    digits = HEADING_NOISE.sub("", text or "").translate(DIGIT_LOOKALIKE)
    return {int(m.group()) for m in YEAR_IN.finditer(digits)
            if FIRST_YEAR <= int(m.group()) <= LAST_YEAR}


def heading_votes(row: list[dict]) -> Counter:
    """What year, if any, the panel says this line states -- and how loudly.

    The consensus winner is often the *worst* reading of a year heading, because
    a line of five characters gives the vote almost nothing to work with:
    `I3II.` won a three-way tie on leaf 66 while PaddleOCR had plainly read
    `1311.`. Counting the year across all eight readings recovers it from
    evidence rather than from a character-substitution guess.
    """
    votes: Counter = Counter()
    for word in row:
        readings = list(word["variants"].values()) + [word["winner"]]
        for reading in readings:
            for year in years_in(reading):
                votes[year] += 1
    return votes


def year_of_line(line: dict) -> tuple[int | None, int, str]:
    """The year a line announces, the readings backing it, and any entry text."""
    text = line["text"]
    # A heading five characters wide gives the vote almost nothing to work with,
    # and the winner regularly collapses to a single character -- `1`, `I`, `r.`,
    # `M.` -- while most of the panel read the year plainly. When the whole line
    # is one short token, what the panel says outweighs what the vote returned.
    if says_only_a_number(text) or (len(line["row"]) == 1 and len(text) <= 6):
        remainder = ""
    elif len(text) > 14:
        return None, 0, ""
    else:
        remainder = glued_entry(line)
        if remainder is None:
            return None, 0, ""
    votes = heading_votes(line["row"])
    if not votes:
        return None, 0, ""
    year, count = votes.most_common(1)[0]
    if count < MIN_YEAR_VOTES:
        return None, count, ""
    return year, count, remainder


def monotone_subsequence(years: list[int]) -> list[int]:
    """Indices of the longest non-decreasing run through the candidates.

    The chronicle only moves forward, so a heading that goes backwards is a
    misreading -- of itself or of the one before it. Rather than trusting
    whichever came first, keep the largest set of headings that can all be true
    together and report the rest. This is what caught `1249.` on leaf 39 being
    read as `1449.`: one candidate contradicted forty of its neighbours.
    """
    if not years:
        return []
    best = [1] * len(years)
    prev = [-1] * len(years)
    for i in range(len(years)):
        for j in range(i):
            if years[j] <= years[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end = max(range(len(years)), key=lambda i: best[i])
    out = []
    while end != -1:
        out.append(end)
        end = prev[end]
    return out[::-1]


def split_entries(text: str, year: int | None) -> list[dict]:
    """Cut a run of prose into dated entries, carrying the month forward.

    Campaner writes the month once and then gives bare days until it changes, so
    a `—20.—` inherits whatever month was last stated. The year does the same
    when the layout missed its display heading.
    """
    marks = list(ENTRY_START.finditer(text))
    if not marks:
        return ([{"month": None, "day": None, "year": year,
                  "text": text.strip()}] if text.strip() else [])

    entries = []
    preamble = text[:marks[0].start()].strip()
    if preamble:
        entries.append({"month": None, "day": None, "year": year,
                        "text": preamble})

    current_month = None
    for n, mark in enumerate(marks):
        end = marks[n + 1].start() if n + 1 < len(marks) else len(text)
        body = text[mark.end():end].strip()

        # a year heading the layout missed, sitting just before this marker
        head = text[marks[n - 1].end() if n else 0:mark.start()]
        found = INLINE_YEAR.search(head.rstrip())
        if found and FIRST_YEAR <= int(found.group(1)) <= LAST_YEAR:
            year = int(found.group(1))

        month = mark.group("month")
        if month:
            current_month = MONTHS[strip_accents(month).lower()]
        day = mark.group("day1") or mark.group("day2")
        if not body:
            continue
        # An "entry" consisting of nothing but a sigla is the tail of the one
        # before it, orphaned when the split fell between the two.
        if entries and re.fullmatch(r"(?:[A-ZÁÉÍÓÚ][a-z]?\.\s*){1,3}", body):
            entries[-1]["text"] = (entries[-1]["text"] + " —" + body).strip()
            continue
        entries.append({
            "month": current_month,
            "day": int(day) if day else None,
            "year": year,
            "text": body,
        })
    return entries


def collapse_repeat(siglum: str) -> str:
    """`G. G. T.` is `G. T.` counted twice, not a siglum of three initials.

    The engines disagree about where the token after the dash ends: some read
    `reos.»—G.` and `T.`, others `reos.»—` and `G.` and `T.`. The alignment keeps
    both, so the `G.` appears at two positions and the vote accepts it at each.
    Leaf 65 prints `—G. T.`, checked against the facsimile, and the same doubling
    produced `B. B. J.`, `M. M. M.`, `Cl. Fl. Fl.` and `J. J. F.` elsewhere.

    Only a three-part siglum is collapsed, and only where two neighbours are
    equal: `M. M.` is Matías Mut and must survive intact.
    """
    parts = siglum.split()
    if len(parts) != 3:
        return siglum
    for n in (0, 1):
        if parts[n] == parts[n + 1]:
            return " ".join(parts[:n] + parts[n + 1:])
    return siglum


def lift_sigla(text: str) -> tuple[str, list[str]]:
    sigla = []
    while True:
        match = SIGLA.search(text)
        if not match:
            break
        sigla.insert(0, collapse_repeat(
            re.sub(r"\s+", " ", match.group(1)).strip()))
        text = text[:match.start()].rstrip()
    return text, sigla


def report_gaps(missing: list[int], headings: list[tuple[int, int]],
                leaves: dict[int, list[dict]], aside: set[int]) -> None:
    """For each year with no heading, whether the book looks like it has one.

    A year can be absent for two quite different reasons and they need telling
    apart before anyone goes hunting: Campaner may simply have had no news to
    report -- 1355 to 1361 is seven consecutive silent years -- or the heading
    may be there and unreadable. The test is whether any line on the leaves that
    bracket the year carries that year in *any* engine's reading, at any vote
    count. If nothing anywhere says 1233, the book does not say 1233.
    """
    print(f"\nyears with no heading, and whether one seems to be on the page:")
    silent, suspect = [], []
    for year in missing:
        before = [p for p, y in headings if y < year]
        after = [p for p, y in headings if y > year]
        span = range(before[-1] if before else 0, (after[0] if after else 10**6) + 1)
        traces = []
        for page in (p for p in span if p in leaves and p not in aside):
            for line in leaves[page]:
                if len(line["text"]) <= 16 and year in heading_votes(line["row"]):
                    traces.append((page, line["text"],
                                   heading_votes(line["row"])[year]))
        (suspect if traces else silent).append((year, traces))

    print(f"  {len(silent)} with no trace anywhere in their span "
          f"-- the chronicle is silent on them: {[y for y, _ in silent]}")
    print(f"  {len(suspect)} with a damaged line that may be the heading:")
    for year, traces in suspect:
        page, text, votes = traces[0]
        print(f"    {year}  p{page} {text!r} ({votes} readings)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    if not source.exists():
        raise SystemExit(f"{source} missing -- run scripts/consensus.py first")

    inventory = {leaf["pdf_page"]: leaf for leaf in
                 json.loads((PROJECT / "data" / "inventory.json").read_text())["leaves"]}

    # ---- pass 1: read every body leaf, and separate chronicle from name list.
    leaves: dict[int, list[dict]] = {}
    body_pages: list[int] = []
    for pdf_page in targets.resolve("all"):
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists() or inventory[pdf_page]["page_class"] != "body":
            continue
        leaves[pdf_page] = page_lines(path)
        body_pages.append(pdf_page)

    tables = fill_table_runs(
        {p for p in body_pages
         if is_table_leaf(leaves[p], inventory[p]["columns"])}, body_pages)
    chronicle = [p for p in body_pages if p not in tables]

    # ---- pass 2: collect every line that announces a year, then keep the
    # largest set of them that can all be true at once. Deciding leaf by leaf
    # cannot tell a misread heading from a real jump; the whole sequence can.
    #
    # Then the excursuses. Campaner interrupts the chronicle to print documents
    # in full -- `II. Cartas del gobernador Gilaberto de Centellas`, `IV.
    # Fragmentos de las Apuntaciones del Notario Mateo Salcet` -- and each dates
    # its own material, so leaf 153 runs 1382, 1384, 1387 in the middle of the
    # 1340s. They are not chronicle, and they are what the chronology rejects. A
    # leaf that states years, none of which can be true where it sits, is inside
    # one; leaves between two such leaves are inside the same one.
    #
    # Removing them changes the sequence, so the chronology is recomputed until
    # it stops moving: an excursus twelve leaves long can otherwise outvote the
    # chronicle around it and get itself accepted instead.
    excursus: set[int] = set()
    for _round in range(4):
        candidates = [
            {"page": pdf_page, "position": position, "year": year,
             "votes": votes, "text": line["text"], "rest": rest}
            for pdf_page in chronicle
            for position, line in enumerate(leaves[pdf_page])
            for year, votes, rest in [year_of_line(line)] if year is not None]

        keep = set(monotone_subsequence([c["year"] for c in candidates]))
        rejected = [c for n, c in enumerate(candidates) if n not in keep]
        accepted = {(c["page"], c["position"]): c
                    for n, c in enumerate(candidates) if n in keep}

        found = fill_table_runs(
            {c["page"] for c in rejected} - {p for p, _ in accepted}, chronicle)
        found = fill_table_runs(found, chronicle)
        found |= spillover(candidates, accepted, body_pages,
                           tables | excursus | found)
        if not found - excursus:
            break
        excursus |= found
        chronicle = [p for p in chronicle if p not in excursus]

    year = None
    entries: list[dict] = []
    headings: list[tuple[int, int]] = []
    anomalies = [f"p{c['page']}: {c['text']!r} reads {c['year']} "
                 f"({c['votes']} readings) but breaks the chronology"
                 for c in rejected]
    skipped_tables = sorted(tables)

    for pdf_page in chronicle:
        lines = leaves[pdf_page]

        buffer: list[dict] = []

        def flush():
            if not buffer:
                return
            text = ""
            for ln in buffer:
                if text.endswith("-"):
                    text = text[:-1] + ln["text"]
                else:
                    text = (text + " " + ln["text"]).strip()
            nonlocal_year = year
            for entry in split_entries(text, nonlocal_year):
                body, sigla = lift_sigla(entry["text"])
                entries.append({**entry, "text": body, "sources": sigla,
                                "pdf_page": pdf_page,
                                "printed": inventory[pdf_page]["printed"],
                                "ia_leaf": inventory[pdf_page]["ia_leaf"]})
            buffer.clear()

        for position, line in enumerate(lines):
            if not line["text"]:
                continue
            if CENTURY_LINE.match(line["text"]):
                flush()
                continue
            candidate = accepted.get((pdf_page, position))
            if candidate is not None:
                flush()
                year = candidate["year"]
                headings.append((pdf_page, year))
                # …and if the heading came glued to its entry, the entry stays.
                if candidate["rest"]:
                    buffer.append({**line, "text": candidate["rest"]})
                continue
            # A rejected candidate is still not prose: dropping it keeps a stray
            # `1449.` out of the middle of an entry.
            if year_of_line(line)[0] is not None:
                continue
            buffer.append(line)
        flush()

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "entries.jsonl").open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # What the chronicle parse set aside is not rubbish -- it is the Jurats
    # lists and the documents Campaner prints in full, both of which want their
    # own parser. Writing the classification down keeps them from being quietly
    # lost between one script and the next.
    # Where each year of the chronicle is stated. Downstream this is what says
    # where an appendix block ends and the chronicle resumes.
    (OUT / "headings.json").write_text(
        json.dumps(headings, ensure_ascii=False), encoding="utf-8")
    (OUT / "sections.json").write_text(json.dumps({
        "chronicle": chronicle,
        "jurats_tables": skipped_tables,
        "document_excursus": sorted(excursus),
        "rejected_headings": [
            {"pdf_page": c["page"], "text": c["text"], "reads": c["year"],
             "readings": c["votes"]} for c in rejected],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    years = [y for _p, y in headings]
    dated = sum(1 for e in entries if e["month"])
    sourced = sum(1 for e in entries if e["sources"])
    print(f"{len(headings)} year headings, {len(set(years))} distinct "
          f"({min(years)}–{max(years)})")
    print(f"{len(entries):,} entries")
    print(f"  with a month      {dated:,}  ({dated/len(entries):.0%})")
    print(f"  with a source     {sourced:,}  ({sourced/len(entries):.0%})")
    print(f"  median length     {sorted(len(e['text']) for e in entries)[len(entries)//2]} chars")

    missing = [y for y in range(min(years), max(years) + 1) if y not in set(years)]
    print(f"\n{len(skipped_tables)} Jurats-table leaves skipped: {skipped_tables}")
    print(f"{len(excursus)} document-excursus leaves set aside: {sorted(excursus)}")
    print(f"years with no heading at all: {len(missing)}")
    if args.report:
        print(f"  {missing[:40]}{' …' if len(missing) > 40 else ''}")
        print(f"\ncandidates rejected by the chronology ({len(anomalies)}):")
        for line in anomalies[:25]:
            print(f"  {line}")
        report_gaps(missing, headings, leaves, tables | excursus)
        top = Counter(s for e in entries for s in e["sources"])
        print(f"\ntop sigla: {dict(top.most_common(12))}")

    print(f"\n-> {OUT / 'entries.jsonl'}")


if __name__ == "__main__":
    main()
