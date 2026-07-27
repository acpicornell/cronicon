"""Score any engine against the adjudicated ground truth, without redrawing.

The sample is frozen: its ids, positions and the 550 human decisions keyed to
them must not move when a new engine appears. So instead of regenerating it, this
aligns the new engine's token stream to the same geometry reference the sample
was drawn on and reads off what it says at each sampled position.

That makes a seventh engine measurable on exactly the same yardstick as the six,
at zero human cost.

Usage:
  python scripts/score_engine.py --engine kraken-cronicon
  python scripts/score_engine.py --engine kraken-cronicon --show-errors 20
"""
from __future__ import annotations

import argparse
import unicodedata
from collections import Counter, defaultdict

from benchmark import (GROUP_ORDER, case_only_difference, load_sample,
                       load_truth, norm)
from consensus import project, tesseract_words
from readings import available_readings
from sample_loci import GEOMETRY, PANEL


def engine_tokens_at(pdf_page: int, engine: str) -> list[str | None]:
    """What `engine` reads at each geometry position of this leaf."""
    words = tesseract_words(pdf_page, GEOMETRY)
    reference = [w["text"] for w in words]
    readings = available_readings(pdf_page)
    if engine not in readings:
        return []
    return project(reference, readings[engine].split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True)
    ap.add_argument("--show-errors", type=int, default=0)
    args = ap.parse_args()

    data = load_sample()
    truth = load_truth()
    population = data["population"]
    total = data["population_total"]

    by_page: dict[int, list[dict]] = defaultdict(list)
    for locus in data["sample"]:
        by_page[locus["pdf_page"]].append(locus)

    counts: dict[str, Counter] = defaultdict(Counter)
    errors: list[tuple] = []
    missing_pages: list[int] = []

    for pdf_page, loci in sorted(by_page.items()):
        stream = engine_tokens_at(pdf_page, args.engine)
        if not stream:
            missing_pages.append(pdf_page)
            continue
        for locus in loci:
            if locus["id"] not in truth:
                continue
            gold = norm(truth[locus["id"]])
            index = locus["index"]
            reading = norm(stream[index] if index < len(stream) else None)
            group = locus["group"]
            if reading == gold or case_only_difference(reading, gold):
                counts[group]["ok"] += 1
            else:
                counts[group]["wrong"] += 1
                errors.append((locus["id"], pdf_page, reading, gold, group))

    if missing_pages:
        print(f"no reading for {args.engine} on pages {missing_pages}\n")

    weighted = 0.0
    for group in GROUP_ORDER:
        n = counts[group]["ok"] + counts[group]["wrong"]
        if n:
            weighted += (population[group] / total) * counts[group]["ok"] / n

    scored = sum(counts[g]["ok"] + counts[g]["wrong"] for g in GROUP_ORDER)
    print(f"{args.engine}: {weighted:.2%} corpus-weighted token accuracy "
          f"({scored} positions scored)")
    print(f"\n{'stratum':14}{'n':>6}{'accuracy':>11}")
    for group in GROUP_ORDER:
        n = counts[group]["ok"] + counts[group]["wrong"]
        if n:
            print(f"{group:14}{n:6d}{counts[group]['ok']/n:11.0%}")

    print("\nfor comparison, the six panel engines on the same positions:")
    for engine in PANEL:
        other: dict[str, Counter] = defaultdict(Counter)
        for locus in data["sample"]:
            if locus["id"] not in truth or engine not in locus["variants"]:
                continue
            gold = norm(truth[locus["id"]])
            reading = norm(locus["variants"][engine])
            ok = reading == gold or case_only_difference(reading, gold)
            other[locus["group"]]["ok" if ok else "wrong"] += 1
        w = sum((population[g] / total) *
                (other[g]["ok"] / (other[g]["ok"] + other[g]["wrong"]))
                for g in GROUP_ORDER
                if other[g]["ok"] + other[g]["wrong"])
        print(f"  {engine:38} {w:.2%}")

    if args.show_errors and errors:
        print(f"\nfirst {args.show_errors} errors:")
        for id_, page, read, gold, group in errors[:args.show_errors]:
            print(f"  #{id_:3d} p{page:<5} [{group:11}] read {read!r:24} "
                  f"printed {gold!r}")


if __name__ == "__main__":
    main()
