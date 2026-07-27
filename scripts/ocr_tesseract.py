"""Tesseract readings of the pilot pages, across the variants worth testing.

Each variant is (scan, dpi, language model, page-segmentation mode). We vary them
one at a time so the benchmark can attribute a difference to a cause: 200 dpi BNE
vs ~630 dpi Internet Archive isolates the scan, spa_old vs spa isolates the
language model, psm 3 vs psm 1 isolates layout analysis on the multi-column pages.

Writes both the plain text (reading order as Tesseract sees it) and the TSV, which
carries the per-word confidence the consensus stage will need.

Run inside the project toolchain so the language set is the pinned one:
  nix develop --command python scripts/ocr_tesseract.py
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import targets

PROJECT = Path(__file__).resolve().parent.parent
PAGES = PROJECT / "data" / "pages"
OUT = PROJECT / "data" / "ocr" / "tesseract"

IA_OFFSET = -2  # IA leaf = BNE pdf page - 2; established by scripts/align_scans.py

# The exploration grid the benchmark compared. Only ever run over the pilot
# pages: fourteen readings of 614 leaves would cost hours to re-answer a settled
# question.
# (scan, dpi, lang, psm)
EXPLORATION = [
    ("bne", 200, "spa_old", 3),
    ("bne", 400, "spa_old", 3),
    ("bne", 600, "spa_old", 3),
    ("bne", 400, "spa", 3),
    ("ia", 300, "spa_old", 3),
    ("ia", 300, "spa", 3),
    ("ia", 300, "spa_old+cat+lat", 3),
    ("ia", 300, "spa_old", 1),
]

# What the production panel actually runs: one Tesseract per scan.
PANEL = [
    ("ia", 300, "spa_old+cat+lat", 3),
    ("bne", 400, "spa_old", 3),
]


def image_for(scan: str, pdf_page: int, dpi: int) -> Path:
    if scan == "bne":
        return PAGES / "bne" / f"p{pdf_page:04d}_{dpi}dpi.png"
    leaf = pdf_page + IA_OFFSET
    # the native-resolution IA renders are not all exactly the same dpi
    candidates = sorted((PAGES / "ia").glob(f"leaf{leaf:04d}_{dpi}dpi.png"))
    if candidates:
        return candidates[0]
    return PAGES / "ia" / f"leaf{leaf:04d}_{dpi}dpi.png"


def tag(scan: str, pdf_page: int, dpi: int, lang: str, psm: int) -> str:
    return f"{scan}_p{pdf_page:04d}_{dpi}dpi_{lang.replace('+', '-')}_psm{psm}"


def run_one(job) -> tuple[str, int, float, str]:
    scan, pdf_page, dpi, lang, psm = job
    name = tag(scan, pdf_page, dpi, lang, psm)
    img = image_for(scan, pdf_page, dpi)
    if not img.exists():
        return name, 0, 0.0, f"missing image {img.name}"

    t0 = time.time()
    for ext, extra in (("txt", []), ("tsv", ["tsv"])):
        dest = OUT / f"{name}.{ext}"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        cmd = ["tesseract", str(img), str(OUT / name), "-l", lang,
               "--psm", str(psm), "--dpi", str(dpi)] + extra
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return name, 0, time.time() - t0, r.stderr.strip().splitlines()[-1:][0]
    txt = OUT / f"{name}.txt"
    size = txt.stat().st_size if txt.exists() else 0
    return name, size, time.time() - t0, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--pages", default="pilot",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--variants", choices=["panel", "exploration"],
                    default="exploration")
    args = ap.parse_args()

    if subprocess.run(["which", "tesseract"], capture_output=True).returncode != 0:
        sys.exit("tesseract not on PATH -- run inside `nix develop`")

    OUT.mkdir(parents=True, exist_ok=True)
    variants = PANEL if args.variants == "panel" else EXPLORATION
    pages = targets.resolve(args.pages)
    jobs = [(scan, pdf_page, dpi, lang, psm)
            for scan, dpi, lang, psm in variants
            for pdf_page in pages]

    print(f"{len(jobs)} jobs ({len(variants)} variants x {len(pages)} leaves), "
          f"{args.workers} workers\n")
    t0 = time.time()
    errors = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(run_one, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            name, size, elapsed, err = fut.result()
            if err:
                errors.append((name, err))
            if n % 12 == 0 or n == len(jobs):
                print(f"  [{n:3d}/{len(jobs)}]  {time.time()-t0:5.1f}s  last: {name} "
                      f"({size/1000:.1f} kB, {elapsed:.1f}s)")

    print(f"\nDone in {time.time()-t0:.1f}s -> {OUT}")
    for name, err in errors:
        print(f"  ERROR {name}: {err}")


if __name__ == "__main__":
    main()
