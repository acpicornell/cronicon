"""Sweep the 23 documents for the symptoms of every defect we have found there.

`audit_entries.py` did this for the chronicle and the lesson transfers exactly:
reading one document end to end works and does not scale. Section II of the
18th-century block was worth reading -- it turned up five classes, four of them
book-wide -- but it was worth reading because it is a diary, where the year
heading, the display month, the folio number and the source siglum all happen to
meet on one leaf. `0225-IV-04` is eight paragraphs of narrative and will show
none of that, and it costs the same to read.

So the direction is reversed. Every symptom found so far is checkable without
reading anything, and most of them are checkable against the panel rather than
against a dictionary: a month heading the winner mangled is one some engine read
plainly, a year that came out `171` is one three engines read as `1711`, a
paragraph that is four characters long is either a piece number or wreckage.

**Every check reports its own fire rate**, for the same reason as the chronicle's
sweep: a check that fires on a fifth of the corpus has found a convention and
needs throwing out, not acting on. The ones that describe the book rather than
accuse it are marked `informational` -- a legal deposition really is one
paragraph of 3 000 characters, and a diary really does have notices of eleven
words.

Nothing here repairs anything. It says where to look.

Usage:
  python scripts/audit_documents.py                    # the report
  python scripts/audit_documents.py --check wall       # every instance of one
  python scripts/audit_documents.py --doc 0114-II-02   # one document
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

import spans
from build_documents import (CONTINUES, LETTER, PIECE_LOOKALIKE, PIECE_MARK,
                             WEDGE, piece_votes, unwedge, year_heading)
from build_text import BREAK_HYPHEN
from layout import is_folio, is_running_head
from parse_entries import (OCR, heading_votes, lift_sigla, page_lines, resolve,
                           split_notes)

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
OUT = DATA / "audit"

# How much each check counts towards a document's rank. A defect that changes
# the text outranks one that changes how it is set, and both outrank a check
# that is only describing the book.
WEIGHT = {
    "wedged": 5, "head-leak": 5, "glued": 5, "bad-month": 4, "broken-year": 4,
    "piece-gap": 3, "dangling-note": 3, "orphan-note": 3, "unlifted-siglum": 3,
    "title-cut": 3, "runt": 2, "stray-tail": 2, "bare-dash": 1,
    "wall": 0, "short-para": 0, "contested": 0,
}
INFORMATIONAL = {"wall", "short-para", "contested"}

# A paragraph with fewer letters than this is not a short paragraph, it is
# wreckage -- calibrated on the chronicle's own `runt`, where the shortest real
# notice has 12 letters and nothing sits in the gap below it.
MIN_LETTERS = 10
# …and one longer than this found no paragraph break at all. Not a defect on its
# face: a deposition or a sentence really does run this long. Informational.
WALL = 1200
TRAILING_DASH = re.compile(r"\s*[-—–]+\s*$")
NOTE_REF = re.compile(r"[\(\[]\s*([0-9IilJ]{1,2})\s*[\)\]]")
MONTHS = set(spans.MONTHS)
# A bare year over a stretch of a diary, or a piece's number: a heading, which
# has no letters in it and is not a paragraph of prose gone wrong.
HEADING = re.compile(r"\s*(?:1[2-8]\d\d|[0-9]{1,2})\s*[.,]?\s*[*°º'’‘]?\s*")


def bare(text: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFD", text)
                     if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^0-9a-z]", "", folded)


def prose_checks(doc: dict, paras: list[str], vocab: Counter
                 ) -> list[tuple[str, str]]:
    """Everything answerable from the assembled text alone."""
    found: list[tuple[str, str]] = []
    called: set[int] = set()
    numbered = {p["paragraph"] for p in doc.get("pieces", [])}
    headings = set(doc.get("headings", []))
    for i, para in enumerate(paras):
        one = " ".join(para.split())
        letters = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", one))
        # A heading is not a short paragraph. `runt` and `bare-dash` both fired
        # on 17% of the corpus on their first run and every one of them was a
        # year over a diary's stretch (`1706.`) or a piece number -- which have
        # no letters by construction. A check firing on a sixth of a corpus has
        # found a convention, which is what the rate is printed for.
        # A heading is not a short paragraph. `runt` and `bare-dash` both fired
        # on 17% of the corpus on their first run and every one of them was a
        # year over a diary's stretch (`1706.`) or a piece number -- which have
        # no letters by construction. Once `build_documents` began recording the
        # centred paragraphs, 30 of the 47 that remained turned out to be
        # headings too: `LECTOREM.`, `EL REY.`, `Autos de Fè.`, `D. FERNANDO`.
        # A check firing on a sixth of a corpus has found a convention, which is
        # what the rate is printed for.
        # …but a heading still calls its notes: the title of a section carries
        # `(1)` as often as not, and skipping it took `orphan-note` from 2 to 13.
        called |= {n for n in (ref_number(m.group(1))
                               for m in NOTE_REF.finditer(one)) if n}
        if HEADING.fullmatch(one) or i in numbered or i in headings:
            continue
        if letters < MIN_LETTERS and i > 1:
            found.append(("runt", f"¶{i}: {one!r}"))
        if len(one) > WALL:
            found.append(("wall", f"¶{i}: {len(one)} chars"))
        elif len(one) < 60 and i > 2:
            found.append(("short-para", f"¶{i}: {one[:50]!r}"))
        if TRAILING_DASH.search(one) and len(one) > MIN_LETTERS:
            found.append(("stray-tail", f"¶{i}: …{one[-38:]!r}"))
        if one and not LETTER.search(one):
            found.append(("bare-dash", f"¶{i}: {one!r}"))
        called |= {n for n in (ref_number(m.group(1))
                               for m in NOTE_REF.finditer(one)) if n}
        # A month heading the winner mangled: it opens a paragraph, it is a
        # misreading of one month and nothing else, and a day follows it.
        head = one.split(" ", 1)[0].rstrip(".,")
        if (bare(head) not in MONTHS and spans.strictly_a_month(head)
                # A digit, or `i.°` -- how the book writes the first of the
                # month. Not the bare letter `l`, which let `Entre las partidas`
                # through: `strictly_a_month` reads `Entre` as two letters off
                # `enero`, and only the day after it says whether that is a
                # heading or a sentence.
                and re.match(r"^\s*(?:[0-9]{1,2}|[Ii]\.?\s*[°ºo])",
                             one[len(head):].lstrip(" .,"))):
            found.append(("bad-month", f"¶{i}: {one[:44]!r}"))
        # A word the line break split that the joined form of the book knows.
        for a, b in zip(one.split(), one.split()[1:]):
            if (a.isalpha() and b.isalpha() and len(a) > 2 and len(b) > 1
                    and not BREAK_HYPHEN.search(a)
                    and vocab[bare(a + b)] >= 5 and not vocab[bare(a)]):
                found.append(("glued", f"¶{i}: {a} {b} -> {a + b}"))
        # An attribution the glossary resolves and that is still in the prose.
        body, sigla = lift_sigla(one)
        if not sigla:
            tail = re.search(r"[-—–]\s*([A-Z][a-z]?\.?(?:\s*[A-Z][a-z]?\.?)*)\s*$",
                             one)
            if tail and resolve(tail.group(1)):
                found.append(("unlifted-siglum", f"¶{i}: …{one[-30:]!r}"))
    notes = {n["number"] for n in doc.get("notes", [])}
    for number in sorted(called - notes):
        found.append(("dangling-note", f"({number}) has no note under it"))
    for number in sorted(notes - called):
        found.append(("orphan-note", f"note ({number}) is called by nothing"))
    # Campaner's numbering, where the document has one, with its holes named.
    numbers = [p["number"] for p in doc.get("pieces", [])]
    if numbers:
        for n in range(1, max(numbers) + 1):
            if n not in set(numbers):
                found.append(("piece-gap", f"piece {n} was not read"))
    if paras and " ".join(doc["title"].split()) not in [
            " ".join(p.split()) for p in paras[:3]]:
        found.append(("title-cut", f"head is {paras[1][:48]!r}"
                      if len(paras) > 1 else "no head"))
    share = doc["certainty"]["contested"] / max(1, doc["words"])
    if share > 0.05:
        found.append(("contested", f"{share:.1%} of its words"))
    return found


def ref_number(raw: str) -> int | None:
    digits = raw.translate(str.maketrans({"I": "1", "i": "1", "l": "1",
                                          "J": "1"}))
    return int(digits) if digits.isdigit() else None


def panel_checks(doc: dict, source: Path) -> list[tuple[str, str]]:
    """Everything that needs the engines rather than the finished text.

    These are the ones worth having, because they say *what the page shows* and
    not merely that our text looks odd: a year heading is broken when three
    engines read a year the winner did not, and the head of a leaf has leaked
    when a line the rules should have removed is still in the stream.
    """
    found: list[tuple[str, str]] = []
    for pdf_page in range(doc["first_leaf"], doc["last_leaf"] + 1):
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        body, _notes = split_notes(page_lines(path))
        # Through `unwedge` first, so the check reports what is still wrong and
        # not what the assembler already repairs one stage later. A sweep that
        # accuses a fixed defect trains you to ignore it.
        rows = [line for line in unwedge(body) if line["text"].strip()]
        for line in rows:
            text = line["text"].strip()
            if is_running_head(text) or is_folio(text, line["bbox"], pdf_page):
                found.append(("head-leak", f"leaf {pdf_page}: {text!r}"))
            # A year the panel states and the winner collapsed -- and that
            # `year_heading` does *not* already recover. Asked of the line and
            # not of the output on the first run, it reported four headings the
            # assembler had repaired one stage later: a sweep that accuses a
            # fixed defect trains you to ignore it.
            if len(text) <= 8 and not LETTER.search(text):
                votes = heading_votes(line["row"])
                if votes and year_heading(line) is None:
                    year, count = votes.most_common(1)[0]
                    if str(year) not in text:
                        found.append(("broken-year",
                                      f"leaf {pdf_page}: {text!r} -- the panel "
                                      f"says {year}, {count} of 8 readings"))
        for i in range(1, len(rows) - 1):
            if (BREAK_HYPHEN.search(rows[i - 1]["text"].strip())
                    and WEDGE.match(rows[i]["text"].strip())
                    and CONTINUES.match(rows[i + 1]["text"].strip())):
                found.append(("wedged", f"leaf {pdf_page}: "
                              f"{rows[i - 1]['text'][-12:]!r} "
                              f"{rows[i]['text'].strip()!r} "
                              f"{rows[i + 1]['text'][:12]!r}"))
    return found


def build_vocab(source: Path, leaves: set[int]) -> Counter:
    """The book as its own dictionary, from the consensus and never from the
    assembled text -- that is this sweep's own input, the trap the long s and
    the rejoining rule each fell into once."""
    vocab: Counter = Counter()
    for path in sorted(source.glob("p0*.json")):
        leaf = json.loads(path.read_text())
        for locus in leaf["loci"]:
            if locus["grade"] == "unanimous":
                vocab[bare(locus["winner"])] += 1
    return vocab


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--check", help="print every instance of one check")
    ap.add_argument("--doc", help="one document id")
    args = ap.parse_args()

    source = OCR / args.consensus
    sections = json.loads((DATA / "documents" / "sections.json").read_text())
    if args.doc:
        sections = [s for s in sections if s["id"] == args.doc]
    leaves = {p for s in sections
              for p in range(s["first_leaf"], s["last_leaf"] + 1)}
    vocab = build_vocab(source, leaves)

    findings: dict[str, list[tuple[str, str]]] = {}
    for doc in sections:
        text = (DATA / "documents" / "sections" / f"{doc['id']}.txt")
        paras = [p for p in text.read_text(encoding="utf-8").split("\n\n")
                 if p.strip()]
        findings[doc["id"]] = (prose_checks(doc, paras, vocab)
                               + panel_checks(doc, source))

    counts = Counter(check for hits in findings.values() for check, _ in hits)
    paragraphs = sum(len(json.loads((DATA / "documents" / "sections.json")
                                    .read_text())[0].get("paragraph_leaves", []))
                     for _ in [0])
    total = sum(len(d.get("paragraph_leaves", [])) for d in sections)

    if args.check:
        for doc_id, hits in findings.items():
            for check, detail in hits:
                if check == args.check:
                    print(f"{doc_id}  {detail}")
        return

    print(f"\n{len(sections)} documents, {total:,} paragraphs\n")
    print(f"  {'check':<18}{'n':>6}{'rate':>9}{'weight':>8}")
    for check, n in counts.most_common():
        mark = "  (informational)" if check in INFORMATIONAL else ""
        print(f"  {check:<18}{n:>6}{n / total:>8.1%}{WEIGHT.get(check, 0):>8}"
              f"{mark}")

    print("\nWhere to look, worst first:")
    ranked = sorted(findings.items(),
                    key=lambda kv: -sum(WEIGHT.get(c, 0) for c, _ in kv[1]))
    for doc_id, hits in ranked:
        score = sum(WEIGHT.get(c, 0) for c, _ in hits)
        if not score:
            continue
        seen = Counter(c for c, _ in hits if WEIGHT.get(c, 0))
        print(f"  {doc_id:<14}{score:>5}   "
              + ", ".join(f"{n}×{c}" for c, n in seen.most_common()))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "documents.json").write_text(json.dumps(
        {doc_id: [{"check": c, "detail": d} for c, d in hits]
         for doc_id, hits in findings.items()},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n-> {OUT / 'documents.json'}")


if __name__ == "__main__":
    main()
