"""Token-level consensus across the panel, and the queue of what it cannot settle.

For every token position on a leaf this records what each engine read there, how
much they agreed, and which reading wins. Positions the panel is unanimous about
are accepted outright -- 360 adjudications found no counter-example, bounding the
shared-error rate at 0.83%. Everything else is graded by how many engines
dissented, and the worst tier is what a human is asked to look at.

Nothing here generates text. The winner is always a string some engine actually
produced; the pipeline can be wrong, but only in ways that some recogniser was
wrong first. That is the whole guarantee.

Word geometry comes from Tesseract's TSV, the only panel member that gives a box
per word, so every position can be cropped from the facsimile for review.

Usage:
  python scripts/consensus.py --pages all
  python scripts/consensus.py --pages 50 --report
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

import layout
import targets
from readings import available_readings

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
PAGES = PROJECT / "data" / "pages"
OUT = OCR / "consensus"

IA_OFFSET = -2
GEOMETRY = ("ia", "300dpi", "spa_old-cat-lat", "psm3")
GEOMETRY_ENGINE = "tess-ia-300dpi-spa_old-cat-lat-psm3"
GEOMETRY_BNE = ("bne", "400dpi", "spa_old", "psm3")
GEOMETRY_BNE_ENGINE = "tess-bne-400dpi-spa_old-psm3"

SCAN_HEALTH = PROJECT / "data" / "scan_health.json"

# The production panel: one engine per family and scan. Two variants of the same
# engine over the same image would vote together and inflate unanimity without
# adding evidence, and unanimity is what the accept rule rests on.
PANEL = [
    "abbyy-bne",
    "abbyy-ia",
    "tess-ia-300dpi-spa_old-cat-lat-psm3",
    "tess-bne-400dpi-spa_old-psm3",
    "vision-bne-400dpi-corr",
    "vision-ia-300dpi-corr",
]

# The book-specific Kraken model, when it has been trained and run. Kept out of
# PANEL by default: adding an engine changes every stratum, and the 550
# adjudications are keyed to the six-engine draw.
KRAKEN_ENGINE = "kraken-cronicon"
PADDLE_ENGINE = "paddle-ppocrv6"

CONTEXT_TOKENS = 3

# Running heads have to be dropped by content, not by position. layout.py strips
# a fixed band off the top, but the two scans crop their margins differently: on
# the BNE leaves the head sits at y≈0.082 and the first body line at 0.093, on the
# Internet Archive leaves the head is at 0.094 and the body at 0.11. No single
# fraction separates them on both, so the band strips the head from the BNE
# engines and not from the IA ones -- and the panel then dutifully votes on
# whether "MAYORICENSE." is there at all.
HEADER_BAND = 0.22
HEADER_LINE = re.compile(
    r"^\s*[\d\W]*\s*(MAYORICENSE|CRONICON|INTRODUCCION)\.?\s*[\d\W]*\s*$",
    re.IGNORECASE)


def is_running_head(line_text: str, line_bbox: list[float]) -> bool:
    return bool(line_bbox[1] < HEADER_BAND and HEADER_LINE.match(line_text))


# A gutter, in fractions of the page width. Words inside a line sit about 0.0066
# apart at this typography; the space between two columns of a Jurats table is
# five times that. Splitting on it is off by default and exists for the table
# leaves alone -- see --split-gutter.
GUTTER_GAP = 0.025


def split_gutters(words: list[dict], gap: float) -> list[list[dict]]:
    """Cut a line where a gap in it is too wide to be a space.

    Tesseract reads the dense Jurats tables as if the columns were one column:
    leaf 312 opens with `Pedro Descatlar. Alfonso`, one line box running from
    x 0.10 to 0.81 across the gutter. That is not only wrong text order -- it
    also hides the column boundary from `layout.find_columns`, which refuses a
    boundary that more than a tenth of the lines cross, so the merged lines
    prevent the detection that would have separated them. Cutting on the gap
    breaks the circle using geometry that is already on disk.
    """
    runs = [[words[0]]]
    for previous, word in zip(words, words[1:]):
        if word["bbox"][0] - previous["bbox"][2] > gap:
            runs.append([])
        runs[-1].append(word)
    return runs


def tesseract_words(pdf_page: int, geometry=GEOMETRY,
                    gutter: float = 0.0) -> list[dict]:
    """Words with normalised boxes, in the shared layout reading order."""
    scan, dpi, lang, psm = geometry
    tsv = OCR / "tesseract" / f"{scan}_p{pdf_page:04d}_{dpi}_{lang}_{psm}.tsv"
    if not tsv.exists():
        return []
    png = (PAGES / "ia" / f"leaf{pdf_page + IA_OFFSET:04d}_{dpi}.png"
           if scan == "ia" else PAGES / "bne" / f"p{pdf_page:04d}_{dpi}.png")
    if not png.exists():
        return []
    with Image.open(png) as im:
        width, height = im.size

    by_line: dict[tuple, list[dict]] = defaultdict(list)
    with tsv.open(encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row.get("level") != "5":
                continue
            text = (row.get("text") or "").strip()
            if not text:
                continue
            left, top = int(row["left"]), int(row["top"])
            by_line[(row["block_num"], row["par_num"], row["line_num"])].append({
                "text": text,
                "bbox": [left / width, top / height,
                         (left + int(row["width"])) / width,
                         (top + int(row["height"])) / height],
            })

    line_boxes = []
    segments: dict[tuple, list[dict]] = {}
    for key, words in by_line.items():
        words.sort(key=lambda w: w["bbox"][0])
        runs = split_gutters(words, gutter) if gutter else [words]
        for n, run in enumerate(runs):
            segments[(*key, n)] = run
            line_boxes.append(((*key, n), layout.Line(
                " ".join(w["text"] for w in run),
                min(w["bbox"][0] for w in run), min(w["bbox"][1] for w in run),
                max(w["bbox"][2] for w in run), max(w["bbox"][3] for w in run))))

    by_line = segments
    key_by_line = {id(ln): key for key, ln in line_boxes}
    ordered, _ = layout.order([ln for _key, ln in line_boxes])

    out: list[dict] = []
    for ln in ordered:
        for word in by_line[key_by_line[id(ln)]]:
            word["line_bbox"] = [ln.x0, ln.y0, ln.x1, ln.y1]
            word["line_text"] = ln.text
            out.append(word)
    return out


def abbyy_words(path: Path, gutter: float = 0.0) -> list[dict]:
    """Word geometry from either ABBYY layer, both of which store it the same way.

    An alternative source of geometry for leaves where Tesseract's segmentation
    fails outright. On the annotated Jurats lists it does not merely merge
    columns: on leaf 115 Tesseract returns nothing at all right of x 0.47, so the
    whole column of notes on which manuscript gives which name is simply absent
    from the panel. Both ABBYY layers read that leaf; the BNE one reads it best,
    numbered names, `AÑO 1312.` labels, notes and all, out to x 0.94.

    This is still not a generative step. It changes which boxes the six
    recognisers are asked to vote on, and nothing about how they vote.
    """
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    width = data["page_width"]
    height = data["page_height"]

    line_boxes = []
    segments: dict[int, list[dict]] = {}
    for line in data["lines"]:
        words = [{"text": w["text"].strip(),
                  "bbox": [w["bbox"][0] / width, w["bbox"][1] / height,
                           w["bbox"][2] / width, w["bbox"][3] / height]}
                 for w in line["words"] if w["text"].strip()]
        if not words:
            continue
        words.sort(key=lambda w: w["bbox"][0])
        for run in (split_gutters(words, gutter) if gutter else [words]):
            segments[len(line_boxes)] = run
            line_boxes.append((len(line_boxes), layout.Line(
                " ".join(w["text"] for w in run),
                min(w["bbox"][0] for w in run), min(w["bbox"][1] for w in run),
                max(w["bbox"][2] for w in run), max(w["bbox"][3] for w in run))))

    key_by_line = {id(ln): key for key, ln in line_boxes}
    ordered, _ = layout.order([ln for _key, ln in line_boxes])

    out: list[dict] = []
    for ln in ordered:
        for word in segments[key_by_line[id(ln)]]:
            word["line_bbox"] = [ln.x0, ln.y0, ln.x1, ln.y1]
            word["line_text"] = ln.text
            out.append(word)
    return out


def tesseract_bne_words(pdf_page: int, gutter: float = 0.0) -> list[dict]:
    """Word boxes off the BNE scan, for the leaves where the IA one is defective."""
    return tesseract_words(pdf_page, geometry=GEOMETRY_BNE, gutter=gutter)


def abbyy_ia_words(pdf_page: int, gutter: float = 0.0) -> list[dict]:
    return abbyy_words(OCR / "abbyy_ia" / f"ia_p{pdf_page:04d}.json", gutter)


def abbyy_bne_words(pdf_page: int, gutter: float = 0.0) -> list[dict]:
    return abbyy_words(OCR / "abbyy_bne" / f"bne_p{pdf_page:04d}.json", gutter)


GEOMETRIES = {"tesseract": (tesseract_words, GEOMETRY_ENGINE),
              "tesseract-bne": (tesseract_bne_words, GEOMETRY_BNE_ENGINE),
              "abbyy-ia": (abbyy_ia_words, "abbyy-ia"),
              "abbyy-bne": (abbyy_bne_words, "abbyy-bne")}

# Each recogniser family reads both scans, so a leaf where one scan is unreadable
# can be voted on the other without changing the size of the panel. scan_health.py
# decides which leaves those are; this is only the correspondence.
SCAN_TWIN = {
    "abbyy-ia": "abbyy-bne",
    "tess-ia-300dpi-spa_old-cat-lat-psm3": "tess-bne-400dpi-spa_old-psm3",
    "vision-ia-300dpi-corr": "vision-bne-400dpi-corr",
}
SCAN_TWIN.update({bne: ia for ia, bne in SCAN_TWIN.items()})


def adjudicated_leaves() -> set[int]:
    """Leaves that carry adjudicated positions, so must not be renumbered."""
    out: set[int] = set()
    for path in sorted((PROJECT / "data" / "adjudication").glob("sample*.json")):
        out |= {x["pdf_page"] for x in json.loads(path.read_text())["sample"]}
    return out


def scan_of(engine: str) -> str | None:
    """Which scan an engine reads, or None for one that only exists on the IA."""
    if "-bne" in engine:
        return "bne"
    if "-ia" in engine:
        return "ia"
    return None


def scan_adjusted(panel: list[str], geometry: str, prefer: str
                  ) -> tuple[list[str], str]:
    """Swap the panel onto the scan that is legible on this leaf.

    Only engines that have a twin on the other scan move. PaddleOCR and Kraken
    read the Internet Archive images alone, so on a leaf where that scan is
    smeared they stay in the panel and stay wrong -- which is the honest outcome:
    the vote is over what the recognisers saw, and three of them saw a blur. What
    this buys is that the other three are no longer looking at the same blur.

    Dropping them instead would leave a panel of three, and the BNE-only trio is
    the one configuration with a *measured* shared error (2 wrong in 386 unanimous
    positions), so it cannot carry the accept rule. Six imperfect votes beat three
    good ones when unanimity is the guarantee.
    """
    if prefer not in ("ia", "bne"):
        return panel, geometry

    def move(engine: str) -> str:
        twin = SCAN_TWIN.get(engine)
        if twin is None or scan_of(engine) == prefer:
            return engine                  # no twin, or already on the good scan
        if twin in panel:
            return engine                  # its twin is a voter too; leave both
        return twin

    swapped = [move(e) for e in panel]
    if prefer == "bne" and geometry == "tesseract":
        geometry = "tesseract-bne"
    elif prefer == "ia" and geometry == "tesseract-bne":
        geometry = "tesseract"
    return swapped, geometry


def project(reference: list[str], other: list[str]) -> list[str | None]:
    """Map another engine's token stream onto the reference positions.

    Tokens the other engine has in excess are appended to the preceding slot, so
    a merge shows up as a mismatch rather than vanishing into the alignment.
    """
    out: list[str | None] = [None] * len(reference)
    matcher = SequenceMatcher(a=reference, b=other, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = other[j1 + k]
        elif tag == "replace":
            span = other[j1:j2]
            for k in range(i1, i2):
                idx = k - i1
                out[k] = span[idx] if idx < len(span) else ""
            if len(span) > (i2 - i1) and i2 > i1:
                out[i2 - 1] = " ".join(span[i2 - i1 - 1:])
        elif tag == "delete":
            for k in range(i1, i2):
                out[k] = ""
        elif tag == "insert" and i1 > 0:
            extra = " ".join(other[j1:j2])
            out[i1 - 1] = f"{out[i1 - 1]} {extra}" if out[i1 - 1] else extra
    return out


def engine_lines(pdf_page: int, engine: str) -> list[tuple[list[float], str]] | None:
    """An engine's positioned lines, as build_ordered.py left them."""
    path = OCR / "ordered" / f"{engine}_p{pdf_page:04d}.json"
    if not path.exists():
        return None
    return [(ln["bbox"], ln["text"])
            for ln in json.loads(path.read_text())["lines"]]


# How far the two scans' crops can differ vertically, and at what resolution to
# search. A line is ~0.012 of the page tall and the BNE and IA crops sit about
# 0.016 apart, so the shift is more than a whole line and cannot be ignored.
OFFSET_RANGE = 0.030
OFFSET_STEP = 0.001
# Below this fraction of reference lines matched, the two are not describing the
# same page well enough to align by geometry, and the page-wide alignment is used.
MIN_LINE_COVERAGE = 0.5


def vertical_offset(ref_boxes: list[tuple], lines: list[tuple]) -> tuple[float, int]:
    """The shift that puts the most engine lines inside a reference line.

    A shift, not a fit. An earlier version fitted scale as well and was ten times
    worse than doing nothing: the two scans differ by where the page was cropped,
    not by how much it was stretched, and a fitted scale turns a constant error
    into one that grows down the leaf.
    """
    best, best_matched = 0.0, -1
    steps = int(OFFSET_RANGE / OFFSET_STEP)
    for k in range(-steps, steps + 1):
        shift = k * OFFSET_STEP
        matched = 0
        for x0, y0, x1, y1 in ref_boxes:
            for bbox, _text in lines:
                centre = (bbox[1] + bbox[3]) / 2
                if y0 + shift <= centre <= y1 + shift and \
                        min(x1, bbox[2]) > max(x0, bbox[0]):
                    matched += 1
                    break
        if matched > best_matched:
            best_matched, best = matched, shift
    return best, best_matched


def project_by_line(words: list[dict], pdf_page: int, engine: str
                    ) -> list[str | None] | None:
    """Align an engine to the reference one printed line at a time.

    `project` matches two flat token streams over the whole leaf, which works
    while the engines agree what order the leaf is read in. Where they do not --
    the tables, the annotated Jurats lists, anything with a column the engines
    split differently -- no token alignment can recover, because the streams are
    not permutations of each other in any local sense. Leaf 115 is the extreme
    case: every engine reads the names, and under a page-wide alignment they land
    in the notes column's slots and the names come back empty.

    Aligning by geometry removes order from the question: a reference line
    competes only with the engine text that overlaps it on the page.

    Returns None when the two geometries are too far apart to match, so the
    caller can fall back rather than align against noise.
    """
    lines = engine_lines(pdf_page, engine)
    if not lines:
        return None

    groups: dict[tuple, list[int]] = {}
    for i, word in enumerate(words):
        groups.setdefault(tuple(word["line_bbox"]), []).append(i)
    shift, matched = vertical_offset(list(groups), lines)
    if matched < MIN_LINE_COVERAGE * len(groups):
        return None

    out: list[str | None] = [None] * len(words)
    taken: set[int] = set()
    for box, indices in groups.items():
        x0, y0, x1, y1 = box
        candidates = []
        for j, (bbox, text) in enumerate(lines):
            centre = (bbox[1] + bbox[3]) / 2
            if y0 + shift <= centre <= y1 + shift and \
                    min(x1, bbox[2]) > max(x0, bbox[0]):
                candidates.append((bbox[0], j, text))
        candidates.sort()
        tokens: list[str] = []
        for _x, j, text in candidates:
            if j in taken:          # one engine line answers one reference line
                continue
            taken.add(j)
            tokens += text.split()
        projected = project([words[i]["text"] for i in indices], tokens)
        for k, i in enumerate(indices):
            out[i] = projected[k]
    return out


def stratum_of(votes: Counter, panel_size: int) -> str:
    top = votes.most_common(1)[0][1]
    if sum(1 for v in votes.values() if v == top) > 1:
        return "tie"
    return f"{top}of{panel_size}"


def grade(stratum: str, panel_size: int) -> str:
    """The four tiers the accept rule and the review queue are defined on."""
    if stratum == f"{panel_size}of{panel_size}":
        return "unanimous"
    if stratum == f"{panel_size - 1}of{panel_size}":
        return "one-dissent"
    if stratum == f"{panel_size - 2}of{panel_size}":
        return "two-dissent"
    return "contested"


def collect(pdf_page: int, panel: list[str] = None, gutter: float = 0.0,
            geometry: str = "tesseract", align: str = "page") -> list[dict]:
    """Every token position on the leaf, with what each engine read there."""
    panel = panel or PANEL
    source, engine = GEOMETRIES[geometry]
    words = source(pdf_page, gutter=gutter)
    if not words:
        return []
    reference = [w["text"] for w in words]
    readings = available_readings(pdf_page)
    projected: dict[str, list[str | None]] = {}
    for key, text in readings.items():
        if key == engine:
            continue
        by_line = (project_by_line(words, pdf_page, key)
                   if align == "line" else None)
        projected[key] = (by_line if by_line is not None
                          else project(reference, text.split()))
    projected[engine] = list(reference)

    loci = []
    for i, word in enumerate(words):
        if is_running_head(word.get("line_text", ""), word["line_bbox"]):
            continue
        variants = {k: projected[k][i] for k in projected}
        votes = Counter(variants[k] for k in panel
                        if variants.get(k) is not None)
        if not votes:
            continue
        stratum = stratum_of(votes, len(panel))
        winner = votes.most_common(1)[0][0]
        loci.append({
            "pdf_page": pdf_page,
            "index": i,
            "stratum": stratum,
            "grade": grade(stratum, len(panel)),
            "winner": winner,
            "bbox": word["bbox"],
            "line_bbox": word["line_bbox"],
            "context": " ".join(reference[max(0, i - CONTEXT_TOKENS):
                                          i + CONTEXT_TOKENS + 1]),
            "variants": variants,
        })
    return loci


def run_one(job) -> tuple[int, Counter, int]:
    """One leaf.

    The panel and the output directory travel *in the job*, not in module
    globals. Worker processes are spawned on macOS, so they re-import this
    module and would silently see the defaults -- which is exactly what happened
    once: `--with-kraken` produced a seven-engine banner, an empty consensus7
    directory, and a six-engine result written over the six-engine result.
    """
    pdf_page, panel, out_dir, gutter, geometry, prefer, align = job
    panel, geometry = scan_adjusted(panel, geometry, prefer)
    loci = collect(pdf_page, panel, gutter, geometry, align)
    if not loci:
        return pdf_page, Counter(), 0
    grades = Counter(locus["grade"] for locus in loci)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"p{pdf_page:04d}.json").write_text(json.dumps({
        "pdf_page": pdf_page, "panel": panel, "geometry": geometry,
        "align": align,
        # Recorded on every leaf, not only the swapped ones, so that a reader of
        # a single file can tell whether it was voted on the default panel
        # without having to know which leaves the health file names.
        "scan": prefer or "default",
        "tokens": len(loci), "grades": dict(grades), "loci": loci,
    }, ensure_ascii=False), encoding="utf-8")
    return pdf_page, grades, len(loci)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="all",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--split-gutter", action="store_true",
                    help="cut reference lines at a column gap; for the dense "
                         "table leaves, and writes to its own directory so the "
                         "book's consensus and the frozen sample are untouched")
    ap.add_argument("--geometry", default="tesseract", choices=list(GEOMETRIES),
                    help="which engine supplies the line and word boxes the "
                         "panel votes on")
    ap.add_argument("--align", default="page", choices=["page", "line"],
                    help="'page' matches each engine's whole token stream against "
                         "the reference; 'line' matches printed line by printed "
                         "line, using the boxes, so the engines need not agree on "
                         "the reading order. Measured: much better where the "
                         "layout is contested (leaf 453 36.1%%->6.4%%, leaf 312 "
                         "38.7%%->11.1%%) and worse on ordinary prose, where the "
                         "page-wide match already works and this one costs "
                         "unanimity. Not the default; see docs/OCR_BENCHMARK.md")
    ap.add_argument("--per-leaf-scan", action="store_true",
                    help="on the leaves data/scan_health.json marks, swap the "
                         "panel onto the scan that is legible there. Four leaves "
                         "(93, 94, 97, 98) are smeared on the Internet Archive "
                         "images and pristine on the BNE ones, and carry 1 909 "
                         "of the contested positions between them")
    ap.add_argument("--out", default=None,
                    help="output directory, relative to the project")
    ap.add_argument("--swap-kraken", action="store_true",
                    help="replace the weakest ABBYY with the book-specific model")
    ap.add_argument("--swap-paddle", action="store_true",
                    help="replace the weakest Tesseract with PaddleOCR, keeping "
                         "six voters: better text without a seventh voice "
                         "breaking agreements that were already right")
    ap.add_argument("--with-paddle", action="store_true",
                    help="add PaddleOCR PP-OCRv6 as a seventh voter, writing to "
                         "its own directory so the six-engine consensus the "
                         "adjudications describe stays intact")
    ap.add_argument("--with-kraken", action="store_true",
                    help="add the book-specific model as a seventh voter and "
                         "write to a separate directory, so the six-engine "
                         "consensus the adjudications describe stays intact")
    args = ap.parse_args()

    panel = list(PANEL)
    suffix = ""
    if args.with_kraken:
        panel.append(KRAKEN_ENGINE)
        suffix += "_kraken"
    if args.with_paddle:
        panel.append(PADDLE_ENGINE)
        suffix += "_paddle"
    if args.swap_paddle:
        panel = [e for e in panel if e != "tess-bne-400dpi-spa_old-psm3"]
        panel.append(PADDLE_ENGINE)
        suffix += "_swap"
    if args.swap_kraken:
        panel = [e for e in panel if e != "abbyy-bne"]
        panel.append(KRAKEN_ENGINE)
        suffix += "_swapk"
    out_dir = OCR / (f"consensus{len(panel)}{suffix}" if suffix else "consensus")
    # Changing the geometry changes every stratum on the leaf, which would
    # renumber the frozen sample and orphan its adjudications. A gutter run
    # therefore never writes over the book's consensus.
    gutter = GUTTER_GAP if args.split_gutter else 0.0
    if args.out:
        out_dir = PROJECT / args.out
    elif gutter:
        out_dir = OCR / f"consensus{len(panel)}{suffix}_gutter"

    prefer: dict[int, str] = {}
    if args.per_leaf_scan:
        if not SCAN_HEALTH.exists():
            raise SystemExit(f"{SCAN_HEALTH} not found -- "
                             f"run scripts/scan_health.py first")
        health = json.loads(SCAN_HEALTH.read_text())
        prefer = {int(k): v for k, v in health["prefer"].items()}
        # Swapping the scan changes the geometry, which renumbers the leaf and
        # would orphan any adjudication on it. It happens that no flagged leaf is
        # an adjudicated one -- but "it happens that" is not a guarantee, and the
        # next time scan_health.py runs it may flag a different leaf.
        clash = sorted(set(prefer) & adjudicated_leaves())
        if clash:
            raise SystemExit(
                f"leaves {clash} carry adjudications and would be renumbered by "
                f"a scan swap.\nRe-key data/ground_truth/adjudicated.tsv by word "
                f"box first, or exclude them from data/scan_health.json.")

    pages = targets.resolve(args.pages)
    print(f"{len(pages)} leaves, panel of {len(panel)}, {args.workers} workers")
    print(f"  {', '.join(panel)}")
    if prefer:
        # Named out loud rather than applied silently: a leaf voted on a
        # different set of engines is a different measurement, and anyone reading
        # the queue afterwards has to know which leaves those were.
        for page in sorted(p for p in prefer if p in set(pages)):
            swapped, geo = scan_adjusted(panel, args.geometry, prefer[page])
            moved = [f"{a}->{b}" for a, b in zip(panel, swapped) if a != b]
            print(f"  p{page:4d} reads the {prefer[page].upper()} scan"
                  + (f": {', '.join(moved)}, geometry {geo}" if moved
                     else " (panel already there)"))
    print()

    t0 = time.time()
    totals = Counter()
    tokens = 0
    empty: list[int] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_one,
                               (page, panel, str(out_dir), gutter, args.geometry,
                                prefer.get(page), args.align))
                   for page in pages]
        for n, future in enumerate(as_completed(futures), 1):
            page, grades, count = future.result()
            if not count:
                empty.append(page)
            totals += grades
            tokens += count
            if n % 100 == 0 or n == len(pages):
                print(f"  [{n:4d}/{len(pages)}]  {tokens:,} tokens  "
                      f"{time.time()-t0:.0f}s")

    print(f"\n{tokens:,} token positions over {len(pages) - len(empty)} leaves")
    for name in ["unanimous", "one-dissent", "two-dissent", "contested"]:
        print(f"  {name:12} {totals[name]:7,}  {totals[name]/tokens:6.1%}")

    review = totals["contested"]
    print(f"\nReview queue at the recommended rule (contested only): "
          f"{review:,} decisions")
    if empty:
        print(f"\n{len(empty)} leaves produced nothing -- missing OCR output: "
              f"{empty[:12]}{' ...' if len(empty) > 12 else ''}")
    print(f"\n-> {out_dir}")


if __name__ == "__main__":
    main()
