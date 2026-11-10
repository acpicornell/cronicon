"""Build the home page's hero image from the book's own frontispiece.

The sibling map editions (`mapes/mut`, `mapes/despuig`) open with their
engraving behind the title, softened under a veil of paper. This edition's
engraving is its frontispiece -- leaf 8 of the Internet Archive scan: a window
of a house in the calle de Zavellá, drawn by B. Ferrá, with `CRONICON
MAYORICENSE` cut into it -- so it is used the same way.

The crop is the upper half of the plate: the medallion, the cornice and the
lettering. The output is committed (`web/hero/frontispici.jpg`, a few hundred
KB), because the page images it is cut from are 1.6 GB and not in git; this
script says exactly how it was made, so it can be made again.

Usage:
  python scripts/build_hero.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

PROJECT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT / "data" / "pages" / "ia" / "leaf0008_300dpi.png"
OUT = PROJECT / "web" / "hero" / "frontispici.jpg"

# Fractions of the leaf: the plate runs x 0.13-0.88; this is its upper half.
REGION = (0.13, 0.10, 0.88, 0.53)
WIDTH = 1400
QUALITY = 72


def main() -> None:
    image = Image.open(SOURCE).convert("L")
    w, h = image.size
    left, top, right, bottom = REGION
    crop = image.crop((round(w * left), round(h * top),
                       round(w * right), round(h * bottom)))
    if crop.width > WIDTH:
        crop = crop.resize((WIDTH, round(crop.height * WIDTH / crop.width)),
                           Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    crop.save(OUT, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    print(f"{OUT.relative_to(PROJECT)}  {crop.width}x{crop.height}  "
          f"{OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
