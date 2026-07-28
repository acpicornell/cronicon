"""Score the engines against the adjudicated sample.

The sample is stratified by how much the engines agreed (see sample_loci.py), so
raw counts over the sample are not the corpus rate. Every figure reported here is
re-weighted by each stratum's true share of the 8 252 token positions on the
twelve pilot pages, which is what makes "how many tokens would need a human?"
answerable.

Three questions are answered:
  1. Per-engine token accuracy -- who reads this typeface best.
  2. Consensus accuracy -- what a majority vote over the panel gets right, and
     crucially how often the panel agrees unanimously *and is wrong*, since no
     amount of voting can catch that.
  3. Review volume -- how many positions a human would have to look at under a
     given acceptance rule, projected to the whole book.

Which panel is scored comes from `--consensus`: each consensus directory records
the panel that built it, and the readings of engines the sample predates --
Kraken and PaddleOCR, drawn after the sample was frozen -- are recovered from
that directory by **matching word boxes**, not indices. Indices renumber whenever
the geometry of a leaf changes; a box does not. A recovered locus is used only
when every engine the sample and the consensus have in common read it
identically, which is the check that the two are talking about the same word. The
rest are reported and skipped rather than quietly scored against the wrong string.

Usage:
  python scripts/benchmark.py
  python scripts/benchmark.py --consensus consensus6_swap_swapk --by-class
"""
from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ADJUDICATION = PROJECT / "data" / "adjudication"
TRUTH = PROJECT / "data" / "ground_truth" / "adjudicated.tsv"
FINGERPRINT = PROJECT / "data" / "ground_truth" / "sample_fingerprint.txt"
INVENTORY = PROJECT / "data" / "inventory.json"
OCR = PROJECT / "data" / "ocr"

GROUP_ORDER = ["unanimous", "one-dissent", "two-dissent", "contested"]

# Boxes are normalised to the page, so two readings of the same word agree to
# well under a thousandth. Rounding to five places makes the join a dictionary
# lookup instead of a search, and is still an order of magnitude tighter than any
# real difference between two engines' idea of where a word starts.
BOX_PLACES = 5

# Disagreement rates (contested, two-dissent, one-dissent) measured on the pilot
# pages of each class. The leaf counts and sizes they get applied to come from
# scripts/inventory.py, which surveyed all 671 leaves -- earlier versions of this
# table carried hand-written estimates, and they were wrong about the body being
# uniformly two-column.
CLASS_RATES = {
    "body": (0.021, 0.056, 0.126),
    "body_late": (0.079, 0.062, 0.128),
    "body_table": (0.150, 0.146, 0.296),   # scored like the appendix name lists
    "intro": (0.103, 0.117, 0.180),
    "appendix": (0.150, 0.146, 0.296),
    "advertencias": (0.103, 0.117, 0.180),  # single-column prose, like the intro
    "front_matter": (0.103, 0.117, 0.180),
    "errata": (0.169, 0.144, 0.267),
}
# Where the worn late body begins, and how wide a column has to get before a leaf
# is a table rather than running text.
LATE_BODY_FROM = 530
TABLE_COLUMNS = 3

# The panels that have actually been built over the whole book, so the ablation
# compares real candidates rather than hypotheticals. Names match the directories
# under data/ocr/. `consensus6_swap_swapk` is the one the edition is built from,
# and until this table existed it was the one nobody had scored.
ABBYY_BNE = "abbyy-bne"
ABBYY_IA = "abbyy-ia"
TESS_IA = "tess-ia-300dpi-spa_old-cat-lat-psm3"
TESS_BNE = "tess-bne-400dpi-spa_old-psm3"
VISION_BNE = "vision-bne-400dpi-corr"
VISION_IA = "vision-ia-300dpi-corr"
PADDLE = "paddle-ppocrv6"
KRAKEN = "kraken-cronicon"

PANELS = {
    "consensus (as documented)": [ABBYY_BNE, ABBYY_IA, TESS_IA, TESS_BNE,
                                  VISION_BNE, VISION_IA],
    "consensus6_swap (paddle for tess-bne)": [ABBYY_BNE, ABBYY_IA, TESS_IA,
                                              VISION_BNE, VISION_IA, PADDLE],
    "consensus6_swap_swapk (production)": [ABBYY_IA, TESS_IA, VISION_BNE,
                                           VISION_IA, PADDLE, KRAKEN],
    "consensus7_paddle": [ABBYY_BNE, ABBYY_IA, TESS_IA, TESS_BNE, VISION_BNE,
                          VISION_IA, PADDLE],
    "consensus7 (kraken)": [ABBYY_BNE, ABBYY_IA, TESS_IA, TESS_BNE, VISION_BNE,
                            VISION_IA, KRAKEN],
    "all eight": [ABBYY_BNE, ABBYY_IA, TESS_IA, TESS_BNE, VISION_BNE, VISION_IA,
                  PADDLE, KRAKEN],
    "BNE scan only": [ABBYY_BNE, TESS_BNE, VISION_BNE],
    "IA scan only": [ABBYY_IA, TESS_IA, VISION_IA, PADDLE, KRAKEN],
}


def book_composition(chars_per_token: float) -> list[tuple[str, int, int, tuple]]:
    """(class, leaves, tokens per leaf, rates) from the full-book inventory.

    Falls back to nothing if the inventory has not been built: the projection is
    the one figure that decides how much of your life this costs, so it should be
    absent rather than guessed.
    """
    if not INVENTORY.exists():
        return []
    leaves = json.loads(INVENTORY.read_text())["leaves"]

    def classify(leaf: dict) -> str:
        if leaf["page_class"] != "body":
            return leaf["page_class"]
        if leaf["columns"] >= TABLE_COLUMNS:
            return "body_table"
        return "body_late" if leaf["pdf_page"] >= LATE_BODY_FROM else "body"

    grouped: dict[str, list[dict]] = defaultdict(list)
    for leaf in leaves:
        if leaf["page_class"] != "plate_or_blank":
            grouped[classify(leaf)].append(leaf)

    out = []
    for name, items in grouped.items():
        chars = sum(leaf["chars"] for leaf in items)
        out.append((name, len(items), round(chars / len(items) / chars_per_token),
                    CLASS_RATES.get(name, CLASS_RATES["body"])))
    return sorted(out, key=lambda row: -row[1])


def _group_accuracy(consensus, group: str) -> float:
    counts = consensus[group]
    n = sum(counts[k] for k in ("correct", "case", "wrong"))
    return (counts["correct"] + counts["case"]) / n if n else 1.0


def read_census(consensus_dir: Path) -> dict:
    """Actual strata counts from the full-book consensus run, if it exists.

    Once the panel has been run over every leaf there is nothing left to project:
    the queue size is a count. Kept alongside the projection rather than
    replacing it, because the difference between the two is itself the finding.
    """
    if not consensus_dir.exists():
        return {}
    totals = Counter()
    for path in consensus_dir.glob("p*.json"):
        totals += Counter(json.loads(path.read_text())["grades"])
    return dict(totals) if totals else {}


def panel_of(consensus_dir: Path) -> list[str]:
    """The panel a consensus directory was built with, as it recorded it."""
    for path in sorted(consensus_dir.glob("p*.json")):
        return json.loads(path.read_text())["panel"]
    return []


def _box_key(pdf_page: int, bbox) -> tuple:
    return (pdf_page, *(round(v, BOX_PLACES) for v in bbox))


def refresh_variants(data: dict, consensus_dir: Path) -> tuple[list[str], int]:
    """Add the readings of engines drawn after the sample was frozen.

    The sample carries the fourteen readings that existed when it was drawn.
    Kraken and PaddleOCR came later, so a panel containing them cannot be scored
    from the sample alone -- and re-adjudicating 550 positions to add two columns
    to a table would be absurd when the readings are already on disk.

    They are taken from the consensus by matching the word box. The guard is that
    every engine the two have in common must have read the position identically:
    if they have not, the box has been re-tokenised and the two records are no
    longer the same word, whatever their boxes say. Those loci keep only the
    engines the sample itself has, so they still count for the panels that do not
    need the new ones.

    Returns the engines that were added and how many loci refused the join.
    """
    if not consensus_dir.exists():
        return [], 0

    by_box: dict[tuple, dict] = {}
    for pdf_page in sorted({locus["pdf_page"] for locus in data["sample"]}):
        path = consensus_dir / f"p{pdf_page:04d}.json"
        if path.exists():
            for locus in json.loads(path.read_text())["loci"]:
                by_box[_box_key(pdf_page, locus["bbox"])] = locus["variants"]

    added: set[str] = set()
    refused = 0
    for locus in data["sample"]:
        found = by_box.get(_box_key(locus["pdf_page"], locus["bbox"]))
        if found is None:
            refused += 1
            continue
        shared = [e for e in locus["variants"] if e in found]
        if any(locus["variants"][e] != found[e] for e in shared):
            refused += 1
            continue
        for engine, reading in found.items():
            if engine not in locus["variants"]:
                locus["variants"][engine] = reading
                added.add(engine)
    return sorted(added), refused


def load_sample() -> dict:
    """Merge every adjudication round into one sample.

    Rounds are disjoint by construction (sample_loci.py refuses to redraw a
    position an earlier round used) and share the same population, so they
    concatenate. Later rounds exist to deepen a single stratum -- the unanimous
    one -- without redoing the whole design.
    """
    merged: dict | None = None
    for path in sorted(ADJUDICATION.glob("sample*.json")):
        data = json.loads(path.read_text())
        if merged is None:
            merged = data
            merged["rounds"] = [data.get("round", 1)]
        else:
            merged["sample"].extend(data["sample"])
            merged["rounds"].append(data.get("round", len(merged["rounds"]) + 1))
    if merged is None:
        raise SystemExit(f"no sample*.json in {ADJUDICATION}")
    return merged


def check_fingerprint(data: dict) -> None:
    """Refuse to score if the sample no longer matches the adjudicated one.

    The truth file is keyed by id alone, so anything that renumbers the sample --
    a changed seed, a reordered population, an extra round inserted in the middle
    -- would silently score every engine against the wrong words. That happened
    once during development and produced a plausible-looking 6.75%. The
    fingerprint turns it into a hard failure.
    """
    def digest(fields) -> str:
        return hashlib.sha256(
            "\n".join(fields(x) for x in data["sample"]).encode()).hexdigest()[:16]

    # v1 hashed the position's index. That catches a redraw, but an index is not
    # what identifies a word: it renumbers whenever a leaf's geometry changes,
    # while the word stays where it was printed. v2 hashes the box as well, so a
    # sample that kept its numbering but moved its boxes -- the one redraw v1
    # would have waved through -- fails too.
    v1 = digest(lambda x: f"{x['id']}:{x['pdf_page']}:{x['index']}")
    actual = digest(lambda x: f"{x['id']}:{x['pdf_page']}:{x['index']}:"
                              + ",".join(f"{v:.5f}" for v in x["bbox"]))
    if not FINGERPRINT.exists():
        FINGERPRINT.write_text(f"v2:{actual}\n")
        print(f"recorded sample fingerprint v2:{actual}")
        return

    expected = FINGERPRINT.read_text().strip()
    if expected == v1:
        # Recorded before boxes were hashed. The sample is the adjudicated one,
        # so upgrade the record rather than demanding a re-adjudication.
        FINGERPRINT.write_text(f"v2:{actual}\n")
        print(f"sample fingerprint upgraded to v2:{actual} (was {v1})")
        return
    if expected != f"v2:{actual}":
        raise SystemExit(
            f"sample fingerprint v2:{actual} does not match the adjudicated "
            f"{expected}.\nThe sample has been redrawn, so "
            f"{TRUTH.name} no longer refers to the same words. Restore the "
            f"drawing parameters, or re-adjudicate and delete "
            f"{FINGERPRINT.name}.")


def zero_failure_upper_bound(n: int, confidence: float = 0.95) -> float:
    """Upper bound on an error rate after n trials with no errors observed.

    The one-sided Clopper-Pearson bound, which for zero failures reduces to
    1 - (1 - confidence)^(1/n) -- the exact form of the familiar "rule of three".
    Reported because "we saw no errors" is not the same claim as "there are none",
    and the difference is what decides whether a stratum can be accepted unread.
    """
    return 1.0 - (1.0 - confidence) ** (1.0 / n) if n else 1.0


def load_truth() -> dict[int, str]:
    out: dict[int, str] = {}
    for line in TRUTH.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if line.startswith("id\t"):
            continue
        parts = line.split("\t")
        out[int(parts[0])] = parts[1] if len(parts) > 1 else ""
    return out


def norm(text: str | None) -> str:
    """Compare in NFC and without surrounding space; nothing else is forgiven."""
    if text is None:
        return ""
    return unicodedata.normalize("NFC", text).strip()


def case_only_difference(a: str, b: str) -> bool:
    """True when two readings differ solely in capitalisation.

    Campaner sets month names, and the headers of the errata table, in small
    capitals. Whether those come back as "Junio" or "JUNIO" is a normalisation
    choice, not a recognition failure, and lumping it in with genuine misreads
    would flatter or damn engines for the wrong reason.
    """
    return a != b and a.casefold() == b.casefold()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-class", action="store_true")
    ap.add_argument("--consensus", default="consensus",
                    help="consensus directory under data/ocr/; its own recorded "
                         "panel is the one scored, and its readings supply the "
                         "engines the sample predates")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    consensus_dir = OCR / args.consensus
    data = load_sample()
    check_fingerprint(data)
    truth = load_truth()
    population = data["population"]
    total_population = data["population_total"]

    added, refused = refresh_variants(data, consensus_dir)
    panel = panel_of(consensus_dir) or data["panel"]
    engines = sorted({e for locus in data["sample"] for e in locus["variants"]})

    print(f"Panel scored: {args.consensus} -- {', '.join(panel)}")
    if added:
        print(f"  {', '.join(added)} recovered from the consensus by word box")
    if refused:
        print(f"  {refused} of {len(data['sample'])} loci refused the join and "
              f"keep only the readings the sample was drawn with")
    missing_from_sample = [e for e in panel if e not in engines]
    if missing_from_sample:
        print(f"  !! {', '.join(missing_from_sample)} have no readings at any "
              f"sampled position; this panel cannot be scored")

    # The strata are a property of the panel that *drew* the sample, and that is
    # not always the panel being scored -- the sample was drawn with Tesseract
    # `spa_old` while even the original consensus was built with `spa_old+cat+lat`.
    # Scoring across that difference is legitimate and is what the ablation does,
    # but a figure produced this way is not the same figure as one produced by
    # the sampling panel, and the two must not be quoted as if they were.
    drift = set(panel) ^ set(data["panel"])
    if drift:
        print(f"  note: the sample was drawn with a different panel "
              f"({', '.join(sorted(drift))} differ). The strata still come from "
              f"the drawing panel, so the weighting is unchanged, but this")
        print(f"  accuracy is not the one published for the drawing panel.")

    # per (engine, group): correct, case-only, wrong
    tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
    consensus: dict[str, Counter] = defaultdict(Counter)
    per_class: dict[tuple[str, str], Counter] = defaultdict(Counter)
    unanimous_wrong: list[dict] = []
    missing = 0
    incomplete = 0

    for locus in data["sample"]:
        gold = norm(truth.get(locus["id"]))
        if locus["id"] not in truth:
            missing += 1
            continue
        group = locus["group"]
        variants = {e: norm(v) for e, v in locus["variants"].items()}

        for engine, reading in variants.items():
            if reading == gold:
                tally[(engine, group)]["correct"] += 1
            elif case_only_difference(reading, gold):
                tally[(engine, group)]["case"] += 1
            else:
                tally[(engine, group)]["wrong"] += 1

        # A locus that refused the box join is missing the late engines. Voting
        # the remainder would score a panel of five as if it were the panel of
        # six, and the strata are defined by how many dissented -- so the count
        # has to be right or the grade is meaningless. Skip and report.
        if any(e not in variants for e in panel):
            incomplete += 1
            continue

        votes = Counter(variants[e] for e in panel if e in variants)
        winner, count = votes.most_common(1)[0]
        tied = sum(1 for v in votes.values() if v == count) > 1
        if winner == gold:
            consensus[group]["correct"] += 1
        elif case_only_difference(winner, gold):
            consensus[group]["case"] += 1
        else:
            consensus[group]["wrong"] += 1
            if group == "unanimous":
                unanimous_wrong.append({"id": locus["id"], "page": locus["pdf_page"],
                                        "read": winner, "truth": gold})
        if tied:
            consensus[group]["tied"] += 1
        per_class[(locus["page_class"], group)]["n"] += 1
        if winner == gold or case_only_difference(winner, gold):
            per_class[(locus["page_class"], group)]["ok"] += 1

    def weighted(counter_for) -> tuple[float, float]:
        """(strict accuracy, accuracy ignoring case-only differences), corpus-weighted."""
        strict = lenient = 0.0
        for group in GROUP_ORDER:
            counts = counter_for(group)
            n = sum(counts[k] for k in ("correct", "case", "wrong"))
            if not n:
                continue
            share = population[group] / total_population
            strict += share * counts["correct"] / n
            lenient += share * (counts["correct"] + counts["case"]) / n
        return strict, lenient

    print(f"\nSample: {len(data['sample'])} adjudicated positions"
          + (f"  ({missing} without a truth row)" if missing else "")
          + (f"  ({incomplete} not scored: the panel is incomplete there)"
             if incomplete else ""))
    print(f"Population: {total_population} token positions on the pilot pages")
    print("Strata shares: " + "  ".join(
        f"{g}={population[g]/total_population:.1%}" for g in GROUP_ORDER))

    print("\n== Per-engine token accuracy (corpus-weighted) ==")
    print(f"{'engine':34} {'strict':>8} {'ignoring case':>14}")
    rows = []
    for engine in engines:
        strict, lenient = weighted(lambda g, e=engine: tally[(e, g)])
        rows.append((lenient, strict, engine))
    for lenient, strict, engine in sorted(rows, reverse=True):
        print(f"{engine:34} {strict:8.2%} {lenient:14.2%}")

    print("\n== Per-engine accuracy within each stratum (raw sample counts) ==")
    header = f"{'engine':34}" + "".join(f"{g:>14}" for g in GROUP_ORDER)
    print(header)
    for engine in panel:
        cells = []
        for group in GROUP_ORDER:
            counts = tally[(engine, group)]
            n = sum(counts[k] for k in ("correct", "case", "wrong"))
            cells.append(f"{(counts['correct']+counts['case'])/n:13.0%} " if n else
                         f"{'-':>14}")
        print(f"{engine:34}" + "".join(cells))

    print("\n== Consensus (majority vote over the panel) ==")
    strict, lenient = weighted(lambda g: consensus[g])
    print(f"corpus-weighted accuracy: {strict:.2%} strict, {lenient:.2%} ignoring case")
    for group in GROUP_ORDER:
        counts = consensus[group]
        n = sum(counts[k] for k in ("correct", "case", "wrong"))
        if not n:
            continue
        ok = counts["correct"] + counts["case"]
        print(f"  {group:12} sample n={n:3d}  vote right {ok/n:6.1%}  "
              f"wrong {counts['wrong']:3d}  ties {counts['tied']:3d}")

    n_unanimous = sum(consensus["unanimous"][k]
                      for k in ("correct", "case", "wrong"))
    print(f"\n  Shared-error check on the unanimous stratum "
          f"({n_unanimous} adjudicated):")
    if unanimous_wrong:
        print(f"    all engines agreed and were wrong {len(unanimous_wrong)} times "
              f"({len(unanimous_wrong)/n_unanimous:.2%})")
        for item in unanimous_wrong[:12]:
            print(f"      #{item['id']:3d} p{item['page']}  read {item['read']!r} "
                  f"-> printed {item['truth']!r}")
    else:
        bound = zero_failure_upper_bound(n_unanimous)
        share = population["unanimous"] / total_population
        print(f"    no shared error observed; 95% upper bound {bound:.2%}")
        print(f"    worst case over the {share:.0%} of the book this stratum covers: "
              f"{bound*share:.2%} of all tokens")

    print("\n== Panel ablation: majority vote over different engine sets ==")
    print("The sampling strata are fixed by the panel that drew the sample, so")
    print("these rows are comparable to each other. They are *not* comparable to")
    print("a figure computed on a different set of loci: every panel here is")
    print("scored only where all its engines have a reading, and the panels that")
    print("include Kraken or PaddleOCR lose the loci that refused the box join.")
    print("Read the ordering, not the absolute value.")

    # Every row is scored on the same loci: those where every engine any panel
    # names has a reading. Otherwise the panels that lost the 55 loci which
    # refused the box join would be compared against panels scored on all 550,
    # and the ones missing the hardest positions would win for that reason alone.
    everyone = {e for members in PANELS.values() for e in members} & set(engines)
    common = [locus for locus in data["sample"]
              if locus["id"] in truth
              and not any(e not in locus["variants"] for e in everyone)]
    print(f"Common subset: {len(common)} of {len(data['sample'])} loci.")

    for label, members in PANELS.items():
        members = [e for e in members if e in engines]
        if len(members) < 2:
            continue
        counts: dict[str, Counter] = defaultdict(Counter)
        unanimous_n = unanimous_bad = 0
        skipped = 0
        for locus in common:
            gold = norm(truth[locus["id"]])
            variants = {e: norm(locus["variants"][e]) for e in members}
            votes = Counter(variants.values())
            winner, top = votes.most_common(1)[0]
            ok = winner == gold or case_only_difference(winner, gold)
            key = "correct" if winner == gold else ("case" if ok else "wrong")
            counts[locus["group"]][key] += 1
            if sum(1 for v in votes.values() if v == top) > 1:
                counts[locus["group"]]["tied"] += 1
            if top == len(members):        # this panel's own unanimous stratum
                unanimous_n += 1
                unanimous_bad += not ok
        strict, lenient = weighted(lambda g, c=counts: c[g])
        ties = sum(counts[g]["tied"] for g in GROUP_ORDER)
        print(f"  {label:38} n={len(members)}  {lenient:7.2%}   ties {ties:3d}"
              f"   unanimous {unanimous_bad}/{unanimous_n} wrong")

    census = read_census(consensus_dir)
    if census:
        total_tokens = sum(census.values())
        print("\n== Human review, whole book (census, not projection) ==")
        print("scripts/consensus.py has now run the panel over all 614 text")
        print("leaves, so these are counted rather than extrapolated.")
        print(f"\n  {total_tokens:,} token positions")
        for name in GROUP_ORDER:
            print(f"    {name:12} {census[name]:8,}  {census[name]/total_tokens:6.1%}")
        residual = sum(
            census[g] / total_tokens * (1 - _group_accuracy(consensus, g))
            for g in GROUP_ORDER if g != "contested")
        print(f"\n  Reviewing the contested tier: {census['contested']:,} decisions,")
        if residual:
            print(f"  leaving {residual:.2%} residual error -- about 1 wrong "
                  f"word in {1/residual:,.0f}.")
        else:
            # A strong panel can get every accepted-tier position in the sample
            # right, which makes the point estimate zero and says nothing about
            # the true rate. The bound is the honest number.
            accepted = sum(
                sum(consensus[g][k] for k in ("correct", "case", "wrong"))
                for g in GROUP_ORDER if g != "contested")
            bound = zero_failure_upper_bound(accepted) if accepted else 1.0
            print(f"  leaving no measured residual: this panel was right at all "
                  f"{accepted}")
            print(f"  adjudicated positions outside the contested tier. That is "
                  f"a bound, not a")
            print(f"  rate -- 95% upper limit {bound:.2%}, about 1 wrong word in "
                  f"{1/bound:,.0f} at worst.")
        print("\n  The pilot projected 17 000. The gap is one class: the pilot's five")
        print("  body pages showed 2.1% contested where the real body average is")
        print("  5.4%. Five pages was never enough to pin a per-class rate, and the")
        print("  other classes came out close or better than predicted.")

    print("\n== The earlier projection, for comparison ==")
    # Leaf sizes are known in characters; the strata are counted in tokens. The
    # conversion is measured on the pilot pages themselves rather than assumed,
    # so it carries this book's own abbreviation and punctuation density.
    pilot_pages = {locus["pdf_page"] for locus in data["sample"]}
    pilot_chars = sum(leaf["chars"] for leaf
                      in json.loads(INVENTORY.read_text())["leaves"]
                      if leaf["pdf_page"] in pilot_pages) if INVENTORY.exists() else 0
    chars_per_token = (pilot_chars / total_population) if pilot_chars else 5.5
    print(f"({chars_per_token:.2f} characters per token, measured on the pilot pages)")
    print("Leaf counts and sizes come from scripts/inventory.py over all 671")
    print("leaves; the disagreement rates come from the pilot pages of each class.")
    print("The twelve pilot pages deliberately over-sample the hard page classes:")
    print("a third of them are introduction, appendix or errata, which together are")
    print("under 5% of the book. Projecting on the pilot's own mix would overstate")
    print("the work by a factor of three, so the projection re-weights by how many")
    print("leaves of each class the book actually has.")
    print()
    composition = book_composition(chars_per_token)
    if not composition:
        print("  (no data/inventory.json -- run scripts/inventory.py first)")
        composition = []
    print(f"  {'class':16}{'leaves':>7}{'tok/page':>9}"
          + "".join(f"{r:>13}" for r in ("contested", "+2-dissent")))
    review_tokens = {"contested": 0.0, "two": 0.0, "one": 0.0}
    total_tokens = 0.0
    for page_class, leaves, per_page_tokens, rates in composition:
        total_tokens += leaves * per_page_tokens
        review_tokens["contested"] += leaves * per_page_tokens * rates[0]
        review_tokens["two"] += leaves * per_page_tokens * (rates[0] + rates[1])
        review_tokens["one"] += leaves * per_page_tokens * sum(rates)
        print(f"  {page_class:16}{leaves:7d}{per_page_tokens:9d}"
              f"{rates[0]:12.1%}{rates[0]+rates[1]:13.1%}")

    print(f"\n  Whole book, estimated running tokens: {total_tokens:,.0f}")
    for label, key in (("contested only", "contested"),
                       ("contested + two dissenters", "two"),
                       ("anything not unanimous", "one")):
        n = review_tokens[key]
        print(f"  {label:28} {n/total_tokens:6.1%} of tokens  "
              f"~{n:,.0f} decisions")

    residual = {
        "accept everything": sum(
            population[g] / total_population * (1 - _group_accuracy(consensus, g))
            for g in GROUP_ORDER),
        "review contested": sum(
            population[g] / total_population * (1 - _group_accuracy(consensus, g))
            for g in GROUP_ORDER if g != "contested"),
        "review contested + two-dissent": sum(
            population[g] / total_population * (1 - _group_accuracy(consensus, g))
            for g in GROUP_ORDER if g not in {"contested", "two-dissent"}),
    }
    print("\n  Residual token error after review (corpus-weighted):")
    for label, rate in residual.items():
        print(f"    {label:32} {rate:.2%}   "
              f"~1 wrong word in {1/rate:,.0f}" if rate else
              f"    {label:32} none measured")

    if args.by_class:
        print("\n== Consensus accuracy by page class (raw sample) ==")
        classes = sorted({c for c, _ in per_class})
        for page_class in classes:
            n = sum(per_class[(page_class, g)]["n"] for g in GROUP_ORDER)
            ok = sum(per_class[(page_class, g)]["ok"] for g in GROUP_ORDER)
            if n:
                print(f"  {page_class:16} n={n:3d}  {ok/n:6.1%}")

    if args.json:
        args.json.write_text(json.dumps({
            "population": population,
            "engines": {e: dict(zip(("strict", "lenient"),
                                    weighted(lambda g, en=e: tally[(en, g)])))
                        for e in engines},
            "consensus": dict(zip(("strict", "lenient"),
                                  weighted(lambda g: consensus[g]))),
            "unanimous_wrong": unanimous_wrong,
        }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
