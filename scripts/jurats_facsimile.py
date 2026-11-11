"""The Jurats lists as read off the facsimile, and how they replace the parse.

The lists are the worst-read leaves in the book and not by a margin. Of the 344
names the parser gave for the 13th and 14th centuries, one was read alike by
all six engines; and reading leaf 114 against the page showed the damage was
structural, not a matter of accents: the page prints six Jurats for 1302 and
the edition had two, both of them belonging to 1303. Names were missing four in
six and filed under the wrong year, because on these leaves the engines do not
agree what order the page is read in.

So the lists are adjudicated against the facsimile at native resolution, one
file per leaf:

    data/adjudication/jurats/p0114.txt

    leaf: 114
    by: claude (facsímil, resolució nativa)
    ---
    1302
    1 | Pedro Sa Verdera, miles
    2 | Guillermo de Buadella
    1310
    * | Los del año anterior.

A year, then `seat | name` for each seat the page fills -- a seat Campaner
prints a number for and no name is simply absent -- or `* | remark` where he
prints a sentence instead of names.

On the annotated leaves (58-60, 114-121) a line `> …` under a year is the note
Campaner sets beside its list, behind the brace: which codex or chronicler
gives those names, and where they disagree. One line per note, line-end
hyphens closed up, otherwise letter for letter. Every word of a note is looked
for in each engine's text of the leaf, and `--check` lists the ones none read.

**This is the one place a model reading a page is most dangerous, and the file
is built to say how far it was trusted.** Family names of 1300s Mallorca are
where a language model normalises `Za-Coma` to `Zacoma` and supplies a
plausible surname with nothing to catch it. Two things stand against that:

- **Every name is compared with what each engine read on that leaf.** Where
  some engine's text contains the name exactly as written here, the name is a
  reading the panel also gave (`source: "variant"`, with the count of engines).
  Where none does, it rests on this file alone (`source: "typed"`).
  `--check` lists those with the nearest thing each engine did read, and every
  one of them is to be looked at again against the page before it stands.
- **Nothing is corrected.** `Francisco de Vilanona` is what leaf 115 prints,
  though the note beside it says Vilanova; `Beruardo Bonet` is leaf 120's own
  turned letter. Campaner's errors and his printer's stand, here as elsewhere.

`override()` is called by `parse_jurats.py`: on a leaf that has a file, the
years the file covers are taken from it and the parser's rows for them dropped.

Usage:
  python scripts/jurats_facsimile.py --check          # names no engine read
  python scripts/jurats_facsimile.py --summary
"""
from __future__ import annotations

import argparse
import difflib
import re
from functools import lru_cache
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
FILES = PROJECT / "data" / "adjudication" / "jurats"
ORDERED = PROJECT / "data" / "ocr" / "ordered"

# Which series a leaf belongs to. A year does not say: 1300 closes the
# thirteenth-century list and the fourteenth opens at 1302.
SERIES = ((58, 60, 13), (114, 122, 14), (225, 229, 15), (311, 315, 16),
          (478, 482, 17), (631, 631, 18))


def century_of(leaf: int) -> int:
    for first, last, century in SERIES:
        if first <= leaf <= last:
            return century
    raise ValueError(f"leaf {leaf} is not in a Jurats series")


def read(path: Path) -> dict:
    head, _, body = path.read_text(encoding="utf-8").partition("\n---\n")
    meta = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
    years: list[tuple[int, list[tuple[int, str]]]] = []
    notes: list[tuple[int, str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.fullmatch(r"1[2-8]\d\d", line):
            years.append((int(line), []))
            continue
        if line.startswith(">"):
            notes.append((years[-1][0], line[1:].strip()))
            continue
        seat, name = (part.strip() for part in line.split("|", 1))
        years[-1][1].append((0 if seat == "*" else int(seat), name))
    return {"pdf_page": int(meta["leaf"]), "by": meta.get("by", "").strip(),
            "years": years, "notes": notes}


def files() -> list[dict]:
    return [read(path) for path in sorted(FILES.glob("p*.txt"))]


@lru_cache(maxsize=None)
def engine_texts(leaf: int) -> dict[str, str]:
    """Each engine's reading of the leaf, whitespace collapsed."""
    out = {}
    for path in sorted(ORDERED.glob(f"*_p{leaf:04d}.txt")):
        engine = path.name.rsplit("_p", 1)[0]
        text = " ".join(path.read_text(encoding="utf-8").split())
        # A name that runs over the end of its line -- `notari y menes-` /
        # `tral.` -- is one name here and two lines to an engine, so the text is
        # also offered with its break hyphens closed up.
        out[engine] = text + " \u2016 " + re.sub(r"(\w)[-\u00ad] (?=[a-zà-ÿ])", r"\1", text)
    return out


def readers(leaf: int, name: str) -> list[str]:
    """The engines whose text of this leaf contains `name` exactly.

    Letter for letter, accents and punctuation included. Only the spacing is
    let go where nothing matches with it: leaf 481 sets `Pedro AndrésRossinyolde
    Defla` squeezed into its column with the word spaces closed up, and every
    engine reads it so. A space is the compositor's, not a letter of the name.
    """
    exact = [engine for engine, text in engine_texts(leaf).items() if name in text]
    if exact:
        return exact
    tight = name.replace(" ", "")
    return [engine for engine, text in engine_texts(leaf).items()
            if tight in text.replace(" ", "")]


def nearest(leaf: int, name: str) -> list[tuple[str, str]]:
    """What each engine has that most resembles `name`, for looking again."""
    out = []
    width = len(name.split())
    for engine, text in engine_texts(leaf).items():
        words = text.split()
        best, score = "", 0.0
        for i in range(len(words) - width + 1):
            cand = " ".join(words[i:i + width])
            ratio = difflib.SequenceMatcher(None, name.lower(), cand.lower()).ratio()
            if ratio > score:
                best, score = cand, ratio
        if score >= 0.6:
            out.append((engine, best))
    return out


def rows() -> list[dict]:
    """Every adjudicated seat and remark as a `jurats.jsonl` row."""
    out = []
    for leaf in files():
        page = leaf["pdf_page"]
        for year, seats in leaf["years"]:
            for seat, name in seats:
                # `order` is the place on the leaf. A year can be printed twice
                # -- leaf 225 has `1401.` and then `1401 (EN 7 DE JULIO.)`, a
                # second set of six -- so (year, seat) does not order the rows.
                row = {"century": century_of(page), "year": year, "seat": seat,
                       "name": name, "pdf_page": page, "by": leaf["by"],
                       "order": len(out)}
                if seat == 0:
                    row["tier"] = "remark"
                else:
                    read_by = readers(page, name)
                    row["tier"] = "adjudicated"
                    row["source"] = "variant" if read_by else "typed"
                    row["engines"] = len(read_by)
                out.append(row)
    return out


WORD = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+")


def unread_words(leaf: int, text: str) -> list[str]:
    """The words of `text` that no engine's reading of the leaf contains."""
    seen: set[str] = set()
    halves: set[str] = set()
    for engine_text in engine_texts(leaf).values():
        seen.update(WORD.findall(engine_text))
        # A word the line break split. The engines interleave the notes column
        # with the names, so `Ca-` and `yetano` are rarely adjacent in their
        # text; both halves read, the first with its hyphen, is the word read.
        halves.update(re.findall(r"([0-9A-Za-zÀ-ÖØ-öø-ÿ]+)[-­](?=\s|$)",
                                 engine_text))

    def split_read(word: str) -> bool:
        return any(word[:k] in halves and word[k:] in seen
                   for k in range(1, len(word)))

    return [w for w in WORD.findall(text) if w not in seen and not split_read(w)]


def in_order(leaf: int, text: str) -> tuple[float, str]:
    """The best share of the note's words some engine read in the same order.

    Presence alone is weak -- `de` and `los` are on every leaf -- so each
    engine's word stream is aligned with the note's, and the share of the
    note's words matched in sequence is taken from the engine that does best.
    A word changed, dropped or normalised in the note lowers it wherever the
    word may happen to occur elsewhere on the leaf.
    """
    words = WORD.findall(text)
    best, who = 0.0, ""
    for engine, engine_text in engine_texts(leaf).items():
        stream = WORD.findall(engine_text.split(" \u2016 ")[0])
        matcher = difflib.SequenceMatcher(None, words, stream, autojunk=False)
        share = sum(b.size for b in matcher.get_matching_blocks()) / max(1, len(words))
        if share > best:
            best, who = share, engine
    return best, who


def notes() -> list[dict]:
    """Campaner's note beside each year of the annotated lists."""
    out = []
    for leaf in files():
        page = leaf["pdf_page"]
        for year, text in leaf["notes"]:
            words = WORD.findall(text)
            unread = unread_words(page, text)
            share, engine = in_order(page, text)
            out.append({"century": century_of(page), "year": year,
                        "pdf_page": page, "text": text, "by": leaf["by"],
                        "words": len(words), "unread": unread,
                        "in_order": round(share, 3), "best_engine": engine,
                        "order": len(out)})
    return out


def override(parsed: list[dict], printed: dict[int, int | None]) -> list[dict]:
    """`parsed` with the years a facsimile file covers taken from the file.

    On a leaf that has a file, every row the parser filed between the file's
    first year and its last is dropped -- including the ones under years the
    page does not have, which is where half the damage was -- and the file's
    rows take their place. A leaf the file covers only in part keeps the
    parser's rows for the rest: leaf 121 ends the annotated list at 1370 and
    opens the compact one at 1371 lower down.
    """
    covered = {leaf["pdf_page"]: (min(y for y, _ in leaf["years"]),
                                  max(y for y, _ in leaf["years"]))
               for leaf in files() if leaf["years"]}
    kept = [r for r in parsed
            if not (r["pdf_page"] in covered
                    and covered[r["pdf_page"]][0] <= r["year"]
                    <= covered[r["pdf_page"]][1])]
    new = [dict(r, printed=printed.get(r["pdf_page"])) for r in rows()]
    return sorted(kept + new, key=lambda r: (r["century"], r["year"],
                                             r["pdf_page"],
                                             r.get("order", r["seat"])))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="list the names no engine read as written here")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()

    names = [r for r in rows() if r["tier"] == "adjudicated"]
    typed = [r for r in names if r["source"] == "typed"]
    if args.check:
        for r in typed:
            print(f"\nleaf {r['pdf_page']}  {r['year']} #{r['seat']}  "
                  f"{r['name']!r}")
            for engine, cand in nearest(r["pdf_page"], r["name"]):
                print(f"      {engine[:28]:28s} {cand}")
    annotated = notes()
    if args.check:
        for n in annotated:
            if n["unread"]:
                print(f"\nleaf {n['pdf_page']}  {n['year']} note: no engine read "
                      f"{n['unread']}")
    by_leaf: dict[int, list[dict]] = {}
    for r in names:
        by_leaf.setdefault(r["pdf_page"], []).append(r)
    if args.summary:
        for page, rs in sorted(by_leaf.items()):
            print(f"  leaf {page}: {len(rs):3d} names, "
                  f"{sum(r['source'] == 'typed' for r in rs):2d} typed, "
                  f"{sum(r['engines'] >= 3 for r in rs):3d} read by 3+ engines")
    print(f"\n{len(names)} names on {len(by_leaf)} leaves; "
          f"{len(names) - len(typed)} also read by some engine, "
          f"{len(typed)} typed")
    words = sum(n["words"] for n in annotated)
    unread = sum(len(n["unread"]) for n in annotated)
    print(f"{len(annotated)} notes, {words} words; {words - unread} also read by "
          f"some engine, {unread} by none")


if __name__ == "__main__":
    main()
