"""Read the book with the fine-tuned Kraken model, as a seventh engine.

The model is given the same line boxes the rest of the pipeline uses -- the ones
Tesseract's TSV supplies, ordered by scripts/layout.py -- rather than its own
segmentation. That is deliberate: the panel's whole design rests on every engine
being compared at the same positions, and letting this one segment differently
would reintroduce the layout-analysis noise that the first disagreement survey
was drowning in.

Line images are cropped from the Internet Archive scan at native ~630 dpi, the
same source and geometry the model was trained on.

Usage:
  nix develop --command .venv-htr/bin/python scripts/ocr_kraken.py --pages pilot
  .venv-htr/bin/python scripts/ocr_kraken.py --pages all --model models/cronicon_best.mlmodel
"""
from __future__ import annotations

import argparse
import io
import json
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
CONSENSUS = PROJECT / "data" / "ocr" / "consensus"
JP2_ZIP = PROJECT / "data" / "ia" / "jp2.zip"
OUT = PROJECT / "data" / "ocr" / "kraken"

IA_OFFSET = -2
STEM = "Cronicon_Mayoricense_Campaner"
PAD_Y = 0.0025
PAD_X = 0.002


def page_lines(pdf_page: int) -> list[dict]:
    """Distinct line boxes on the leaf, in reading order, from the consensus."""
    path = CONSENSUS / f"p{pdf_page:04d}.json"
    if not path.exists():
        return []
    seen: dict[tuple, None] = {}
    for locus in json.loads(path.read_text())["loci"]:
        seen.setdefault(tuple(locus["line_bbox"]), None)
    return [{"bbox": list(bbox)} for bbox in seen]


def leaf_image(pdf_page: int) -> Image.Image | None:
    with zipfile.ZipFile(JP2_ZIP) as archive:
        try:
            blob = archive.read(f"{STEM}_jp2/{STEM}_{pdf_page + IA_OFFSET:04d}.jp2")
        except KeyError:
            return None
    image = Image.open(io.BytesIO(blob))
    return image.convert("L") if image.mode != "L" else image


def recognise_page(model, pdf_page: int) -> list[dict] | None:
    lines = page_lines(pdf_page)
    if not lines:
        return None
    image = leaf_image(pdf_page)
    if image is None:
        return None
    width, height = image.size

    from kraken.lib.xml import XMLPage  # noqa: F401  (import check)
    from kraken import rpred
    from kraken.containers import BBoxLine, Segmentation

    boxes = []
    for n, line in enumerate(lines):
        x0, y0, x1, y1 = line["bbox"]
        box = (max(0, int((x0 - PAD_X) * width)),
               max(0, int((y0 - PAD_Y) * height)),
               min(width, int((x1 + PAD_X) * width)),
               min(height, int((y1 + PAD_Y) * height)))
        boxes.append(BBoxLine(id=f"line_{n}", bbox=box))

    segmentation = Segmentation(type="bbox", imagename=f"p{pdf_page:04d}",
                                text_direction="horizontal-lr",
                                script_detection=False, lines=boxes)
    predictions = list(rpred.rpred(model, image, segmentation, pad=16))

    out = []
    for line, record in zip(lines, predictions):
        out.append({"text": str(record).strip(), "bbox": line["bbox"]})
    return out


_MODEL = None


def _worker(job):
    """One leaf. The model is loaded once per worker process and reused."""
    global _MODEL
    model_path, pdf_page, out_dir = job
    if _MODEL is None:
        from kraken.lib import models
        try:
            from kraken.models.loaders import load_models
            _MODEL = models.TorchSeqRecognizer(load_models(model_path)[0])
        except Exception:
            _MODEL = models.load_any(model_path)
    dest = Path(out_dir) / f"ia_p{pdf_page:04d}.json"
    if dest.exists() and dest.stat().st_size > 0:
        return pdf_page, -1
    lines = recognise_page(_MODEL, pdf_page)
    if lines is None:
        return pdf_page, 0
    dest.write_text(json.dumps({"pdf_page": pdf_page, "lines": lines},
                               ensure_ascii=False), encoding="utf-8")
    dest.with_suffix(".txt").write_text(
        "\n".join(ln["text"] for ln in lines), encoding="utf-8")
    return pdf_page, len(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="pilot")
    ap.add_argument("--model", default="models/cronicon_best.mlmodel")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", default=None,
                    help="output directory; defaults to data/ocr/kraken. Use a "
                         "separate one to keep an unfine-tuned baseline apart.")
    args = ap.parse_args()

    global OUT
    if args.out:
        OUT = PROJECT / args.out

    import sys
    sys.path.insert(0, str(PROJECT / "scripts"))
    import targets

    # kraken 7 writes safetensors, which the legacy `models.load_any` cannot
    # read -- it only knows the CoreML container. The new loaders module handles
    # both, so try it first and keep the old path for downloaded .mlmodel files.
    OUT.mkdir(parents=True, exist_ok=True)
    pages = targets.resolve(args.pages)
    print(f"{len(pages)} leaves with {Path(args.model).name}, "
          f"{args.workers} workers\n")

    t0 = time.time()
    done = skipped = 0
    jobs = [(args.model, page, str(OUT)) for page in pages]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_worker, job) for job in jobs]
        for n, future in enumerate(as_completed(futures), 1):
            _page, count = future.result()
            skipped += count < 0
            done += count > 0
            if n % 50 == 0 or n == len(jobs):
                rate = n / max(1e-9, time.time() - t0)
                print(f"  [{n:4d}/{len(jobs)}]  {done} read, {skipped} cached, "
                      f"{rate:.1f} leaves/s")

    print(f"\nDone in {time.time()-t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
