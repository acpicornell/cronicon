"""Which leaves a run should process, and which engines make up the panel.

The pilot scripts were hardwired to twelve pages. For the full book the target
set comes from data/inventory.json, so plates and blank leaves are skipped
automatically rather than being OCRed into noise that later has to be filtered.

Two engine sets are kept deliberately apart:

* EXPLORATION -- the fourteen readings the benchmark compared. Only ever run over
  the pilot pages; running fourteen variants over 614 leaves would cost hours to
  answer a question already answered.
* PANEL -- the six the report recommends. One engine per (family, scan), because
  the guarantee the pipeline rests on is unanimity, and two variants of the same
  engine over the same image vote together without adding evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from pilot_pages import PAGES as PILOT_PAGES

PROJECT = Path(__file__).resolve().parent.parent
INVENTORY = PROJECT / "data" / "inventory.json"

IA_OFFSET = -2

# (engine id, scan, dpi, extra) for the production run.
PANEL = [
    ("abbyy-bne", "bne", None, None),
    ("abbyy-ia", "ia", None, None),
    ("tess-ia-300dpi-spa_old-cat-lat-psm3", "ia", 300, ("spa_old+cat+lat", 3)),
    ("tess-bne-400dpi-spa_old-psm3", "bne", 400, ("spa_old", 3)),
    ("vision-bne-400dpi-corr", "bne", 400, True),
    ("vision-ia-300dpi-corr", "ia", 300, True),
]

# Resolutions each scan has to be rendered at to serve the panel.
BNE_DPI = sorted({dpi for _, scan, dpi, _ in PANEL if scan == "bne" and dpi})
IA_DPI = sorted({dpi for _, scan, dpi, _ in PANEL if scan == "ia" and dpi})


def inventory() -> list[dict]:
    if not INVENTORY.exists():
        raise SystemExit("data/inventory.json missing -- run scripts/inventory.py")
    return json.loads(INVENTORY.read_text())["leaves"]


def resolve(spec: str) -> list[int]:
    """PDF page numbers for a target spec.

    'pilot' -- the twelve benchmark pages
    'all'   -- every leaf carrying running text (plates and blanks excluded)
    'every' -- literally every leaf, plates included
    or a comma-separated list of page numbers.
    """
    if spec == "pilot":
        return list(PILOT_PAGES)
    if spec in {"all", "every"}:
        return [leaf["pdf_page"] for leaf in inventory()
                if spec == "every" or leaf["page_class"] != "plate_or_blank"]
    return [int(part) for part in spec.replace(",", " ").split()]


def describe(pages: list[int]) -> str:
    leaves = {leaf["pdf_page"]: leaf for leaf in inventory()}
    classes: dict[str, int] = {}
    for page in pages:
        name = leaves.get(page, {}).get("page_class", "unknown")
        classes[name] = classes.get(name, 0) + 1
    return "  ".join(f"{name}={count}" for name, count in sorted(classes.items()))
