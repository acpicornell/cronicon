"""Render the pilot pages of the BNE scan to PNG.

The BNE PDF wraps one JPEG-2000 image per page at ~200 dpi; that is the whole of
the information available from this scan. We therefore extract the embedded image
at its native size rather than letting MuPDF rasterise the page, and produce the
higher-"dpi" variants by explicit Lanczos upscaling. Those variants carry no extra
information -- they exist only because Tesseract's line finder wants a larger
x-height -- and the benchmark reports them as upscales, not as a better scan.

Usage:
  python scripts/render_pages.py                        # pilot pages, native + 2x
  python scripts/render_pages.py --pages all --scales 2 # every text leaf at 400 dpi
"""
from __future__ import annotations

import argparse
import io
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import fitz
from PIL import Image

import targets

PROJECT = Path(__file__).resolve().parent.parent
PDF = PROJECT / "data" / "raw" / "Cronicon-mayoricense.pdf"
OUT = PROJECT / "data" / "pages" / "bne"


def native_dpi(page: fitz.Page, pix_width: int) -> int:
    """dpi implied by an image of pix_width px covering the page width."""
    return round(pix_width / (page.rect.width / 72.0))


def extract(doc: fitz.Document, pno: int) -> tuple[Image.Image, int]:
    page = doc[pno]
    images = page.get_images(full=True)
    if len(images) != 1:
        raise SystemExit(f"page {pno}: expected 1 embedded image, found {len(images)}")
    info = doc.extract_image(images[0][0])
    img = Image.open(io.BytesIO(info["image"]))
    if img.mode != "L":
        img = img.convert("L")
    return img, native_dpi(page, img.width)


def render_one(job: tuple[int, list[float]]) -> tuple[int, int]:
    pno, scales = job
    doc = fitz.open(PDF)
    img, dpi = extract(doc, pno)
    doc.close()

    written = 0
    for scale in scales:
        eff = round(dpi * scale)
        out = OUT / f"p{pno:04d}_{eff}dpi.png"
        if out.exists():
            continue
        im = img
        if scale != 1:
            im = img.resize((round(img.width * scale), round(img.height * scale)),
                            Image.LANCZOS)
        im.save(out, dpi=(eff, eff))
        written += 1
    return pno, written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="pilot",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--scales", type=float, nargs="+", default=[1, 2],
                    help="Upscale factors over the native ~200 dpi. Default: 1 2")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    pages = targets.resolve(args.pages)
    print(f"{len(pages)} leaves x {len(args.scales)} scales, "
          f"{args.workers} workers")

    written = 0
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(render_one, (pno, args.scales)) for pno in pages]
        for n, future in enumerate(as_completed(futures), 1):
            _pno, count = future.result()
            written += count
            if n % 100 == 0 or n == len(pages):
                print(f"  [{n:4d}/{len(pages)}]  {written} images written")


if __name__ == "__main__":
    main()
