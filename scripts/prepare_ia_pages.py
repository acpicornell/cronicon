"""Convert Internet Archive JP2 leaves to the PNGs the engines read.

The IA leaves are ~630 dpi greyscale, about three times the linear resolution of
the BNE scan. They are downsampled to 300 dpi here because that is what the
benchmark found best for Tesseract -- more pixels did not help it, and on the BNE
scan upsampling actively hurt.

Reads either the loose leaves fetched one at a time (`fetch_ia.py --leaves`) or
the full `jp2.zip` (`fetch_ia.py --images`), decompressing each leaf on the fly so
the 1.6 GB archive is never unpacked to disk.

Usage:
  python scripts/prepare_ia_pages.py                  # every leaf available
  python scripts/prepare_ia_pages.py --native         # also keep full resolution
  python scripts/prepare_ia_pages.py --leaves 48 198
"""
from __future__ import annotations

import argparse
import io
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
IA = PROJECT / "data" / "ia"
LOOSE = IA / "jp2"
ZIP = IA / "jp2.zip"
OUT = PROJECT / "data" / "pages" / "ia"

# The leaves are ~7.5 in wide; IA does not stamp a dpi into the JP2, so it is
# derived from the BNE page geometry, which we do know exactly.
PAGE_WIDTH_INCHES = 7.55
TARGET_DPI = 300


def sources(wanted: set[int] | None) -> list[tuple[int, str]]:
    """(leaf number, locator) for every available leaf.

    The locator is either a filesystem path or a name inside the zip. Bytes are
    not read here: JP2 decoding is the expensive part and it happens in worker
    processes, so handing them a locator rather than a 2 MB blob keeps the
    pickling cost off the critical path.
    """
    found: dict[int, str] = {}
    if LOOSE.exists():
        for path in sorted(LOOSE.glob("*.jp2")):
            leaf = int(path.stem.split("_")[-1])
            if wanted is None or leaf in wanted:
                found[leaf] = str(path)

    if ZIP.exists():
        with zipfile.ZipFile(ZIP) as archive:
            for name in archive.namelist():
                if not name.endswith(".jp2"):
                    continue
                leaf = int(Path(name).stem.split("_")[-1])
                if leaf in found or (wanted is not None and leaf not in wanted):
                    continue
                found[leaf] = f"zip:{name}"
    return sorted(found.items())


def read_blob(locator: str) -> bytes:
    if locator.startswith("zip:"):
        with zipfile.ZipFile(ZIP) as archive:
            return archive.read(locator[4:])
    return Path(locator).read_bytes()


def convert_one(job: tuple[int, str, bool]) -> tuple[int, int]:
    leaf, locator, keep_native = job
    targets = [TARGET_DPI] if not keep_native else None
    if targets is not None and all(
            (OUT / f"leaf{leaf:04d}_{dpi}dpi.png").exists() for dpi in targets):
        return leaf, 0
    return leaf, len(convert(leaf, read_blob(locator), keep_native))


def convert(leaf: int, blob: bytes, keep_native: bool) -> list[str]:
    img = Image.open(io.BytesIO(blob))
    if img.mode != "L":
        img = img.convert("L")
    native = round(img.width / PAGE_WIDTH_INCHES)

    written = []
    targets = [TARGET_DPI] + ([native] if keep_native else [])
    for dpi in dict.fromkeys(targets):
        out = OUT / f"leaf{leaf:04d}_{dpi}dpi.png"
        if out.exists():
            continue
        image = img
        if dpi != native:
            scale = dpi / native
            image = img.resize((round(img.width * scale), round(img.height * scale)),
                               Image.LANCZOS)
        image.save(out, dpi=(dpi, dpi))
        written.append(out.name)
    return written


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--native", action="store_true",
                    help="also keep the full-resolution render (~4x the disk)")
    ap.add_argument("--leaves", type=int, nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=8,
                    help="JP2 decoding is the bottleneck and parallelises cleanly")
    args = ap.parse_args()

    if not LOOSE.exists() and not ZIP.exists():
        raise SystemExit("no JP2 source; run scripts/fetch_ia.py --images first")

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = set(args.leaves) if args.leaves else None
    items = sources(wanted)
    print(f"{len(items)} leaves available, {args.workers} workers")

    converted = skipped = 0
    jobs = [(leaf, locator, args.native) for leaf, locator in items]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(convert_one, job) for job in jobs]
        for n, future in enumerate(as_completed(futures), 1):
            _leaf, written = future.result()
            converted += bool(written)
            skipped += not written
            if n % 50 == 0 or n == len(jobs):
                print(f"  [{n:4d}/{len(jobs)}]  "
                      f"{converted} converted, {skipped} already present")

    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
