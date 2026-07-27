"""Turn the unanimous consensus lines into a Kraken training set.

The panel agrees on every word of 8 849 printed lines. Those lines are, as far as
550 adjudications could tell, correct: no counter-example was found in 360
unanimous positions, which bounds their error at 0.83%. That is clean enough to
train on, and it costs no human time -- the labels are a by-product of the
consensus we already ran.

Line images are cropped from the Internet Archive scan at its native ~630 dpi,
not from the 300 dpi renders the engines read: a recogniser is trained once and
should see the best pixels available, and at native resolution a printed line is
~100 px tall, which is what Kraken's architecture wants.

Two exclusions matter for honesty:

* The twelve pilot pages are held out entirely. They carry the 550 adjudicated
  positions, and they are the only ground truth not derived from the consensus
  itself -- training on them would make the evaluation circular.
* The validation split is by *leaf*, not by line. Lines from one leaf share paper,
  inking and wear, so a random line split would leak and flatter the model.

Usage:
  python scripts/build_htr_dataset.py
  python scripts/build_htr_dataset.py --val-fraction 0.1
"""
from __future__ import annotations

import argparse
import io
import json
import random
import unicodedata
import zipfile
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

from pilot_pages import PAGES as PILOT_PAGES

PROJECT = Path(__file__).resolve().parent.parent
CONSENSUS = PROJECT / "data" / "ocr" / "consensus"
JP2_ZIP = PROJECT / "data" / "ia" / "jp2.zip"
OUT = PROJECT / "data" / "htr"

IA_OFFSET = -2
STEM = "Cronicon_Mayoricense_Campaner"

MIN_TOKENS = 3          # a two-word line teaches almost nothing
MIN_LINE_HEIGHT = 0.006  # normalised; rejects specks the layout took for a line
MAX_LINE_HEIGHT = 0.030  # rejects two lines merged into one box
PAD_Y = 0.0025           # a little air above and below the glyphs
PAD_X = 0.002
SEED = 20260727


def clean_lines(page_data: dict) -> list[dict]:
    """Lines where every token is unanimous, with their text and box."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for locus in page_data["loci"]:
        grouped[tuple(locus["line_bbox"])].append(locus)

    out = []
    for bbox, loci in grouped.items():
        if len(loci) < MIN_TOKENS:
            continue
        if not all(l["grade"] == "unanimous" for l in loci):
            continue
        height = bbox[3] - bbox[1]
        if not MIN_LINE_HEIGHT <= height <= MAX_LINE_HEIGHT:
            continue
        loci.sort(key=lambda l: l["index"])
        text = " ".join(l["winner"] for l in loci).strip()
        if not text:
            continue
        out.append({"bbox": list(bbox),
                    "text": unicodedata.normalize("NFC", text)})
    return out


def render_page(job: tuple[int, list[dict], str]) -> tuple[int, int]:
    pdf_page, lines, split = job
    leaf = pdf_page + IA_OFFSET
    with zipfile.ZipFile(JP2_ZIP) as archive:
        name = f"{STEM}_jp2/{STEM}_{leaf:04d}.jp2"
        try:
            blob = archive.read(name)
        except KeyError:
            return pdf_page, 0
    image = Image.open(io.BytesIO(blob))
    if image.mode != "L":
        image = image.convert("L")
    width, height = image.size

    target = OUT / split
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for n, line in enumerate(lines):
        x0, y0, x1, y1 = line["bbox"]
        box = (max(0, int((x0 - PAD_X) * width)),
               max(0, int((y0 - PAD_Y) * height)),
               min(width, int((x1 + PAD_X) * width)),
               min(height, int((y1 + PAD_Y) * height)))
        if box[2] - box[0] < 40 or box[3] - box[1] < 20:
            continue
        stem = target / f"p{pdf_page:04d}_l{n:03d}"
        image.crop(box).save(stem.with_suffix(".png"))
        stem.with_suffix(".gt.txt").write_text(line["text"] + "\n",
                                               encoding="utf-8")
        written += 1
    return pdf_page, written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--val-fraction", type=float, default=0.1)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    if not JP2_ZIP.exists():
        raise SystemExit("data/ia/jp2.zip missing -- run fetch_ia.py --images")

    held_out = set(PILOT_PAGES)
    pages: dict[int, list[dict]] = {}
    for path in sorted(CONSENSUS.glob("p*.json")):
        data = json.loads(path.read_text())
        if data["pdf_page"] in held_out:
            continue
        lines = clean_lines(data)
        if lines:
            pages[data["pdf_page"]] = lines

    ordered = sorted(pages)
    rng = random.Random(SEED)
    rng.shuffle(ordered)
    cut = max(1, round(len(ordered) * args.val_fraction))
    split_of = {page: ("val" if i < cut else "train")
                for i, page in enumerate(ordered)}

    total_lines = sum(len(v) for v in pages.values())
    print(f"{len(pages)} leaves contribute {total_lines:,} unanimous lines")
    print(f"held out entirely: {len(held_out)} pilot pages "
          f"(they carry the adjudicated ground truth)")
    print(f"split by leaf: {len(ordered)-cut} train / {cut} val\n")

    jobs = [(page, lines, split_of[page]) for page, lines in pages.items()]
    written = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(render_page, job) for job in jobs]
        for n, future in enumerate(as_completed(futures), 1):
            _page, count = future.result()
            written += count
            if n % 100 == 0 or n == len(jobs):
                print(f"  [{n:4d}/{len(jobs)}]  {written:,} line images")

    for split in ("train", "val"):
        n = len(list((OUT / split).glob("*.png")))
        chars = sum(len(p.read_text(encoding="utf-8").strip())
                    for p in (OUT / split).glob("*.gt.txt"))
        print(f"\n{split:5}  {n:6,} lines  {chars:9,} characters")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
