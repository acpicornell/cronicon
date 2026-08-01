"""Generate the static site from the database.

Vanilla HTML, CSS and JavaScript, as in every sibling project: there is no
`package.json` anywhere in the Corpus Balear and there should not be one here.
For an edition whose whole argument is *you can check this*, putting a build
step between the data and the page is the wrong instinct -- someone has to be
able to read `app.js` and see exactly what happens to the transcription.

What Astro would have bought is real URLs per year, and a chronicle needs them:
people arrive asking "what happened in Mallorca in 1521", and `#1521` is not an
answer a search engine can give. So the year pages are generated here, in
Python, which is the toolchain this project already has.

Three surfaces, deliberately:

  the reader     One page per year and one per document, with the text already
                 in the HTML, and full-text search over the lot. Doubtful words
                 are marked in the text and link to the facsimile.

                 The search payload (`search.json`, 2.4 MB, 659 KB over the
                 wire) is fetched on the first keystroke, never on load: the
                 reader who came to browse 1521 does not pay for it. Shipping
                 the text rather than an inverted index is deliberate -- an
                 index is 276 KB but cannot show *what* it matched, and a
                 chronicle search with no line of context around the hit is
                 barely a search at all.

  the apparatus  Every word's certainty is published rather than summarised.
                 It is 100 MB as JSON and 4.7 MB as zstd parquet, which is the
                 only reason this is possible at all.

  the corpus     `data/*.parquet`, queryable *remotely*: DuckDB reads parquet
                 over HTTP with range requests, so

                     SELECT * FROM 'https://cronicon.corpusbalear.org/data/entry.parquet'
                     WHERE year = 1521;

                 works without downloading anything.

Usage:
  python scripts/build_site.py
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path

import duckdb

PROJECT = Path(__file__).resolve().parent.parent
WEB = PROJECT / "web"
DB = PROJECT / "db" / "cronicon.duckdb"

SITE = "https://cronicon.corpusbalear.org"
MONTHS = {1: "Gener", 2: "Febrer", 3: "Març", 4: "Abril", 5: "Maig", 6: "Juny",
          7: "Juliol", 8: "Agost", 9: "Setembre", 10: "Octubre",
          11: "Novembre", 12: "Desembre"}
# Only these two are marked in the reading text. One dissenter is right 99% of
# the time on the chronicle and marking it would paint the page for nothing.
DOUBTFUL = ("two-dissent", "contested")


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def num(n: int) -> str:
    """Thousands separator, Catalan. `f"{n:,}"` gives 2,500, which reads as a
    decimal to the audience this site is written for."""
    return f"{n:,}".replace(",", ".")


def pct(x: float) -> str:
    """A percentage with a Catalan decimal comma: 1,9% and not 1.9%."""
    return f"{x:.1f}".replace(".", ",")


def head(title: str, description: str, canonical: str, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!DOCTYPE html>
<html lang="ca">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{esc(description)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:locale" content="ca_ES">
<link rel="canonical" href="{esc(canonical)}">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
"""


# The five places the edition has. The index used to be all of them at once --
# search, 572 year boxes, the documents table and the glossary stacked into a
# 7 500px scroll -- which made every one of them hard to find.
# Two labels each: the articles read better on a wide screen and are what push
# the bar past the width of a phone, where the five have to fit without the
# type shrinking.
TABS = (("", "Inici", "Inici"),
        ("anys/", "Els anys", "Anys"),
        ("jurats/", "Els jurats", "Jurats"),
        ("documents/", "Els documents", "Documents"),
        ("abreviatures/", "Les abreviatures", "Sigles"),
        ("metode.html", "El mètode", "Mètode"))


def masthead(depth: int = 0, here: str = "") -> str:
    up = "../" * depth
    tabs = "".join(
        f'<a href="{up}{href}"{" class=\'on\'" if href == here else ""}>'
        f'<span class="wide">{label}</span>'
        f'<span class="narrow">{short}</span></a>'
        for href, label, short in TABS)
    return f"""<header>
  <div class="wrap">
    <p class="eyebrow"><a href="https://corpusbalear.org/">Corpus Balear</a></p>
    <h1><a href="{up}">Cronicón Mayoricense</a></h1>
    <p class="sub">Àlvar Campaner i Fuertes · Palma, 1881 · notícies de Mallorca
       de 1229 a 1800</p>
  </div>
</header>
<nav class="tabs"><div class="wrap">{tabs}</div></nav>
"""


GITHUB = "https://github.com/acpicornell/corpusbalear"
GH_ICON = ('<svg class="gh" viewBox="0 0 16 16" width="15" height="15" '
           'aria-hidden="true" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 '
           '8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49'
           '-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01'
           '-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51'
           '-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02'
           '.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27'
           '1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15'
           ' 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2'
           ' 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')


def foot(depth: int = 0) -> str:
    """The foot, in the shape the portal and poblacio use.

    Two paragraphs of links was not a footer. What belongs here is what a
    reader needs when they have finished reading: who made it, how to cite it,
    what they may do with it, and where the sources are.
    """
    up = "../" * depth
    return f"""<footer>
  <div class="wrap">
    <div class="footer-grid">
      <div class="footer-about">
        <p class="footer-brand">Cronicón Mayoricense</p>
        <p>Transcripció obtinguda pel consens de sis reconeixedors
           independents. <strong>Cap model generatiu ha escrit ni un caràcter
           del text.</strong> Cada paraula duu el seu grau de certesa i les
           dubtoses van marcades.</p>
      </div>
      <div class="footer-col">
        <h3>L'edició</h3>
        <a href="{up}anys/">Els anys</a>
        <a href="{up}documents/">Els documents</a>
        <a href="{up}abreviatures/">Les abreviatures</a>
        <a href="{up}metode.html">El mètode i les xifres</a>
      </div>
      <div class="footer-col">
        <h3>Les fonts</h3>
        <a href="https://archive.org/details/CroniconMayoricenseCampaner"
           rel="noopener">Facsímil a l'Internet Archive</a>
        <a href="https://bdh.bne.es/" rel="noopener">Biblioteca Nacional</a>
        <a href="{up}data/">Dades en parquet</a>
        <a href="{GITHUB}" rel="noopener">{GH_ICON}Codi al repositori</a>
      </div>
    </div>
    <div class="footer-bottom">
      <p>© 2026 Antoni C. Picornell Company ·
         <a href="https://creativecommons.org/licenses/by-nc/4.0/"
            rel="noopener">CC BY-NC 4.0</a>
         (reutilització no comercial amb atribució).</p>
      <p>Com citar: Picornell Company, A. C. <em>Cronicón Mayoricense</em>,
         edició digital del text d'Álvaro Campaner (Palma, 1881).
         cronicon.corpusbalear.org</p>
    </div>
  </div>
</footer>
</body>
</html>
"""


def tail(depth: int = 0) -> str:
    """The foot with the script that hides the uncertainty marks, at any depth."""
    up = "../" * depth
    return foot(depth).replace(
        "</body>", f'<script src="{up}app.js"></script>\n</body>')


DOUBT_NOTE = "lectura discutida pel panell"


def doubtful_words(con, pages) -> dict[str, list[str]]:
    """Doubtful word -> the readings the panel rejected, where it can be sure.

    Marking is by the word as published rather than by position, because the
    entry text has been hyphen-stitched and re-joined and the word index no
    longer lines up with the leaf's. That approximation is fine for drawing a
    dotted underline -- the word really was doubtful somewhere on the leaf --
    and it is *not* fine for naming the rivals: the same word can be doubtful
    twice on one leaf and have been argued about differently each time. 9% of
    them are.

    So the variants are offered only where every doubtful occurrence of that
    word agrees on them, and elsewhere the mark stays as it was. Showing the
    union would be telling the reader that engines read something here that
    they read somewhere else.
    """
    rows = con.execute(
        "SELECT text, variants FROM word WHERE pdf_page IN "
        f"({','.join(str(p) for p in pages)}) AND tier IN {DOUBTFUL}"
    ).fetchall()
    seen: dict[str, set] = {}
    for word, variants in rows:
        seen.setdefault(word, set()).add(tuple(variants or ()))
    return {w: list(v.pop()) if len(v) == 1 else []
            for w, v in ((w, set(s)) for w, s in seen.items())}


def mark_doubt(text: str, doubtful: dict[str, list[str]]) -> str:
    """Underline the words the panel argued about, leaving the rest clean.

    The title names what it read instead, when that is known: a reader hovering
    a dotted word wants to know what the argument was, and `?` alone tells them
    only that there was one.
    """
    out = []
    for token in text.split(" "):
        bare = token.strip(".,;:»«()¿?¡!—-")
        if bare and bare in doubtful:
            rivals = doubtful[bare]
            note = (f"{DOUBT_NOTE}. També s'hi llegia: "
                    + " · ".join(rivals)) if rivals else DOUBT_NOTE
            out.append(f'<span class="d" title="{esc(note)}">{esc(token)}</span>')
        else:
            out.append(esc(token))
    return " ".join(out)


LONG_ENTRY = 1500     # characters before an entry is broken up to be read
PARAGRAPH = 900       # rough target for each piece


def tables_on(con, pages) -> tuple[dict[str, str], dict[str, str]]:
    """The inline tables of these leaves, keyed by the text of their first row.

    A table's rows are still in the notice's prose, exactly as the panel read
    them -- nothing was moved out. What this returns is the same words set as a
    table, and `lay_out_tables` swaps the run of text for it, so the reader sees
    the figures in the column the page put them in. The key is the first row's
    own text because that is what survives both assemblies unchanged.
    """
    if not pages:
        return {}, {}
    rows = con.execute(
        "SELECT table_id, seq, label, figure, tier, text FROM table_row "
        f"WHERE pdf_page IN ({','.join(str(p) for p in pages)}) "
        "ORDER BY table_id, seq").fetchall()
    grouped: dict[int, list] = {}
    for tid, _seq, label, figure, tier, text in rows:
        grouped.setdefault(tid, []).append((label, figure, tier, text))
    out, ends = {}, {}
    for cells in grouped.values():
        body = "".join(
            f'<tr class="{"d" if tier not in ("unanimous", "adjudicated") else ""}">'
            f"<th>{esc(label or '')}</th>"
            f'<td class="num">{esc(figure or "")}</td></tr>'
            for label, figure, tier, _text in cells)
        key = cells[0][3]
        out[key] = f'<table class="inline-table"><tbody>{body}</tbody></table>'
        ends[key] = cells[-1][3]
    return out, ends


def lay_out_tables(text: str, tables: dict[str, str],
                   last: dict[str, str]) -> list[str]:
    """Split a notice's prose where a table starts, and set the table as one.

    Matched on the first row's text rather than on a stored offset: the notice
    is hyphen-stitched and re-joined out of the same word records, so an offset
    into the leaf means nothing here, and the row text is the one thing both
    assemblies agree on.
    """
    # Every table in the run, not the first: the notice of 1750 carries two --
    # the dead of the plague to August and the harvest of the year -- and
    # returning at the first left the second as prose.
    found = sorted(((text.find(key), key) for key in tables
                    if text.find(key) >= 0))
    if not found:
        return [text]
    pieces, at = [], 0
    for start, key in found:
        if start < at:
            continue
        # The table runs to the end of its last row; everything after it is
        # prose again -- `Y 101,716 moliendas de aceite.—Co. Fr.` follows the
        # harvest of 1750 and is a sentence, not a fifth row.
        end = text.find(last[key], start)
        end = end + len(last[key]) if end >= 0 else start + len(key)
        if text[at:start].strip():
            pieces.append(text[at:start].strip())
        pieces.append(tables[key])
        at = end
    if text[at:].strip():
        pieces.append(text[at:].strip())
    return pieces


def notemarks(notes, doubtful: dict[str, list[str]]) -> str:
    """A notice's footnotes, under it, numbered as the book numbers them.

    Campaner's notes are half the scholarship in the book -- he corrects
    Terrassa's dates, quotes the accounts the notice summarises, and says where
    he found them -- and the site printed the `(1)` in the text with nothing on
    the page for it to point at.
    """
    if not notes:
        return ""
    return ('<div class="notes">'
            + "".join(f'<p><span class="num">({number})</span> '
                      f"{mark_doubt(text, doubtful)}</p>"
                      for number, text in notes)
            + "</div>")


def paragraphs(text: str) -> list[str]:
    """Break a very long entry into readable pieces at sentence ends.

    This is typography and nothing else -- no character is added, removed or
    moved, and the database keeps the entry whole. It exists because a few
    stretches of the chronicle genuinely run on without ever dating themselves:
    the Germanía is twenty-eight leaves and 115 000 characters between 1520 and
    1525, one entry because Campaner gives no marker in it, and one `<p>` of
    that length is not a page anyone can read.

    Breaking at the page turn would be truer, and is not possible here: the
    entry does not record where each leaf's share of it begins.
    """
    if len(text) <= LONG_ENTRY:
        return [text]
    out: list[str] = []
    for chunk in _regroup(re.split(r"(?<=[.»])\s+(?=[«A-ZÁÉÍÓÚÑ¿¡])", text)):
        # Some stretches run for thousands of characters without a full stop
        # followed by a capital -- Campaner quotes documents that punctuate
        # differently. Fall back to any sentence end, and then to the em dash he
        # uses to separate one notice from the next.
        out.extend(_regroup(re.split(r"(?<=[.;:»])\s+|\s+(?=—)", chunk))
                   if len(chunk) > 2 * PARAGRAPH else [chunk])
    return out or [text]


def _regroup(pieces: list[str]) -> list[str]:
    """Glue the pieces back up to roughly PARAGRAPH characters each."""
    out, buf = [], ""
    for piece in pieces:
        buf = f"{buf} {piece}".strip() if buf else piece
        if len(buf) >= PARAGRAPH:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def read_sigla(con) -> dict[str, str]:
    """Siglum -> the name Campaner gives it in his introduction."""
    return {row[0]: row[1] for row in
            con.execute("SELECT siglum, expansion FROM siglum").fetchall()}


# Why a siglum has no name, which is two different things and should not be
# reported as one. 249 attributions of 3 253 are unnamed: 226 of them are
# `L. V.`, `N. F.` and `T. A.`, which the chronicle cites constantly and the
# introduction's glossary does not list; the other 23 are single initials, the
# first half of a two-part siglum whose second half no engine placed.
NOT_IN_GLOSSARY = "No consta al glossari de la introducció."
TRUNCATED = "Sigla incompleta: només se n'ha llegit la primera inicial."


def cite(siglum: str, sigla: dict[str, str]) -> str:
    """A source chip that gives up its name when clicked.

    The abbreviation alone is useless to anyone who has not read the
    introduction, and the introduction is the one section this edition drops.
    """
    name = sigla.get(siglum)
    if name is None:
        name = TRUNCATED if len(siglum.split()) == 1 else NOT_IN_GLOSSARY
        known = False
    else:
        known = True
    return ('<span class="cite">'
            f'<button class="sig{"" if known else " unglossed"}" type="button"'
            f' aria-expanded="false" title="{esc(name)}">'
            f'{esc(siglum)}</button>'
            f'<span class="sig-name">{esc(name)}</span>'
            '</span>')


def year_page(con, year: int, years: list[int], sigla: dict[str, str]) -> str:
    """A year, in the order the book prints it.

    Ordered by `id`, which is the order the leaves were read, and deliberately
    not by month and day. November 1644 runs 5, 6, 9, 15, 22, 11, 19 in the
    book -- checked against the facsimile, it is Campaner's own disorder --
    and sorting the page by date silently repaired it. This edition leaves his
    errors standing; quietly reordering his notices is the same correction as
    quietly respelling his words. It also puts a notice that states no day back
    where it belongs, under the date it continues, instead of at the head of
    the month.
    """
    entries = con.execute("""
        SELECT id, month, day, text, sources, pdf_page, printed_page
        FROM entry WHERE year = ? ORDER BY id
    """, [year]).fetchall()
    # A note is printed where its notice is, and belongs under it. 245 of them
    # were parsed, stored and never shown: the page said `(1)` and pointed at
    # nothing.
    notes: dict[int, list[tuple[int, str]]] = {}
    for entry_id, number, text in con.execute("""
        SELECT f.entry_id, f.number, f.text FROM footnote f
        JOIN entry e ON e.id = f.entry_id WHERE e.year = ? ORDER BY f.id
    """, [year]).fetchall():
        notes.setdefault(entry_id, []).append((number, text))
    opening = con.execute(
        "SELECT numeral, from_year, to_year, sources, pdf_page "
        "FROM century WHERE from_year = ?", [year]).fetchone()
    # The notes the book prints on these leaves that no notice calls: the
    # superscript that would have called them was never read. They are shown at
    # the foot of the year, where the book has them, rather than kept back --
    # 62 of the 257 notes are in that position and they are Campaner's
    # scholarship, not filler.
    unplaced = con.execute("""
        SELECT DISTINCT f.number, f.text, f.pdf_page FROM footnote f
        WHERE f.entry_id IS NULL AND f.pdf_page IN (
            SELECT pdf_page FROM entry WHERE year = ?)
        ORDER BY f.pdf_page, f.number""", [year]).fetchall()

    pages = {e[5] for e in entries} | ({opening[4]} if opening else set())
    inline, table_ends = tables_on(con, pages)
    doubtful: dict[str, list[str]] = {}
    if pages:
        doubtful = doubtful_words(con, pages)

    i = years.index(year)
    prev_y = years[i - 1] if i else None
    next_y = years[i + 1] if i + 1 < len(years) else None

    parts = [head(f"{year} · Cronicón Mayoricense",
                  f"Notícies de Mallorca de l'any {year} segons el Cronicón "
                  f"Mayoricense de Campaner (1881).",
                  f"{SITE}/anys/{year}/", depth=2),
             masthead(depth=2, here="anys/"),
             '<main class="wrap read">',
             f'<nav class="yearnav">',
             f'<a href="../{prev_y}/">← {prev_y}</a>' if prev_y else "<span></span>",
             f'<h2>{year}</h2>',
             f'<a href="../{next_y}/">{next_y} →</a>' if next_y else "<span></span>",
             "</nav>",
             # The switch belongs on the page that carries the marks, not only
             # on the index where there are none to hide.
             '<p class="readmode"><label class="toggle">'
             '<input type="checkbox" id="plain"> amaga la incertesa'
             "</label></p>"]

    # A century opens by naming its witnesses -- `Anales etc. por Terrassa.—
    # Notas sacadas de los libros de la Procuracion Real, por D. B. Jaume…` --
    # and that list is the closest the book comes to a bibliography. It stands
    # at the head of the first year of the century, which is where the book
    # prints it.
    if opening:
        numeral, first, last, sources, _leaf = opening
        parts.append(
            '<section class="opening">'
            f"<h3>Segle {esc(numeral)} · {first}–{last}</h3>"
            "<p class=\"lede\">Campaner obre el segle nomenant els manuscrits "
            "que el conten:</p>"
            f"<p>{mark_doubt(sources, doubtful)}</p>"
            "</section>")

    if not entries:
        # A silence is information, not a hole. 49 years carry no dated entry;
        # for 27 of them there is no trace of a heading anywhere between the
        # years that bracket them -- Campaner simply had no news. The rest fall
        # inside a stretch of continuous narrative, like the twenty-eight leaves
        # of the Germanía between 1520 and 1525, where the chronicle runs on
        # without stopping to date itself.
        parts.append('<p class="empty">El cronista no dóna cap notícia datada '
                     "d'aquest any. Pot ser que no en tingués, o que l'any caigui "
                     "dins d'un relat seguit que no s'atura a datar-se —com els "
                     "vint-i-vuit fulls de la Germania, entre 1520 i 1525.</p>")
    # Read as a chronicle rather than as a stack of forty identical cards: the
    # month rules a section, the day sits in the margin like the marginal date
    # of a manuscript, and the leaf is named once per run instead of on every
    # notice. The month heading is emitted whenever the month *changes* in
    # reading order, never by sorting -- so where Campaner's own months run out
    # of order, the page says so twice rather than tidying it.
    running_month = object()
    running_leaf = None
    # `sense mes` earns its place only where it separates the undated notices
    # from the dated ones. On a year that is undated throughout -- the whole of
    # the thirteenth century is -- it heads a section there is nothing to
    # distinguish it from, and the em dash under it marks an absence twice.
    dated = any(month for _i, month, *_r in entries)

    def leafmark(page: int) -> str:
        url = ("https://archive.org/details/CroniconMayoricenseCampaner/"
               f"page/n{page - 2}/mode/2up")
        return (f'<p class="leafmark"><a href="{url}" rel="noopener">'
                f"full {page} al facsímil</a></p>")

    for entry_id, month, day, text, sources, page, printed in entries:
        if month != running_month and (month or dated):
            parts.append('<h3 class="month">'
                         f'{esc(MONTHS.get(month) or "sense mes")}</h3>')
            running_month = month
        # The leaf is named once per run of notices that share it, and the run
        # is *not* broken by a month heading: 1644 sits entirely on leaf 429,
        # and flushing on the month printed "full 429" under every month.
        if running_leaf is not None and page != running_leaf:
            parts.append(leafmark(running_leaf))
        running_leaf = page
        cites = " ".join(cite(s, sigla) for s in (sources or []))
        parts.append(
            '<article class="notice">'
            f'<p class="when">{day or ("&mdash;" if dated else "")}</p>'
            '<div class="said">'
            + "".join(
                piece if piece.startswith("<table")
                else f"<p>{mark_doubt(piece, doubtful)}</p>"
                for para in paragraphs(text)
                for piece in lay_out_tables(para, inline, table_ends))
            + (f'<p class="prov">{cites}</p>' if cites else "")
            + notemarks(notes.get(entry_id), doubtful)
            + "</div></article>")
    if running_leaf is not None:
        parts.append(leafmark(running_leaf))
    if unplaced:
        parts.append(
            '<section class="unplaced"><h3 class="section">Notes sense crida</h3>'
            "<p class=\"hint\">Campaner imprimeix aquestes notes en aquests fulls "
            "i la crida que hi remetia —un <em>(1)</em> volat de dos caràcters— "
            "no s'ha pogut llegir, així que no sabem a quina notícia van.</p>"
            + notemarks([(n, t) for n, t, _p in unplaced], doubtful)
            + "</section>")
    parts.append("</main>")
    # The year pages are where the uncertainty marks actually are, so they are
    # the pages that most need the script that hides them. They shipped without
    # it: the preference was stored on the index and then never applied.
    parts.append(tail(2))
    return "\n".join(parts)


# How many opening paragraphs may be the section's own heading: the numeral,
# the title, and the `(pág. 71 del texto.)` Campaner puts under it.
HEAD_LINES = 3


def document_page(con, doc) -> str:
    """One of the 23 pieces Campaner reprints in full.

    These are 21% of the edition and had nowhere to live: the index listed them
    in a table of dead rows, so a search hit inside the Centellas letters could
    only be reported, never opened. They are also the part measured worst --
    1 wrong word in 96 against the chronicle's 1 in 706 -- so the page says so
    at the top rather than leaving the reader to assume the two are alike.
    """
    _id, numeral, title, genre, first, last, words, contested, text = doc
    doubtful = doubtful_words(con, range(first, last + 1))

    paras = [p for p in text.split("\n") if p.strip()]
    # Which leaf each paragraph opens on, so a seventeen-leaf document can be
    # traced back to the page from anywhere in it rather than only from its
    # head. Named once per run, as on the year pages.
    at = json.loads((PROJECT / "data" / "documents" / "sections.json").read_text())
    per_para = next((d.get("paragraph_leaves") or [] for d in at
                     if d["id"] == _id), [])
    chunks, running = [], None
    for i, para in enumerate(paras):
        leaf = per_para[i] if i < len(per_para) else None
        if leaf and leaf != running:
            if running is not None:
                chunks.append(f'<p class="leafmark"><a href="'
                              f"https://archive.org/details/"
                              f"CroniconMayoricenseCampaner/page/n{running - 2}"
                              f'/mode/2up" rel="noopener">full {running} al '
                              "facsímil</a></p>")
            running = leaf
        # The numeral and the title Campaner prints at the head of a section
        # are a heading, not the first two paragraphs of the text. They were
        # being set as body, so the page opened with a bare `III.` in reading
        # type and the title indistinguishable from the first sentence.
        # The heading is the numeral, the title as the catalogue records it,
        # and the source note Campaner sets under them. Recognising the title by
        # its shape was tried and fails on the commonest kind -- `Algunas
        # noticias é indicaciones curiosas extraidas…` opens with an ordinary
        # capital -- so it is recognised by *being* the title, which is a fact
        # the catalogue already holds.
        flat = " ".join(para.split())
        tag = ("h3" if i < HEAD_LINES and len(para) < 260 and
               (i == 0 or flat == " ".join(title.split())
                or para.startswith(("«", "(", '"')) or para.isupper())
               else "p")
        chunks.append(f'<{tag} id="p{i}" class="{"dochead" if tag == "h3" else ""}">'
                      f"{mark_doubt(para, doubtful)}</{tag}>")
    if running is not None:
        chunks.append(f'<p class="leafmark"><a href="'
                      f"https://archive.org/details/CroniconMayoricenseCampaner"
                      f'/page/n{running - 2}/mode/2up" rel="noopener">'
                      f"full {running} al facsímil</a></p>")
    body = "".join(chunks)
    # Campaner's own apparatus, set smaller as the book sets it. 62 notes come
    # off these leaves and none of them reached a page: they were separated
    # from the body -- which is why the documents read as prose -- and then
    # counted and dropped. They are where he says which manuscript a passage
    # comes from and where he corrects it.
    notes = con.execute(
        "SELECT number, text, pdf_page FROM footnote WHERE document_id = ? "
        "ORDER BY pdf_page, number", [_id]).fetchall()
    docnotes = ("" if not notes else
                '<section class="docnotes"><h3 class="section">Notes de '
                "Campaner</h3>"
                + "".join(f'<p><span class="num">({n})</span> '
                          f"{mark_doubt(t, doubtful)} "
                          f'<a class="leafref" href="'
                          f"https://archive.org/details/"
                          f"CroniconMayoricenseCampaner/page/n{p - 2}/mode/2up"
                          f'" rel="noopener">full {p}</a></p>'
                          for n, t, p in notes)
                + "</section>")
    leaf_url = ("https://archive.org/details/CroniconMayoricenseCampaner/"
                f"page/n{first - 2}/mode/2up")
    return (head(f"{numeral}. {title} · Cronicón Mayoricense",
                 f"{title} — {genre or 'document'} reproduït sencer al Cronicón "
                 f"Mayoricense de Campaner (1881), fulls {first}–{last}.",
                 f"{SITE}/documents/{_id}/", depth=2)
            + masthead(depth=2, here="documents/") + f"""
<main class="wrap read">
  <nav class="yearnav"><h2 class="doctitle">{esc(title)}</h2></nav>
  <p class="readmode"><label class="toggle">
     <input type="checkbox" id="plain"> amaga la incertesa</label></p>
  <p class="prov">{esc(genre or '')} · secció {esc(numeral)} ·
     {num(words)} mots · {pct(100*contested/words if words else 0)}% discutits ·
     <a href="{leaf_url}" rel="noopener">fulls {first}–{last} al facsímil</a></p>
  <p class="caveat">Els documents són la part del llibre pitjor mesurada:
     <strong>un mot errat de cada 96</strong>, contra un de cada 706 a la
     crònica. Són en català medieval i llatí, i els reconeixedors hi van pitjor.
     <a href="../../metode.html">Com se sap?</a></p>
  <div class="doc">{body}</div>
  {docnotes}
</main>
""" + tail(2))


CENTURIES = ((1229, 1300, "XIII"), (1301, 1400, "XIV"), (1401, 1500, "XV"),
             (1501, 1600, "XVI"), (1601, 1700, "XVII"), (1701, 1800, "XVIII"))
BAR_MIN, BAR_MAX = 4, 52


def density(counts: dict, first: int, last: int, peak: int) -> str:
    """One century as a strip of bars, a year each, height by how much news.

    Replaces 572 identical boxes that filled a 7 500px page and said nothing:
    every year looked the same, and the only signal -- the count -- was six
    points of type underneath. As bars the same data becomes the shape of the
    chronicle, and the eye lands on 1715 without being told.

    **Square root, not linear.** The distribution is savage: median 4 notices,
    peak 108 in 1715. Scaled linearly the median year is a 2px stub against a
    52px spike and half the book reads as empty, which is false -- it is a
    chronicle of ordinary years with a few violent ones.

    A year with no news keeps a stub rather than vanishing: it is still a fact
    about the book, and it still has a page saying so.
    """
    out = []
    for year in range(first, last + 1):
        n = counts.get(year, 0)
        height = (BAR_MIN + round((BAR_MAX - BAR_MIN) * math.sqrt(n / peak))
                  if n else 2)
        label = (f"{year} · {num(n)} notícies" if n != 1 else f"{year} · 1 notícia")
        if not n:
            label = f"{year} · cap notícia"
        out.append(f'<a class="bar{"" if n else " void"}" href="../anys/{year}/"'
                   f' style="height:{height}px" title="{esc(label)}"'
                   f' aria-label="{esc(label)}"></a>')
    return "".join(out)


def years_page(con, years: list[int], counts: dict) -> str:
    peak = max(counts.values()) or 1
    blocks = []
    for first, last, roman in CENTURIES:
        span = [y for y in range(first, last + 1)]
        told = sum(counts.get(y, 0) for y in span)
        silent = sum(1 for y in span if not counts.get(y))
        ticks = "".join(
            f'<span style="left:{100 * (y - first) / (last - first):.4f}%">{y}</span>'
            for y in range(first if first % 10 == 0 else (first // 10 + 1) * 10,
                           last + 1, 20))
        blocks.append(f"""
  <section class="century">
    <h2>Segle {roman} <small>{first}–{last} · {num(told)} notícies ·
        {num(silent)} anys sense cap</small></h2>
    <div class="strip">{density(counts, first, last, peak)}</div>
    <div class="axis">{ticks}</div>
  </section>""")

    return (head("Els anys · Cronicón Mayoricense",
                 "Els 572 anys del Cronicón Mayoricense, segle a segle, amb "
                 "quantes notícies dona Campaner de cadascun.",
                 f"{SITE}/anys/", depth=1)
            + masthead(depth=1, here="anys/") + f"""
<main class="wrap">
  <p class="hint">Cada barra és un any i l'alçada diu quantes notícies en dona
     Campaner. L'escala és d'arrel quadrada: 1715 en té {num(peak)} i la
     majoria d'anys en tenen quatre, i amb escala lineal mig llibre semblaria
     buit. Els anys sense cap notícia queden com un traç, perquè també són una
     dada.</p>
  {"".join(blocks)}
</main>
""" + tail(1))


def documents_page(con) -> str:
    docs = con.execute("SELECT id, numeral, title, genre, first_leaf, last_leaf, "
                       "words, contested FROM document "
                       "ORDER BY block_leaf, number").fetchall()
    rows = "".join(
        f"<tr><td>{esc(n)}</td>"
        f'<td><a href="{esc(i)}/">{esc(t)}</a></td><td>{esc(g or "")}</td>'
        f'<td class="num">{a}–{b}</td><td class="num">{num(w)}</td>'
        f'<td class="num">{pct(100 * c / w if w else 0)}%</td></tr>'
        for i, n, t, g, a, b, w, c in docs)
    total = num(sum(d[6] for d in docs))
    return (head("Els documents · Cronicón Mayoricense",
                 "Els 23 documents que Campaner reprodueix sencers dins el "
                 "Cronicón Mayoricense: cartes, sentències, relacions i "
                 "fragments en castellà, català medieval i llatí.",
                 f"{SITE}/documents/", depth=1)
            + masthead(depth=1, here="documents/") + f"""
<main class="wrap">
  <p class="hint">Al final de cada segle la crònica s'atura i Campaner
     reprodueix documents sencers: {len(docs)} peces, {total} mots, una cinquena
     part del llibre. Són en castellà, català medieval i llatí, i és la part
     pitjor mesurada — <a href="../metode.html">un mot errat de cada 96</a>,
     contra un de cada 706 a la crònica.</p>
  <div class="scroll">
  <table>
    <thead><tr><th>núm.</th><th>títol</th><th>gènere</th><th>fulls</th>
      <th class="num">mots</th><th class="num">discutits</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</main>
""" + tail(1))


# Twelve sigla carry 84% of the attributions; the rest are pooled. Nine was
# the first cut and it was wrong: `M. S.` alone has 98 attributions, most of
# them in the fifteenth century, and pooling it drew a large anonymous grey
# block over exactly the stretch the chart is meant to explain. Colours are
# chosen to sit on the cream and to survive being next to each other.
BANDS = (("G. T.", "#8b3a2f"), ("B. J.", "#b5714a"), ("M. M.", "#d9a05b"),
         ("G. V.", "#7a8b5a"), ("G. F.", "#4a7a68"), ("J. F.", "#3f6b8a"),
         ("J. V.", "#6b5b95"), ("Jn. Br.", "#a05a7a"), ("L. V.", "#8a6f4e"),
         ("M. S.", "#c08552"), ("Cl. Fl.", "#5b7f9c"), ("N. F.", "#6e8f74"))
OTHER = "#c3b9a8"
CHART_W, CHART_H, VOL_H = 1020, 300, 46


def slug(siglum: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", siglum.lower())).strip("-")


def sources_by_decade(con) -> tuple[list[int], dict, dict]:
    rows = con.execute("""
        SELECT (year//10)*10 AS decade, s, count(*) AS n
        FROM (SELECT year, unnest(sources) AS s FROM entry WHERE year IS NOT NULL)
        GROUP BY 1, 2""").fetchall()
    per: dict[int, dict[str, int]] = {}
    total: dict[str, int] = {}
    for decade, siglum, n in rows:
        per.setdefault(int(decade), {})[siglum] = n
        total[siglum] = total.get(siglum, 0) + n
    return sorted(per), per, total


def sources_chart(con, sigla: dict[str, str]) -> str:
    """Who reports each stretch of the book, decade by decade.

    The most interesting thing in the database and the least visible: Campaner
    names his manuscript for 3 365 of the notices, so the edition can show the
    hand-over of the witnesses across five centuries -- Terrassa carrying the
    14th and 15th, Jaume the 16th, Mut the 18th.

    Two charts and not one, deliberately. The shares alone would say that the
    1300s rest on Terrassa as confidently as the 1700s rest on Mut, and they do
    not: that decade has six attributions against 265. The volume strip above
    is linear precisely so a thin decade *looks* thin -- the square root that
    keeps the year bars legible would hide the one thing this strip is for.
    """
    decades, per, total = sources_by_decade(con)
    shown = [b for b, _ in BANDS]
    colour = dict(BANDS)
    peak = max(sum(per[d].values()) for d in decades)
    step = CHART_W / len(decades)

    cells, bars, ticks = [], [], []
    for i, decade in enumerate(decades):
        counts = per[decade]
        volume = sum(counts.values())
        x = i * step
        height = max(1.0, VOL_H * volume / peak)
        bars.append(f'<rect x="{x:.2f}" y="{VOL_H - height:.2f}" width="{step:.2f}" '
                    f'height="{height:.2f}" fill="var(--accent)" opacity=".55">'
                    f"<title>{decade}s · {num(volume)} atribucions</title></rect>")
        y = 0.0
        order = shown + [b for b in counts if b not in shown]
        for band in order:
            n = counts.get(band, 0) if band in shown else 0
            if band not in shown:
                n = sum(v for k, v in counts.items() if k not in shown)
                if not n:
                    continue
            if not n:
                continue
            h = CHART_H * n / volume
            name = sigla.get(band, band) if band in shown else "altres fonts"
            cells.append(
                f'<rect class="band" data-band="{esc(slug(band) if band in shown else "altres")}" '
                f'x="{x:.2f}" y="{y:.2f}" width="{step:.2f}" height="{h:.2f}" '
                f'fill="{colour.get(band, OTHER)}">'
                f"<title>{decade}s · {esc(name)} · {num(n)} de {num(volume)} "
                f"({pct(100 * n / volume)}%)</title></rect>")
            y += h
            if band not in shown:
                break
        if decade % 100 == 0:
            # The axis is HTML, not SVG text: the chart is stretched to the
            # width of the page with preserveAspectRatio="none", which would
            # stretch the lettering with it.
            ticks.append(f'<span style="left:{100 * x / CHART_W:.3f}%">{decade}</span>')

    legend = "".join(
        f'<a class="key" href="{slug(band)}/"><span style="background:{col}"></span>'
        f"{esc(band)} <small>{esc(sigla.get(band, ''))}</small></a>"
        for band, col in BANDS)
    rest = sum(n for b, n in total.items() if b not in shown)
    legend += (f'<span class="key"><span style="background:{OTHER}"></span>'
               f"altres <small>{num(rest)} atribucions</small></span>")

    return f"""
  <figure class="chart">
    <svg viewBox="0 0 {CHART_W} {VOL_H + 6}" preserveAspectRatio="none"
         class="volume" role="img"
         aria-label="Quantes atribucions duu cada dècada">
      {''.join(bars)}
      <rect x="0" y="{VOL_H}" width="{CHART_W}" height="1" fill="var(--border)"/>
    </svg>
    <svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none"
         class="stack" role="img"
         aria-label="Quina font reporta cada dècada, de 1300 a 1800">
      {''.join(cells)}
    </svg>
    <div class="axis">{''.join(ticks)}</div>
    <figcaption>A dalt, quantes atribucions duu cada dècada — {num(peak)} a la
      més densa i sis a la més prima. A baix, de qui són. Passant per sobre es
      veuen les xifres; clicant una font, on la fa servir.</figcaption>
  </figure>
  <div class="keys">{legend}</div>"""


def dossier(who: dict) -> str:
    """What the introduction says about one source, where it says anything.

    This is the part of the book that makes the chronicle usable and the part it
    was easiest to drop: the abbreviation list gives `M. M.—Matías Mut.` and the
    leaf before it says he was an esparto-worker from Llucmajor whose diary runs
    1680 to 1715 in a hand Campaner calls very bad, and that we know his
    birthday because on 15 April 1686 he wrote «Dit dia jo vaig fer 47 anys».
    """
    if not who.get("role") and not who.get("work"):
        return ""
    line = " · ".join(x for x in (who.get("life"), who.get("role")) if x)
    facts = []
    if who.get("span"):
        facts.append(f"<dt>Anys que abraça</dt><dd>{esc(who['span'])}</dd>")
    if who.get("work"):
        facts.append(f"<dt>El manuscrit</dt><dd><em>{esc(who['work'])}</em></dd>")
    return (f'<div class="dossier">'
            + (f"<p class=\"who-line\">{esc(line)}</p>" if line else "")
            + (f"<dl>{''.join(facts)}</dl>" if facts else "")
            + (f"<p>{esc(who['note'])}</p>" if who.get("note") else "")
            + (f'<p class="aside">Segons la introducció, full '
               f'{who["leaf"]} del facsímil.</p>' if who.get("leaf") else "")
            + "</div>")


def source_page(con, siglum: str, expansion: str) -> str:
    """One manuscript: who wrote it, and where the chronicle draws on it.

    It used to be a grid of years and nothing else, which is the least
    interesting thing that can be said about a source.
    """
    who = con.execute(
        "SELECT expansion, life, role, span, work, note, leaf FROM siglum "
        "WHERE siglum = ?", [siglum]).fetchone()
    fields = ("name", "life", "role", "span", "work", "note", "leaf")
    record = dict(zip(fields, who)) if who else {}
    named = expansion or record.get("name") or "font no glossada a la introducció"
    rows = con.execute(
        "SELECT year, count(*) n FROM entry WHERE year IS NOT NULL "
        "AND list_contains(sources, ?) GROUP BY 1 ORDER BY 1", [siglum]).fetchall()
    total = sum(n for _, n in rows)
    years = "".join(f'<a href="../../anys/{y}/">{y}<small>{n}</small></a>'
                    for y, n in rows)
    first, last = (rows[0][0], rows[-1][0]) if rows else (0, 0)
    return (head(f"{siglum} · {named} · Cronicón Mayoricense",
                 f"Les {num(total)} notícies que Campaner atribueix a "
                 f"{named} al Cronicón Mayoricense.",
                 f"{SITE}/abreviatures/{slug(siglum)}/", depth=2)
            + masthead(depth=2, here="abreviatures/") + f"""
<main class="wrap read">
  <nav class="yearnav"><h2 class="doctitle">{esc(siglum)} · {esc(named)}</h2></nav>
  {dossier(record)}
  <h3 class="section">On el cita el Cronicón</h3>
  <p class="hint">Campaner li atribueix <strong>{num(total)}</strong> notícies,
     repartides en {num(len(rows))} anys entre {first} i {last}.</p>
  <div class="yeargrid">{years}</div>
</main>
""" + tail(2))


# Campaner writes a Jurat's trade after a comma -- `Juan Sala, perayre` -- for
# 341 of the 1 979 names. It is the most interesting column in the table and the
# easiest to mistake for a surname: taking the last word of the name makes
# `perayre` the commonest family in Mallorca, with 70 seats.
TRADES = {
    "perayre": "paraire", "apotecari": "apotecari", "forner": "forner",
    "dr. en leyes": "doctor en lleis", "doncel": "donzell", "notari": "notari",
    "assabonador": "saboner", "caballero": "cavaller", "argenter": "argenter",
    "ferrer": "ferrer", "pellisser": "pellisser", "texidor": "teixidor",
    "sabater": "sabater", "sastre": "sastre", "blanquer": "blanquer",
    "flassader": "flassader", "sucrer": "sucrer", "fuster": "fuster",
    "jurista": "jurista", "draper": "draper", "tintorer": "tintorer",
    "esparter": "esparter", "manescal": "manescal", "chirurgid": "cirurgià",
    "apuntador": "apuntador",
}
CENTURY_NAMES = {13: "XIII", 14: "XIV", 15: "XV", 16: "XVI", 17: "XVII",
                 18: "XVIII"}


def trade_of(name: str) -> str | None:
    """The trade Campaner notes after the comma, normalised, or None."""
    if "," not in name:
        return None
    tail = name.split(",", 1)[1].strip().strip(".").lower()
    return TRADES.get(tail)


def jurats_index(con) -> str:
    """The six series, and who sat in them.

    The Jurats governed the Ciutat i Regne, six of them at a time, replaced
    every year at Christmas by Real privilege of 7 July 1240. Campaner prints
    the lists as appendices inside the body and they are the hardest leaves in
    the book: only a quarter of these names are read the same way by all six
    engines, which the page has to say rather than imply.
    """
    series = con.execute("""
        SELECT century, count(*), min(year), max(year), count(DISTINCT year)
        FROM jurat GROUP BY 1 ORDER BY 1""").fetchall()
    tiers = dict(con.execute(
        "SELECT tier, count(*) FROM jurat GROUP BY 1").fetchall())
    total = sum(tiers.values())

    blocks = "".join(
        f'<a class="serie" href="{c}/">'
        f'<span class="sig">Segle {CENTURY_NAMES[c]}</span>'
        f"<strong>{num(n)} noms</strong>"
        f'<span class="span">{first}–{last}</span>'
        f'<span class="n">{years} anys documentats</span></a>'
        for c, n, first, last, years in series)

    names = [r[0] for r in con.execute("SELECT name FROM jurat").fetchall()]
    trades = Counter(t for t in (trade_of(n) for n in names) if t)
    chips = "".join(f'<li>{esc(t)} <small>{n}</small></li>'
                    for t, n in trades.most_common(18))

    return (head("Els jurats · Cronicón Mayoricense",
                 f"Els {num(total)} jurats de la Ciutat i Regne de Mallorca que "
                 "Campaner llista, de 1240 a 1715, amb el grau de certesa de "
                 "cada nom.",
                 f"{SITE}/jurats/", depth=1)
            + masthead(depth=1, here="jurats/") + f"""
<main class="wrap">
  <section class="opener">
    <p class="kicker">Els qui governaven</p>
    <h2>{num(total)} jurats, de 1240 a 1715</h2>
    <p class="lede">Per privilegi reial de Jaume I, del 7 de juliol de 1240,
       Mallorca es governava per sis jurats que es renovaven cada any per Nadal
       i que elegien els seus successors. Campaner en llista els noms segle a
       segle, com a apèndix dins del cos del llibre.</p>
  </section>

  <div class="source-grid">{blocks}</div>

  <section class="matter">
    <h2 class="section">No tots eren cavallers</h2>
    <p>De 341 noms, Campaner n'anota l'ofici darrere una coma. El gremi seia al
       costat del jurista i del donzell:</p>
    <ul class="subjects">{chips}</ul>
  </section>

  <section class="matter">
    <h2 class="section">Quant se'n pot refiar</h2>
    <p>Aquests fulls són els més difícils del llibre: llistes atapeïdes, tipus
       petit i noms propis mallorquins del 1300, que és exactament on un
       reconeixedor no té cap paraula coneguda a què agafar-se.
       <strong>Només {num(tiers.get('unanimous', 0))} dels {num(total)} noms
       ({tiers.get('unanimous', 0) / total:.0%}) els llegeixen igual els sis
       motors</strong>, contra el 79% del llibre sencer. Cada nom porta el seu
       grau i els dubtosos van marcats.</p>
    <p class="aside">Un nom marcat no vol dir que sigui erroni: vol dir que no
       s'ha comprovat contra el facsímil i que els reconeixedors no hi van
       coincidir del tot.</p>
  </section>
</main>
""" + tail(1))


def jurats_century(con, century: int) -> str:
    """One century's series, year by year, six seats to the row."""
    rows = con.execute(
        "SELECT year, seat, name, tier, pdf_page FROM jurat "
        "WHERE century = ? ORDER BY year, seat", [century]).fetchall()
    by_year: dict[int, list] = {}
    for year, seat, name, tier, page in rows:
        by_year.setdefault(year, []).append((seat, name, tier, page))

    dated = {r[0] for r in con.execute(
        "SELECT DISTINCT year FROM entry WHERE year IS NOT NULL").fetchall()}
    out = []
    for year, seats in sorted(by_year.items()):
        page = seats[0][3]
        link = (f'<a href="../../anys/{year}/">{year}</a>'
                if year in dated else str(year))
        cells = "".join(
            f'<li class="{"d" if tier not in ("unanimous", "adjudicated") else ""}"'
            f' title="{esc(DOUBT_NOTE) if tier not in ("unanimous", "adjudicated") else ""}">'
            f"{esc(name)}</li>"
            for _seat, name, tier, _p in seats)
        out.append(f'<article class="serie-year"><h3>{link}</h3>'
                   f'<ol class="seats">{cells}</ol>'
                   f'<p class="leafmark">full {page}</p></article>')

    order = sorted(CENTURY_NAMES)
    i = order.index(century)
    prev_c = order[i - 1] if i else None
    next_c = order[i + 1] if i + 1 < len(order) else None
    roman = CENTURY_NAMES[century]
    return (head(f"Jurats del segle {roman} · Cronicón Mayoricense",
                 f"Els jurats de Mallorca del segle {roman} segons el Cronicón "
                 "Mayoricense de Campaner.",
                 f"{SITE}/jurats/{century}/", depth=2)
            + masthead(depth=2, here="jurats/") + f"""
<main class="wrap">
  <nav class="yearnav">
    {f'<a href="../{prev_c}/">← segle {CENTURY_NAMES[prev_c]}</a>' if prev_c else "<span></span>"}
    <h2>Segle {roman}</h2>
    {f'<a href="../{next_c}/">segle {CENTURY_NAMES[next_c]} →</a>' if next_c else "<span></span>"}
  </nav>
  <p class="readmode"><label class="toggle">
     <input type="checkbox" id="plain"> amaga la incertesa</label></p>
  <p class="hint">{num(len(rows))} noms en {len(by_year)} anys. L'any enllaça
     amb les seves notícies quan en té.</p>
  <div class="serie-grid">{"".join(out)}</div>
</main>
""" + tail(2))


def abbreviations_page(con) -> str:
    used = dict(con.execute(
        "SELECT s, count(*) FROM (SELECT unnest(sources) AS s FROM entry) "
        "GROUP BY 1").fetchall())
    glossed = con.execute(
        "SELECT siglum, expansion FROM siglum ORDER BY siglum").fetchall()
    # Each source as a card rather than a table row: the table could hold a name
    # and a count, and Campaner gives a trade, a manuscript, a span of years and
    # usually a date of death.
    people = con.execute("""
        SELECT siglum, expansion, life, role, span, work, attributions
        FROM siglum WHERE attributions > 0
        ORDER BY attributions DESC""").fetchall()
    cards = "".join(
        f'<a class="source-card" href="{slug(g)}/">'
        f'<span class="sig">{esc(g)}</span>'
        f"<strong>{esc(x.rstrip('.'))}</strong>"
        + (f"<span class=\"role\">{esc(r)}</span>" if r else "")
        + (f"<span class=\"span\">{esc(sp)}</span>" if sp else "")
        + (f"<em>{esc(w)}</em>" if w else "")
        + f'<span class="n">{num(a or 0)} notícies</span></a>'
        for g, x, _l, r, sp, w, a in people)
    bare = sorted(((g, n) for g, n in used.items()
                   if g not in {x[0] for x in glossed}), key=lambda r: -r[1])
    missing = ", ".join(f"<code>{esc(g)}</code> ({num(n)})" for g, n in bare)
    chart = sources_chart(con, dict(glossed))
    return (head("Les abreviatures · Cronicón Mayoricense",
                 "Les sigles amb què Campaner atribueix cada notícia al "
                 "manuscrit d'on la treu, amb el nom que en dona la introducció.",
                 f"{SITE}/abreviatures/", depth=1)
            + masthead(depth=1, here="abreviatures/") + f"""
<main class="wrap">
  <p class="hint">Campaner atribueix cada notícia al manuscrit d'on la treu, i
     les glossa a la introducció — la part del llibre que aquesta edició no
     publica. Sense això les sigles del cos no volen dir res. A les pàgines
     d'any es pot clicar qualsevol sigla per veure'n el nom.</p>

  <h2 class="section">Qui ho explica, segle a segle</h2>
  <p class="hint">La crònica no descansa sempre sobre els mateixos testimonis.
     Terrassa duu el gruix del segle XIV i del XV, Jaume el XVI, Mut el
     XVIII — i allà on una dècada penja d'una sola font és on convé
     desconfiar.</p>
  {chart}

  <h2 class="section">Els qui van escriure</h2>
  <p class="hint">Un notari, un espardenyer, un cirurgià d'hospital, el rector
     de Campos, el bidell de la Seu. Campaner els descriu un per un vuit fulls
     abans de la llista d'abreviatures, i és la part del llibre que fa que la
     crònica es pugui fer servir: diu qui eren, què és el manuscrit, quins anys
     abraça i on parava el 1881.</p>
  <div class="source-grid">{cards}</div>
  <p class="hint">La crònica en cita {len(bare)} més que la introducció no
     glossa: {missing}. Les d'una sola inicial són sigles de dues que el
     facsímil no deixa llegir senceres.</p>
</main>
""" + tail(1))


# Campaner's own account of what the noticiaris record, from the introduction
# (leaf 15), which this edition otherwise drops. Nothing describes the book
# better than the list he wrote himself, and no summary of ours would be
# evidence of anything.
SUBJECTS = ("acontecimientos políticos y militares",
            "solemnidades religiosas", "fiestas y costumbres populares",
            "reyertas de los bandos de la época", "ejecuciones capitales",
            "calamidades públicas", "sequías", "epidemias",
            "tormentas marítimas", "afecciones meteorológicas")


def shape_of_the_book(counts: dict, first: int, last: int) -> str:
    """The whole chronicle as one strip: how much news each of 572 years carries.

    The same square root the century strips use, and for the same reason -- a
    median of four notices against a peak of 108 in 1715 makes half the book
    look empty under a linear scale, which is false. Here it doubles as the only
    picture on a page that has no pictures: the shape *is* the argument, because
    what it shows is 1521 and 1715 standing out of five centuries of ordinary
    years without anyone having to say so.
    """
    peak = max(counts.values()) or 1
    peak_year = max(counts, key=lambda y: counts[y])
    early = sum(n for y, n in counts.items() if y <= 1300)
    late = sum(n for y, n in counts.items() if y >= 1701)
    span = last - first
    bars = []
    for year in range(first, last + 1):
        n = counts.get(year, 0)
        h = 4 + 56 * math.sqrt(n / peak) if n else 1.5
        x = 1000 * (year - first) / span
        bars.append(f'<rect x="{x:.3f}" y="{62 - h:.2f}" width="1.5" '
                    f'height="{h:.2f}" class="{"y" if n else "y void"}"/>')
    ticks = "".join(
        f'<span style="left:{100 * (y - first) / span:.3f}%">{y}</span>'
        for y in range(1300, last, 100))
    return (f'<figure class="shape">'
            f'<svg viewBox="0 0 1000 62" preserveAspectRatio="none" '
            f'role="img" aria-label="Notícies per any, de {first} a {last}">'
            + "".join(bars) + "</svg>"
            f'<div class="shape-axis"><span style="left:0">{first}</span>{ticks}'
            f'<span style="left:100%">{last}</span></div>'
            "<figcaption>Una barra per any. La crònica s'espesseix a mesura que "
            f"s'acosta al temps de Campaner —{num(early)} notícies al segle XIII "
            f"contra {num(late)} al XVIII— perquè els noticiaris que buida no "
            f"comencen fins al 1372. El pic és {peak_year}, "
            f"amb {num(counts[peak_year])}.</figcaption>"
            "</figure>")


def specimen(con) -> str:
    """One real notice, chosen by its date so that a rebuild cannot move it.

    A text edition sells itself with its text. This one is the Festa de
    l'Estendard called off by a snowfall, which is dated, attributed, three
    lines long, and says in one breath what the whole book is for.
    """
    row = con.execute("""
        SELECT text, sources, pdf_page FROM entry
        WHERE year = 1613 AND month = 12 AND day = 31 LIMIT 1""").fetchone()
    if not row:
        return ""
    text, sources, page = row
    sigla = read_sigla(con)
    cites = " ".join(cite(s, sigla) for s in (sources or []))
    return f"""
  <section class="specimen">
    <p class="kicker">Una notícia, tal com queda</p>
    <article class="notice">
      <p class="when">31<small>des.</small></p>
      <div class="said">
        <p>{esc(text)}</p>
        <p class="prov">{cites}</p>
      </div>
    </article>
    <p class="specimen-note">Any <a href="anys/1613/">1613</a>, full 388 del
       facsímil. La sigla s'obre i diu de quin manuscrit surt la notícia.</p>
  </section>"""


def index_page(con, years: list[int], counts: dict) -> str:
    """The way in.

    It used to be the search box and four links over a strip of five numbers,
    which told a first-time reader nothing about what this book is -- and the
    book says it better than we could. So the page now opens with Campaner's own
    account of it, from the introduction this edition otherwise drops, and with
    one real notice; the numbers moved to the foot, where a reader who wants
    them will look.
    """
    stats = con.execute("""SELECT (SELECT count(*) FROM entry),
                                  (SELECT count(DISTINCT year) FROM entry
                                   WHERE year IS NOT NULL),
                                  (SELECT count(*) FROM jurat),
                                  (SELECT count(*) FROM document),
                                  (SELECT count(*) FROM word)""").fetchone()
    busiest = con.execute(
        "SELECT year, count(*) n FROM entry WHERE year IS NOT NULL "
        "GROUP BY 1 ORDER BY n DESC, year LIMIT 6").fetchall()
    loud = " · ".join(f'<a href="anys/{y}/">{y}</a> <small>{n}</small>'
                      for y, n in busiest)
    longest = con.execute(
        "SELECT id, numeral, title, words FROM document "
        "ORDER BY words DESC LIMIT 3").fetchall()
    docs = "".join(f'<li><a href="documents/{esc(i)}/">{esc(t)}</a> '
                   f"<small>{num(w)} mots</small></li>"
                   for i, _n, t, w in longest)

    subjects = "".join(f"<li>{esc(s)}</li>" for s in SUBJECTS)

    return (head("Cronicón Mayoricense · Campaner, 1881",
                 "Edició digital del Cronicón Mayoricense de Campaner (Palma, "
                 f"1881): {num(stats[0])} notícies datades de Mallorca entre "
                 "1229 i 1800, amb el grau de certesa de cada paraula.",
                 f"{SITE}/") + masthead(here="") + f"""
<main class="wrap">
  <section class="opener">
    <p class="kicker">Edició digital · Corpus Balear</p>
    <h2>Cinc segles de notícies de Mallorca, dia a dia</h2>
    <p class="lede">L'any 1881 Àlvar Campaner va buidar els noticiaris,
       dietaris i anals manuscrits que corrien per l'illa —molts inèdits, i
       alguns a punt de perdre's— i en va ordenar les notícies per data, de la
       conquesta de 1229 fins al 1800. Els va escriure un notari, un
       espardenyer, un cirurgià d'hospital, el rector de Campos, el bidell de
       la Seu. Això és aquell llibre, llegit de nou paraula per paraula.</p>
    <p class="cta"><a class="button" href="anys/">Entra per un any</a>
       <a href="#cerca">o cerca un mot</a></p>
  </section>

  {shape_of_the_book(counts, years[0], years[-1])}

  <div class="twin">
    <blockquote class="pull">
      <p>El presente libro no es una Historia de Mallorca… compónenlo elementos
         tomados de muy diversas fuentes y colocados por el órden de los
         tiempos, á fin de que sirvan de algun auxilio al curioso investigador
         de los hechos y antiguas costumbres é instituciones de la isla.</p>
      <cite>Campaner, introducció, 1881</cite>
    </blockquote>
    <div class="matter">
      <p>Els qui van escriure aquests noticiaris hi anotaven, en paraules del
         mateix Campaner:</p>
      <ul class="subjects">{subjects}</ul>
      <p class="aside">Ho recollia, deia, «salvando de la destruccion ó del
         extravío algunos de los trabajos de nuestros antepasados, de los cuales
         bastantes han sido ya pasto del polvo y la polilla».</p>
    </div>
  </div>
{specimen(con)}
  <section id="cerca" class="find">
    <h2 class="section">Cerca-hi</h2>
    <div class="tools">
      <input type="search" id="q" placeholder="Cerca un mot, una frase, un any…"
             autocomplete="off" spellcheck="false">
      <label class="toggle"><input type="checkbox" id="plain"> amaga la incertesa</label>
    </div>
    <p class="hint">Dins les {num(stats[0])} notícies i els {stats[3]}
       documents sencers. Sense accents també va: <em>germania</em> troba
       <em>Germanía</em>. Entre cometes, cerca la frase exacta.</p>
    <div id="results"></div>
  </section>

  <div class="doors">
    <section>
      <h2>Els anys amb més notícia</h2>
      <p class="loud">{loud}</p>
      <p><a href="anys/">Tots els anys, segle a segle →</a></p>
    </section>
    <section>
      <h2>Els documents més llargs</h2>
      <ul class="plainlist">{docs}</ul>
      <p><a href="documents/">Els {stats[3]} documents sencers →</a></p>
    </section>
    <section>
      <h2>Qui ho explica</h2>
      <p>Vint-i-sis testimonis, cadascun amb el seu ofici i el seu manuscrit,
         tal com els descriu la introducció.</p>
      <p><a href="abreviatures/">Les fonts, una per una →</a></p>
    </section>
    <section>
      <h2>Els qui governaven</h2>
      <p>{num(stats[2])} jurats de la Ciutat i Regne entre 1240 i 1715, sis
         cada any. Paraires i apotecaris al costat de donzells.</p>
      <p><a href="jurats/">Les sis sèries →</a></p>
    </section>
    <section>
      <h2>Què és fiable</h2>
      <p>Cada paraula porta el grau d'acord dels sis reconeixedors que la van
         llegir.</p>
      <p><a href="metode.html">El mètode i les xifres →</a></p>
    </section>
  </div>

  <section class="who">
    <h2 class="section">Qui era Campaner</h2>
    <div class="who-grid">
      <div>
        <p><strong>Àlvar Campaner i Fuertes</strong> —a la portada del llibre,
           <em>Álvaro Campaner y Fuertes</em>— va néixer a Valverde del Camino,
           Huelva, el 1834 i va morir a Palma el 1894. Doctor en dret i fiscal
           de l'Audiència de Mallorca, era sobretot numismàtic: va fundar el
           <em>Memorial numismático español</em> el 1866 i va publicar la
           <em>Numismática balear</em> el 1879.</p>
        <p>No va escriure una història: va reunir la matèria primera perquè
           algú altre en pogués fer una. Aquesta edició fa el mateix un pas
           més enllà, en dades consultables.</p>
      </div>
      <div class="stats">
        <div><strong>{num(stats[0])}</strong>notícies datades</div>
        <div><strong>{stats[1]}</strong>anys</div>
        <div><strong>{num(stats[2])}</strong>jurats</div>
        <div><strong>{stats[3]}</strong>documents</div>
        <div><strong>{num(stats[4])}</strong>paraules</div>
      </div>
    </div>
  </section>
</main>
""" + tail(0))


def method_page(con) -> str:
    tiers = dict(con.execute("SELECT tier, count(*) FROM word GROUP BY 1").fetchall())
    total = sum(tiers.values())
    adj = con.execute("""
        SELECT family, tier, count(*),
               round(100.0*count(*) FILTER (WHERE chose = winner)/count(*), 1)
        FROM adjudication WHERE winner IS NOT NULL
        GROUP BY 1,2 ORDER BY 1, 3 DESC""").fetchall()
    order = {"adjudicated": -1, "unanimous": 0, "one-dissent": 1,
             "two-dissent": 2, "contested": 3}
    label = {"adjudicated": "resolt contra el facsímil",
             "unanimous": "els sis coincideixen", "one-dissent": "un discrepa",
             "two-dissent": "en discrepen dos", "contested": "en discrepen tres o més"}

    tier_rows = "".join(
        f"<tr><td>{label[t]}</td><td class='num'>{num(tiers.get(t, 0))}</td>"
        f"<td class='num'>{pct(100*tiers.get(t,0)/total)}%</td></tr>"
        for t in sorted(tiers, key=lambda t: order[t]))
    adj_rows = "".join(
        f"<tr><td>{'la crònica' if f=='sample' else 'els documents'}</td>"
        f"<td>{label.get(t, t)}</td><td class='num'>{n}</td>"
        f"<td class='num'>{p}%</td></tr>"
        for f, t, n, p in sorted(adj, key=lambda r: (r[0], order.get(r[1], 9))))

    return (head("El mètode · Cronicón Mayoricense",
                 "Com s'ha obtingut aquesta transcripció i què se n'ha mesurat.",
                 f"{SITE}/metode.html") + masthead(here="metode.html") + f"""
<main class="wrap read">
  <h2 class="section">Com s'ha fet</h2>
  <p>Sis reconeixedors independents llegeixen cada full de <strong>dos
     escanejos diferents</strong> del mateix exemplar, i cada posició s'adjudica
     per majoria. La paraula publicada és sempre una que algun motor va llegir
     de veritat: <strong>cap model generatiu ha escrit ni un caràcter</strong>.
     El text pot equivocar-se, però només allà on algun reconeixedor s'equivocà
     abans.</p>
  <p>Res no es modernitza. <em>formacion</em>, <em>dia</em>, <em>Setiembre</em>,
     <em>mallorquin</em> i les errades del mateix Campaner es queden com són.</p>

  <h2 class="section">Quant d'acord es posen</h2>
  <div class="scroll"><table><thead><tr><th>grau</th><th class="num">paraules</th>
    <th class="num">%</th></tr></thead><tbody>{tier_rows}</tbody></table></div>

  <h2 class="section">I quan encerten</h2>
  <p>870 posicions s'han resolt mirant el facsímil, una a una. Aquestes són
     dues mesures separades i no s'han de barrejar: el llibre no és igual de
     fiable pertot.</p>
  <div class="scroll"><table><thead><tr><th>part</th><th>grau</th><th class="num">n</th>
    <th class="num">encerts</th></tr></thead><tbody>{adj_rows}</tbody></table></div>
  <p>D'aquí surt que la crònica en castellà va per <strong>1 paraula errada de
     cada 113</strong> i els documents en català medieval i llatí per
     <strong>1 de cada 39</strong>. Per això les paraules discutides van
     marcades: una xifra sola descriuria malament totes dues meitats.</p>

  <h2 class="section">Consultar-ho tot</h2>
  <p>Tota l'edició és consultable en SQL sense descarregar res, perquè DuckDB
     llegeix parquet per HTTP demanant només els bytes que necessita:</p>
  <pre>SELECT year, count(*) FROM '{SITE}/data/entry.parquet'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;</pre>
  <p>Les taules són <code>word</code> (cada paraula amb el seu grau de certesa i
     la seva caixa al facsímil), <code>entry</code>, <code>jurat</code>,
     <code>document</code>, <code>footnote</code>, <code>siglum</code>,
     <code>leaf</code> i <code>adjudication</code> —les 870 lectures
     verificades—. Són <a href="data/">5,7 MB en total</a>.</p>
</main>
""" + foot(0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    WEB.mkdir(exist_ok=True)
    (WEB / "anys").mkdir(exist_ok=True)
    (WEB / "jurats").mkdir(exist_ok=True)
    (WEB / "documents").mkdir(exist_ok=True)

    dated = [r[0] for r in con.execute(
        "SELECT DISTINCT year FROM entry WHERE year IS NOT NULL ORDER BY 1"
    ).fetchall()]
    # Every year of the span gets a page, not only the ones with entries: the
    # index links the whole grid, and a year the chronicle is silent about is a
    # fact about the book rather than a missing file.
    years = list(range(dated[0], dated[-1] + 1))
    sigla = read_sigla(con)

    for year in years:
        target = WEB / "anys" / str(year)
        target.mkdir(exist_ok=True)
        (target / "index.html").write_text(year_page(con, year, years, sigla),
                                           encoding="utf-8")

    documents = con.execute(
        "SELECT id, numeral, title, genre, first_leaf, last_leaf, words, "
        "contested, text FROM document ORDER BY block_leaf, number").fetchall()
    for doc in documents:
        target = WEB / "documents" / doc[0]
        target.mkdir(exist_ok=True)
        (target / "index.html").write_text(document_page(con, doc),
                                           encoding="utf-8")

    # The searchable book. Two arrays, positional rather than keyed, because the
    # keys would be a third of the bytes: entries as [year, leaf, text] and
    # documents as [id, title, text]. Fetched on the first keystroke.
    (WEB / "search.json").write_text(json.dumps(
        {"e": con.execute(
            "SELECT year, pdf_page, text FROM entry WHERE year IS NOT NULL "
            "ORDER BY id").fetchall(),
         "d": [[d[0], d[2], d[8]] for d in documents]},
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # The index's payload: enough to search and browse without another request.
    counts = dict(con.execute(
        "SELECT year, count(*) FROM entry WHERE year IS NOT NULL GROUP BY 1"
    ).fetchall())
    payload = {
        "years": [{"y": y, "n": counts.get(y, 0)} for y in years],
        "documents": [dict(zip(("id", "numeral", "title", "genre", "first_leaf",
                                "last_leaf", "words", "contested"), row))
                      for row in con.execute(
            "SELECT id, numeral, title, genre, first_leaf, last_leaf, words, "
            "contested FROM document ORDER BY block_leaf, number").fetchall()],
        "sigla": [dict(zip(("siglum", "expansion", "attributions"), row))
                  for row in con.execute(
            "SELECT siglum, expansion, attributions FROM siglum "
            "ORDER BY attributions DESC NULLS LAST").fetchall()],
        "stats": dict(zip(
            ("leaves", "words", "entries", "jurats", "documents", "adjudications"),
            con.execute("""SELECT (SELECT count(*) FROM leaf),
                                  (SELECT count(*) FROM word),
                                  (SELECT count(*) FROM entry),
                                  (SELECT count(*) FROM jurat),
                                  (SELECT count(*) FROM document),
                                  (SELECT count(*) FROM adjudication)""").fetchone())),
        "tiers": dict(con.execute(
            "SELECT tier, count(*) FROM word GROUP BY 1").fetchall()),
    }
    (WEB / "data.json").write_text(json.dumps(payload, ensure_ascii=False,
                                              separators=(",", ":")),
                                   encoding="utf-8")

    (WEB / "jurats" / "index.html").write_text(jurats_index(con),
                                               encoding="utf-8")
    for (century,) in con.execute(
            "SELECT DISTINCT century FROM jurat ORDER BY 1").fetchall():
        target = WEB / "jurats" / str(century)
        target.mkdir(exist_ok=True)
        (target / "index.html").write_text(jurats_century(con, century),
                                           encoding="utf-8")

    (WEB / "index.html").write_text(index_page(con, years, counts),
                                    encoding="utf-8")
    (WEB / "metode.html").write_text(method_page(con), encoding="utf-8")
    (WEB / "anys" / "index.html").write_text(
        years_page(con, years, counts), encoding="utf-8")
    (WEB / "documents" / "index.html").write_text(
        documents_page(con), encoding="utf-8")
    (WEB / "abreviatures").mkdir(exist_ok=True)
    (WEB / "abreviatures" / "index.html").write_text(
        abbreviations_page(con), encoding="utf-8")
    # One page per source in the chart: where that manuscript is cited, year by
    # year. Years and counts only -- listing the notices themselves would put a
    # second copy of the corpus on the site.
    for band, _colour in BANDS:
        row = con.execute("SELECT expansion FROM siglum WHERE siglum = ?",
                          [band]).fetchone()
        target = WEB / "abreviatures" / slug(band)
        target.mkdir(exist_ok=True)
        (target / "index.html").write_text(
            source_page(con, band, row[0] if row else ""), encoding="utf-8")

    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
               f"<url><loc>{SITE}/</loc><priority>1.0</priority></url>",
               f"<url><loc>{SITE}/metode.html</loc></url>",
               f"<url><loc>{SITE}/anys/</loc></url>",
               f"<url><loc>{SITE}/documents/</loc></url>",
               f"<url><loc>{SITE}/abreviatures/</loc></url>",
               f"<url><loc>{SITE}/jurats/</loc></url>"]
    sitemap += [f"<url><loc>{SITE}/jurats/{c}/</loc></url>"
                for (c,) in con.execute(
                    "SELECT DISTINCT century FROM jurat ORDER BY 1").fetchall()]
    sitemap += [f"<url><loc>{SITE}/anys/{y}/</loc></url>" for y in years]
    sitemap += [f"<url><loc>{SITE}/abreviatures/{slug(b)}/</loc></url>"
                for b, _c in BANDS]
    sitemap += [f"<url><loc>{SITE}/documents/{d[0]}/</loc></url>"
                for d in documents]
    sitemap.append("</urlset>")
    (WEB / "sitemap.xml").write_text("\n".join(sitemap), encoding="utf-8")

    (WEB / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n",
        encoding="utf-8")

    size = sum(p.stat().st_size for p in WEB.rglob("*") if p.is_file())
    print(f"{len(years)} year pages, {len(documents)} document pages, "
          f"data.json {(WEB / 'data.json').stat().st_size/1024:.0f} KB, "
          f"search.json {(WEB / 'search.json').stat().st_size/1024:.0f} KB")
    print(f"web/ is {size/1048576:.1f} MB in total")
    con.close()


if __name__ == "__main__":
    main()
