"""Draw a stratified sample of token positions to adjudicate against the facsimile.

Adjudicating every token of twelve pages is roughly 7 600 decisions, which is not
a pilot. Adjudicating only the contested ones would answer "when the engines
disagree, who is right?" but leave the more dangerous question untouched: how
often do they agree *and are all wrong*? A stratified sample answers both from a
few hundred decisions.

Strata are the vote margins over the engine panel: unanimous, one dissenter, and
so on down to ties. Each stratum is sampled independently, so the rare-but-costly
cases are represented, and per-engine accuracy is recovered afterwards by
weighting each stratum by its true share of the corpus.

Geometry comes from Tesseract's TSV, which is the only reading in the panel that
gives a box per word, so every sampled position can be cropped from the facsimile.

## Two families, and why they must not be merged

The first family -- `sample*.json`, rounds 1 and 2 -- is drawn from the twelve
pilot leaves and is **frozen**: the strata come from the panel as it stood then,
the geometry from the plain `spa_old` Tesseract, and 550 adjudications are keyed
to its ids. Nothing about it may move.

The second -- `documents*.json` -- is drawn from the leaves Campaner prints
documents on, which the first family does not touch at all: not one of its 550
positions falls on a document leaf, so everything the benchmark says about this
book is a statement about Spanish chronicle prose. That family is drawn from the
production consensus, because there is no legacy adjudication on those leaves to
protect and every reason to measure the panel that actually ships.

They are separate files with separate populations because their strata shares are
different. Merging them would weight medieval Catalan by the chronicle's
proportions and quietly corrupt every figure that depends on them.

Usage:
  python scripts/sample_loci.py --per-stratum 100 60 50 50
  python scripts/sample_loci.py --family documents --from-consensus \\
      consensus6_swap_swapk --pages documents --per-stratum 200 50 30 40
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

from consensus import project, stratum_of, tesseract_words
from pilot_pages import PILOT, CLASS_OF
from readings import available_readings

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
PAGES = PROJECT / "data" / "pages"
OUT = PROJECT / "data" / "adjudication"

IA_OFFSET = -2
# The benchmark's geometry provider, deliberately still the plain spa_old
# variant and not the production panel's: renumbering the sample would
# invalidate every adjudication in data/ground_truth/.
GEOMETRY = ("ia", "300dpi", "spa_old", "psm3")
GEOMETRY_ENGINE = "tess-ia-300dpi-spa_old-psm3"

PANEL = [
    "abbyy-bne",
    "abbyy-ia",
    "tess-bne-400dpi-spa_old-psm3",
    "tess-ia-300dpi-spa_old-psm3",
    "vision-bne-400dpi-corr",
    "vision-ia-300dpi-corr",
]

SEED = 20260727
CONTEXT_TOKENS = 3      # tokens of context either side, for readability
SHEET_WIDTH = 1600
LABEL_HEIGHT = 30
CROP_PAD_Y = 0.0016
# Crops are scaled to a constant line height rather than a constant width, so a
# three-word footnote line does not end up rendered ten times larger than a full
# line of body text on the same sheet.
TARGET_LINE_HEIGHT = 78


def collect(pdf_page: int) -> list[dict]:
    """Every token position on the page, with what each engine read there.

    Strata are computed from the PANEL alone -- six readings chosen to be as
    independent as possible -- so that the sample design does not shift when a
    Tesseract variant is added or dropped. Every *available* reading is still
    recorded at each position, which is what lets the same 300 adjudications
    score the dpi and language-model ablations for free.
    """
    words = tesseract_words(pdf_page, GEOMETRY)
    reference = [w["text"] for w in words]
    readings = available_readings(pdf_page)
    projected = {k: project(reference, text.split())
                 for k, text in readings.items() if k != GEOMETRY_ENGINE}
    projected[GEOMETRY_ENGINE] = list(reference)

    loci = []
    for i, word in enumerate(words):
        variants = {k: projected[k][i] for k in projected}
        panel_votes = Counter(variants[k] for k in PANEL
                              if variants.get(k) is not None)
        if not panel_votes:
            continue
        loci.append({
            "pdf_page": pdf_page,
            "page_class": CLASS_OF[pdf_page],
            "index": i,
            "stratum": stratum_of(panel_votes, len(PANEL)),
            "bbox": word["bbox"],
            "line_bbox": word["line_bbox"],
            "context": " ".join(reference[max(0, i - CONTEXT_TOKENS):
                                          i + CONTEXT_TOKENS + 1]),
            "variants": variants,
        })
    return loci


def collect_from_consensus(pdf_page: int, consensus: Path) -> list[dict]:
    """Every position on a leaf, taken from a consensus already built.

    `collect` recomputes the vote with a fixed panel and geometry, which is what
    keeps the frozen sample frozen. For a new family that is the wrong thing: the
    production consensus chooses its scan and its alignment per leaf, and a sample
    drawn any other way would measure a pipeline nobody runs.
    """
    path = consensus / f"p{pdf_page:04d}.json"
    if not path.exists():
        return []
    leaf = json.loads(path.read_text())
    return [{
        "pdf_page": pdf_page,
        "page_class": CLASS_OF.get(pdf_page, "document"),
        "index": locus["index"],
        "stratum": locus["stratum"],
        "grade": locus["grade"],
        "bbox": locus["bbox"],
        "line_bbox": locus["line_bbox"],
        "context": locus["context"],
        "variants": locus["variants"],
    } for locus in leaf["loci"]]


def document_leaves() -> list[int]:
    """The leaves the documents occupy, from build_documents.py's catalogue."""
    path = PROJECT / "data" / "documents" / "sections.json"
    if not path.exists():
        raise SystemExit(f"{path} missing -- run scripts/build_documents.py")
    pages: set[int] = set()
    for section in json.loads(path.read_text()):
        pages.update(range(section["first_leaf"], section["last_leaf"] + 1))
    return sorted(pages)


def crop(image: Image.Image, locus: dict) -> Image.Image:
    """The whole printed line, with the sampled word boxed."""
    w, h = image.size
    lx0, ly0, lx1, ly1 = locus["line_bbox"]
    box = (max(0, int(lx0 * w) - 12), max(0, int((ly0 - CROP_PAD_Y) * h)),
           min(w, int(lx1 * w) + 12), min(h, int((ly1 + CROP_PAD_Y) * h)))
    piece = image.crop(box).convert("RGB")

    draw = ImageDraw.Draw(piece)
    x0, y0, x1, y1 = locus["bbox"]
    draw.rectangle([int(x0 * w) - box[0] - 3, int(y0 * h) - box[1] - 3,
                    int(x1 * w) - box[0] + 3, int(y1 * h) - box[1] + 3],
                   outline=(220, 0, 0), width=4)
    return piece


def build_sheets(sample: list[dict], per_sheet: int,
                 prefix: str = "sample") -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    by_page: dict[int, list[dict]] = defaultdict(list)
    for locus in sample:
        by_page[locus["pdf_page"]].append(locus)

    images = {p: Image.open(sorted(
        (PAGES / "ia").glob(f"leaf{p + IA_OFFSET:04d}_*dpi.png"),
        key=lambda q: int(q.stem.split("_")[-1][:-3]))[-1]).convert("L")
        for p in by_page}

    ordered = sorted(sample, key=lambda x: (x["pdf_page"], x["index"]))
    sheets = []
    for start in range(0, len(ordered), per_sheet):
        chunk = ordered[start:start + per_sheet]
        crops = []
        for locus in chunk:
            piece = crop(images[locus["pdf_page"]], locus)
            scale = min(TARGET_LINE_HEIGHT / piece.height, SHEET_WIDTH / piece.width)
            crops.append(piece.resize((max(1, round(piece.width * scale)),
                                       max(1, round(piece.height * scale))),
                                      Image.LANCZOS))

        height = sum(c.height + LABEL_HEIGHT for c in crops) + 8
        sheet = Image.new("RGB", (SHEET_WIDTH, height), (255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        y = 4
        for locus, piece in zip(chunk, crops):
            draw.text((8, y + 8), f"#{locus['id']}  p{locus['pdf_page']}", fill=(0, 0, 0))
            y += LABEL_HEIGHT
            sheet.paste(piece, (0, y))
            y += piece.height
            draw.line([(0, y - 1), (SHEET_WIDTH, y - 1)], fill=(180, 180, 180))

        path = OUT / f"{prefix}_sheet_{start // per_sheet:02d}.png"
        sheet.save(path)
        sheets.append(path)
    return sheets


def previous_rounds(family: str = "sample") -> tuple[set[tuple[int, int]], int]:
    """Positions already drawn in this family, and the highest id issued so far.

    Rounds must be disjoint: re-adjudicating a position we have already settled
    would inflate the sample size without adding any information about the book.
    Ids run on across families as well, so that a truth file keyed by id alone
    can never confuse a chronicle position with a document one.
    """
    taken: set[tuple[int, int]] = set()
    highest = 0
    for path in sorted(OUT.glob("*.json")):
        if not path.name.startswith(("sample", "documents")):
            continue
        data = json.loads(path.read_text())
        if "sample" not in data:
            continue
        for locus in data["sample"]:
            highest = max(highest, locus["id"])
            if path.name.startswith(family):
                taken.add((locus["pdf_page"], locus["index"]))
    return taken, highest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-stratum", type=int, nargs="*", default=None,
                    help="sample sizes for [unanimous, 5of6, 4of6, rest]")
    ap.add_argument("--per-sheet", type=int, default=12)
    ap.add_argument("--sheets", action="store_true",
                    help="also build the old contact sheets. They scale every "
                         "crop to 78 pixels, which is not enough to see a "
                         "diacritic -- kept only because the frozen family was "
                         "adjudicated from them")
    ap.add_argument("--round", type=int, default=1,
                    help="Round 1 writes sample.json. Later rounds write "
                         "sample_roundN.json, draw only positions no earlier "
                         "round used, and number ids on from the last one.")
    ap.add_argument("--family", default="sample",
                    help="which sample family: 'sample' is the frozen chronicle "
                         "one, 'documents' the leaves Campaner prints documents "
                         "on. Separate files, separate populations")
    ap.add_argument("--from-consensus", default=None,
                    help="draw from a consensus already built, using its own "
                         "panel and per-leaf choices, instead of recomputing the "
                         "vote with the frozen geometry")
    ap.add_argument("--pages", default="pilot",
                    help="pilot | documents | comma-separated leaves")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing sample; invalidates the "
                         "adjudications keyed to it")
    args = ap.parse_args()

    # The frozen family exists to be scored against 550 adjudications keyed to
    # its ids. Anything that changes how it is drawn renumbers it, so those two
    # options are refused there rather than merely discouraged.
    if args.family == "sample" and (args.from_consensus or args.pages != "pilot"):
        raise SystemExit(
            "the 'sample' family is frozen: it is drawn from the pilot leaves "
            "with the panel and geometry of the day, and 550 adjudications are "
            "keyed to its ids.\nUse --family documents for a new population.")

    if args.pages == "pilot":
        pages = [p for p, _, _, _ in PILOT]
    elif args.pages == "documents":
        pages = document_leaves()
    else:
        pages = [int(p) for p in args.pages.split(",")]

    all_loci: list[dict] = []
    if args.from_consensus:
        consensus = OCR / args.from_consensus
        if not consensus.exists():
            raise SystemExit(f"{consensus} missing -- run consensus.py first")
        for pdf_page in pages:
            all_loci.extend(collect_from_consensus(pdf_page, consensus))
        panel_used = json.loads(
            next(iter(sorted(consensus.glob("p*.json")))).read_text())["panel"]
    else:
        for pdf_page in pages:
            all_loci.extend(collect(pdf_page))
        panel_used = PANEL

    counts = Counter(locus["stratum"] for locus in all_loci)
    panel = len(panel_used)
    groups = {
        "unanimous": [x for x in all_loci if x["stratum"] == f"{panel}of{panel}"],
        "one-dissent": [x for x in all_loci if x["stratum"] == f"{panel-1}of{panel}"],
        "two-dissent": [x for x in all_loci if x["stratum"] == f"{panel-2}of{panel}"],
        "contested": [x for x in all_loci
                      if x["stratum"] in {"tie", f"{panel-3}of{panel}",
                                          f"{panel-4}of{panel}",
                                          f"{panel-5}of{panel}"}],
    }

    print(f"{len(all_loci):,} token positions over {len(pages)} leaves "
          f"[{args.family}]")
    for name, items in groups.items():
        print(f"  {name:12s} {len(items):6,}  {len(items)/len(all_loci):6.1%}")
    print(f"  raw strata: {dict(counts.most_common())}")

    OUT.mkdir(parents=True, exist_ok=True)
    taken: set[tuple[int, int]] = set()
    first_id = 1
    if args.round > 1 or args.family != "sample":
        taken, highest = previous_rounds(args.family)
        first_id = highest + 1
        print(f"  round {args.round}: {len(taken)} positions already drawn in "
              f"this family, ids continue from {first_id}")

    sizes = args.per_stratum or [100, 60, 50, 50]
    # Round 1 was drawn before rounds existed and keeps the bare seed; later
    # rounds offset by their number. Changing this renumbers the sample and
    # silently invalidates every adjudication in data/ground_truth/.
    rng = random.Random(SEED if args.round == 1 else SEED + args.round)
    sample: list[dict] = []
    for (name, items), size in zip(groups.items(), sizes):
        available = [x for x in items if (x["pdf_page"], x["index"]) not in taken]
        picked = rng.sample(available, min(size, len(available)))
        for locus in picked:
            locus["group"] = name
        sample.extend(picked)

    for n, locus in enumerate(sorted(sample, key=lambda x: (x["pdf_page"],
                                                            x["index"])), first_id):
        locus["id"] = n

    stem = (args.family if args.round == 1
            else f"{args.family}_round{args.round}")
    name, prefix = f"{stem}.json", stem
    if (OUT / name).exists() and not args.force:
        raise SystemExit(
            f"{name} already exists.\n"
            "A drawn sample is data, not something to recompute: the adjudications\n"
            "in data/ground_truth/ are keyed to its ids, and anything that changes\n"
            "an engine's output changes the strata and therefore which positions\n"
            "get drawn. Repairing the ABBYY-IA parser once silently renumbered it\n"
            "this way. Pass --force only if you intend to re-adjudicate from\n"
            "scratch, and delete data/ground_truth/sample_fingerprint.txt too.")
    (OUT / name).write_text(json.dumps({
        "seed": SEED if args.round == 1 else SEED + args.round,
        "round": args.round, "family": args.family, "panel": panel_used,
        "consensus": args.from_consensus,
        "leaves": pages,
        "population": {group: len(items) for group, items in groups.items()},
        "population_total": len(all_loci),
        "sample": sorted(sample, key=lambda x: x["id"]),
    }, ensure_ascii=False, indent=1))

    span = f"ids {first_id}-{first_id + len(sample) - 1}"
    # The contact sheets scale every crop to a constant 78-pixel line, which is
    # comfortable for reading words and *not enough to tell an acute accent from
    # the dot of an i* -- the one shared error round 2 recorded turned out to be
    # the adjudication being wrong for exactly that reason. They are kept for the
    # frozen family, which was adjudicated from them and must stay reproducible,
    # and refused for anything new: scripts/review.py shows the same positions at
    # native resolution.
    if args.sheets:
        sheets = build_sheets(sample, args.per_sheet, prefix)
        print(f"\nsampled {len(sample)} positions ({span}) -> {len(sheets)} "
              f"review sheets in {OUT}")
    else:
        print(f"\nsampled {len(sample)} positions ({span}) -> {OUT / name}")
        print(f"\nAdjudicate them at native resolution:\n"
              f"  python scripts/review.py --sample {name}")


if __name__ == "__main__":
    main()
