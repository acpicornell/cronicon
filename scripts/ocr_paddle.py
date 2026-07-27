"""Read the book with PaddleOCR's recogniser, as a candidate seventh engine.

PP-OCRv6 is a classical detector/recogniser, not a vision-language model: it
cannot emit text it did not see, which is what qualifies it for this panel at
all. PaddleOCR also ships a VL variant; that one is deliberately not used here.

Only the *recognition* half is used. Line boxes come from the same source as
every other engine, so the panel compares readings of the same regions rather
than each engine's idea of where the lines are.

PaddlePaddle on macOS is CPU-only -- there is no Metal backend for the classical
pipeline -- which is fine at this scale.

Usage:
  .venv-paddle/bin/python scripts/ocr_paddle.py --pages pilot --workers 6
"""
from __future__ import annotations

import argparse
import io
import json
import os
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
CONSENSUS = PROJECT / "data" / "ocr" / "consensus"
JP2_ZIP = PROJECT / "data" / "ia" / "jp2.zip"
OUT = PROJECT / "data" / "ocr" / "paddle"

IA_OFFSET = -2
STEM = "Cronicon_Mayoricense_Campaner"
PAD_Y = 0.0025
PAD_X = 0.002

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

_MODEL = None


def page_lines(pdf_page: int) -> list[dict]:
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
            blob = archive.read(
                f"{STEM}_jp2/{STEM}_{pdf_page + IA_OFFSET:04d}.jp2")
        except KeyError:
            return None
    image = Image.open(io.BytesIO(blob))
    return image.convert("L") if image.mode != "L" else image


def _worker(job) -> tuple[int, int]:
    global _MODEL
    pdf_page, out_dir, model_name = job
    dest = Path(out_dir) / f"ia_p{pdf_page:04d}.json"
    if dest.exists() and dest.stat().st_size > 0:
        return pdf_page, -1

    lines = page_lines(pdf_page)
    image = leaf_image(pdf_page)
    if not lines or image is None:
        return pdf_page, 0

    if _MODEL is None:
        from paddleocr import TextRecognition
        _MODEL = TextRecognition(**({"model_name": model_name} if model_name else {}))

    width, height = image.size
    out = []
    for line in lines:
        x0, y0, x1, y1 = line["bbox"]
        box = (max(0, int((x0 - PAD_X) * width)),
               max(0, int((y0 - PAD_Y) * height)),
               min(width, int((x1 + PAD_X) * width)),
               min(height, int((y1 + PAD_Y) * height)))
        crop = image.crop(box).convert("RGB")
        try:
            results = _MODEL.predict(np.array(crop))
        except Exception:
            results = []
        text = results[0]["rec_text"].strip() if results else ""
        score = float(results[0].get("rec_score", 0.0)) if results else 0.0
        out.append({"text": text, "bbox": line["bbox"], "confidence": score})

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"pdf_page": pdf_page, "lines": out},
                               ensure_ascii=False), encoding="utf-8")
    dest.with_suffix(".txt").write_text(
        "\n".join(ln["text"] for ln in out), encoding="utf-8")
    return pdf_page, len(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="pilot")
    ap.add_argument("--model", default=None,
                    help="recognition model; default is PaddleOCR's own default "
                         "(PP-OCRv6_medium_rec)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(PROJECT / "scripts"))
    import targets

    global OUT
    if args.out:
        OUT = PROJECT / args.out
    OUT.mkdir(parents=True, exist_ok=True)
    pages = targets.resolve(args.pages)
    print(f"{len(pages)} leaves, {args.workers} workers\n")

    t0 = time.time()
    done = skipped = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_worker, (page, str(OUT), args.model))
                   for page in pages]
        for n, future in enumerate(as_completed(futures), 1):
            _page, count = future.result()
            skipped += count < 0
            done += count > 0
            if n % 10 == 0 or n == len(pages):
                print(f"  [{n:4d}/{len(pages)}]  {done} read, {skipped} cached, "
                      f"{n/max(1e-9, time.time()-t0):.2f} leaves/s")

    print(f"\nDone in {time.time()-t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
