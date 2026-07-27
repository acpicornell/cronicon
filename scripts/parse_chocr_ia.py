"""Extract the Internet Archive ABBYY reading for the pilot leaves from chOCR.

chOCR is hOCR plus per-character detail: every `ocrx_word` carries `x_wconf`, and
every character inside it carries its own bbox and confidence. That per-word
confidence is what lets the consensus stage weigh this engine instead of treating
it as one anonymous vote, so it is worth parsing properly rather than falling back
on the flat `_djvu.txt`.

The file is ~400 MB uncompressed, so we stream it and only materialise the pages
we asked for.

Usage:
  python scripts/parse_chocr_ia.py
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import argparse

import targets

PROJECT = Path(__file__).resolve().parent.parent
CHOCR = PROJECT / "data" / "ia" / "Cronicon_Mayoricense_Campaner_chocr.html.gz"
OUT = PROJECT / "data" / "ocr" / "abbyy_ia"

IA_OFFSET = -2

PAGE_RE = re.compile(r'<div class="ocr_page" id="page_(\d+)" '
                     r'title="bbox (\d+) (\d+) (\d+) (\d+)')
LINE_RE = re.compile(r'<span class="ocr_line"[^>]*title="bbox (\d+) (\d+) (\d+) (\d+)')
WORD_RE = re.compile(r'<span class="ocrx_word"[^>]*title="bbox '
                     r'(\d+) (\d+) (\d+) (\d+); x_wconf (\d+)')
CHAR_RE = re.compile(r'<span class="ocrx_cinfo" title="x_bboxes '
                     r'(\d+) (\d+) (\d+) (\d+)[^"]*"[^>]*>(.*?)</span>', re.S)

ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}


def unescape(s: str) -> str:
    for k, v in ENTITIES.items():
        s = s.replace(k, v)
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="pilot",
                    help="pilot | all | every | comma-separated page numbers")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = {p + IA_OFFSET: p for p in targets.resolve(args.pages)}
    pages: dict[int, dict] = {}

    current_leaf = None
    line = None          # the line record currently being filled
    word_buf: list[tuple] = []
    word_meta: tuple | None = None

    def flush() -> None:
        """Commit the word whose characters have been accumulating.

        Two quirks of ABBYY's output are repaired here.

        A word's characters appear *after* its opening tag, so the word can only
        be committed once the next tag arrives. That next tag is sometimes a new
        ocr_line rather than a new ocrx_word -- flushing lazily filed the last
        word of every line under the following line. Hence the explicit flush at
        each line and page boundary too.

        And about 2.4% of ocrx_word spans contain *two* words separated by a
        space, with a word-level bbox covering only part of them (`mento el` on
        leaf 48 is boxed over `el` alone). The per-character boxes are right, so
        the span is split on its spaces and each piece gets a box built from its
        own characters. The word-level bbox is never used.
        """
        nonlocal word_meta, word_buf
        if word_meta is not None and line is not None:
            piece: list[tuple] = []
            for char in word_buf + [(0, 0, 0, 0, " ")]:
                if char[4].strip():
                    piece.append(char)
                    continue
                if piece:
                    text = unescape("".join(c[4] for c in piece)).strip()
                    if text:
                        line["words"].append({
                            "text": text,
                            "conf": word_meta[4],
                            "bbox": [min(c[0] for c in piece),
                                     min(c[1] for c in piece),
                                     max(c[2] for c in piece),
                                     max(c[3] for c in piece)],
                        })
                    piece = []
        word_meta = None
        word_buf = []

    with gzip.open(CHOCR, "rt", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            m = PAGE_RE.search(raw)
            if m:
                flush()
                line = None
                current_leaf = int(m.group(1))
                if current_leaf in wanted:
                    pages[current_leaf] = {"leaf": current_leaf,
                                           "pdf_page": wanted[current_leaf],
                                           "page_width": int(m.group(4)),
                                           "page_height": int(m.group(5)),
                                           "lines": []}
            if current_leaf not in wanted:
                continue

            m = LINE_RE.search(raw)
            if m:
                flush()
                line = {"bbox": [int(g) for g in m.groups()], "words": []}
                pages[current_leaf]["lines"].append(line)
                continue

            m = WORD_RE.search(raw)
            if m:
                flush()
                word_meta = tuple(int(g) for g in m.groups())
                continue

            for cm in CHAR_RE.finditer(raw):
                x0, y0, x1, y1, char = cm.groups()
                word_buf.append((int(x0), int(y0), int(x1), int(y1), char))

        flush()

    for leaf, page in sorted(pages.items()):
        pdf_page = page["pdf_page"]
        name = f"ia_p{pdf_page:04d}"
        (OUT / f"{name}.json").write_text(
            json.dumps(page, ensure_ascii=False, indent=1))
        text = "\n".join(" ".join(w["text"] for w in ln["words"])
                         for ln in page["lines"] if ln["words"])
        (OUT / f"{name}.txt").write_text(text, encoding="utf-8")
        nwords = sum(len(ln["words"]) for ln in page["lines"])
        confs = [w["conf"] for ln in page["lines"] for w in ln["words"]]
        mean = sum(confs) / len(confs) if confs else 0
        if args.quiet:
            continue
        print(f"  leaf {leaf:4d} -> pdf p{pdf_page:04d}  "
              f"{len(page['lines']):3d} lines  {nwords:4d} words  "
              f"mean conf {mean:.1f}  low(<80) {sum(c < 80 for c in confs)}")

    missing = set(wanted) - set(pages)
    if missing:
        print(f"  MISSING leaves: {sorted(missing)}")


if __name__ == "__main__":
    main()
