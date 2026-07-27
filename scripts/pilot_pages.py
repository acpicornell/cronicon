"""The pilot page set: one entry per page class in the book.

`pdf_page` is the 0-based index into data/raw/Cronicon-mayoricense.pdf (the BNE
scan). `printed` is the page number printed on the leaf, which is what aligns the
BNE scan with the independent Internet Archive / Google digitisation; roman
numerals for the introduction, None where the leaf carries no number.

Kept as a module rather than a JSON file so the rationale for each choice stays
next to the choice.
"""
from __future__ import annotations

PILOT = [
    # (pdf_page, printed, page_class, why this page)
    (14, "V", "intro", "introduction opener, single wide column + footnote"),
    (17, "VIII", "intro", "introduction, dense small type, many proper nouns"),
    (20, "XI", "intro", "introduction with quoted Catalan in italics"),
    (30, "3", "body", "early body, two columns, long quoted paragraphs"),
    (34, "7", "body_years", "several year headings on one page, short entries"),
    (36, "9", "body_years", "year headings out of order in the OCR layer"),
    (50, "23", "body", "clean two-column body, dense proper nouns"),
    (200, "173", "body_notes", "body with source sigla and an em-dash entry chain"),
    (627, "600", "body_late", "late body, worn type"),
    (629, "602", "body_late", "late body, heavy bleed-through"),
    (631, None, "appendix_list", "appendix I: Jurats name list, tabular layout"),
    (642, None, "errata", "errata page, single column, small type"),
]

PAGES = [p for p, _, _, _ in PILOT]
CLASS_OF = {p: c for p, _, c, _ in PILOT}
PRINTED_OF = {p: pr for p, pr, _, _ in PILOT}
