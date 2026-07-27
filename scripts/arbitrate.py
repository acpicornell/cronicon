"""How far can the contested positions be resolved without a human?

Plain majority voting leaves 3.7% of the book's words unresolved -- about 17 000
decisions. This measures what deterministic arbitration rules recover from that,
scored against the same 550 adjudicated positions the benchmark uses, so the
answer is a measurement rather than an argument.

The rules, in increasing order of how much they assume:

  majority        what the benchmark already does; the baseline.
  medoid          pick the candidate closest to all the others by character
                  similarity. Cannot invent: it only ever returns a string some
                  engine actually produced. Breaks ties that plain counting
                  cannot.
  character-vote  vote per character position and build the winner. This *can*
                  return a string no engine produced, which is the failure mode
                  the whole project exists to avoid, so it is reported separately
                  and its invented outputs are counted.
  lexicon         prefer a candidate the book itself attests elsewhere. Built
                  from every unanimous position in all 614 leaves -- 27 316
                  distinct words -- and deliberately not from a Spanish
                  dictionary, which would "correct" Campaner's 1881 spelling.
                  Applied everywhere it loses; applied only where the panel is
                  actually stuck it is the best rule measured.

Usage:
  python scripts/arbitrate.py
"""
from __future__ import annotations

import json
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from benchmark import (ADJUDICATION, GROUP_ORDER, case_only_difference,
                       load_sample, load_truth, norm)
from readings import available_readings, tokens

PROJECT = Path(__file__).resolve().parent.parent

PANEL = [
    "abbyy-bne",
    "abbyy-ia",
    "tess-bne-400dpi-spa_old-psm3",
    "tess-ia-300dpi-spa_old-psm3",
    "vision-bne-400dpi-corr",
    "vision-ia-300dpi-corr",
]


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(a=a, b=b, autojunk=False).ratio()


def rule_majority(variants: dict[str, str], lexicon: set[str]) -> tuple[str, bool]:
    votes = Counter(variants.values())
    top = votes.most_common(1)[0][1]
    winners = [v for v, n in votes.items() if n == top]
    return winners[0], len(winners) > 1


def rule_medoid(variants: dict[str, str], lexicon: set[str]) -> tuple[str, bool]:
    """The candidate with the most total character-similarity to the others.

    Plain counting sees `Gaçó,` `Gacó,` `Gagó,` as a three-way tie; by character
    similarity they are all near each other and the reading two engines share
    wins on aggregate agreement rather than on raw count.
    """
    votes = Counter(variants.values())
    candidates = list(votes)
    if len(candidates) == 1:
        return candidates[0], False
    readings = list(variants.values())
    scored = [(sum(similarity(c, r) for r in readings), votes[c], c)
              for c in candidates]
    best = max(scored)
    tied = sum(1 for s in scored if s[0] == best[0]) > 1
    return best[2], tied


def rule_character_vote(variants: dict[str, str], lexicon: set[str]
                        ) -> tuple[str, bool]:
    """Vote per character position against the medoid as a spine."""
    spine, _ = rule_medoid(variants, lexicon)
    readings = list(variants.values())
    columns: list[Counter] = [Counter() for _ in range(len(spine))]
    for reading in readings:
        matcher = SequenceMatcher(a=spine, b=reading, autojunk=False)
        seen = set()
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    columns[i1 + k][reading[j1 + k]] += 1
                    seen.add(i1 + k)
            elif tag == "replace":
                span = reading[j1:j2]
                for k in range(i1, i2):
                    idx = k - i1
                    columns[k][span[idx] if idx < len(span) else ""] += 1
                    seen.add(k)
            elif tag == "delete":
                for k in range(i1, i2):
                    columns[k][""] += 1
                    seen.add(k)
    out = "".join(col.most_common(1)[0][0] if col else spine[i]
                  for i, col in enumerate(columns))
    return out, False


def rule_lexicon(variants: dict[str, str], lexicon: dict[str, int]) -> tuple[str, bool]:
    """Medoid, but restricted to candidates the book itself attests elsewhere."""
    votes = Counter(variants.values())
    attested = {v for v in votes if lexicon.get(strip_punct(v), 0) >= MIN_ATTESTATIONS}
    if not attested or len(attested) == len(votes):
        return rule_medoid(variants, lexicon)
    filtered = {k: v for k, v in variants.items() if v in attested}
    winner, tied = rule_medoid(filtered, lexicon)
    return winner, tied


# A word has to appear this many times elsewhere in the book before its presence
# counts as evidence. Once is not attestation: a one-off unanimous misreading
# would otherwise be enshrined as a real word and start winning arguments.
MIN_ATTESTATIONS = 3


def strip_punct(token: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFC", token)
                   if c.isalnum() or c in "áéíóúüñçÁÉÍÓÚÜÑÇ").lower()


def build_lexicon(sampled: set[tuple[int, int]]) -> dict[str, int]:
    """The book's own vocabulary, counted from every unanimous position in it.

    Not a dictionary of Spanish: a dictionary of *this book*. Modern Spanish
    would insist on `formación`, `día`, `Septiembre`, `mallorquín`; Campaner
    printed `formacion`, `dia`, `Setiembre`, `mallorquin`, and a transcription
    that silently modernises them is worse than one that misreads them, because
    the error looks right.

    Read from the full-book consensus -- all 614 leaves -- rather than the twelve
    pilot pages, which is the difference between 1 544 words and the real
    vocabulary. Adjudicated positions are excluded so it cannot memorise the
    answers it is about to be tested against.
    """
    from consensus import OUT as CONSENSUS_DIR

    lexicon: Counter = Counter()
    for path in sorted(CONSENSUS_DIR.glob("p*.json")):
        data = json.loads(path.read_text())
        page = data["pdf_page"]
        for locus in data["loci"]:
            if locus["grade"] != "unanimous":
                continue
            if (page, locus["index"]) in sampled:
                continue
            word = strip_punct(locus["winner"] or "")
            if len(word) > 2:
                lexicon[word] += 1
    return lexicon


def main() -> None:
    data = load_sample()
    truth = load_truth()
    population = data["population"]
    total = data["population_total"]

    sampled = {(x["pdf_page"], x["index"]) for x in data["sample"]}
    lexicon = build_lexicon(sampled)
    frequent = sum(1 for v in lexicon.values() if v >= MIN_ATTESTATIONS)
    print(f"Lexicon from the whole book: {len(lexicon):,} distinct words, "
          f"{frequent:,} seen {MIN_ATTESTATIONS}+ times")
    print(f"Scoring {len(data['sample'])} adjudicated positions\n")

    def rule_lexicon_contested_only(variants, lexicon, group=None):
        """The book's vocabulary, but only where the panel is actually stuck.

        The earlier version applied it everywhere and lost overall: it rescued
        contested positions but damaged the tiers where the panel was already
        nearly right. Confining it to the contested tier keeps the gain and drops
        the damage.
        """
        if group != "contested":
            return rule_majority(variants, lexicon)
        return rule_lexicon(variants, lexicon)

    rules = {
        "majority (baseline)": rule_majority,
        "medoid": rule_medoid,
        "character-vote": rule_character_vote,
        "lexicon everywhere": rule_lexicon,
        "lexicon on contested only": rule_lexicon_contested_only,
    }

    results: dict[str, dict] = {}
    for name, rule in rules.items():
        counts: dict[str, Counter] = defaultdict(Counter)
        invented = 0
        for locus in data["sample"]:
            if locus["id"] not in truth:
                continue
            gold = norm(truth[locus["id"]])
            variants = {e: norm(locus["variants"][e]) for e in PANEL
                        if e in locus["variants"]}
            try:
                winner, tied = rule(variants, lexicon, locus["group"])
            except TypeError:
                winner, tied = rule(variants, lexicon)
            group = locus["group"]
            right = winner == gold or case_only_difference(winner, gold)
            counts[group]["ok" if right else "wrong"] += 1
            # A rule is only useful if the positions it calls *decisively* are
            # reliable: those are the ones that could skip the review queue.
            counts[group]["tied" if tied else "decisive"] += 1
            if not tied:
                counts[group]["decisive_ok" if right else "decisive_wrong"] += 1
            if winner not in set(variants.values()):
                invented += 1

        weighted = 0.0
        for group in GROUP_ORDER:
            n = counts[group]["ok"] + counts[group]["wrong"]
            if n:
                weighted += (population[group] / total) * counts[group]["ok"] / n
        results[name] = {"counts": counts, "weighted": weighted,
                         "invented": invented}

    print(f"{'rule':22}{'accuracy':>10}{'contested ok':>14}{'ties left':>11}"
          f"{'invented':>10}")
    for name, res in results.items():
        c = res["counts"]["contested"]
        n = c["ok"] + c["wrong"]
        print(f"{name:22}{res['weighted']:9.2%}"
              f"{c['ok']/n:13.0%} ({c['ok']}/{n})"
              f"{sum(res['counts'][g]['tied'] for g in GROUP_ORDER):6d}"
              f"{res['invented']:10d}")

    print("\nPer-stratum accuracy (raw sample counts):")
    print(f"{'rule':22}" + "".join(f"{g:>14}" for g in GROUP_ORDER))
    for name, res in results.items():
        cells = []
        for group in GROUP_ORDER:
            c = res["counts"][group]
            n = c["ok"] + c["wrong"]
            cells.append(f"{c['ok']/n:13.0%} " if n else f"{'-':>14}")
        print(f"{name:22}" + "".join(cells))

    baseline = results["majority (baseline)"]["weighted"]
    print("\nOn the contested stratum, split by whether the rule was decisive:")
    print(f"{'rule':22}{'decisive':>10}{'of which right':>16}{'ties left':>11}")
    for name, res in results.items():
        c = res["counts"]["contested"]
        dec = c["decisive"]
        right = c["decisive_ok"]
        print(f"{name:22}{dec:9d}{right/dec if dec else 0:15.0%}"
              f"{c['tied']:11d}")

    print("\nChange against plain majority:")
    for name, res in results.items():
        if name.startswith("majority"):
            continue
        gain = (res["weighted"] - baseline) * 100
        note = ""
        if res["invented"]:
            note = (f"  -- and returns {res['invented']} strings no engine read, "
                    "which is the one thing this pipeline must never do")
        print(f"  {name:22} {gain:+.2f} accuracy points{note}")


if __name__ == "__main__":
    main()
