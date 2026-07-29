"""Sweep the whole chronicle for the symptoms of every defect we have found.

Reading the edition year by year works and does not scale. Year 1229 was worth
reading -- it turned up five defect classes, four of them book-wide -- but it
was worth reading because it is the *first* page of the book, where the century
banner, the first gathering signature and the first footnote all happen to meet.
1230 will show none of that, and it costs the same to read.

So the direction is reversed here. The symptoms are known and every one of them
is checkable without reading anything: a notice that opens in lower case had its
split fall inside a sentence, a `(1)` with no note under it lost its note, a
tail that resolves against Campaner's own glossary and is still sitting in the
prose was never lifted. This runs all of them over all 3 446 notices and returns
a ranked list of where to look, which is a hundred places rather than 572 pages.

**Every check reports its own fire rate, and that is the point.** A check that
fires on a third of the book has found a convention, not a defect, and saying so
is how it gets thrown out instead of quietly generating work. Three of the
checks below are marked `informational` for exactly that reason: they describe
the book rather than accuse it.

Nothing here repairs anything. It says where to look.

Usage:
  python scripts/audit_entries.py                 # the report
  python scripts/audit_entries.py --check split   # every instance of one check
  python scripts/audit_entries.py --year 1644     # one year
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from parse_entries import MONTHS, SIGLA, lift_sigla, resolve

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
OUT = DATA / "audit"

MONTH_NAME = {n: name for name, n in MONTHS.items()}
DAYS_IN = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
           7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

# How much each check counts towards a year's rank. A defect that changes the
# text outranks one that changes where a link points, and both outrank a check
# that is only describing the book.
WEIGHT = {
    "split": 5, "glued": 5, "runt": 4, "dangling-note": 3, "orphan-note": 3,
    "unlifted-siglum": 3, "stray-tail": 2, "leaf-backwards": 2, "bad-day": 2,
    "doubled": 2, "bare-dash": 1, "month-backwards": 0, "long-undated": 0,
}
INFORMATIONAL = {"month-backwards", "long-undated"}

WORD = re.compile(r"[a-záéíóúüñ]+")


def vocabulary() -> Counter:
    """Every lower-case word of the edition, with how often the book uses it.

    The book is its own dictionary, and it has to be: `formacion`, `Setiembre`
    and `mallorquin` are correct here and wrong in any Spanish word list, and
    the medieval Catalan of the documents is in no word list at all.
    """
    counts: Counter = Counter()
    for path in sorted((DATA / "text").glob("p*.txt")):
        text = unicodedata.normalize("NFC", path.read_text(encoding="utf-8"))
        counts.update(WORD.findall(text.lower()))
    return counts


# A word the line-break broke and nothing put back together: `bandole ros`,
# `Cle ro`, `apre saron`. Both halves must be too short to stand on their own,
# the whole must be a word the book uses, and each half must be rarer than the
# whole -- otherwise `de` + `l` and every other real pair of short words fires.
MIN_JOINED = 5


def broken_words(text: str, vocab: Counter) -> list[str]:
    tokens = text.split()
    out = []
    for a, b in zip(tokens, tokens[1:]):
        left, right = a.lower().strip(".,;:»«()¿?¡!—-"), b.lower().strip(".,;:»«()¿?¡!—-")
        if not (WORD.fullmatch(left) and WORD.fullmatch(right)):
            continue
        if len(left) < 2 or len(right) < 2 or len(left) + len(right) < 6:
            continue
        joined = vocab[left + right]
        if joined >= MIN_JOINED and vocab[left] < joined and vocab[right] < joined:
            out.append(f"{a} {b} -> {left + right}")
    return out


NOTE_REF = re.compile(r"[\(\[]\s*(\d{1,2})\s*[\)\]]")
# A notice opens with a capital, an opening quote, a numeral or a bracket.
#
# Opening in lower case looked like the diagnosis and is not, which this sweep
# established on its first run: it fired 204 times, and **201 of the 204 carry
# their date perfectly well**. Campaner's other date form is a sentence opener --
# `…contra el partido de Felipe V.—El 29 llegaron de Barcelona el Teniente de
# Rey…`, 149 of them, plus 33 of `—En 31 de Octubre decretó el Virey…` -- and
# the parser lifts `El 29` into the date column exactly as it lifts `AGOSTO
# 12.—`, leaving a verb behind. That is the book's convention, not a broken cut.
#
# So the check is lower case **and no date recovered**, which is 3 notices. A
# check that fires on 6% of the book has found a convention; keeping the count
# honest is what turns it back into a check.
OPENS_WELL = re.compile(r"^[\"«(\[¿¡A-ZÁÉÍÓÚÑ0-9]")
# Opening with the dash that should have introduced a date is a different and
# milder thing -- the sentence is whole and only its marker was lost -- and
# lumping the two together buried 60 real splits among 211 hits.
OPENS_BARE = re.compile(r"^\s*[-—–*·•]")
TRAILING_DASH = re.compile(r"[-—–]\s*$")
# `—J.` alone at the end: half an attribution, which is worse than none.
LONE_INITIAL = re.compile(r"[-—–]\s*[A-ZÁÉÍÓÚ]\s*\.?\s*$")


def sigla_still_in(text: str) -> list[str] | None:
    """A tail that resolves against the glossary and was left in the prose."""
    match = SIGLA.search(text)
    if not match:
        return None
    return resolve(match.group(0))


def check_entry(entry: dict, vocab: Counter, called: set) -> list[tuple[str, str]]:
    """Every symptom this one notice shows, as (check, what was seen)."""
    text = entry["text"]
    found: list[tuple[str, str]] = []

    if text and not OPENS_WELL.match(text):
        if OPENS_BARE.match(text):
            found.append(("bare-dash", text[:60]))
        elif not entry.get("day") and not entry.get("month"):
            found.append(("split", text[:60]))
    if len(text) < 30:
        found.append(("runt", text))
    for broken in broken_words(text, vocab):
        found.append(("glued", broken))

    numbers = {int(m.group(1)) for m in NOTE_REF.finditer(text)}
    have = {n["number"] for n in entry.get("notes") or ()}
    for missing in sorted(numbers - have):
        found.append(("dangling-note", f"({missing}) in the text, no note"))

    if TRAILING_DASH.search(text) or LONE_INITIAL.search(text):
        found.append(("stray-tail", text[-40:]))
    left = sigla_still_in(text)
    if left:
        found.append(("unlifted-siglum", f"{' '.join(left)} in {text[-40:]!r}"))

    day, month = entry.get("day"), entry.get("month")
    if day and month and day > DAYS_IN[month]:
        found.append(("bad-day", f"{day} of {MONTH_NAME[month]}"))

    # Compared with the accents folded away, because the two copies are two
    # readings of one word and need not agree: leaf 380 prints `Relacion
    # Relación Anónima`, which is one `Relacion` the alignment gave two slots
    # and the panel read differently in each.
    tokens = text.split()
    for a, b in zip(tokens, tokens[1:]):
        bare = fold(a)
        if len(bare) > 2 and bare == fold(b):
            found.append(("doubled", f"{a} {b}"))
    return found


def fold(token: str) -> str:
    plain = unicodedata.normalize("NFD", token.lower().strip(".,;:»«()¿?¡!—-"))
    return "".join(c for c in plain if unicodedata.category(c) != "Mn")


def chronicle_leaves() -> set[int]:
    """The leaves this parser is answerable for.

    A note on a document leaf belongs to `build_documents.py`, which separates
    its own; counting those here turned 22 orphans into 111 and buried them.
    """
    path = DATA / "entries" / "sections.json"
    if not path.exists():
        return set()
    return set(json.loads(path.read_text())["chronicle"])


def run(entries: list[dict], notes: dict) -> list[dict]:
    vocab = vocabulary()
    called = {(e["pdf_page"], n["number"], n["column"])
              for e in entries for n in e.get("notes") or ()}

    findings: list[dict] = []

    def add(check, entry, detail):
        findings.append({"check": check, "year": entry.get("year"),
                         "month": entry.get("month"), "day": entry.get("day"),
                         "pdf_page": entry["pdf_page"], "detail": detail,
                         "excerpt": entry["text"][:90]})

    for entry in entries:
        for check, detail in check_entry(entry, vocab, called):
            add(check, entry, detail)

    # A note the leaves print and no notice calls. Counted against the leaf
    # rather than a notice, because the notice that should have called it is
    # exactly what is missing.
    chronicle = chronicle_leaves()
    for page, printed in notes.items():
        if chronicle and int(page) not in chronicle:
            continue
        for note in printed:
            if (int(page), note["number"], note["column"]) in called:
                continue
            near = [e for e in entries if e["pdf_page"] == int(page)]
            findings.append({
                "check": "orphan-note", "year": near[0]["year"] if near else None,
                "month": None, "day": None, "pdf_page": int(page),
                "detail": f"({note['number']}) col{note['column']} called by nothing",
                "excerpt": note["text"][:90]})

    # Order-of-the-book checks, per year and in the order the book prints it.
    by_year: dict[int, list[dict]] = defaultdict(list)
    for entry in entries:
        if entry.get("year"):
            by_year[entry["year"]].append(entry)
    for year, group in by_year.items():
        for before, after in zip(group, group[1:]):
            if after["pdf_page"] < before["pdf_page"]:
                add("leaf-backwards", after,
                    f"leaf {before['pdf_page']} then {after['pdf_page']}")
            if (before.get("month") and after.get("month")
                    and after["month"] < before["month"]):
                add("month-backwards", after,
                    f"{MONTH_NAME[before['month']]} then "
                    f"{MONTH_NAME[after['month']]}")
        # A long notice with no month among dated ones has probably lost its
        # date marker -- or is one of the stretches the chronicle simply runs
        # on through. The check cannot tell, which is why it only ranks.
        dated = sum(1 for e in group if e.get("month"))
        if dated >= 3:
            for entry in group:
                if not entry.get("month") and len(entry["text"]) > 300:
                    add("long-undated", entry, f"{len(entry['text'])} chars")

    return findings

# Ranking notices by how doubtful their words are was tried here and taken out.
# The entry text has been hyphen-stitched and re-joined, so it can only be
# matched to the leaf's words by the word itself, and a word doubtful *once* on
# a leaf then marks every occurrence of it: the check fired on 58% of the book.
# `review.py` does the same thing properly, keyed by word box, and this file is
# about the parse rather than the reading.


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", help="list every instance of one check")
    ap.add_argument("--year", type=int, help="list everything found in one year")
    ap.add_argument("--top", type=int, default=20,
                    help="how many years to rank")
    args = ap.parse_args()

    entries = [json.loads(line) for line in
               (DATA / "entries" / "entries.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    notes_file = DATA / "entries" / "footnotes.json"
    notes = json.loads(notes_file.read_text()) if notes_file.exists() else {}
    findings = run(entries, notes)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "findings.json").write_text(
        json.dumps(findings, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.check:
        for f in findings:
            if f["check"] == args.check:
                print(f"{f['year']} p{f['pdf_page']:<4} {f['detail']}")
                print(f"      {f['excerpt']}")
        return
    if args.year:
        for f in findings:
            if f["year"] == args.year:
                print(f"[{f['check']}] p{f['pdf_page']} {f['detail']}")
                print(f"      {f['excerpt']}")
        return

    tally = Counter(f["check"] for f in findings)
    print(f"{len(entries):,} notices, {sum(len(v) for v in notes.values()):,} "
          f"footnotes as printed\n")
    print(f"{'check':17} {'hits':>6}  {'per notice':>10}   weight")
    for check in sorted(tally, key=lambda c: -tally[c]):
        mark = "  (informational)" if check in INFORMATIONAL else ""
        print(f"  {check:15} {tally[check]:>6}  {tally[check]/len(entries):>9.1%}"
              f"   {WEIGHT.get(check, 1)}{mark}")

    score: Counter = Counter()
    for f in findings:
        if f["year"]:
            score[f["year"]] += WEIGHT.get(f["check"], 1)
    ranked = [(y, n) for y, n in score.most_common() if n]
    print(f"\nWhere to look, worst first ({len(ranked)} years carry anything "
          f"at all):")
    for year, points in ranked[:args.top]:
        kinds = Counter(f["check"] for f in findings
                        if f["year"] == year and WEIGHT.get(f["check"], 1))
        detail = ", ".join(f"{n}×{c}" for c, n in kinds.most_common())
        print(f"  {year}  {points:>4}   {detail}")

    print(f"\n-> {OUT / 'findings.json'}")


if __name__ == "__main__":
    main()
