"""The editorial rules, such as they are, in one place and applied by machine.

An edition has to say what it changed. This module holds every transformation
this project makes to what the panel voted for, so that the list is short,
auditable, and impossible to apply by accident somewhere else.

There is exactly one rule so far, and it repairs an error rather than tidying the
book: **the long s**.

Leaves 335-367 reproduce a booklet printed in 1541 -- `LA FELICISSIMA VINGUda de
Don Carlos cinque Emperador de Romans` -- in its own typography, which uses the
long s, `ſ`. Five of the six engines read that letter as `f`, and the vote
therefore returns `cofa`, `moffen`, `eftat`, `boffer` where the page says `coſa`,
`moſſen`, `eſtat`, `boſſer`. That is not 1881 orthography to be preserved: `ſ`
and `f` are different letters, and the transcription is simply wrong.

It is also not something to guess at. The distinction cannot be recovered from
the text, because 16th-century Catalan has plenty of real f: `fer`, `fet`, `fos`,
`fins`, `foren`, `fonch` are all words, and so are `ser`, `set`, `sos`, `sins`.
A lexicon on its own settles 29% of the cases and mangles some of the rest.

What settles most of it is the panel, as everywhere else in this pipeline.
Tesseract with `spa_old` reads the long s correctly -- `eſteril`, `coſa`,
`moſſen`, `boſſer`, `eſtigueſſen`, `prouiſio` -- and is simply outvoted five to
one. But an engine reading `ſ` is evidence, not proof: checked against the
facsimile, leaf 342 prints `fonch` and leaf 362 `fins` with a full crossbar, and
Tesseract offers `ſonch` and `ſins` for them anyway. The rule therefore has a
veto, and the four outcomes are:

  repaired, panel     an engine read this token with `ſ`, agreeing with the
                      winner in every other character, and the printed form is
                      not a word the book uses elsewhere.          1 292 tokens
  repaired, attested  no engine did, but the same word was confirmed that way
                      elsewhere on the reprint.                      189 tokens
  ambiguous           an engine read `ſ`, but the printed form is a real word of
                      this book. The `f` stands and the token is listed.
                                                                     465 tokens
  untouched           no engine ever read a `ſ` there.                542 tokens

The untouched residue is mostly right as it stands -- `feren`, `foren`, `offici`,
`front`, `fortuna`, `forçat`, `Magnifich` all have a real f. Some are not:
`Cæfar` should be `Cæſar`. Those, and the 465 ambiguous ones, go to review rather
than being repaired on a hunch. `fe`, `fa` and `fi` are the big ambiguous
classes: on the page they really are `ſe`, `ſa`, `ſi`, and they are also real
words, so they are left alone. That is the safe direction to be wrong in.

Separately from the repair there is a *reading* form, `reading_form`, which folds
`ſ` to `s` so that a search for `cosa` finds it. That is a normalisation, not a
correction, and the verbatim text keeps the long s.

Usage:
  python scripts/editorial.py --report
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import targets

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"

LONG_S = "ſ"
# Two independent signs that a leaf is set with the long s, and a leaf has to
# show both. On its own the first also fires on leaf 478, and the second on the
# Jurats tables, where an engine reads `Villafranca` as `Villaſranca`.
LOOKS_LIKE_LONG_S = re.compile(r"[aeiou]ff?[aeioutlrn]")
LONG_S_TEXT_RATE = 0.04
LONG_S_READING_RATE = 0.03


def nfc(text: str | None) -> str:
    return unicodedata.normalize("NFC", text or "")


def reading_form(text: str) -> str:
    """The searchable form: the long s folded to s. Not a correction."""
    return nfc(text).replace(LONG_S, "s")


def long_s_leaves(source: Path) -> list[int]:
    """The leaves set in the long s, derived rather than listed.

    Both signals must fire, and the run is then closed: leaves 347 and 356 sit
    inside the reprint and are mostly woodcut, so neither signal reaches its
    threshold on them.

    Both are read off the consensus and never off `data/text/`, which is this
    rule's own output: taking the first signal from the assembled text made the
    detection vanish the moment the repair had been applied once.
    """
    by_text: set[int] = set()
    by_reading: set[int] = set()
    for pdf_page in targets.resolve("all"):
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        loci = json.loads(path.read_text())["loci"]
        if not loci:
            continue
        long_s = sum(1 for lo in loci
                     if any(LONG_S in nfc(v) for v in lo["variants"].values()))
        if long_s / len(loci) > LONG_S_READING_RATE:
            by_reading.add(pdf_page)
        looks = sum(1 for lo in loci
                    if LOOKS_LIKE_LONG_S.search(nfc(lo["winner"]).lower()))
        if looks / len(loci) > LONG_S_TEXT_RATE:
            by_text.add(pdf_page)

    both = sorted(by_text & by_reading)
    return list(range(both[0], both[-1] + 1)) if both else []


def panel_long_s(locus: dict) -> str | None:
    """The winner as some engine read it, if one read an `f` in it as `ſ`.

    The reading has to match the winner character for character apart from that
    one substitution. Without it the rule accepts an engine's collapse of
    `Villafranca,` into `Villaﬁ"ſifﬁca` on the strength of the `ſ` in it.
    """
    winner = nfc(locus["winner"])
    if "f" not in winner:
        return None
    votes = Counter(
        nfc(v) for v in locus["variants"].values()
        if v and LONG_S in nfc(v) and nfc(v).replace(LONG_S, "f") == winner)
    return votes.most_common(1)[0][0] if votes else None


def word_of(token: str) -> str:
    return "".join(c for c in nfc(token)
                   if c.isalnum() or c in "áéíóúüñçàèòïÁÉÍÓÚÜÑÇ").lower()


# How often a word must appear outside the reprint before its f is presumed real.
ATTESTED = 3


def clean_lexicon(source: Path, leaves: set[int]) -> Counter:
    """The book's vocabulary from every leaf that is *not* set in the long s."""
    lexicon: Counter = Counter()
    for path in sorted(source.glob("p*.json")):
        data = json.loads(path.read_text())
        if data["pdf_page"] in leaves:
            continue
        for locus in data["loci"]:
            if locus["grade"] != "unanimous":
                continue
            word = word_of(locus["winner"] or "")
            if len(word) > 1:
                lexicon[word] += 1
    return lexicon


def long_s_repairs(source: Path, leaves: list[int]
                   ) -> tuple[dict, Counter, Counter]:
    """{(leaf, index): repaired}, what each tier settled, and what is ambiguous.

    An engine reading `ſ` is evidence, not proof. Checked against the facsimile,
    leaf 342 prints `fonch` and leaf 362 `fins` with a full crossbar -- real f,
    both of them real Catalan words -- and Tesseract offers `ſonch` and `ſins`
    for them anyway. Repairing on the panel alone would have corrupted 29 and 18
    tokens of perfectly good text.

    So the panel's reading is vetoed by the book's own vocabulary: if the printed
    form is a word this book uses elsewhere, outside the reprint, the `f` stands
    and the token is reported as ambiguous instead. That leaves `fe`, `fa` and
    `fi` unrepaired -- they really are `ſe`, `ſa`, `ſi` on the page, and they are
    also real words -- which is the safe direction to be wrong in.
    """
    lexicon = clean_lexicon(source, set(leaves))
    direct: dict[tuple[int, int], str] = {}
    attested: dict[str, str] = {}
    support: Counter = Counter()
    ambiguous: Counter = Counter()

    for pdf_page in leaves:
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        for locus in json.loads(path.read_text())["loci"]:
            repaired = panel_long_s(locus)
            if repaired is None:
                continue
            printed = repaired.replace(LONG_S, "f")
            if lexicon.get(word_of(printed), 0) >= ATTESTED:
                ambiguous[printed] += 1
                continue
            direct[(pdf_page, locus["index"])] = repaired
            if support[repaired] >= support.get(attested.get(printed, ""), 0):
                attested[printed] = repaired
            support[repaired] += 1

    tiers = Counter({"panel": len(direct)})
    out = dict(direct)
    for pdf_page in leaves:
        path = source / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        for locus in json.loads(path.read_text())["loci"]:
            key = (pdf_page, locus["index"])
            winner = nfc(locus["winner"])
            if key in out or "f" not in winner:
                continue
            if winner in attested:
                out[key] = attested[winner]
                tiers["attested"] += 1
            elif ambiguous.get(winner):
                tiers["ambiguous"] += 1
            else:
                tiers["left as printed"] += 1
    return out, tiers, ambiguous


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    source = OCR / args.consensus
    leaves = long_s_leaves(source)
    print(f"long s on {len(leaves)} leaves: {leaves[0]}–{leaves[-1]}")
    repairs, tiers, ambiguous = long_s_repairs(source, leaves)
    total = sum(tiers.values())
    for tier in ("panel", "attested", "ambiguous", "left as printed"):
        print(f"  {tier:16} {tiers[tier]:6,}  {tiers[tier]/total:5.1%}")
    print(f"\n{len(repairs):,} tokens repaired")

    if args.report:
        shown = Counter((v.replace(LONG_S, "f"), v) for v in repairs.values())
        print("\nmost repaired:")
        for (printed, fixed), n in shown.most_common(15):
            print(f"  {printed:>18} -> {fixed:<18} {n:4d}")
        print("\nvetoed as real words of this book, left for review:")
        for printed, n in ambiguous.most_common(15):
            print(f"  {printed:>18} {n:4d}")


if __name__ == "__main__":
    main()
