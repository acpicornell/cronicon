"""Fetch the independent Internet Archive / Google digitisation of the Cronicon.

Item: https://archive.org/details/CroniconMayoricenseCampaner
A Google Books scan (667 leaves, 600 ppi JP2) with Internet Archive's own ABBYY
run. It is a different scanner and a different ABBYY version from the BNE PDF we
hold locally, so its errors are uncorrelated with ours -- which is the whole point
of using it as a second reading.

Downloads the derivative files whole (they are small relative to the images), and
individual JP2 leaves on demand through Archive.org's in-zip path access, so we
never pull the 1.6 GB image zip for a 12-page pilot.

Usage:
  python scripts/fetch_ia.py --derivatives     # page numbers, djvu.txt, chocr
  python scripts/fetch_ia.py --leaves 22 24    # specific leaves as JP2
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUT = PROJECT / "data" / "ia"

ITEM = "CroniconMayoricenseCampaner"
STEM = "Cronicon_Mayoricense_Campaner"
BASE = f"https://archive.org/download/{ITEM}"

# Archive.org drops long transfers; each attempt resumes where the last stopped.
MAX_RESUME_ATTEMPTS = 20

DERIVATIVES = [
    f"{STEM}_page_numbers.json",   # leaf -> printed page number
    f"{STEM}_djvu.txt",            # flat OCR text, for quick greps
    f"{STEM}_chocr.html.gz",       # word boxes + per-word confidence
]


def curl(url: str, dest: Path, resumable: bool = False) -> None:
    """Download to dest, via a .part file so an interrupted run leaves no half file.

    Archive.org drops long transfers regularly -- the 1.6 GB image zip failed at
    316 MB on the first attempt. It serves `accept-ranges: bytes`, so large files
    are fetched with `-C -` and retried until they complete, resuming from
    whatever the previous attempt managed rather than starting over.
    """
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {dest.name}  (exists)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    command = ["curl", "-fsSL", "--retry", "5", "--retry-delay", "5",
               "--retry-all-errors", url, "-o", str(tmp)]
    if resumable:
        command[1:1] = ["-C", "-"]

    for attempt in range(1, MAX_RESUME_ATTEMPTS + 1):
        result = subprocess.run(command)
        if result.returncode == 0:
            break
        if not resumable:
            tmp.unlink(missing_ok=True)
            sys.exit(f"failed to fetch {url}")
        got = tmp.stat().st_size if tmp.exists() else 0
        print(f"  attempt {attempt} stopped at {got/1e6:.0f} MB, resuming")
    else:
        sys.exit(f"gave up on {url} after {MAX_RESUME_ATTEMPTS} attempts")

    tmp.rename(dest)
    print(f"  {dest.name}  {dest.stat().st_size/1e6:.1f} MB")


def fetch_derivatives() -> None:
    for name in DERIVATIVES:
        curl(f"{BASE}/{name}", OUT / name)


def fetch_images() -> Path:
    """The whole JP2 set (~1.6 GB, 667 leaves) for the full-book run."""
    dest = OUT / "jp2.zip"
    curl(f"{BASE}/{STEM}_jp2.zip", dest, resumable=True)
    return dest


def fetch_leaf(leaf: int) -> Path:
    """Pull one JP2 out of the image zip without downloading the zip.

    Archive.org serves a file inside a zip at
    <base>/<zip>/<path-inside-zip>, with the inner slash percent-encoded.
    """
    name = f"{STEM}_{leaf:04d}.jp2"
    url = f"{BASE}/{STEM}_jp2.zip/{STEM}_jp2%2F{name}"
    dest = OUT / "jp2" / name
    curl(url, dest)
    return dest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--derivatives", action="store_true")
    ap.add_argument("--images", action="store_true",
                    help="the full ~1.6 GB JP2 set; resumes if interrupted")
    ap.add_argument("--leaves", type=int, nargs="*", default=[])
    args = ap.parse_args()

    if args.derivatives:
        fetch_derivatives()
    if args.images:
        fetch_images()
    for leaf in args.leaves:
        fetch_leaf(leaf)


if __name__ == "__main__":
    main()
