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


# A word must appear this often in the book before a join is made on attestation
# alone. Higher than ATTESTED because this tier has no reading from any engine
# behind it -- only the fact that the book uses the joined form and neither half.
ATTESTED_JOIN = 5
# What the engines make of a line-break hyphen when they do not read it as one.
# Leaf 95 prints `Tarrago-/na,` and the panel offers `Tarrago-`, `Tarrago.`,
# `Tarrago,` and `Tarrago_` for the same mark; the winner was `Tarrago.`, so the
# hyphen stitch never fired and the published text read `Tarrago. na,`.
BREAK_MARK = re.compile(r"[.,_·]+$")
# …and a token that ends in a hyphen the *assembler* already stitches is not this
# rule's business. Measured before it was believed: without this the rule fired
# 2 481 times on 547 leaves, joining `patronato`, `construir` and `necesario`
# -- every ordinary hyphenated line break in the book, all of them already
# joined correctly one stage later.
ALREADY_STITCHED = re.compile(r"[-‐‑­–—]$")


# A line-break hyphen the winner read as a stop or a comma is evidence the panel
# can give directly, and it needs no dictionary: `Tarrago-` / `na,` is never read
# `Tarragona` by any engine, because no engine sees both lines as one word, but
# several of them read the hyphen. Measured over the book, with the token last on
# its printed line and the next line opening in lower case:
#
#   engines reading `X-`   candidates   real breaks
#   1                      12           1 (`transfi-` also has 3)
#   2                      4            3 -- `el.` / `gobierno` is not one
#   3 or more              12           12
#
# One engine is noise: `buenos,` / `nuevos,`, `de.` / `la`, `día,` / `li`. Two
# need the joined form to be a word of the book, which keeps `Tarragona`,
# `campanario` and `refresco` and drops `el gobierno`. No left-half veto here,
# unlike the other tiers: `fue-ron`, `es-caparon`, `re-fresco` break after a
# common word, and the hyphen, not the dictionary, is what says they are broken.
BREAK_HYPHEN_READ = re.compile(r"[-‐‑­]$")
HYPHEN_READERS = 3
HYPHEN_READERS_ATTESTED = 2


def read_as_break(left: dict, right: dict, stem: str,
                  lexicon: Counter) -> str | None:
    """`stem` without its hyphen, if the panel read a line-break hyphen there."""
    if left.get("line_bbox") is None or left["line_bbox"] == right["line_bbox"]:
        return None
    if stem == nfc(left["winner"] or "") and not stem.endswith("-"):
        return None               # nothing was misread: no stop, no comma
    tail = nfc(right["winner"] or "")
    if not tail or not tail[0].islower():
        return None
    word = re.sub(r"[-‐‑­]+$", "", stem)
    if not word or re.search(r"[-‐‑–—]", word):
        return None
    readers = sum(1 for v in left["variants"].values()
                  if v and BREAK_HYPHEN_READ.search(nfc(v).strip())
                  and word_of(v) == word_of(word))
    if readers >= HYPHEN_READERS:
        return word
    if (readers >= HYPHEN_READERS_ATTESTED
            and lexicon.get(word_of(word) + word_of(tail), 0) >= ATTESTED):
        return word
    return None


def split_words(source: Path, lexicon: Counter) -> tuple[dict, Counter, Counter]:
    """Words the line break split and the vote never put back together.

    `dive rsos`, `Novie mbre`, `ciu dad`, `bandole ros`, `Tarrago. na`. Three
    different causes, one repair:

      the panel disagreed   Leaf 107: three engines read `diversos` and five read
                            `dive` + `rsos`, and the majority wins slot by slot.
                            The span re-vote cannot help, because `fold()` strips
                            whitespace, so both readings are the same class to it
                            and neither is longer than the other.
      the hyphen was misread Leaf 95 prints `Tarrago-/na,` and the winner was
                            `Tarrago.`, which `BREAK_HYPHEN` does not stitch.
      nobody joined it      Leaf 429: all eight engines read `bandole` + `ros:`.
                            There is no reading to recover, only the fact that
                            the book uses `bandoleros` and uses neither half.

    Two tiers of evidence, as with the long s. `panel` where some engine read the
    joined form; `attested` where none did but the book uses it {ATTESTED_JOIN}
    times or more. And the same veto: **refused when both halves are words this
    book uses**, which is what keeps `de` + `l`, `en` + `torn` and every other
    real pair of short words intact.
    """
    joins: dict[tuple[int, int], str] = {}
    tiers: Counter = Counter()
    refused: Counter = Counter()
    ambiguous: Counter = Counter()

    for path in sorted(source.glob("p*.json")):
        data = json.loads(path.read_text())
        page = data["pdf_page"]
        loci = data["loci"]
        for n, left in enumerate(loci[:-1]):
            right = loci[n + 1]
            head, tail = nfc(left["winner"] or ""), nfc(right["winner"] or "")
            if not head or not tail or ALREADY_STITCHED.search(head):
                continue
            # A clitic is not half a word. Leaves 123, 149 and 155 are medieval
            # Catalan and gave `qu'` + `ell`, `qu'` + `il`, `qu'` + `es`, which
            # fold to `qu` -- not a word the book uses -- and would have been
            # joined on that technicality.
            if head.endswith(("'", "’")):
                continue
            stem = BREAK_MARK.sub("", head)
            a, b = word_of(stem), word_of(tail)
            # A hyphen the panel read is `hyphen_breaks`' repair, not a join:
            # the pair straddles a line break and the stitch joins it there.
            if read_as_break(left, right, stem, lexicon):
                continue
            # Three characters on the left, because two is where the guess stops
            # being one: `er` + `en` makes the Catalan `eren` and could as
            # easily be two words on a leaf written in Catalan.
            if len(a) < 3 or len(b) < 2:
                continue
            whole = a + b
            if lexicon.get(whole, 0) < ATTESTED:
                continue
            # **The left half must not be a word.** Requiring that of both halves
            # was tried and is too weak on one side and too strong on the other:
            # it let `de` + `Ntro.` become `deNtro.` and `des` + `Portell` become
            # `desPortell`, because the second half of each is rare, while
            # refusing `Tarrago` + `na` and `VINGU` + `da`, whose second half is
            # an ordinary Catalan word. A broken word's *first* half is never a
            # word the book uses -- `dive`, `bandole`, `Tarrago`, `capítu` are
            # not -- and a common word on the left is overwhelmingly just a word.
            if lexicon.get(a, 0) >= ATTESTED:
                refused[f"{a} {b}"] += 1
                continue
            by_engine = any(word_of(v or "") == whole
                            for v in left["variants"].values())
            if not by_engine:
                # With no engine reading behind it the join rests on attestation
                # alone, and there the right half must not be a word either.
                # Leaf 105 gave `despes` + `es` -> `despeses`, and read as the
                # Catalan it is, `lo dit Jordi despès és bestrach del seu propi`
                # is two words: `es` is a word of this book and `despeses` a
                # plausible one, so the looser veto corrupted a good reading.
                if (lexicon.get(whole, 0) < ATTESTED_JOIN
                        or lexicon.get(b, 0) >= ATTESTED):
                    ambiguous[f"{a} {b}"] += 1
                    continue
            # The repair keeps whatever the right-hand token carried after the
            # word -- `ros:` is `bandoleros:` and the colon is Campaner's.
            repaired = stem + tail
            # …but never a dash left standing inside the word it just made.
            if re.search(r"[-‐‑–—]", repaired):
                continue
            joins[(page, left["index"])] = repaired
            tiers["panel" if by_engine else "attested"] += 1
    return joins, tiers, refused + ambiguous


_JOINS: dict[Path, tuple[dict, Counter, Counter]] = {}


def joins_for(source: Path) -> dict:
    """`split_words` for a consensus directory, computed once per process.

    Every assembly of the book has to apply the same rules or they drift, and
    this project has already paid for that lesson twice: `build_text.py` and
    `parse_entries.py` publish the same prose and cut the same notices out of
    it, and when only the first was given this rule the audit went on reporting
    `dive rsos` in the entries after the published text had been repaired of it.
    Both callers ask here, and the answer is cached because the lexicon costs a
    pass over 614 leaves.
    """
    if source not in _JOINS:
        _JOINS[source] = split_words(source, clean_lexicon(source, set()))
    return _JOINS[source][0]


def hyphen_breaks(source: Path, lexicon: Counter) -> dict[tuple[int, int], str]:
    """{(leaf, index): `stem-`} where the panel read a line-break hyphen the
    winner turned into a stop or a comma.

    The repair restores the hyphen and nothing else; the assemblers' ordinary
    stitch then joins the word across the line, exactly as it joins every other
    break. A join made here instead could not reach: the two halves sit on two
    printed lines, and `spans.apply_joins` works inside one.
    """
    out: dict[tuple[int, int], str] = {}
    for path in sorted(source.glob("p*.json")):
        data = json.loads(path.read_text())
        loci = data["loci"]
        for n, left in enumerate(loci[:-1]):
            head = nfc(left["winner"] or "")
            if not head or ALREADY_STITCHED.search(head):
                continue
            word = read_as_break(left, loci[n + 1], BREAK_MARK.sub("", head),
                                 lexicon)
            if word:
                out[(data["pdf_page"], left["index"])] = word + "-"
    return out


_REPAIRS: dict[Path, dict] = {}


def repairs_for(source: Path) -> dict:
    """Every per-slot repair of the editorial rules, computed once per process.

    The long s and the misread break hyphen. `build_text.py` used to compute the
    long s for itself and `parse_entries.page_lines` -- which assembles the
    notices *and* the documents -- passed no repairs at all, so the 1 481 tokens
    of the 1541 reprint the rule repairs were repaired in `data/text/` and
    nowhere a reader could see them: the document showed 10 `ſ` where the
    published text had 1 681. The same lesson as `joins_for`, paid again.
    """
    if source not in _REPAIRS:
        long_s, _tiers, _ambiguous = long_s_repairs(source,
                                                    long_s_leaves(source))
        breaks = hyphen_breaks(source, clean_lexicon(source, set()))
        _REPAIRS[source] = {**breaks, **long_s}
    return _REPAIRS[source]


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
