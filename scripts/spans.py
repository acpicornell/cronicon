"""Vote on a run of slots as one span, where the engines disagree how to cut it.

The consensus stage votes one geometric slot at a time. That works while the
engines agree where a word ends, and it breaks completely where they do not --
which is exactly where the dashes are, because `cuartos.—J. V.—30.—Mataron` is
one printed stretch that every engine tokenises differently:

    paddle    cuartos.—J. | V.  | —30.—Mataron | ''  | ''
    tess-ia   cuartos.—   | J.  | P.           | —   | 30.—Mataron
    abbyy-ia  cuartos.    | ''  | ''           | —   | /. V. — 30. — Mataron

Voting slot by slot compares readings that are not readings of the same thing.
Worse, it lets the empty string win: at three of those five slots more engines
returned '' than returned any one word, so the vote deleted `—30.—Mataron`
outright. An empty reading is not a recogniser saying the paper is blank; it is
its tokens having landed in the neighbouring slot. Absence of evidence counted
as evidence of absence, 5 476 times, up to 9 668 words.

The fix is to vote on the whole run at once: join each engine's readings across
it and compare the joined strings. The winner is still a string an engine
produced -- no text is invented here, which is the rule this project is built
on -- but it is compared against strings that cover the same ink.

Two deliberate limits:

- **A span never enters the unanimous stratum.** Agreement is measured after
  folding whitespace and dash shapes, so it is weaker than the slot-level
  unanimity that the accept rule rests on. The best a span can grade is
  one-dissent, and it therefore always goes to review.
- **An adjudicated slot stops the merge.** Where a person settled a word against
  the facsimile, that decision outranks anything computed here.
"""
from __future__ import annotations

import re
from collections import Counter

# Every dash the engines produce for the book's em dash, plus the hyphen that
# ABBYY writes for it. Folded together only to *compare* readings; the winning
# string keeps whatever the engine actually wrote.
DASHES = re.compile(r"[-‐‑–—]+")
SPACE = re.compile(r"\s+")


def fold(text: str) -> str:
    """Compare two readings of the same ink, ignoring where the spaces fell.

    **Case is not a disagreement here.** The thing this vote most often has to
    recover is a display heading, which the book sets in small capitals, and a
    small capital is exactly what the engines are least consistent about: leaf
    632 prints `DICIEMBRE 24.—Se terminó…` and the panel returned
    `DICIEMBRE`, `DICIEMBRE`, `DiciEMBRE` and two empty strings. Comparing
    exactly, that is 2 against 2 and `revote` refuses to outvote the blanks, so
    the month was dropped and the entry published as `24.—Se terminó…`. Folding
    case makes it 3 against 2, which is what the page shows.

    The string published is still the raw reading of an engine -- the fold
    decides only which readings are *the same reading*. Measured over the whole
    book: 438 spans -> 472, 1 514 words -> 1 667, and all 34 of the new ones are
    a display month, a source siglum or a name in a source list -- `Diciembre
    7.—Pagó`, `JULIO 24.—Fundicion`, `B. J. Octubre`, `—J. F.`
    """
    return DASHES.sub("—", SPACE.sub("", text)).casefold()


def joined(loci: list[dict], engine: str) -> str:
    parts = [locus["variants"].get(engine, "") or "" for locus in loci]
    return SPACE.sub(" ", " ".join(parts)).strip()


def grade_of(votes: int, size: int) -> str:
    """One-dissent is the ceiling: see the module docstring."""
    if votes >= size - 1:
        return "one-dissent"
    if votes == size - 2:
        return "two-dissent"
    return "contested"


def revote(loci: list[dict], panel: list[str]) -> tuple[str, str] | None:
    """The panel's reading of a run of slots, or None to leave the run alone.

    Returns (text, grade). Refused when the run's best reading is empty, when
    fewer than two engines support it, or when the engines that read nothing
    there outnumber it -- in that order of suspicion.

    **A span vote may only recover text, never remove it.** Leaf 429 shows why:
    over `ABRiL 3.—Marchó`, three engines skipped the display heading and read
    only `3.—Marchó`, outvoting the three that read it. That is the same mistake
    this module exists to fix, one level up -- reading less is not a vote
    against. So the result has to be strictly longer than what the slots already
    said, and has to still contain every word they had.
    """
    readings = {engine: joined(loci, engine) for engine in panel}
    classes: Counter = Counter(fold(text) for text in readings.values())
    if not classes:
        return None

    blank = classes.get("", 0)
    best, votes = max(
        ((key, n) for key, n in classes.items() if key),
        key=lambda kv: (kv[1], len(kv[0])), default=(None, 0))
    if best is None or votes < 2 or votes <= blank:
        return None

    standing = fold(" ".join(x["winner"] for x in loci if x["winner"]))
    if len(best) <= len(standing):
        return None
    if any(fold(x["winner"]) not in best for x in loci if x["winner"].strip()):
        return None

    # Among the engines that agree, the most common raw spacing; ties broken by
    # panel order so the output does not depend on dict iteration.
    raw = [readings[e] for e in panel if fold(readings[e]) == best]
    text = Counter(raw).most_common(1)[0][0]
    return text, grade_of(votes, len(panel))


def merge(row: list[dict], panel: list[str], settled: list[str | None]
          ) -> list[dict]:
    """Re-vote every run of unsettled slots in one line.

    `row` is the line's loci in reading order and `settled` the adjudicated
    text per slot, or None. Returns a list of groups: each is a dict with the
    slots it covers and, when the span vote fired, the text and grade it
    produced.
    """
    groups: list[dict] = []
    n = 0
    while n < len(row):
        locus = row[n]
        if locus["grade"] == "unanimous" or settled[n] is not None:
            groups.append({"loci": [locus], "at": [n]})
            n += 1
            continue

        end = n
        while (end + 1 < len(row) and row[end + 1]["grade"] != "unanimous"
               and settled[end + 1] is None):
            end += 1

        run = row[n:end + 1]
        # The damage signature is a slot the vote emptied. Where every slot in
        # the run still has a word, the engines merely disagree about spelling,
        # which is the review queue's business and not this one's.
        needs = any(not x["winner"].strip() for x in run)
        result = revote(run, panel) if needs else None
        if result is None:
            groups += [{"loci": [x], "at": [i]} for i, x in enumerate(run, n)]
        else:
            text, grade = result
            groups.append({"loci": run, "at": list(range(n, end + 1)),
                           "text": text, "grade": grade})
        n = end + 1
    return groups


WORDISH = re.compile(r"[^0-9a-z]")
# A date marker glued to the word after it: the comparison is between
# `—19.—Te-Deum` and `Te-Deum`, and it is the word that has to match, not the
# marker in front of it.
MARKER = re.compile(r"^[^A-Za-zÀ-ÖØ-öø-ÿ]+")


def same_word(a: str, b: str) -> bool:
    import unicodedata

    def key(text: str) -> str:
        bare = "".join(c for c in unicodedata.normalize("NFD",
                                                        MARKER.sub("", text))
                       if unicodedata.category(c) != "Mn")
        return WORDISH.sub("", bare.lower())
    return len(key(b)) >= 3 and key(a) == key(b)


# A day opening a notice, in digits or in the letters the engines read for
# them: `3.—`, `II.—`, `i.°—`.
DAY_MARKER = re.compile(r"\s*[0-9IilJ|/SO]{1,2}\s*[.,]?\s*[°ºo]?\s*[.,]?\s*[-—–]")

MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "setiembre", "septiembre", "octubre", "noviembre",
          "diciembre")


def month_of(text: str) -> str | None:
    """Which month a reading is of, tolerating one wrong letter.

    A display month is the class the engines read worst -- `Mavo`, `SETIENBRE`,
    `Acosro`, `JuNio` -- and a heading that lands in two slots comes back as two
    *different* misreadings of the same word, so comparing the strings finds
    nothing. 31 headings in the book are doubled this way.
    """
    import unicodedata
    bare = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn").lower()
    bare = WORDISH.sub("", bare)
    for name in MONTHS:
        if name in bare:
            return name
    for name in MONTHS:
        if len(bare) == len(name) and sum(
                x != y for x, y in zip(bare, name)) <= 2:
            return name
    return None


def alike(a: str, b: str) -> bool:
    """Two readings of one printed word: literally equal, or the same month."""
    if same_word(a, b):
        return True
    month = month_of(a)
    return month is not None and month == month_of(b)


def doubled(before: dict, after: dict, panel: list[str], word: str) -> bool:
    """Did the alignment write one printed word into two slots?

    `JUNIO JuNio`, `Setiembre SETIEMBRE`, `FEBRERO Febrero` and `AÑO 1319.
    1319.` are all one display heading counted twice: the engines disagree
    where it ends, the alignment gives it two slots, and the vote fills both.
    `etc., etc.` and `Felipe Felipe` are Campaner writing the word twice.

    The panel tells them apart without anyone having to guess. If some engine
    read the word twice over the same two slots, the page says it twice; if no
    engine did, the second one is the alignment's and not the book's.
    """
    for engine in panel:
        seen = sum(1 for group in (before, after)
                   if any(alike(read, word)
                          for locus in group["loci"]
                          for read in str(
                              locus["variants"].get(engine, "")).split()))
        if seen >= 2:
            return False
    return True


def apply_joins(groups: list[dict], joins: dict) -> list[dict]:
    """Merge the pairs an editorial rule says are one word split in two.

    Passed through here rather than substituted slot by slot so that the word
    record keeps its evidence: as one group the pair reports `printed` as
    `dive rsos`, the box as the union of both, and the grade as the worse of the
    two. Rewriting slot one to `diversos` and slot two to nothing would publish
    the same text and lose the other half of what the panel actually read.

    An adjudicated slot is never merged: a decision taken against the facsimile
    outranks a rule that works from the panel's readings.
    """
    if not joins:
        return groups
    out: list[dict] = []
    n = 0
    while n < len(groups):
        here, nxt = groups[n], groups[n + 1] if n + 1 < len(groups) else None
        key = (here["loci"][-1]["pdf_page"], here["loci"][-1]["index"])
        if (nxt is not None and key in joins
                and not here.get("settled") and not nxt.get("settled")
                and len(here["loci"]) == 1 and len(nxt["loci"]) == 1):
            # The worse of the two grades, and never `unanimous`: the panel was
            # unanimous about two slots, not about the one word this makes.
            worst = max(here["grade"], nxt["grade"], key=rank_of)
            out.append({"loci": here["loci"] + nxt["loci"],
                        "at": here["at"] + nxt["at"],
                        "text": joins[key], "settled": False,
                        "grade": "one-dissent" if worst == "unanimous" else worst})
            n += 2
            continue
        out.append(here)
        n += 1
    return out


RANKS = {"unanimous": 0, "one-dissent": 1, "two-dissent": 2, "contested": 3,
         "adjudicated": 0}


def rank_of(grade: str) -> int:
    return RANKS.get(grade, 3)


def layout(row: list[dict], panel: list[str], settled: list[str | None],
           reading=None, joins: dict | None = None) -> list[dict]:
    """One line, assembled: span re-vote, then the doubling check.

    Both callers must use this. `build_text.py` publishes the prose and
    `parse_entries.py` cuts the same prose into notices, and while they each
    joined the winners themselves the two drifted apart -- the entries kept
    `Te-Deum Te-Deum` and lost `—30.—Mataron` after the published text had been
    repaired of both. Two assemblies of one book is one too many.

    `reading(locus)` supplies a slot's final text, so the caller can apply its
    decisions and editorial repairs; it defaults to the panel's winner. `joins`
    carries the pairs `editorial.split_words` found to be one word the line
    break split in two.
    """
    reading = reading or (lambda locus: locus["winner"])
    groups = merge(row, panel, settled)
    for group in groups:
        if "text" not in group:
            fixed = settled[group["at"][0]]
            group["text"] = (fixed if fixed is not None
                             else reading(group["loci"][0]))
            group["grade"] = ("adjudicated" if fixed is not None
                              else group["loci"][0]["grade"])
            group["settled"] = fixed is not None
        else:
            group["settled"] = False
    return apply_joins(groups, joins or {})


def dedupe(groups: list[dict], panel: list[str]) -> list[dict]:
    """Drop a word the alignment wrote twice, across the whole leaf.

    Run over the leaf and not line by line, because a display heading lands on
    the line boundary as often as inside one: leaf 430 ends a line with `—J.
    Agosto` and opens the next with `Acosro 3.—De vuelta`, one `AGOSTO` in two
    slots on two lines, and a per-line pass cannot see it.
    """
    for n in range(len(groups) - 1):
        head = groups[n]["text"].split()
        tail = groups[n + 1]["text"].split()
        if not (head and tail and alike(head[-1], tail[0])):
            continue
        if groups[n + 1].get("settled"):
            continue
        if not doubled(groups[n], groups[n + 1], panel, tail[0]):
            continue
        # Which copy to drop is not arbitrary for a month: the heading belongs
        # to the notice it *opens*, and the day follows it. Leaf 430 doubles
        # `AGOSTO` across a line break as `…—J. Agosto` / `Acosro 3.—De vuelta`;
        # dropping the second copy leaves the heading stranded at the foot of
        # the July notice and takes the month away from `3.—De vuelta`.
        rest = " ".join(tail[1:] + (groups[n + 2]["text"].split()
                                    if n + 2 < len(groups) else []))
        keep_second = bool(month_of(tail[0]) and DAY_MARKER.match(rest)
                           and not groups[n].get("settled"))
        # Whichever copy survives, it gets the best-supported reading of the
        # two. Leaf 198 doubles May as `MAYO` on its own line and `Mavo` over
        # the day; keeping the position the day requires while keeping `Mavo`
        # would throw away the reading three engines gave for the one two did.
        word = best_reading(groups[n], groups[n + 1], panel,
                            tail[0] if keep_second else head[-1])
        if keep_second:
            groups[n].setdefault("printed", groups[n]["text"])
            groups[n]["text"] = " ".join(head[:-1])
            groups[n + 1].setdefault("printed", groups[n + 1]["text"])
            groups[n + 1]["text"] = " ".join([word] + tail[1:])
        else:
            groups[n].setdefault("printed", groups[n]["text"])
            groups[n]["text"] = " ".join(head[:-1] + [word])
            groups[n + 1].setdefault("printed", groups[n + 1]["text"])
            groups[n + 1]["text"] = " ".join(tail[1:])
    return groups


def strictly_a_month(text: str) -> str | None:
    """The month this token misreads, when the token is *only* that month.

    `month_of` also matches a month with something stuck to it -- `Abril.—B.`,
    `-G. T. OCTUBRE`, `B. J. (1) NOVIEMBRE`, `1355. Marzo` -- and 13 of the 103
    slots this rule would otherwise touch are of that kind. Replacing one of
    those with the plain month name deletes a siglum, a footnote reference or a
    year: the same error the span vote is written to avoid one level up, where
    reading less is not a vote against. So the token has to be the same length
    as the month, letter for letter, and differ in at most two of them.
    """
    if not text or SPACE.search(text.strip()):
        return None
    import unicodedata
    bare = "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn").lower()
    bare = WORDISH.sub("", bare)
    if bare in MONTHS:
        return None                      # already right; nothing to recover
    for name in MONTHS:
        if len(bare) == len(name) and sum(
                x != y for x, y in zip(bare, name)) <= 2:
            return name
    return None


def months(groups: list[dict], panel: list[str]) -> list[dict]:
    """Take a display month heading from the panel where the winner mangled it.

    `Mavo 20.`, `Acosro 3.`, `OcruBRE 28.`, `Jusio 7.`, `FEsRERO 6.`, `ENBRO`.
    A month set in display capitals is the class the engines read worst -- it is
    five or six letters of a face that appears nowhere else on the leaf -- and
    the vote regularly returns the worst of the eight readings, exactly as it
    does for the year headings. This is the same rule the years already get:
    *ask the panel, not the winner*, and publish a string an engine produced.

    It fires on **90 slots over 89 leaves**, and never invents: the winner has
    to be a misreading of one month and nothing else (`strictly_a_month`), a day
    marker has to follow it so the slot is a heading and not prose, and some
    engine has to have read that month plainly. Where no engine did, the
    winner stands and goes to review.
    """
    for n, group in enumerate(groups):
        month = strictly_a_month(group["text"])
        if month is None or group.get("settled"):
            continue
        after = groups[n + 1]["text"] if n + 1 < len(groups) else ""
        if not DAY_MARKER.match(after):
            continue
        counts: Counter = Counter(
            read
            for engine in panel
            for locus in group["loci"]
            for read in str(locus["variants"].get(engine, "")).split()
            if WORDISH.sub("", read.lower()) in MONTHS
            and month_of(read) == month)
        if not counts:
            continue
        # Most engines first; then the fully capitalised form, because the book
        # sets these in small capitals throughout -- checked on the facsimile at
        # leaves 605 and 627 -- and `data/documents` renders small capitals as
        # capitals under the same finding.
        group["text"] = max(counts, key=lambda r: (counts[r], r.isupper(), r))
    return groups


def best_reading(before: dict, after: dict, panel: list[str],
                 word: str) -> str:
    """The panel's best reading of a word two slots both claimed.

    Preferring a form that is exactly a month name over one that is merely
    close to it is the whole point: `MAYO` and `Mavo` get the same number of
    votes on leaf 198 and only one of them is the word.
    """
    counts: Counter = Counter()
    for engine in panel:
        for locus in before["loci"] + after["loci"]:
            for read in str(locus["variants"].get(engine, "")).split():
                if alike(read, word):
                    counts[read] += 1
                    break
    if not counts:
        return word
    exact = {m for m in MONTHS}
    return max(counts, key=lambda r: (
        WORDISH.sub("", r.lower()) in exact, counts[r], len(r), r))


def alternatives(loci: list[dict], panel: list[str], chosen: str) -> list[str]:
    """What the engines read here that the edition did not print.

    Kept so the site can show a doubtful word's rivals instead of a bare
    question mark: the reader is being told the panel argued, and the argument
    is the useful part. Blanks are dropped -- an engine that placed nothing in
    this slot is not offering a reading of it, which is the whole lesson of the
    span re-vote above.
    """
    seen: list[str] = []
    for engine in panel:
        read = " ".join(locus["variants"].get(engine, "") or ""
                        for locus in loci).strip()
        read = SPACE.sub(" ", read)
        if read and read != chosen and read not in seen:
            seen.append(read)
    return seen


def union(boxes: list[list[float]]) -> list[float]:
    """One box covering the whole span, so a crop of it shows what was voted on."""
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]
