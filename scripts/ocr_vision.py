"""Apple Vision readings of the pilot pages.

Uses the system Vision framework through pyobjc -- VNRecognizeTextRequest at the
accurate recognition level, which runs on the Neural Engine of the M-series chip.
No network, no API cost, no tokens: it is a classical recogniser, not a generative
model, so it cannot invent text that is not on the page.

Adapted from ../nomenclators/madoz/scripts/apple_vision_reocr_all.py, which is the
fleet's working version of this.

One caveat the benchmark has to account for: Vision reports each recognised line
with a bounding box but concatenates nothing itself -- reading order across two
columns is our problem, not its. We therefore keep the boxes and sort into columns
ourselves rather than trusting observation order.

Usage:
  python scripts/ocr_vision.py                       # both scans
  python scripts/ocr_vision.py --scan ia --language-correction off
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import targets

PROJECT = Path(__file__).resolve().parent.parent
PAGES = PROJECT / "data" / "pages"
OUT = PROJECT / "data" / "ocr" / "vision"

IA_OFFSET = -2

# (scan, dpi) -- Vision normalises internally, so resolution matters far less to
# it than to Tesseract; we still test both scans to isolate the source image.
VARIANTS = [("bne", 400), ("ia", 300)]


def image_for(scan: str, pdf_page: int, dpi: int) -> Path:
    if scan == "bne":
        return PAGES / "bne" / f"p{pdf_page:04d}_{dpi}dpi.png"
    return PAGES / "ia" / f"leaf{pdf_page + IA_OFFSET:04d}_{dpi}dpi.png"


def recognise(img_path: Path, correction: bool) -> list[dict]:
    """Return one record per recognised line: text, confidence, normalised box."""
    from Cocoa import NSURL
    from Foundation import NSDictionary
    import Quartz
    import Vision

    url = NSURL.fileURLWithPath_(str(img_path))
    source = Quartz.CGImageSourceCreateWithURL(url, None)
    if source is None:
        return []
    cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
    if cg_image is None:
        return []

    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
        cg_image, NSDictionary.dictionary())
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(correction)
    request.setRecognitionLanguages_(["es-ES"])

    ok, _err = handler.performRequests_error_([request], None)
    if not ok:
        return []

    lines = []
    for obs in (request.results() or []):
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        box = obs.boundingBox()
        lines.append({
            "text": candidates[0].string(),
            "confidence": float(candidates[0].confidence()),
            # Vision's origin is bottom-left, normalised 0..1
            "x": float(box.origin.x),
            "y": float(box.origin.y),
            "w": float(box.size.width),
            "h": float(box.size.height),
        })
    return lines


def run_one(job) -> tuple[str, int, float]:
    scan, pdf_page, dpi, correction = job
    suffix = "corr" if correction else "raw"
    name = f"{scan}_p{pdf_page:04d}_{dpi}dpi_{suffix}"
    dest = OUT / f"{name}.json"
    if dest.exists() and dest.stat().st_size > 0:
        return name, -1, 0.0

    t0 = time.time()
    lines = recognise(image_for(scan, pdf_page, dpi), correction)
    dest.write_text(json.dumps(lines, ensure_ascii=False, indent=1))
    # reading order is reconstructed later; this is Vision's own order
    (OUT / f"{name}.txt").write_text(
        "\n".join(ln["text"] for ln in lines), encoding="utf-8")
    return name, len(lines), time.time() - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pages", default="pilot",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--language-correction", choices=["on", "off", "both"],
                    default="both")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    corrections = {"on": [True], "off": [False], "both": [True, False]}[
        args.language_correction]
    pages = targets.resolve(args.pages)
    jobs = [(scan, pdf_page, dpi, corr)
            for scan, dpi in VARIANTS
            for pdf_page in pages
            for corr in corrections]

    print(f"{len(jobs)} jobs, {args.workers} workers\n")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(run_one, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            name, nlines, elapsed = fut.result()
            if n % 8 == 0 or n == len(jobs):
                state = "cached" if nlines < 0 else f"{nlines} lines, {elapsed:.1f}s"
                print(f"  [{n:3d}/{len(jobs)}]  {time.time()-t0:5.1f}s  {name} ({state})")
    print(f"\nDone in {time.time()-t0:.1f}s -> {OUT}")


if __name__ == "__main__":
    main()
