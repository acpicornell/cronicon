"""Resolve the sigla the chronicle attributes its entries to.

Every entry ends `—G. T.`, `—B. J.`, `—M. M.`, naming the manuscript it comes
from. That is the most interesting thing about this book -- you can ask which
source reports what -- and as bare initials it is useless. Campaner glosses them
in the introduction, `Las abreviaturas más notables empleadas en este libro son:`
followed by a two-column list, and then names the principal sources again, in
full, at the head of each century.

Two difficulties, both about reading rather than parsing:

  the columns    The list is set two to the leaf and the shared reading order
                 interleaves them, so `A. T.—Agustin de Torrella.` arrives
                 between two right-column entries. Read from a consensus built
                 with `--split-gutter`, which separates them.

  the swash      The sigla are set in a swash italic whose capitals are 𝒜 ℳ 𝒩 𝒥,
                 and every engine mangles it: `MS. y MSS.` comes back as
                 `5VCS. y íhCSS.` and `M. M.` as a bare `M.`. Those entries are
                 adjudicated against the facsimile and kept in
                 `data/sigla/adjudicated.tsv`, which overrides the parse where
                 the parse failed and nowhere else.

The century headers are collected too, unparsed. `SIGLO XIV. / DE 1301 Á 1400.`
is followed by that century's sources in full -- in a parenthesis for the 13th to
15th, without one for the 16th to 18th -- and it is where the sigla the general
list omits are named: `T. A.` is Tomás Amorós in the 18th-century list and Tomás
Aguiló in the 16th-century one, which is exactly why matching a name there to a
siglum is inference. This script stores the text and does not guess.

Usage:
  python scripts/parse_sigla.py --report
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import targets
from parse_entries import OCR, page_lines

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "sigla"

OPENS_GLOSSARY = re.compile(r"abreviaturas\s+m[áa]s\s+notables", re.IGNORECASE)
# `G. T.—Guillermo Terrassa.`, `ls.—Libras.`, `C. y R.—Ciudad y Reino.`
GLOSS = re.compile(r"^\s*([A-Za-zÁÉÍÓÚÑ][\w.\s]{0,14}?\.)\s*[—–-]\s*(\S.*?)\s*$")


def tidy(siglum: str) -> str:
    return re.sub(r"\s+", " ", siglum).strip()


def read_glossary(lines: list[dict]) -> dict[str, str]:
    """The `SIGLA—Expansion.` pairs following the introduction's own heading."""
    started = False
    out: dict[str, str] = {}
    for line in lines:
        text = line["text"].strip()
        if not started:
            started = bool(OPENS_GLOSSARY.search(text))
            continue
        match = GLOSS.match(text)
        if not match:
            continue
        siglum, expansion = tidy(match.group(1)), match.group(2).strip()
        # A gloss is initials and a name, not a sentence.
        if len(siglum) > 12 or len(expansion) > 40 or not expansion:
            continue
        out.setdefault(siglum, expansion)
    return out


SOURCE_FIELDS = ("name", "life", "role", "span", "work", "note", "leaf")


def read_sources() -> dict[str, dict]:
    """Who each siglum is, from `sources.tsv`.

    The glossary on leaf 25 gives `G. T.—Guillermo Terrassa.` and stops. The
    eight leaves before it give the man, his trade, what the manuscript
    physically is, the years it covers and where it was in 1881 -- eight leaves
    of dossier that this edition drops along with the rest of the introduction,
    and without which a siglum is a pair of initials.

    Entered by hand rather than parsed: the introduction runs its footnotes in
    two columns under the text and interleaves them, so the leaves are among the
    worst in the book for reading order, and there are twenty-six sources. Each
    row carries the leaf it came from, which is what makes it checkable.
    """
    path = OUT / "sources.tsv"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        if not row.strip() or row.startswith("#"):
            continue
        cells = row.split("\t")
        siglum, rest = cells[0], cells[1:]
        record = {field: (rest[n].strip() if n < len(rest) else "")
                  for n, field in enumerate(SOURCE_FIELDS)}
        out[tidy(siglum)] = {k: v for k, v in record.items() if v}
    return out


def read_adjudicated() -> dict[str, str]:
    path = OUT / "adjudicated.tsv"
    if not path.exists():
        return {}
    out = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        if not row.strip() or row.startswith("#") or "\t" not in row:
            continue
        siglum, expansion = row.split("\t", 1)
        out[tidy(siglum)] = expansion.strip()
    return out


def century_sources(path: Path) -> list[dict]:
    """The list of sources at the head of each century, as printed.

    Read from what `parse_entries.py` delimited rather than delimited again
    here. Both scripts wanted the same six blocks and each had its own rule for
    where they end, and the two disagreed: counting lines until something looked
    like an entry kept the misread year heading `ISOI.` on the end of the 16th
    century's list and ran the 18th's on into a footnote about the Conde de
    Peralada. The other rule is typographic -- the list is set across the
    measure and the columns start where it stops -- and it is right on all six.

    Stored verbatim, minus the brackets the 13th to 15th centuries print it in:
    turning `por TomAs Amorós` into `T. A.` is inference, and the point of this
    file is to hold what the book says.
    """
    if not path.exists():
        return []
    out = []
    for century in json.loads(path.read_text()):
        text = century["text"]
        if "(" in text and ")" in text:
            text = text[text.find("(") + 1:text.rfind(")")]
        out.append({"century": century["numeral"], "pdf_page": century["pdf_page"],
                    "sources": re.sub(r"\s+", " ", text).strip()})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--tables", default="consensus6_swap_swapk_gutter")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    gutter = OCR / args.tables
    leaves = {}
    for page in targets.resolve("all"):
        best = gutter / f"p{page:04d}.json"
        plain = source / f"p{page:04d}.json"
        if best.exists():
            leaves[page] = page_lines(best)
        elif plain.exists():
            leaves[page] = page_lines(plain)

    parsed: dict[str, str] = {}
    where = 0
    for page in sorted(leaves):
        found = read_glossary(leaves[page])
        if found:
            parsed, where = found, page
            break
    adjudicated = read_adjudicated()
    glossary = {**parsed, **adjudicated}

    entries = PROJECT / "data" / "entries" / "entries.jsonl"
    used: Counter = Counter()
    if entries.exists():
        for row in entries.open(encoding="utf-8"):
            for siglum in json.loads(row)["sources"]:
                used[tidy(siglum)] += 1

    resolved = sum(n for s, n in used.items() if s in glossary)
    total = sum(used.values())
    centuries = century_sources(PROJECT / "data" / "entries" / "centuries.json")

    sources = read_sources()
    # Two of the sources the introduction describes -- the Capuchin librarian
    # Luis de Villafranca and Nicolás Ferrer de Sant Jordi -- are used all
    # through the chronicle and are simply not in the abbreviation list. They
    # belong in the glossary the site shows even though the book's own list
    # omits them, and the record says where each one comes from.
    described = {s: d for s, d in sources.items() if s not in glossary}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sigla.json").write_text(json.dumps({
        "glossary_leaf": where,
        "glossary": [{"siglum": s, "expansion": e,
                      "source": "adjudicated" if s in adjudicated else "parsed",
                      "attributions": used.get(s, 0),
                      **({"who": sources[s]} if s in sources else {})}
                     for s, e in sorted(glossary.items())],
        "unglossed": [{"siglum": s, "attributions": n,
                       **({"who": sources[s]} if s in sources else {})}
                      for s, n in used.most_common() if s not in glossary],
        "described_only": sorted(described),
        "century_sources": centuries,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"glossary on leaf {where}: {len(glossary)} abbreviations "
          f"({len(parsed)} parsed, {len(adjudicated)} adjudicated)")
    print(f"{resolved:,} of {total:,} attributions resolved "
          f"({resolved/total:.0%}) over {len(used)} distinct sigla")
    print(f"{len(centuries)} century headers with their own source lists")
    covered = sum(n for s, n in used.items() if s in sources)
    print(f"{len(sources)} sources described from the introduction, "
          f"covering {covered:,} of {total:,} attributions "
          f"({covered/total:.0%})")

    if args.report:
        print("\nunglossed, by how often the chronicle uses them:")
        for siglum, n in used.most_common():
            if siglum not in glossary:
                print(f"  {siglum:<12} {n:4d}")
        print("\ncentury source lists:")
        for c in centuries:
            print(f"  SIGLO {c['century']:<5} p{c['pdf_page']}  "
                  f"{c['sources'][:96]}…")

    print(f"\n-> {OUT / 'sigla.json'}")


if __name__ == "__main__":
    main()
