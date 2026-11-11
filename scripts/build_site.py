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
                 in the HTML; a thematic route per subject; and full-text
                 search over the lot. Disputed words are marked in the text,
                 by position (`doubt.py`), and every leaf can be opened beside
                 what was read from it.

                 The search index (`search/*.json`, one shard per century plus
                 the documents and the Jurats) is fetched on the first search,
                 never on load: the reader who came to browse 1521 does not pay
                 for it. Shipping the text rather than an inverted index is
                 deliberate -- an index is a tenth of the size but cannot show
                 *what* it matched, and a chronicle search with no line of
                 context around the hit is barely a search at all.

  the apparatus  Every word's certainty is published rather than summarised.
                 It is 100 MB as JSON and 4.7 MB as zstd parquet, which is the
                 only reason this is possible at all.

  the corpus     `data/*.parquet`, queryable *remotely*: DuckDB reads parquet
                 over HTTP, so

                     SELECT * FROM 'https://cronicon.corpusbalear.org/data/entry.parquet'
                     WHERE year = 1521;

                 works with nothing installed but DuckDB. Workers static
                 assets answer a range request with the whole file (measured
                 on deploy), so DuckDB fetches the file once rather than the
                 bytes it needs; at 0.6 MB for the notices that is fine.

**The pages must run under the site's own Content-Security-Policy**, which is
`script-src 'self'; style-src 'self'` with no `'unsafe-inline'` and one foreign
origin, for images only. So nothing here writes a `style` attribute, an inline
script or an inline handler: what varies with the data is an SVG attribute or a
class, and `check_site.py` fails the build otherwise. `dev_server.py` serves the
result with the real headers, because a plain file server does not, and that
hid a year index whose every bar was an inline style.

Usage:
  python scripts/build_site.py
  python scripts/build_site.py --themes-report   # read the routes before trusting them
  python scripts/check_site.py
  python scripts/dev_server.py                   # http://127.0.0.1:8788
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import random
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import duckdb

import parse_entries
import themes
from doubt import DOUBTFUL, Doubt

PROJECT = Path(__file__).resolve().parent.parent
WEB = PROJECT / "web"
DB = PROJECT / "db" / "cronicon.duckdb"

SITE = "https://cronicon.corpusbalear.org"
ARCHIVE = "https://archive.org/details/CroniconMayoricenseCampaner"
MONTHS = {1: "Gener", 2: "Febrer", 3: "Març", 4: "Abril", 5: "Maig", 6: "Juny",
          7: "Juliol", 8: "Agost", 9: "Setembre", 10: "Octubre",
          11: "Novembre", 12: "Desembre"}
# Below this share of text tokens placed on the leaf, the doubt marks cannot be
# trusted to sit on the right words, and the build stops rather than publish them.
MIN_ALIGNED = 0.95


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def num(n: int) -> str:
    """Thousands separator, Catalan. `f"{n:,}"` gives 2,500, which reads as a
    decimal to the audience this site is written for."""
    return f"{n:,}".replace(",", ".")


def pct(x: float) -> str:
    """A percentage with a Catalan decimal comma: 1,9% and not 1.9%."""
    return f"{x:.1f}".replace(".", ",")


_VERSIONS: dict[str, str] = {}


def asset(name: str) -> str:
    """A hand-written file's URL, with a fingerprint of its contents.

    `style.css?v=3f9a1c2e` changes whenever the stylesheet does, so a page can
    never be shown with a stylesheet from before it was built. That happened:
    the redesign changed every class name, a browser kept the old `style.css`
    it had cached under a server that sent no cache headers, and the new pages
    came out with their bars as one black block and their words run together.
    """
    if name not in _VERSIONS:
        digest = hashlib.sha256((WEB / name).read_bytes()).hexdigest()[:8]
        _VERSIONS[name] = f"{name}?v={digest}"
    return _VERSIONS[name]


def facsimile(page: int, label: str | None = None, cls: str = "leaf") -> str:
    """A link to one leaf of the facsimile, which the page can open in place.

    It is an ordinary link to the Internet Archive's reader and works as one
    with no script at all. `app.js` reads `data-leaf` and, when the reader
    clicks, shows that page's image in a dialog instead of sending them away --
    the image is fetched then and not before, from the one foreign origin the
    Content-Security-Policy admits.
    """
    return (f'<a class="{cls}" href="{ARCHIVE}/page/n{page - 2}/mode/2up" '
            f'data-leaf="{page}" rel="noopener">'
            f"{label or f'full {page}'}</a>")


def jsonld() -> str:
    """The edition described for machines, in the shape the sibling sites use."""
    data = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "Cronicón Mayoricense", "url": f"{SITE}/",
         "inLanguage": "ca",
         "isPartOf": {"@type": "CollectionPage", "name": "Corpus Balear",
                      "url": "https://corpusbalear.org/"}},
        {"@type": "Dataset", "name": "Cronicón Mayoricense — edició digital",
         "description": "Transcripció del Cronicón Mayoricense d'Álvaro "
                        "Campaner (Palma, 1881): notícies de Mallorca de 1229 "
                        "a 1800, amb el grau de certesa de cada paraula.",
         "url": f"{SITE}/", "inLanguage": ["es", "ca", "la"],
         "license": "https://creativecommons.org/licenses/by-nc/4.0/",
         "creator": {"@type": "Person", "name": "Antoni C. Picornell Company"},
         "isBasedOn": {"@type": "Book", "name": "Cronicón Mayoricense",
                       "author": {"@type": "Person",
                                  "name": "Álvaro Campaner y Fuertes"},
                       "datePublished": "1881"},
         "distribution": [{"@type": "DataDownload",
                           "encodingFormat": "application/vnd.apache.parquet",
                           "contentUrl": f"{SITE}/data/entry.parquet"}]}]}
    # `</` cannot appear inside a script element, data block or not.
    return ('<script type="application/ld+json">'
            + json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
            + "</script>")


def head(title: str, description: str, canonical: str, up: str,
         noindex: bool = False, extra: str = "") -> str:
    """Everything before the page's own content.

    `theme.js` comes before the stylesheets and is not deferred: it sets the
    reader's theme on <html> before anything is painted. It is a file rather
    than an inline block because the Content-Security-Policy allows no inline
    script, and `data-root` is there for the same reason -- a script that needs
    to fetch `search/c16.json` from three directories down has no inline
    variable to read the way from.
    """
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    return f"""<!DOCTYPE html>
<html lang="ca" data-root="{up}">
<head>
<meta charset="utf-8">
<title>{esc(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{esc(description)}">
<meta name="color-scheme" content="light dark">
{robots}<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta property="og:locale" content="ca_ES">
<link rel="canonical" href="{esc(canonical)}">
<link rel="icon" href="{up}favicon.svg" type="image/svg+xml">
<script src="{up}{asset('theme.js')}"></script>
<link rel="preload" href="{up}vendor/fonts/ebgaramond-normal-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{up}{asset('vendor/fonts/fonts.css')}">
<link rel="stylesheet" href="{up}{asset('style.css')}">
{extra}</head>
<body>
<a class="skip" href="#main">Salta al contingut</a>
"""


# The places the edition has. The brand is the way home, so "Inici" is not one
# of them; the search box is a form of its own beside these.
NAV = (("anys/", "Anys"),
       ("temes/", "Temes"),
       ("documents/", "Documents"),
       ("jurats/", "Jurats"),
       ("abreviatures/", "Fonts"),
       ("metode.html", "Mètode"))

ICON_SEARCH = ('<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" '
               'fill="none" stroke="currentColor" stroke-width="1.8" '
               'stroke-linecap="round"><circle cx="8.5" cy="8.5" r="5.5"/>'
               '<path d="M13 13l4.5 4.500"/></svg>')
ICON_THEME = ('<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">'
              '<circle cx="10" cy="10" r="7.2" fill="none" stroke="currentColor" '
              'stroke-width="1.6"/><path d="M10 2.800a7.200 7.200 0 0 1 0 14.400z" '
              'fill="currentColor"/></svg>')


def masthead(up: str, here: str = "") -> str:
    """The bar every page carries: the way home, the sections, search, theme.

    The search box is a real form that navigates to `/cerca/?q=…`, so it works
    with scripts off and from any page -- search used to exist on the home page
    and nowhere else.
    """
    current = ' aria-current="page"'
    links = " ".join(
        f'<a href="{up}{href}"{current if href == here else ""}>{label}</a>'
        for href, label in NAV)
    return f"""<header class="site-header">
  <div class="wrap bar">
    <a class="brand" href="{up or './'}">
      <span class="brand-name">Cronicón Mayoricense</span>
      <span class="brand-sub">Campaner · Palma, 1881</span>
    </a>
    <nav class="nav" aria-label="Seccions">{links}</nav>
    <form class="search" action="{up}cerca/" method="get" role="search">
      <label class="vh" for="hq">Cerca dins el Cronicón</label>
      <input type="search" id="hq" name="q" placeholder="Cerca…"
             autocomplete="off" spellcheck="false">
      <button type="submit" aria-label="Cerca">{ICON_SEARCH}</button>
    </form>
    <button class="theme" type="button" id="theme"
            aria-label="Canvia entre tema clar i fosc">{ICON_THEME}</button>
  </div>
</header>
"""


def crumbs(*steps: tuple[str, str | None]) -> str:
    """Where this page sits: (label, href) pairs, the last one with no href."""
    parts = []
    for label, href in steps:
        parts.append(f'<a href="{href}">{esc(label)}</a>' if href
                     else f'<span aria-current="page">{esc(label)}</span>')
    return ('<nav class="crumbs" aria-label="On sou">'
            + ' <span class="sep" aria-hidden="true">›</span> '.join(parts)
            + "</nav>")


GITHUB = "https://github.com/acpicornell/cronicon"
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

# The facsimile, in place. One dialog per page, empty until a reader asks for a
# leaf; the image is created by `app.js` on that click and never before, so a
# reader who does not open it makes no request to the Archive at all. The
# close button is a `method="dialog"` form: it works without a handler.
FACSIMILE_DIALOG = """<dialog id="facs" class="facs" aria-labelledby="facs-title">
  <header>
    <h2 id="facs-title">Full <span id="facs-n"></span> del facsímil</h2>
    <div class="facs-ctl">
      <button type="button" id="facs-prev">← anterior</button>
      <button type="button" id="facs-next">següent →</button>
      <a id="facs-ext" href="https://archive.org/details/CroniconMayoricenseCampaner"
         rel="noopener">a l'Internet Archive</a>
      <form method="dialog"><button>Tanca</button></form>
    </div>
  </header>
  <div class="facs-stage" id="facs-stage"></div>
  <p class="facs-note">Exemplar digitalitzat per Google, servit per l'Internet
     Archive. La imatge es demana ara, en obrir-la.</p>
</dialog>
"""


def foot(up: str, scripts: tuple[str, ...] = ()) -> str:
    """The foot every Corpus Balear edition carries, in the same words.

    Centred, small and quiet, as on the sibling sites (`mapes/mut`, the
    nomenclators): what the edition is, its licence, how to cite it, that it is
    part of the Corpus Balear, and the code. The sections are in the header and
    are not repeated here.
    """
    tags = "".join(f'<script src="{up}{asset(name)}" defer></script>\n'
                   for name in ("app.js", *scripts))
    return f"""<footer class="site-footer">
  <div class="wrap">
    <p>Edició digital del <em>Cronicón Mayoricense</em> d'Álvaro Campaner
       (Palma, 1881), elaborada a partir del facsímil dipositat a Internet
       Archive pel consens de sis reconeixedors independents. Les poques
       lectures fetes directament sobre el facsímil hi van comptades: vegeu
       <a href="{up}metode.html#facsimil">el mètode</a>.</p>
    <p>© 2026 Antoni C. Picornell Company ·
       <a href="https://creativecommons.org/licenses/by-nc/4.0/"
          rel="noopener">CC BY-NC 4.0</a>
       (reutilització no comercial amb atribució). Text original (1881):
       domini públic.</p>
    <p>Com citar: Picornell Company, A. C. <em>Cronicón Mayoricense</em>
       (1881), edició digital. Corpus Balear · cronicon.corpusbalear.org</p>
    <p>Part del <a href="https://corpusbalear.org/" rel="noopener">Corpus
       Balear</a> · edicions digitals de fonts històriques de les Illes
       Balears.</p>
    <p class="foot-links">
      <a href="{GITHUB}" rel="noopener">{GH_ICON}Codi al repositori</a>
      <a href="{ARCHIVE}" rel="noopener">Facsímil a Internet Archive</a>
      <a href="{up}metode.html#dades">Dades en parquet</a>
    </p>
  </div>
</footer>
{FACSIMILE_DIALOG}{tags}</body>
</html>
"""


def page(title: str, description: str, path: str, here: str, body: str, *,
         main: str = "wrap", trail: str = "", scripts: tuple[str, ...] = (),
         noindex: bool = False, extra: str = "", root: str | None = None) -> str:
    """One whole page: head, masthead, `<main>`, foot.

    `path` is the page's own path under the site (`anys/1521/`), and everything
    relative is derived from it, so no page states its own depth. `root`
    overrides that for the one page that is served from any depth, the 404.
    """
    depth = path.count("/")
    up = root if root is not None else "../" * depth
    return (head(title, description, f"{SITE}/{path}", up, noindex, extra)
            + masthead(up, here)
            + f'<main id="main" class="{main}">\n{trail}{body}\n</main>\n'
            + foot(up, scripts))


# How a disputed reading is shown, as the reader last left it. Three states and
# not a checkbox: "hidden" and "marked" were the two there were, and what a
# reader of a critical edition wants is the third -- the rival readings set in
# the line. It is also the only way to them without a pointer: a hover tooltip
# does not exist on a phone or from a keyboard.
DOUBT_CONTROL = """<fieldset class="doubt-ctl">
  <legend>Lectures discutides</legend>
  <label><input type="radio" name="doubt" value="on"> marcades</label>
  <label><input type="radio" name="doubt" value="variants"> amb les variants</label>
  <label><input type="radio" name="doubt" value="off"> amagades</label>
  <p class="note">Un mot <span class="d">puntejat</span> és una lectura en què
     els reconeixedors no es van posar d'acord. Tocant-lo es veu què més s'hi
     va llegir. <a href="{up}metode.html">Com es mesura</a></p>
</fieldset>"""


# Disputed readings are marked by position, in `doubt.py`.


LONG_ENTRY = 1500     # characters before an entry is broken up to be read
PARAGRAPH = 900       # rough target for each piece


class InlineTables:
    """The tables of a run of leaves, set where their rows stand in the prose.

    A table's rows are still in the notice's text, exactly as the panel read
    them -- nothing was moved out. This finds each row there and sets the same
    words as a table row, so the reader sees the figures in the column the
    page put them in.

    **Row by row, not first-row-to-last.** It used to find a table's first row,
    find its last, and replace everything between; so when the assembler broke
    a paragraph in the middle of a table the last row was not in that paragraph
    and only the first was replaced -- by the whole table, whose other rows
    then came again as prose underneath. A ledger of forty rows was printed
    twice. Each row is now found on its own, in its table's order, and rows
    that follow one another with nothing between them are one table.

    One instance per page: a row is set once, and a table that runs across
    several paragraphs carries on where it left off.
    """
    LOOKAHEAD = 3     # rows of a table that may be skipped to find the next

    def __init__(self, rows: list[tuple]) -> None:
        # (table_id, seq, label, figure, tier, text), in table order
        self.tables: dict[int, list[tuple]] = {}
        for row in rows:
            if row[5]:
                self.tables.setdefault(row[0], []).append(row)
        self.at = {tid: 0 for tid in self.tables}

    @staticmethod
    def row_html(label, figure, tier) -> str:
        # One cell per figure, unit or ditto mark, so a ledger's columns line
        # up -- libras, sueldos and dineros under one another -- the way the
        # page sets them.
        cells = "".join(f'<td class="num">{esc(c)}</td>'
                        for c in (figure or "").split())
        klass = ' class="d"' if tier in DOUBTFUL else ""
        return f"<tr{klass}><th>{esc(label or '')}</th>{cells}</tr>"

    def lay_out(self, text: str) -> list[str]:
        """`text` cut where table rows stand in it: prose and `<table>`s."""
        pieces: list[str] = []
        run: list[str] = []
        at = 0

        def flush() -> None:
            if run:
                pieces.append('<table class="inline-table"><tbody>'
                              + "".join(run) + "</tbody></table>")
                run.clear()

        while True:
            best = None
            for tid, rows in self.tables.items():
                for n in range(self.at[tid], min(self.at[tid] + self.LOOKAHEAD,
                                                 len(rows))):
                    found = text.find(rows[n][5], at)
                    if found >= 0 and (best is None or found < best[0]):
                        best = (found, tid, n)
            if best is None:
                break
            found, tid, n = best
            between = text[at:found].strip()
            if between:
                flush()
                pieces.append(between)
            _tid, _seq, label, figure, tier, row_text = self.tables[tid][n]
            run.append(self.row_html(label, figure, tier))
            self.at[tid] = n + 1
            at = found + len(row_text)
        flush()
        if text[at:].strip():
            pieces.append(text[at:].strip())
        return pieces or [text]

    @staticmethod
    def join(markup: str) -> str:
        """Tables that follow one another with nothing between are one table.

        The assembler opens a paragraph wherever the printer indents, and a
        ledger indents the first line of every entry, so a table of forty rows
        arrives as forty paragraphs and would be set as forty tables, each
        with column widths of its own.
        """
        return markup.replace(
            '</tbody></table><table class="inline-table"><tbody>', "")


def tables_on(con, pages) -> InlineTables:
    """The inline tables of these leaves."""
    pages = list(pages)
    if not pages:
        return InlineTables([])
    return InlineTables(con.execute(
        "SELECT table_id, seq, label, figure, tier, text FROM table_row "
        f"WHERE pdf_page IN ({','.join(str(p) for p in pages)}) "
        "ORDER BY table_id, seq").fetchall())


def notemarks(notes, mark) -> str:
    """A notice's footnotes, under it, numbered as the book numbers them.

    Campaner's notes are half the scholarship in the book -- he corrects
    Terrassa's dates, quotes the accounts the notice summarises, and says where
    he found them -- and the site printed the `(1)` in the text with nothing on
    the page for it to point at. `mark` turns a note's text into HTML with its
    disputed readings marked.
    """
    if not notes:
        return ""
    return ('<div class="notes" lang="es" translate="no">'
            + "".join(f'<p><span class="num">({number})</span> {mark(text)}</p>'
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


def century_of(year: int) -> tuple[int, str]:
    """(13..18, roman numeral) of the century Campaner files this year under."""
    for n, (first, last, roman) in enumerate(CENTURIES, 13):
        if first <= year <= last:
            return n, roman
    raise ValueError(year)


def year_page(con, year: int, counts: dict, sigla: dict[str, str],
              doubt: Doubt, window: dict[int, tuple[int, int]]) -> str:
    """A year, in the order the book prints it.

    Ordered by `id`, which is the order the leaves were read, and deliberately
    not by month and day. November 1644 runs 5, 6, 9, 15, 22, 11, 19 in the
    book -- checked against the facsimile, it is Campaner's own disorder --
    and sorting the page by date silently repaired it. This edition leaves his
    errors standing; quietly reordering his notices is the same correction as
    quietly respelling his words. It also puts a notice that states no day back
    where it belongs, under the date it continues, instead of at the head of
    the month.

    Every notice has an address, `#n<id>`: a search hit or a thematic route can
    land on the notice itself rather than at the head of a year with a hundred
    of them. The id is the notice's position in the book, so it is stable for
    as long as the parse is and no longer -- which is why nothing outside this
    build stores one.
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
    # they are Campaner's scholarship, not filler.
    unplaced = con.execute("""
        SELECT DISTINCT f.number, f.text, f.pdf_page FROM footnote f
        WHERE f.entry_id IS NULL AND f.pdf_page IN (
            SELECT pdf_page FROM entry WHERE year = ?)
        ORDER BY f.pdf_page, f.number, f.text""", [year]).fetchall()

    leaves = sorted({e[5] for e in entries})
    inline = tables_on(
        con, set(leaves) | ({opening[4]} if opening else set()))

    # Earlier and later *years with news*. The 44 years the chronicle is silent
    # about keep their page -- a silence is a fact about the book -- but a
    # reader stepping through the 1520s should not have to step through four
    # pages that say there is nothing to read.
    told = sorted(counts)
    earlier = [y for y in told if y < year]
    later = [y for y in told if y > year]
    prev_y = earlier[-1] if earlier else None
    next_y = later[0] if later else None
    c_num, roman = century_of(year)
    decade = year // 10 * 10

    def in_decade(y: int) -> str:
        if y == year:
            return f'<span aria-current="page">{y}</span>'
        if counts.get(y):
            return f'<a href="../{y}/">{y}</a>'
        return (f'<a class="void" href="../{y}/" '
                f'aria-label="{y}, sense notícies">{y}</a>')

    strip = " ".join(in_decade(y) for y in range(decade, decade + 10)
                    if CENTURIES[0][0] <= y <= CENTURIES[-1][1])
    if entries:
        span = (f"full {leaves[0]}" if len(leaves) == 1
                else f"fulls {leaves[0]}–{leaves[-1]}")
        sub = (("1 notícia" if len(entries) == 1
                else f"{num(len(entries))} notícies")
               + " · " + facsimile(leaves[0], f"{span} del facsímil"))
    else:
        sub = "sense notícies datades"

    head_ = f"""<header class="year-head">
  {f'<a class="step" rel="prev" href="../{prev_y}/"><span aria-hidden="true">←</span> {prev_y}</a>' if prev_y else '<span class="step"></span>'}
  <h1 class="numeral">{year}</h1>
  {f'<a class="step" rel="next" href="../{next_y}/">{next_y} <span aria-hidden="true">→</span></a>' if next_y else '<span class="step"></span>'}
</header>
<p class="year-sub">{sub}</p>
<nav class="decade" aria-label="Els anys de la dècada">{strip}</nav>"""

    parts: list[str] = []
    months: list[tuple[str, str]] = []

    # A century opens by naming its witnesses -- `Anales etc. por Terrassa.—
    # Notas sacadas de los libros de la Procuracion Real, por D. B. Jaume…` --
    # and that list is the closest the book comes to a bibliography. It stands
    # at the head of the first year of the century, which is where the book
    # prints it.
    if opening:
        numeral, first, last, sources, leaf = opening
        parts.append(
            '<section class="opening">'
            f"<h2>Segle {esc(numeral)} · {first}–{last}</h2>"
            '<p class="hint">Campaner obre el segle nomenant els manuscrits '
            "que el conten:</p>"
            f'<p lang="es" translate="no">'
            f"{doubt.mark(sources, leaf, leaf).html()}</p>"
            "</section>")

    if not entries:
        # A silence is information, not a hole. For most of the silent years
        # there is no trace of a heading anywhere between the years that
        # bracket them -- Campaner simply had no news. The rest fall inside a
        # stretch of continuous narrative, like the twenty-eight leaves of the
        # Germanía between 1520 and 1525, where the chronicle runs on without
        # stopping to date itself.
        near = " i ".join(
            f'<a href="../{y}/">{y}</a>' for y in (prev_y, next_y) if y)
        parts.append('<p class="empty">El cronista no dóna cap notícia datada '
                     "d'aquest any. Pot ser que no en tingués, o que l'any caigui "
                     "dins d'un relat seguit que no s'atura a datar-se —com els "
                     "vint-i-vuit fulls de la Germania, entre 1520 i 1525.</p>"
                     f'<p class="empty">Els anys amb notícies més propers són '
                     f"{near}.</p>")
    # Read as a chronicle rather than as a stack of forty identical cards: the
    # month rules a section, the day sits in the margin like the marginal date
    # of a manuscript, and the leaf is named once per run instead of on every
    # notice. The month heading is emitted whenever the month *changes* in
    # reading order, never by sorting -- so where Campaner's own months run out
    # of order, the page says so twice rather than tidying it. That is also why
    # the headings are numbered `m1`, `m2`… by appearance and not by month.
    running_month = object()
    running_leaf = None
    # `sense mes` earns its place only where it separates the undated notices
    # from the dated ones. On a year that is undated throughout -- the whole of
    # the thirteenth century is -- it heads a section there is nothing to
    # distinguish it from, and the em dash under it marks an absence twice.
    dated = any(month for _i, month, *_r in entries)

    def leafmark(leaf: int) -> str:
        return ('<p class="leafmark">'
                + facsimile(leaf, f"full {leaf} al facsímil") + "</p>")

    for entry_id, month, day, text, sources, leaf, _printed in entries:
        if month != running_month and (month or dated):
            label = MONTHS.get(month) or "sense mes"
            months.append((f"m{len(months) + 1}", label))
            parts.append(f'<h2 class="month" id="{months[-1][0]}">'
                         f"{esc(label)}</h2>")
            running_month = month
        # The leaf is named once per run of notices that share it, and the run
        # is *not* broken by a month heading: 1644 sits entirely on leaf 429,
        # and flushing on the month printed "full 429" under every month.
        if running_leaf is not None and leaf != running_leaf:
            parts.append(leafmark(running_leaf))
        running_leaf = leaf
        cites = " ".join(cite(s, sigla) for s in (sources or []))
        marked = doubt.mark(text, *window[entry_id])
        when = str(day) if day else ("—" if dated else "§")
        parts.append(
            f'<article class="notice" id="n{entry_id}">'
            f'<p class="when"><a href="#n{entry_id}" '
            f'aria-label="Enllaç a aquesta notícia">{when}</a></p>'
            '<div class="said">'
            '<div lang="es" translate="no">'
            + "".join(
                piece if piece.startswith("<table")
                else f"<p>{marked.html(piece)}</p>"
                for para in paragraphs(text)
                for piece in inline.lay_out(para))
            + "</div>"
            + (f'<p class="prov">{cites}</p>' if cites else "")
            + notemarks(notes.get(entry_id),
                        lambda t: doubt.mark(t, *window[entry_id]).html())
            + "</div></article>")
    if running_leaf is not None:
        parts.append(leafmark(running_leaf))
    if unplaced:
        where = {t: p for _n, t, p in unplaced}
        parts.append(
            '<section class="unplaced"><h2>Notes sense crida</h2>'
            '<p class="hint">Campaner imprimeix aquestes notes en aquests fulls '
            "i la crida que hi remetia —un <em>(1)</em> volat de dos caràcters— "
            "no s'ha pogut llegir, així que no sabem a quina notícia van.</p>"
            + notemarks([(n, t) for n, t, _p in unplaced],
                        lambda t: doubt.mark(t, where[t], where[t]).html())
            + "</section>")

    jump = ("" if len(months) < 2 else
            '<nav class="months" aria-label="Els mesos d\'aquest any">'
            "<h2>Mesos</h2><ol>"
            + " ".join(f'<li><a href="#{anchor}">{esc(label)}</a></li>'
                      for anchor, label in months)
            + "</ol></nav>")
    rail = (f'<aside class="rail">{jump}'
            + DOUBT_CONTROL.format(up="../../") + "</aside>") if entries else ""

    body = (head_ + f'\n<div class="reading">{rail}'
            f'<div class="text">{InlineTables.join("".join(parts))}</div></div>')
    return page(f"{year} · Cronicón Mayoricense",
                f"Notícies de Mallorca de l'any {year} segons el Cronicón "
                "Mayoricense de Campaner (1881).",
                f"anys/{year}/", "anys/", body, main="wrap page",
                trail=crumbs(("Inici", "../../"), ("Els anys", "../"),
                             (f"Segle {roman}", f"../#s{c_num}"),
                             (str(year), None)),
                noindex=not entries)


# How many opening paragraphs may be the section's own heading: the numeral,
# the title, and the `(pág. 71 del texto.)` Campaner puts under it.
HEAD_LINES = 3
# A year standing at the head of a stretch of a document, the way Campaner sets
# it: alone on its line in `Fragmentos… de Mos. Jaume Viquet`, or run into the
# first sentence of the year it opens -- `1637. A 30 Sctembre 1637 prengué
# possesió Don Alonso de Cardona…`. Either way it is a heading and not prose,
# and the documents that are diaries read as a wall without it.
DOC_YEAR = re.compile(r"^\s*(1[2-8]\d\d)\s*[.,]?\s*(?=$|[«\"A-ZÁÉÍÓÚÑ])")


def sourced(paragraph: str, sigla: dict[str, str], marked) -> str:
    """A document paragraph with its source attribution set as chips.

    The diaries Campaner reprints credit their manuscript exactly as the
    chronicle does -- `…y ya se cantaron vísperas en el coro.—M. M.` -- and 132
    of these paragraphs end in one. On a year page that abbreviation is a button
    that gives up the name; here it was a pair of initials in the middle of a
    sentence, which is the state the whole `sigla` machinery exists to fix.

    Lifting it also settles the dash. The engines return the mark before a
    siglum as `—`, `-`, `- ` or nothing at all, so the same attribution was
    printed four ways down one page; the chip carries its own separator, so what
    the reader sees no longer depends on which engine won a punctuation slot.
    The text keeps the panel's reading -- `data/documents/sections/*.txt` and
    the database are untouched. This is how the page is set, not what it says.
    """
    body, sources = parse_entries.lift_sigla(paragraph)
    if not sources:
        return marked.html(paragraph)
    return (marked.html(body) + '<span class="attrib" lang="ca">'
            + "".join(cite(s, sigla) for s in sources) + "</span>")


# The language most of each document is written in, for `lang`: a screen reader
# pronounces by it and a browser hyphenates and offers to translate by it, and
# every page of this site used to claim to be Catalan throughout. The chronicle
# is Spanish; these are the documents that are not. Several are mixed --
# Campaner introduces a Catalan text in Spanish, and section VII carries a
# Latin and Catalan booklet of 1541 inside Spanish notes -- and take the
# language of the bulk of their text.
DOC_LANG = {
    "0114-II-02": "ca", "0114-IV-04": "ca", "0225-II-02": "ca",
    "0311-II-02": "ca", "0311-III-03": "ca", "0311-VI-06": "ca",
    "0478-III-03": "ca", "0478-V-05": "ca", "0478-VI-06": "ca",
    "0478-VII-07": "ca",
}
BLOCKS = {114: "XIV", 225: "XV", 311: "XVI", 478: "XVII", 631: "XVIII"}


def document_page(con, doc, sigla: dict[str, str], doubt: Doubt,
                  before, after) -> str:
    """One of the pieces Campaner reprints in full.

    These are 21% of the edition and had nowhere to live: the index listed them
    in a table of dead rows, so a search hit inside the Centellas letters could
    only be reported, never opened. They are also the part measured worst --
    1 wrong word in 96 against the chronicle's 1 in 706 -- so the page says so
    at the top rather than leaving the reader to assume the two are alike.
    """
    _id, numeral, title, genre, first, last, words, contested, text, block = doc
    lang = DOC_LANG.get(_id, "es")

    paras = [p for p in text.split("\n") if p.strip()]
    # One alignment for the whole document: its paragraphs follow one another
    # down the same leaves, and a short one could not find its own place among
    # forty thousand tokens.
    marks = doubt.mark_many(paras, first, last)
    # Which leaf each paragraph opens on, so a seventeen-leaf document can be
    # traced back to the page from anywhere in it rather than only from its
    # head. Named once per run, as on the year pages.
    at = json.loads((PROJECT / "data" / "documents" / "sections.json").read_text())
    per_para = next((d.get("paragraph_leaves") or [] for d in at
                     if d["id"] == _id), [])
    # The paragraphs Campaner sets centred, which are headings and were being
    # published as prose: the chapter openings of the `Historia de los Reyes`,
    # `LECTOREM.` and `PROHEMI.` in the 1541 reprint, `EL REY.` and `Vt.
    # Claver.` under a royal cédula, `Declaració de Amet, cochero de Berga.`
    # over each deposition.
    heads = set(next((d.get("headings") or [] for d in at
                      if d["id"] == _id), []))
    # The leaves of this document that carry no running text: the engraved
    # plates. Leaf 151 is the genealogical tree of the kings of Mallorca and the
    # section prints its `ESPLICACION` on the leaf after it, so a reader meets
    # the explanation of a diagram the edition never mentions.
    plates = set(range(first, last + 1)) - {
        p for (p,) in con.execute(
            "SELECT DISTINCT pdf_page FROM word WHERE pdf_page BETWEEN ? AND ?",
            [first, last]).fetchall()}

    def platemark(pages) -> str:
        """Where a plate stands, and the way to see it.

        Explaining a genealogical tree and not showing it is absurd, and the
        plate is 1881 and public domain. It is not committed: the page images
        are 1.6 GB in `data/pages/`, gitignored. The Archive serves them over
        IIIF from the same scan this edition cites, so the cost here is a URL
        -- and the image is asked for when the reader opens it, like every
        other leaf, rather than loaded into a page they may never scroll.
        """
        return "".join(
            f'<p class="plate" lang="ca">Làmina gravada · '
            + facsimile(leaf, f"veure el full {leaf}") + "</p>"
            for leaf in pages)

    def leafmark(leaf: int) -> str:
        return ('<p class="leafmark" lang="ca">'
                + facsimile(leaf, f"full {leaf} al facsímil") + "</p>")

    # Campaner numbers the pieces inside two of these sections -- the 21 letters
    # of Gilaberto de Centellas and the 21 of the `Nota de varias ejecuciones` --
    # and that numbering is the only thing that delimits one letter from the
    # next, since the salutation `Molt alt e molt poderos princep e Senyor`
    # recurs inside a letter as readily as at its head. Without it the section
    # is fourteen leaves of unbroken prose. Where the number stands alone in the
    # text it becomes the heading; where the alignment put a word of the
    # salutation in its slot the heading is set above the paragraph instead, so
    # that no word is dropped to print a number.
    pieces = {p: n for n, p in con.execute(
        "SELECT number, paragraph FROM piece WHERE document_id = ? "
        "ORDER BY number", [_id]).fetchall()}
    # The ledgers Campaner sets inside these sections, shown as the columns the
    # page puts them in, exactly as the year pages do. Nothing is moved out of
    # the prose: the same words are set as a table.
    inline = tables_on(con, range(first, last + 1))

    chunks, running = [], None
    # What the reader can jump to: the numbered pieces, the years of a diary
    # and the headings Campaner centres. Collected as the page is laid out, so
    # the list is the page's own structure and nothing is in it that is not.
    contents: list[tuple[str, str, str]] = []
    seen_years: Counter = Counter()
    for i, para in enumerate(paras):
        leaf = per_para[i] if i < len(per_para) else None
        if leaf and running is not None and leaf > running + 1:
            gap = [p for p in range(running + 1, leaf) if p in plates]
            if gap:
                chunks.append(platemark(gap))
        if leaf and leaf != running:
            if running is not None:
                chunks.append(leafmark(running))
            running = leaf
        # The numeral and the title Campaner prints at the head of a section
        # are a heading, not the first two paragraphs of the text. The heading
        # is the numeral, the title as the catalogue records it, and the source
        # note Campaner sets under them. Recognising the title by its shape was
        # tried and fails on the commonest kind -- `Algunas noticias é
        # indicaciones curiosas extraidas…` opens with an ordinary capital --
        # so it is recognised by *being* the title, which is a fact the
        # catalogue already holds.
        flat = " ".join(para.split())
        year = DOC_YEAR.match(flat)
        # No `i >= HEAD_LINES` guard: the first year of a diary sits inside the
        # range reserved for the numeral and the title -- `VI`, the title,
        # `1636.` -- and skipping it left the diary's opening year as a bare
        # paragraph while every later one was a heading. A numeral or a title
        # cannot match DOC_YEAR, so the range needs no protecting.
        if year:
            seen_years[year.group(1)] += 1
            n = seen_years[year.group(1)]
            anchor = f"y{year.group(1)}" + (f"-{n}" if n > 1 else "")
            contents.append((anchor, year.group(1), "year"))
            chunks.append(f'<h3 class="docyear" id="{anchor}">'
                          f"{year.group(1)}</h3>")
            rest = flat[year.end():].strip()
            if rest:
                chunks.append(f'<p id="p{i}">{sourced(rest, sigla, marks[i])}</p>')
            continue
        if i in pieces:
            contents.append((f"n{pieces[i]}", f"Peça {pieces[i]}", "piece"))
            chunks.append(f'<h3 class="piece" id="n{pieces[i]}">'
                          f'<span>{pieces[i]}</span></h3>')
            if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", para):
                continue      # the paragraph *is* the number: it is the heading
        # The first paragraphs that are the numeral, the title and its source
        # note are already the page's <h1> and its subline, so they are not
        # printed a second time as the first lines of the text.
        if i < HEAD_LINES and len(para) < 260 and (
                i == 0 or flat == " ".join(title.split())
                or para.startswith(("«", "(", '"')) or para.isupper()):
            # ...and only what the header already shows verbatim is left
            # out: the bare numeral and the paragraph that *is* the title.
            # Anything else up there -- `(pág. 71 del texto.)`, a title the
            # catalogue records shorter than the book prints it -- stays.
            numeral_only = i == 0 and re.fullmatch(r"[IVXLC .]+", flat)
            if not numeral_only and flat != " ".join(title.split()):
                chunks.append(f'<p id="p{i}" class="dochead">'
                              f"{marks[i].html()}</p>")
            continue
        if i in heads:
            contents.append((f"p{i}", flat[:70] + ("…" if len(flat) > 70 else ""),
                             "head"))
            chunks.append(f'<h3 id="p{i}" class="dochead">'
                          f"{marks[i].html()}</h3>")
            continue
        ident = f' id="p{i}"'
        for piece in inline.lay_out(para):
            if piece.startswith("<table"):
                chunks.append(piece)
            else:
                # The id goes on the first stretch only: a paragraph a ledger
                # cuts in two is still one paragraph, with one address.
                chunks.append(f"<p{ident}>{sourced(piece, sigla, marks[i])}</p>")
                ident = ""

    # …and the plates that stand after the last paragraph, which no gap between
    # two paragraphs can reach: section II of the 18th-century block ends with
    # eight of them.
    if running is not None:
        trailing = [p for p in range(running + 1, last + 1) if p in plates]
        if trailing:
            chunks.append(platemark(trailing))
        chunks.append(leafmark(running))
    # A leaf that turns in the middle of a table: the mark naming the leaf
    # just left goes under the table rather than through it. The account of
    # 1318 runs from leaf 160 on to 161 and its total was cut off from its own
    # rows by `full 160 al facsímil`.
    i = 1
    while i < len(chunks) - 1:
        if (chunks[i].startswith('<p class="leafmark"')
                and chunks[i - 1].startswith("<table")
                and chunks[i + 1].startswith("<table")):
            j = i + 1
            while j < len(chunks) and chunks[j].startswith("<table"):
                j += 1
            chunks[i:j] = chunks[i + 1:j] + [chunks[i]]
            i = j
        else:
            i += 1
    body = InlineTables.join("".join(chunks))

    # A statement of what is missing from the numbering. Two of Centellas'
    # twenty-one numbers were not recovered -- leaf 134's is on the page and no
    # engine returned it at all -- and a reader counting the letters is owed
    # that rather than left to wonder.
    gap_note = ""
    if pieces:
        got = sorted(pieces.values())
        gaps = [n for n in range(1, got[-1] + 1) if n not in set(got)]
        if gaps:
            gap_note = (f'<p class="note">Campaner numera {got[-1]} peces; '
                        f"{'el número' if len(gaps) == 1 else 'els números'} "
                        + ", ".join(str(n) for n in gaps)
                        + " no s'ha pogut llegir en cap dels vuit motors, així "
                        "que la peça comença on ho fa el text.</p>")
    toc = ""
    if len(contents) >= 3:
        toc = ('<nav class="toc" aria-label="Contingut del document">'
               "<h2>Contingut</h2><ol>"
               + "".join(f'<li class="t-{kind}"><a href="#{anchor}" lang="{lang}">'
                         f"{esc(label)}</a></li>"
                         for anchor, label, kind in contents)
               + f"</ol>{gap_note}</nav>")
    # Campaner's own apparatus, set smaller as the book sets it. They are where
    # he says which manuscript a passage comes from and where he corrects it.
    notes = con.execute(
        "SELECT number, text, pdf_page FROM footnote WHERE document_id = ? "
        "ORDER BY pdf_page, number", [_id]).fetchall()
    docnotes = ("" if not notes else
                '<section class="docnotes"><h2>Notes de Campaner</h2>'
                + "".join(f'<p><span class="num">({n})</span> '
                          f'<span lang="es" translate="no">'
                          f"{doubt.mark(t, p, p).html()}</span> "
                          + facsimile(p, f"full {p}", "leafref") + "</p>"
                          for n, t, p in notes)
                + "</section>")

    def step(row, rel: str, arrow: str) -> str:
        if not row:
            return '<span class="step"></span>'
        label = esc(row[2][:60] + ("…" if len(row[2]) > 60 else ""))
        inner = (f'<span aria-hidden="true">←</span> {label}' if rel == "prev"
                 else f'{label} <span aria-hidden="true">→</span>')
        return f'<a class="step" rel="{rel}" href="../{esc(row[0])}/">{inner}</a>'

    span = f"full {first}" if first == last else f"fulls {first}–{last}"
    share = pct(100 * contested / words if words else 0)
    body = f"""<header class="doc-head">
  <p class="kicker">Segle {BLOCKS.get(block, '')} · secció {esc(numeral)}</p>
  <h1 lang="{lang}" translate="no">{esc(title)}</h1>
  <p class="year-sub">{num(words)} mots · {share}% discutits ·
     {facsimile(first, f"{span} del facsímil")}</p>
</header>
<p class="caveat">Els documents són la part del llibre pitjor mesurada:
   <strong>un mot errat de cada 96</strong>, contra un de cada 706 a la
   crònica. Molts són en català medieval i en llatí, i els reconeixedors hi
   van pitjor. <a href="../../metode.html">Com se sap?</a></p>
<div class="reading">
  <aside class="rail">{toc}{DOUBT_CONTROL.format(up="../../")}</aside>
  <div class="text">
    <div class="doc" lang="{lang}" translate="no">{body}</div>
    {docnotes}
    <nav class="pager" aria-label="Altres documents">
      {step(before, "prev", "←")}{step(after, "next", "→")}
    </nav>
  </div>
</div>"""
    return page(f"{numeral}. {title} · Cronicón Mayoricense",
                f"{title} — {genre or 'document'} reproduït sencer al Cronicón "
                f"Mayoricense de Campaner (1881), fulls {first}–{last}.",
                f"documents/{_id}/", "documents/", body, main="wrap page",
                trail=crumbs(("Inici", "../../"), ("Els documents", "../"),
                             (f"{numeral} · segle {BLOCKS.get(block, '')}", None)))


CENTURIES = ((1229, 1300, "XIII"), (1301, 1400, "XIV"), (1401, 1500, "XV"),
             (1501, 1600, "XVI"), (1601, 1700, "XVII"), (1701, 1800, "XVIII"))
BAR_MIN, BAR_MAX = 4, 52
STRIP_H, STRIP_CELL = 56, 10


def year_label(year: int, n: int) -> str:
    if not n:
        return f"{year} · cap notícia"
    return f"{year} · 1 notícia" if n == 1 else f"{year} · {num(n)} notícies"


def density(counts: dict, first: int, last: int, peak: int, up: str) -> str:
    """One stretch of years as a strip of bars, height by how much news.

    Replaces 572 identical boxes that filled a 7 500px page and said nothing:
    every year looked the same, and the only signal -- the count -- was six
    points of type underneath. As bars the same data becomes the shape of the
    chronicle, and the eye lands on 1715 without being told.

    **Square root, not linear.** The distribution is savage: median 4 notices,
    peak 108 in 1715. Scaled linearly the median year is a 2px stub against a
    52px spike and half the book reads as empty, which is false -- it is a
    chronicle of ordinary years with a few violent ones.

    **Drawn as SVG, with the height in an attribute.** It used to be 572 `<a>`
    with `style="height:…"`, and the site's own Content-Security-Policy forbids
    inline styles: deployed, every bar would have collapsed to nothing. An SVG
    `height` is geometry, not style, and needs no exception.

    The strip is a picture and a pointer target; it is hidden from assistive
    technology and kept out of the tab order, because the decade rows beneath
    it are the same links as text. A year with no news keeps a stub rather than
    vanishing: it is still a fact about the book.
    """
    out = []
    for k, year in enumerate(range(first, last + 1)):
        n = counts.get(year, 0)
        h = (BAR_MIN + round((BAR_MAX - BAR_MIN) * math.sqrt(n / peak))
             if n else 2)
        x = k * STRIP_CELL
        out.append(
            f'<a href="{up}anys/{year}/" tabindex="-1">'
            f"<title>{esc(year_label(year, n))}</title>"
            # `fill` as an attribute, so the strip is still a strip of bars if
            # the stylesheet is missing or stale: an SVG shape with no fill is
            # black, and 572 full-height hit areas are one black block.
            f'<rect class="hit" x="{x}" y="0" width="{STRIP_CELL}" '
            f'height="{STRIP_H}" fill="none" pointer-events="all"/>'
            f'<rect class="bar{"" if n else " void"}" x="{x + 1}" '
            f'y="{STRIP_H - h}" width="{STRIP_CELL - 2}" height="{h}" '
            f'fill="currentColor"/></a>')
    return (f'<svg class="strip" viewBox="0 0 {(last - first + 1) * STRIP_CELL} '
            f'{STRIP_H}" preserveAspectRatio="none" aria-hidden="true">'
            + "".join(out) + "</svg>")


def years_page(con, counts: dict) -> str:
    peak = max(counts.values()) or 1
    blocks = []
    for c_num, (first, last, roman) in enumerate(CENTURIES, 13):
        told = sum(counts.get(y, 0) for y in range(first, last + 1))
        silent = sum(1 for y in range(first, last + 1) if not counts.get(y))
        rows = []
        for decade in range(first // 10 * 10, last + 1, 10):
            cells = []
            for year in range(max(decade, first), min(decade + 9, last) + 1):
                n = counts.get(year, 0)
                cells.append(
                    f'<a href="{year}/">{year} <small>{n}</small></a>' if n else
                    f'<a class="void" href="{year}/" '
                    f'aria-label="{year}, sense notícies">{year}</a>')
            # A century starts on its --01, so the decade row of 1300 exists
            # twice: the year 1300 closes the thirteenth and 1301-09 open the
            # fourteenth. Each row is named by the first year it holds.
            opens = max(decade, first)
            rows.append(f'<li id="d{opens}"><span class="dec">{opens}</span> '
                        f'<span class="yrs">{" ".join(cells)}</span></li>')
        blocks.append(f"""
  <section class="century" id="s{c_num}">
    <h2>Segle {roman} <small>{first}–{last} · {num(told)} notícies ·
        {num(silent)} anys sense cap</small></h2>
    {density(counts, first, last, peak, "../")}
    <ol class="decades">{"".join(rows)}</ol>
  </section>""")
    jump = " ".join(f'<a href="#s{c}">Segle {roman}</a>'
                   for c, (_f, _l, roman) in enumerate(CENTURIES, 13))
    body = f"""<header class="page-head">
  <h1>Els anys</h1>
  <p class="lede">De la conquesta de 1229 fins al 1800, any per any. Cada barra
     és un any i l'alçada diu quantes notícies en dona Campaner.</p>
</header>
<nav class="jump" aria-label="Segles">{jump}</nav>
<p class="hint">L'escala és d'arrel quadrada: 1715 té {num(peak)} notícies i la
   majoria d'anys en tenen quatre, i amb escala lineal mig llibre semblaria
   buit. Els anys sense cap notícia queden com un traç, perquè també són una
   dada; a les files de sota surten en gris.</p>
{"".join(blocks)}"""
    return page("Els anys · Cronicón Mayoricense",
                "Els 572 anys del Cronicón Mayoricense, segle a segle, amb "
                "quantes notícies dona Campaner de cadascun.",
                "anys/", "anys/", body,
                trail=crumbs(("Inici", "../"), ("Els anys", None)))


def documents_page(con) -> str:
    docs = con.execute(
        "SELECT id, numeral, title, genre, first_leaf, last_leaf, words, "
        "contested, block_leaf FROM document "
        "ORDER BY block_leaf, first_leaf, id").fetchall()
    total = num(sum(d[6] for d in docs))
    sections = []
    for block, roman in BLOCKS.items():
        cards = "".join(
            f'<a class="card doc-card" href="{esc(i)}/">'
            f'<span class="tag">secció {esc(n)}</span> '
            f'<strong lang="{DOC_LANG.get(i, "es")}" translate="no">{esc(t)}</strong> '
            f'<span class="meta">fulls {a}–{b} · {num(w)} mots · '
            f"{pct(100 * c / w if w else 0)}% discutits</span></a>"
            for i, n, t, _g, a, b, w, c, bl in docs if bl == block)
        if cards:
            sections.append(f'<section class="century"><h2>Segle {roman}</h2>'
                            f'<div class="cards">{cards}</div></section>')
    body = f"""<header class="page-head">
  <h1>Els documents</h1>
  <p class="lede">Al final de cada segle la crònica s'atura i Campaner
     reprodueix documents sencers: cartes, sentències, relacions i dietaris.
     Són {len(docs)} peces i {total} mots, una cinquena part del llibre.</p>
</header>
<p class="hint">Són en castellà, català medieval i llatí, i és la part pitjor
   mesurada — <a href="../metode.html">un mot errat de cada 96</a>, contra un
   de cada 706 a la crònica.</p>
{"".join(sections)}"""
    return page("Els documents · Cronicón Mayoricense",
                f"Els {len(docs)} documents que Campaner reprodueix sencers dins "
                "el Cronicón Mayoricense: cartes, sentències, relacions i "
                "fragments en castellà, català medieval i llatí.",
                "documents/", "documents/", body, main="wrap column",
                trail=crumbs(("Inici", "../"), ("Els documents", None)))


# Twelve sigla carry 84% of the attributions; the rest are pooled. Nine was
# the first cut and it was wrong: `M. S.` alone has 98 attributions, most of
# them in the fifteenth century, and pooling it drew a large anonymous grey
# block over exactly the stretch the chart is meant to explain. The order here
# is the order of the bands; their colours are `--band-0`…`--band-11` in
# style.css, one set for each theme.
BANDS = ("G. T.", "B. J.", "M. M.", "G. V.", "G. F.", "J. F.",
         "J. V.", "Jn. Br.", "L. V.", "M. S.", "Cl. Fl.", "N. F.")
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

    Every colour is a class (`band-3`), defined once in `style.css` for the
    light theme and once for the dark. They used to be hex values in `style`
    attributes, which the Content-Security-Policy blocks and a dark theme
    cannot reach.
    """
    decades, per, total = sources_by_decade(con)
    index = {band: k for k, band in enumerate(BANDS)}
    peak = max(sum(per[d].values()) for d in decades)
    step = CHART_W / len(decades)

    cells, bars, ticks = [], [], []
    for i, decade in enumerate(decades):
        counts = per[decade]
        volume = sum(counts.values())
        x = i * step
        height = max(1.0, VOL_H * volume / peak)
        bars.append(f'<rect class="vol" x="{x:.2f}" y="{VOL_H - height:.2f}" '
                    f'width="{step:.2f}" height="{height:.2f}">'
                    f"<title>{decade}s · {num(volume)} atribucions</title></rect>")
        y = 0.0
        rest = sum(n for band, n in counts.items() if band not in index)
        for band, n in [(b, counts.get(b, 0)) for b in BANDS] + [(None, rest)]:
            if not n:
                continue
            h = CHART_H * n / volume
            name = sigla.get(band, band) if band else "altres fonts"
            klass = f"band-{index[band]}" if band else "band-other"
            cells.append(
                f'<rect class="band {klass}" x="{x:.2f}" y="{y:.2f}" '
                f'width="{step:.2f}" height="{h:.2f}">'
                f"<title>{decade}s · {esc(name)} · {num(n)} de {num(volume)} "
                f"({pct(100 * n / volume)}%)</title></rect>")
            y += h
        # The axis is HTML, not SVG text: the chart is stretched to the width
        # of the page with preserveAspectRatio="none", which would stretch the
        # lettering with it. One equal cell per decade, labelled at the turn of
        # each century, so the labels sit under their bars with no position
        # written into the markup.
        ticks.append(f"<span>{decade if decade % 100 == 0 else ''}</span>")

    legend = "".join(
        f'<a class="key" href="{slug(band)}/"><span class="swatch band-{k}"></span>'
        f"{esc(band)} <small>{esc(sigla.get(band, ''))}</small></a>"
        for k, band in enumerate(BANDS))
    rest = sum(n for b, n in total.items() if b not in index)
    legend += ('<span class="key"><span class="swatch band-other"></span>'
               f"altres <small>{num(rest)} atribucions</small></span>")

    return f"""
  <figure class="chart">
    <svg viewBox="0 0 {CHART_W} {VOL_H + 6}" preserveAspectRatio="none"
         class="volume" role="img"
         aria-label="Quantes atribucions duu cada dècada">
      {''.join(bars)}
    </svg>
    <svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none"
         class="stack" role="img"
         aria-label="Quina font reporta cada dècada, de {decades[0]} a {decades[-1] + 9}">
      {''.join(cells)}
    </svg>
    <div class="ticks" aria-hidden="true">{''.join(ticks)}</div>
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
    years = " ".join(f'<a href="../../anys/{y}/">{y} <small>{n}</small></a>'
                    for y, n in rows)
    first, last = (rows[0][0], rows[-1][0]) if rows else (0, 0)
    query = "../../cerca/?f=" + quote(siglum)
    body = f"""<header class="page-head">
  <p class="kicker">Font · {esc(siglum)}</p>
  <h1 lang="es" translate="no">{esc(named.rstrip('.'))}</h1>
</header>
{dossier(record)}
<h2>On el cita el Cronicón</h2>
<p class="hint">Campaner li atribueix <strong>{num(total)}</strong> notícies,
   repartides en {num(len(rows))} anys entre {first} i {last}.
   <a href="{query}">Llegeix-les totes a la cerca</a>, o tria un any:</p>
<div class="yeargrid">{years}</div>"""
    return page(f"{siglum} · {named} · Cronicón Mayoricense",
                f"Les {num(total)} notícies que Campaner atribueix a "
                f"{named} al Cronicón Mayoricense.",
                f"abreviatures/{slug(siglum)}/", "abreviatures/", body,
                main="wrap column",
                trail=crumbs(("Inici", "../../"), ("Les fonts", "../"),
                             (siglum, None)))


# Campaner writes a Jurat's trade after a comma -- `Juan Sala, perayre` -- for
# 341 of the 1 979 names. It is the most interesting column in the table and the
# easiest to mistake for a surname: taking the last word of the name makes
# `perayre` the commonest family in Mallorca, with 70 seats.
CENTURY_NAMES = {13: "XIII", 14: "XIV", 15: "XV", 16: "XVI", 17: "XVII",
                 18: "XVIII"}

# Campaner writes a Jurat's trade after a comma -- `Juan Sala, perayre` -- and
# reading all 2 436 names off the facsimile showed where: **always against the
# sixth seat.** The first is the knight's (`caballero`, `doncel`, `miles`), the
# second and third the citizens' and jurists' (`Dr. en leyes`), and the sixth
# the menestral's; not one trade stands against any other seat. So the trades
# are not a property of "the Jurats", they are the sixth Jurat.
ARTISAN_SEAT = 6
# One trade, several spellings. Only spellings are merged -- `perayre` and
# `peraire` are one word set two ways -- never two words for what may be the
# same craft: `apotecari`, `especiayre` and `boticario` stay three rows,
# because whether an apothecary and a spicer were one guild in 1460 is a
# historian's call and not a chart's. Each row is named by the form Campaner
# prints most and lists the others.
TRADE_SPELLINGS = {
    "peraire": "perayre", "pelliser": "pellisser",
    "cirurgiá": "chirurgiá", "chirurgià": "chirurgiá",
    "teixidor": "texidor", "menescal": "manescal",
    "picapedras": "picapedrer", "sellater": "selleter", "jerrer": "jarrer",
    "speciayre": "especiayre", "spicier": "especiayre",
    "notari y menestral": "notari",
}
BAR_W, BAR_H = 150, 12


def artisan_trades(con) -> tuple[list[dict], dict[int, tuple[int, int]]]:
    """The sixth seat's trades, commonest first, and how often one is stated.

    Returns the rows -- trade, the spellings printed, a count per century --
    and, per century, (sixth Jurats, of them with a trade). The second half is
    what keeps the chart honest: before 1500 Campaner's sources name the trade
    for a third to two thirds of them, and after it for every one, so a trade
    that looks rare in the fourteenth century may only be unrecorded.
    """
    rows = con.execute(
        "SELECT century, name FROM jurat WHERE seat = ? AND tier <> 'remark' "
        "ORDER BY id", [ARTISAN_SEAT]).fetchall()
    stated: dict[int, list[int]] = {}
    trades: dict[str, dict] = {}
    for century, name in rows:
        seen = stated.setdefault(century, [0, 0])
        seen[0] += 1
        if "," not in name:
            continue
        seen[1] += 1
        # The trade is what follows the last comma: `Miguel Fiol, menor,
        # forner` is a baker, and `menor` tells him from his father.
        printed = name.rsplit(",", 1)[1].strip().rstrip(".")
        form = printed[0].lower() + printed[1:]
        trade = trades.setdefault(
            TRADE_SPELLINGS.get(form, form),
            {"forms": Counter(), "by": Counter(), "n": 0})
        trade["forms"][form] += 1
        trade["by"][century] += 1
        trade["n"] += 1
    out = [dict(trade=t, **v) for t, v in trades.items()]
    out.sort(key=lambda r: (-r["n"], r["trade"]))
    return out, {c: tuple(v) for c, v in sorted(stated.items())}


def trades_chart(con) -> str:
    """Ranked bars, one hue, with the figures per century beside them.

    More than twenty trades, so not a stacked chart of twenty colours: a bar on
    a common baseline compares exactly, and the table beside it is the split by
    century in figures. Every number the bars encode is printed in the row, so
    nothing is carried by the picture alone. The bar's length is an SVG
    attribute, not a style.
    """
    trades, stated = artisan_trades(con)
    centuries = sorted(stated)
    shown = [t for t in trades if t["n"] >= 2]
    once = [t for t in trades if t["n"] == 1]
    peak = shown[0]["n"]
    total = sum(t["n"] for t in trades)

    def row(t: dict) -> str:
        others = [f for f in t["forms"] if f != t["trade"]]
        also = (f' <small>també {", ".join(esc(f) for f in sorted(others))}'
                "</small>" if others else "")
        width = max(2, round(BAR_W * t["n"] / peak))
        cells = "".join(
            f'<td class="num">{t["by"][c] or ""}</td>' for c in centuries)
        return (f'<tr><th scope="row" lang="ca" translate="no">'
                f'{esc(t["trade"])}{also}</th>'
                f'<td class="barcell"><svg width="{BAR_W}" height="{BAR_H}" '
                f'viewBox="0 0 {BAR_W} {BAR_H}" aria-hidden="true">'
                f'<rect width="{width}" height="{BAR_H}" rx="3" '
                f'fill="currentColor"><title>{esc(t["trade"])} · {t["n"]}'
                f'</title></rect></svg></td>'
                f'<td class="num total">{t["n"]}</td>{cells}</tr>')

    head = "".join(f'<th scope="col" class="num">{CENTURY_NAMES[c]}</th>'
                   for c in centuries)
    recorded = "".join(
        f'<td class="num">{have} de {seats}</td>'
        for seats, have in (stated[c] for c in centuries))
    rest = ", ".join(
        f'<span lang="ca" translate="no">{esc(t["trade"])}</span>' for t in once)
    return f"""<figure class="trades">
  <div class="scroll"><table class="ranked">
    <caption>Oficis del sisè jurat, tal com els escriu Campaner, per segle</caption>
    <thead><tr><th scope="col">ofici</th><th scope="col"><span class="vh">proporció</span></th>
      <th scope="col" class="num">total</th>{head}</tr></thead>
    <tbody>{"".join(row(t) for t in shown)}</tbody>
    <tfoot><tr><th scope="row" colspan="3">sisens jurats amb l'ofici anotat</th>
      {recorded}</tr></tfoot>
  </table></div>
  <figcaption>{num(total)} sisens jurats amb ofici, en {len(trades)} oficis.
    Un sol cop hi surten: {rest}. S'han ajuntat només les grafies d'un mateix
    mot (<em>perayre</em> i <em>peraire</em>), no els oficis que podrien ser el
    mateix (<em>apotecari</em>, <em>especiayre</em>, <em>boticario</em>).</figcaption>
</figure>"""


def jurats_index(con) -> str:
    """The six series, and who sat in them.

    The Jurats governed the Ciutat i Regne, six of them at a time, replaced
    every year at Christmas under a privilege of Jaume I given on 7 July.
    Campaner's source dates it 1240 and the historiography 1249; the page says
    both rather than choose, since the edition does not correct the book and
    must not repeat its errors as fact either. Campaner prints
    the lists as appendices inside the body and they are the hardest leaves in
    the book: only a quarter of these names are read the same way by all six
    engines, which the page has to say rather than imply.
    """
    series = con.execute("""
        SELECT century, count(*) FILTER (WHERE tier <> 'remark'), min(year),
               max(year), count(DISTINCT year),
               count(*) FILTER (WHERE tier = 'adjudicated')
        FROM jurat GROUP BY 1 ORDER BY 1""").fetchall()
    tiers = dict(con.execute(
        "SELECT tier, count(*) FROM jurat WHERE tier <> 'remark' "
        "GROUP BY 1 ORDER BY 1").fetchall())
    total = sum(tiers.values())
    checked = tiers.get("adjudicated", 0)
    panel = total - checked
    typed = con.execute(
        "SELECT count(*) FROM jurat WHERE source = 'typed'").fetchone()[0]
    # What a reader may rely on, said for the state the lists are actually in.
    trust = (
        f"<p><strong>Per això els {num(total)} noms s'han llegit directament "
        "del facsímil</strong>, full per full i any per any, i cada un s'ha "
        "comparat amb el que n'havia llegit cada reconeixedor. "
        f"{num(checked - typed)} coincideixen lletra per lletra amb la lectura "
        f"d'algun motor; els altres {num(typed)} duen una lletra volada "
        "(<em>B.ª</em>, <em>Mig.<sup>l</sup></em>) que cap motor no reprodueix. "
        "Res no s'hi ha corregit: les errades d'impremta de Campaner hi són "
        "tal com les va deixar.</p>"
        if not panel else
        f"<p><strong>{num(checked)} dels {num(total)} noms s'han llegit "
        "directament del facsímil</strong>, any per any, i cada un s'ha "
        "comparat amb el que n'havia llegit cada reconeixedor: van sense "
        f"marca. Dels altres {num(panel)}, només "
        f"{num(tiers.get('unanimous', 0))} els llegeixen igual els sis motors; "
        "porten el seu grau i els discutits van marcats.</p>"
        '<p class="aside">Un nom marcat no vol dir que sigui erroni: vol dir '
        "que no s'ha comprovat contra el facsímil i que els reconeixedors no "
        "hi van coincidir del tot.</p>")

    blocks = "".join(
        f'<a class="card" href="{c}/">'
        f'<span class="tag">Segle {CENTURY_NAMES[c]}</span>'
        f"<strong>{num(n)} noms</strong>"
        f'<span class="meta">{first}–{last} · {years} anys documentats</span> '
        + ('<span class="n">llegits del facsímil</span>' if read == n
           else f'<span class="n">{num(read)} llegits del facsímil</span>' if read
           else '<span class="n">lectura dels reconeixedors</span>')
        + "</a>"
        for c, n, first, last, years, read in series)

    _trades, stated = artisan_trades(con)
    early = [c for c in stated if stated[c][1] < stated[c][0]]

    body = f"""<header class="page-head">
  <p class="kicker">Els qui governaven</p>
  <h1>{num(total)} jurats, de 1240 a 1715</h1>
  <p class="lede">Durant gairebé cinc segles, la Ciutat i Regne de Mallorca
     el governaren sis jurats que es renovaven cada any per Nadal. Campaner
     en dona els noms segle a segle, en sis llistes que imprimeix com a
     apèndix dins el cos del llibre.</p>
</header>
<div class="cards">{blocks}</div>

<section class="matter">
  <h2>Què eren els jurats</h2>
  <p>La Universitat de la Ciutat i Regne de Mallorca —l'illa sencera com a
     comunitat, no només Palma— tenia al capdavant sis magistrats d'un any. El
     càrrec era obligatori i gratuït: qui sortia elegit no el podia refusar ni
     en treia cap sou. Cada seient corresponia a un estament, i la presidència
     anava sempre al primer: <strong>un cavaller</strong>; després,
     <strong>dos ciutadans</strong>, <strong>dos mercaders</strong> i, en el
     sisè lloc, <strong>un menestral</strong>. Campaner ho resumeix així:
     <q lang="es" translate="no">desde entonces acostumbraron ser un
     caballero, dos ciudadanos, dos mercaderes y un artista</q>.</p>
  <p>Qui llegeixi la crònica els trobarà a cada pàgina: hi surten al costat dels
     morbers quan hi ha por de contagi, fent venir blat en els anys de
     carestia, armant galeres, anant a la Seo darrere les banderes dels
     gremis per cantar un Te-Deum, o sortint amb les maces alçades a
     reunir el consell de guerra. Es reunien a la Casa de la Juraria,
     a Cort, el mateix lloc on avui hi ha l'Ajuntament de Palma.</p>

  <h3>Quan comencen</h3>
  <p>Els creà Jaume I amb un privilegi donat a València el 7 de juliol. La
     font que Campaner copia el data <strong>el 1240</strong>
     (<a href="../anys/1240/">notícia de 1240</a>); la historiografia el
     situa <strong>el 1249</strong>. El mateix Campaner hi dona motius de
     dubte: a la seva llista, els noms de 1240 i de 1245 només els dona algun
     catàleg antic i Bonet no en posa cap, i els set de 1248, diu, el seu informant els anomena
     <q lang="es" translate="no">Cónsules de Mallorca</q>,
     <q lang="es" translate="no">pues en este año todavía no se habían
     instituido los Jurados</q>.</p>
  <p>Ell mateix avisa que la llista és insegura fins al darrer terç del
     segle XIV: no va anar als arxius, sinó que confronta la llista del
     P. Villafranca, que recull les de catàlegs anteriors, amb les notes de
     l'arxiver de l'Audiència Miguel Bonet, de qui es fia més. Per això les
     llistes dels segles XIII i XIV porten anys buits, anys amb noms de més i
     comentaris com <q lang="es" translate="no">Villafranca no pone
     ninguno</q>.</p>

  <h3>Com s'elegien</h3>
  <p>El sistema va canviar més d'un cop. Durant el primer segle i mig, els
     sis que plegaven per Nadal triaven ells mateixos els sis que entraven:
     és el que s'anomena <em>franquesa</em>. Cap al tombant del 1400 s'hi
     barrejà l'atzar amb els vots del Gran i General Consell, amb diverses
     fórmules que es feien i es desfeien; el 1444, breument, es recuperà la
     cooptació. La solució que va quedar, des de 1447 i fins al final, fou la
     <em>insaculació</em> o <em>sac i sort</em>: cada estament tenia la seva
     bossa amb els noms dels qui podien ser jurats, i cada any se'n treia un
     a l'atzar. La llista en guarda el rastre: Campaner imprimeix dues eleccions
     el 1401 —la segona encapçalada <q lang="es" translate="no">1401 (en 7 de
     julio.)</q>— i dues el 1444, l'any del canvi de règim —la segona,
     <q lang="es" translate="no">1444 en 23 junio.</q></p>

  <h3>Quan acaben</h3>
  <p>La derrota austriacista va portar la Nova Planta, signada el 28 de
     novembre de 1715, i amb ella el model castellà de regidors designats per
     la corona. Els darrers noms que Campaner copia són els de 1715. La
     institució, però, no es va extingir de cop: va sobreviure tres anys més,
     provisionalment, i no es va abolir formalment fins al 22 de juliol de
     1718.</p>
  <p class="aside">Fonts d'aquest apartat, a més del mateix Campaner:
     <a href="https://ca.wikipedia.org/wiki/Jurats_de_la_Ciutat_i_Regne_de_Mallorca"
        rel="noopener">«Jurats de la Ciutat i Regne de Mallorca»</a>, Viquipèdia,
     i Antonio Planas Rosselló, <cite>Los jurados de la Ciudad y Reino de
     Mallorca (1249-1718)</cite>, 2005.</p>
</section>

<section class="matter">
  <h2>El sisè jurat: l'ofici del menestral</h2>
  <p>A la llista de Campaner el primer seient és el del cavaller o donzell,
     el segon i el tercer els dels ciutadans —molts, doctors en lleis— i
     <strong>el sisè, el del menestral</strong>.
     Campaner n'escriu l'ofici darrere una coma, i a la llista només en porta
     aquest seient: cap ofici no surt en cap dels altres cinc.</p>
  {trades_chart(con)}
  <p class="aside">Abans de 1500 l'ofici no hi és sempre: les fonts de
     Campaner el donen per a
     {" i ".join(f"{stated[c][1]} dels {stated[c][0]} sisens jurats del segle {CENTURY_NAMES[c]}" for c in early if stated[c][1] > 1)},
     i després per a tots. Un ofici que sembla rar al segle XIV potser només
     és que no es va anotar.</p>
  <p class="aside">No es compta aquí qui va repetir càrrec, perquè la llista
     dona noms i no persones: <span lang="es" translate="no">Pedro Net</span>
     hi surt deu vegades entre 1363 i 1586, que són avis, fills i nets del
     mateix nom.</p>
</section>

<section class="matter">
  <h2>Quant se'n pot refiar</h2>
  <p>Aquests fulls són els més difícils del llibre per als reconeixedors:
     llistes atapeïdes en columnes, on no es posen d'acord sobre l'ordre de
     lectura, i els noms acabaven sota l'any que no era o es perdien.</p>
  {trust}
</section>"""
    return page("Els jurats · Cronicón Mayoricense",
                f"Els {num(total)} jurats de la Ciutat i Regne de Mallorca que "
                "Campaner llista, de 1240 a 1715, amb el grau de certesa de "
                "cada nom.",
                "jurats/", "jurats/", body, main="wrap column",
                trail=crumbs(("Inici", "../"), ("Els jurats", None)))


def jurats_century(con, century: int) -> str:
    """One century's series, year by year, six seats to the card.

    Two grades of doubt here and only here. Everywhere else a single dissenting
    engine is not worth a mark -- it is right 99% of the time on prose -- but
    these leaves are where the panel is weakest: 719 of the 1 984 names have
    one dissenter, and a name is exactly the kind of word a reader will copy
    into a genealogy. So one dissent is shown faintly and two or more as
    everywhere else, and the page says which is which.
    """
    rows = con.execute(
        "SELECT year, seat, name, tier, pdf_page FROM jurat "
        "WHERE century = ? ORDER BY id", [century]).fetchall()
    by_year: dict[int, list] = {}
    for year, seat, name, tier, leaf in rows:
        by_year.setdefault(year, []).append((seat, name, tier, leaf))

    dated = {r[0] for r in con.execute(
        "SELECT DISTINCT year FROM entry WHERE year IS NOT NULL").fetchall()}

    def grade(tier: str) -> str:
        if tier in DOUBTFUL:
            return ' class="d"'
        return ' class="d1"' if tier == "one-dissent" else ""

    read = sum(1 for r in rows if r[3] == "adjudicated")
    names = sum(1 for r in rows if r[3] != "remark")

    out = []
    for year, seats in sorted(by_year.items()):
        link = (f'<a href="../../anys/{year}/">{year}</a>'
                if year in dated else str(year))
        # In the order the leaf has them, because a year is not always one
        # list of six: 1401 is printed twice -- `1401.` and then `1401 (EN 7 DE
        # JULIO.)`, a second election -- and a sentence may stand in place of
        # names (`Los del año anterior.`) or between two sets of them. `value`
        # is the seat Campaner numbers: a year may fill the third and the sixth
        # and leave the rest blank, and the list must say so.
        parts, run = [], []

        def flush() -> None:
            if run:
                parts.append('<ol class="seats" lang="es" translate="no">'
                             + " ".join(run) + "</ol>")
                run.clear()

        for seat, name, tier, _p in seats:
            if tier == "remark":
                flush()
                parts.append('<p class="remark" lang="es" translate="no">'
                             f"{esc(name)}</p>")
            else:
                run.append(f'<li value="{seat}"{grade(tier)}>{esc(name)}</li>')
        flush()
        leaves = sorted({p for _s, _n, _t, p in seats})
        marks = " · ".join(facsimile(p) for p in leaves)
        out.append(f'<article class="serie-year" id="y{year}"><h2>{link}</h2>'
                   + "".join(parts)
                   + f'<p class="leafmark">{marks}</p></article>')

    decades = sorted({y // 10 * 10 for y in by_year})
    jump = " ".join(
        f'<a href="#y{min(y for y in by_year if y // 10 * 10 == d)}">{d}</a>'
        for d in decades)
    order = sorted(CENTURY_NAMES)
    i = order.index(century)
    prev_c = order[i - 1] if i else None
    next_c = order[i + 1] if i + 1 < len(order) else None
    roman = CENTURY_NAMES[century]
    body = f"""<header class="year-head">
  {f'<a class="step" rel="prev" href="../{prev_c}/"><span aria-hidden="true">←</span> segle {CENTURY_NAMES[prev_c]}</a>' if prev_c else '<span class="step"></span>'}
  <h1>Jurats del segle {roman}</h1>
  {f'<a class="step" rel="next" href="../{next_c}/">segle {CENTURY_NAMES[next_c]} <span aria-hidden="true">→</span></a>' if next_c else '<span class="step"></span>'}
</header>
<p class="year-sub">{num(names)} noms en {len(by_year)} anys</p>
<nav class="jump" aria-label="Dècades">{jump}</nav>
<div class="tools">
  <label for="jf">Filtra per nom</label>
  <input type="search" id="jf" autocomplete="off" spellcheck="false"
         placeholder="Zaforteza, perayre, notari…">
  <span id="jf-n" class="tally" role="status"></span>
</div>
<p class="hint">L'any enllaça amb les seves notícies quan en té.
   {("Tots aquests noms s'han llegit directament del facsímil i comparat amb el que n'havien llegit els reconeixedors." if read == names else "")}
   {("" if read == names else "Un nom <span class='d'>puntejat</span> és una lectura en què dos o més reconeixedors discrepen; un de <span class='d1'>subratllat fi</span>, una en què en discrepa un de sol. Cap dels dos vol dir que sigui erroni." + (" Els que no duen marca en els anys llegits del facsímil s'han comprovat contra la pàgina." if read else ""))}</p>
<div class="serie-grid">{"".join(out)}</div>"""
    return page(f"Jurats del segle {roman} · Cronicón Mayoricense",
                f"Els jurats de Mallorca del segle {roman} segons el Cronicón "
                "Mayoricense de Campaner.",
                f"jurats/{century}/", "jurats/", body,
                trail=crumbs(("Inici", "../../"), ("Els jurats", "../"),
                             (f"Segle {roman}", None)))


def abbreviations_page(con) -> str:
    used = dict(con.execute(
        "SELECT s, count(*) FROM (SELECT unnest(sources) AS s FROM entry) "
        "GROUP BY 1").fetchall())
    glossed = con.execute(
        "SELECT siglum, expansion FROM siglum ORDER BY siglum").fetchall()
    # Each source as a card rather than a table row: the table could hold a name
    # and a count, and Campaner gives a trade, a manuscript, a span of years and
    # usually a date of death. Only the twelve in the chart have a page of
    # their own; the rest are cards that say what the introduction says.
    people = con.execute("""
        SELECT siglum, expansion, life, role, span, work, attributions
        FROM siglum WHERE attributions > 0
        ORDER BY attributions DESC, siglum""").fetchall()

    def card(g, x, r, sp, w, a) -> str:
        inner = (f'<span class="tag">{esc(g)}</span> '
                 f'<strong lang="es" translate="no">{esc(x.rstrip("."))}</strong>'
                 + (f'<span class="role">{esc(r)}</span>' if r else "")
                 + (f'<span class="meta">{esc(sp)}</span>' if sp else "")
                 + (f'<em lang="es" translate="no">{esc(w)}</em>' if w else "")
                 + f'<span class="n">{num(a or 0)} notícies</span>')
        return (f'<a class="card" href="{slug(g)}/">{inner}</a>' if g in BANDS
                else f'<div class="card">{inner}</div>')

    cards = "".join(card(g, x, r, sp, w, a) for g, x, _l, r, sp, w, a in people)
    bare = sorted(((g, n) for g, n in used.items()
                   if g not in {x[0] for x in glossed}),
                  key=lambda r: (-r[1], r[0]))
    missing = ", ".join(f"<code>{esc(g)}</code> ({num(n)})" for g, n in bare)
    chart = sources_chart(con, dict(glossed))
    body = f"""<header class="page-head">
  <h1>Les fonts</h1>
  <p class="lede">Campaner atribueix cada notícia al manuscrit d'on la treu,
     amb una sigla, i les glossa a la introducció — la part del llibre que
     aquesta edició no publica. Sense això les sigles del cos no volen dir
     res.</p>
</header>
<p class="hint">A les pàgines d'any es pot tocar qualsevol sigla per veure'n
   el nom.</p>

<h2>Qui ho explica, segle a segle</h2>
<p class="hint">La crònica no descansa sempre sobre els mateixos testimonis.
   Terrassa duu el gruix del segle XIV i del XV, Jaume el XVI, Mut el
   XVIII — i allà on una dècada penja d'una sola font és on convé
   desconfiar.</p>
{chart}

<h2>Els qui van escriure</h2>
<p class="hint">Un notari, un espardenyer, un cirurgià d'hospital, el rector
   de Campos, el bidell de la Seu. Campaner els descriu un per un vuit fulls
   abans de la llista d'abreviatures, i és la part del llibre que fa que la
   crònica es pugui fer servir: diu qui eren, què és el manuscrit, quins anys
   abraça i on parava el 1881.</p>
<div class="cards">{cards}</div>
<p class="hint">La crònica en cita {len(bare)} més que la introducció no
   glossa: {missing}. Les d'una sola inicial són sigles de dues que el
   facsímil no deixa llegir senceres.</p>"""
    return page("Les fonts · Cronicón Mayoricense",
                "Les sigles amb què Campaner atribueix cada notícia al "
                "manuscrit d'on la treu, amb el nom que en dona la introducció.",
                "abreviatures/", "abreviatures/", body, main="wrap column",
                trail=crumbs(("Inici", "../"), ("Les fonts", None)))


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
    years without anyone having to say so. And every bar is the way into its
    year.
    """
    peak = max(counts.values()) or 1
    peak_year = max(counts, key=lambda y: counts[y])
    early = sum(n for y, n in counts.items() if y <= 1300)
    late = sum(n for y, n in counts.items() if y >= 1701)
    # The axis is a grid whose first track is the short thirteenth century and
    # the other five a hundred years each -- `.axis-book` in style.css. Those
    # proportions are written there, not here, because a position in a `style`
    # attribute is something the Content-Security-Policy forbids; so the bounds
    # they assume are checked rather than trusted.
    assert (first, last) == (1229, 1800), "the .axis-book grid assumes 1229-1800"
    ticks = "".join(f"<span>{y}</span>" for y in (first, 1300, 1400, 1500,
                                                  1600, 1700))
    return ('<figure class="shape">'
            + density(counts, first, last, peak, "")
            + f'<div class="axis-book" aria-hidden="true">{ticks}'
            f'<span class="end">{last}</span></div>'
            "<figcaption>Una barra per any; cada barra obre el seu any. La "
            "crònica s'espesseix a mesura que s'acosta al temps de Campaner "
            f"—{num(early)} notícies al segle XIII contra {num(late)} al "
            "XVIII— perquè els noticiaris que buida no comencen fins al 1372. "
            f'El pic és <a href="anys/{peak_year}/">{peak_year}</a>, '
            f"amb {num(counts[peak_year])}.</figcaption>"
            "</figure>")


def specimen(con) -> str:
    """One real notice, chosen by its date so that a rebuild cannot move it.

    A text edition sells itself with its text. This one is the Festa de
    l'Estendard called off by a snowfall, which is dated, attributed, three
    lines long, and says in one breath what the whole book is for. It is what
    the home page shows where a script would show today's date in other
    centuries -- and what stays there if the script does not run.
    """
    row = con.execute("""
        SELECT id, text, sources FROM entry
        WHERE year = 1613 AND month = 12 AND day = 31 LIMIT 1""").fetchone()
    if not row:
        return ""
    entry_id, text, sources = row
    sigla = read_sigla(con)
    cites = " ".join(cite(s, sigla) for s in (sources or []))
    return f"""<article class="notice">
      <p class="when"><a href="anys/1613/#n{entry_id}">1613</a> <small>31 des.</small></p>
      <div class="said">
        <div lang="es" translate="no"><p>{esc(text)}</p></div>
        <p class="prov">{cites}</p>
      </div>
    </article>"""


def index_page(con, counts: dict, routes: dict) -> str:
    """The way in.

    It used to be the search box and four links over a strip of five numbers,
    which told a first-time reader nothing about what this book is -- and the
    book says it better than we could. So the page opens with what it is, one
    real notice, and the ways in: a word, a year, a subject.
    """
    stats = con.execute("""SELECT (SELECT count(*) FROM entry),
                                  (SELECT count(DISTINCT year) FROM entry
                                   WHERE year IS NOT NULL),
                                  (SELECT count(*) FROM jurat
                                   WHERE tier <> 'remark'),
                                  (SELECT count(*) FROM document),
                                  (SELECT count(*) FROM word)""").fetchone()
    busiest = con.execute(
        "SELECT year, count(*) n FROM entry WHERE year IS NOT NULL "
        "GROUP BY 1 ORDER BY n DESC, year LIMIT 6").fetchall()
    loud = " · ".join(f'<a href="anys/{y}/">{y}</a> <small>{n}</small>'
                      for y, n in busiest)
    longest = con.execute(
        "SELECT id, numeral, title, words FROM document "
        "ORDER BY words DESC LIMIT 1").fetchall()
    docs = "".join(f'<li><a href="documents/{esc(i)}/" lang="es" translate="no">'
                   f"{esc(t)}</a> <small>{num(w)} mots</small></li>"
                   for i, _n, t, w in longest)
    subjects = "".join(f"<li>{esc(s)}</li>" for s in SUBJECTS)
    themes_ = "".join(
        f'<a class="card" href="temes/{t.slug}/"><strong>{esc(t.title)}</strong> '
        f'<span class="meta">{esc(t.blurb)}</span> '
        f'<span class="n">{num(len(routes[t.slug]))} notícies</span></a>'
        for t in themes.THEMES)
    years = sorted(counts)

    # The frontispiece behind the title, softened under a veil of paper, as
    # the sibling map editions open with their engraving. The image is set in
    # style.css, not here: a `style` attribute is what the CSP forbids.
    body = f"""<section class="hero">
 <div class="hero__panel">
  <p class="kicker">Edició digital · Corpus Balear</p>
  <h1>Cinc segles de notícies de Mallorca, dia a dia</h1>
  <p class="lede">L'any 1881 Àlvar Campaner va buidar els noticiaris,
     dietaris i anals manuscrits que corrien per l'illa —molts inèdits, i
     alguns a punt de perdre's— i en va ordenar les notícies per data, de la
     conquesta de 1229 fins al 1800. Els va escriure un notari, un
     espardenyer, un cirurgià d'hospital, el rector de Campos, el bidell de
     la Seu. Això és aquell llibre, llegit de nou paraula per paraula.</p>
  <form class="search big" action="cerca/" method="get" role="search">
    <label class="vh" for="q">Cerca un mot, una frase o un any</label>
    <input type="search" id="q" name="q" autocomplete="off" spellcheck="false"
           placeholder="Cerca un mot, una frase, un any…">
    <button type="submit">Cerca</button>
  </form>
  <p class="cta"><a class="button" href="anys/">Entra per un any</a>
     <a href="temes/">o per un tema</a></p>
 </div>
 <p class="hero__credit">Frontispici del llibre: <span lang="es"
    translate="no">«Ventana de una casa en la calle de Zavellá, dibujada por
    B. Ferrá»</span>. {facsimile(10, "full 10")}</p>
</section>

{shape_of_the_book(counts, years[0], years[-1])}

<section class="today" id="avui">
  <h2 id="avui-title">Una notícia, tal com queda</h2>
  <div id="avui-body">
    {specimen(con)}
  </div>
  <p class="today-ctl">
    <button type="button" class="button ghost" id="atzar" hidden>Una altra
       notícia, a l'atzar</button>
    <span class="note">Les dates són les que dona el llibre; abans de 1582,
       del calendari julià. Les inicials al peu de cada notícia
       (<span translate="no">G. T.</span>, <span translate="no">J. F.</span>…)
       són les de l'autor del manuscrit d'on Campaner la va treure; toca-les
       per veure'n el nom.</span>
  </p>
</section>

<section class="block">
  <h2>Entra per un tema</h2>
  <p class="hint">Campaner mateix diu què anotaven els noticiaris: «ejecuciones
     capitales, calamidades públicas, sequías, epidemias, tormentas
     marítimas». Cada tema és una cerca ja feta sobre el text, no una tria.</p>
  <div class="cards">{themes_}</div>
</section>

<div class="doors">
  <section>
    <h2>Els anys amb més notícia</h2>
    <p class="loud">{loud}</p>
    <p><a href="anys/">Tots els anys, segle a segle</a></p>
  </section>
  <section>
    <h2>El document més llarg</h2>
    <ul class="plainlist">{docs}</ul>
    <p><a href="documents/">Els {stats[3]} documents sencers</a></p>
  </section>
  <section>
    <h2>Qui ho explica</h2>
    <p>Vint-i-sis testimonis, cadascun amb el seu ofici i el seu manuscrit,
       tal com els descriu la introducció.</p>
    <p><a href="abreviatures/">Les fonts, una per una</a></p>
  </section>
  <section>
    <h2>Els qui governaven</h2>
    <p>{num(stats[2])} jurats de la Ciutat i Regne entre 1240 i 1715, sis
       cada any.</p>
    <p><a href="jurats/">Les sis sèries</a></p>
  </section>
  <section>
    <h2>Què és fiable</h2>
    <p>Cada paraula porta el grau d'acord dels sis reconeixedors que la van
       llegir, i les discutides es veuen al text.</p>
    <p><a href="metode.html">El mètode i les xifres</a></p>
  </section>
</div>

<div class="twin">
  <blockquote class="pull" lang="es" translate="no">
    <p>El presente libro no es una Historia de Mallorca… compónenlo elementos
       tomados de muy diversas fuentes y colocados por el órden de los
       tiempos, á fin de que sirvan de algun auxilio al curioso investigador
       de los hechos y antiguas costumbres é instituciones de la isla.</p>
    <cite lang="ca">Campaner, introducció, 1881</cite>
  </blockquote>
  <div class="matter">
    <p>Els qui van escriure aquests noticiaris hi anotaven, en paraules del
       mateix Campaner:</p>
    <ul class="subjects" lang="es" translate="no">{subjects}</ul>
    <p class="aside">Ho recollia, deia, <span lang="es">«salvando de la
       destruccion ó del extravío algunos de los trabajos de nuestros
       antepasados, de los cuales bastantes han sido ya pasto del polvo y la
       polilla»</span>.</p>
  </div>
</div>

<section class="who">
  <h2>Qui era Campaner</h2>
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
      <div><strong>{num(stats[0])}</strong> notícies datades</div>
      <div><strong>{stats[1]}</strong> anys</div>
      <div><strong>{num(stats[2])}</strong> jurats</div>
      <div><strong>{stats[3]}</strong> documents</div>
      <div><strong>{num(stats[4])}</strong> paraules</div>
    </div>
  </div>
</section>"""
    return page("Cronicón Mayoricense · Campaner, 1881",
                "Edició digital del Cronicón Mayoricense de Campaner (Palma, "
                f"1881): {num(stats[0])} notícies datades de Mallorca entre "
                "1229 i 1800, amb el grau de certesa de cada paraula.",
                "", "", body, scripts=("home.js",), extra=jsonld() + "\n")


def method_page(con) -> str:
    """How the transcription was made, what was measured, and what is left.

    Every figure on this page is computed from the database or the decision
    log at build time, so the page cannot drift from the edition it describes.
    """
    q = lambda sql: con.execute(sql).fetchone()
    tiers = dict(con.execute("SELECT tier, count(*) FROM word GROUP BY 1").fetchall())
    total = sum(tiers.values())
    adj = con.execute("""
        SELECT family, tier, count(*),
               round(100.0*count(*) FILTER (WHERE chose = winner)/count(*), 1)
        FROM adjudication WHERE winner IS NOT NULL
        GROUP BY 1,2 ORDER BY 1, 3 DESC""").fetchall()
    adj_n = dict(con.execute(
        "SELECT family, count(*) FROM adjudication GROUP BY 1").fetchall())
    leaves, line_aligned, bne = q(
        "SELECT count(*), count(*) FILTER (WHERE align = 'line'), "
        "count(*) FILTER (WHERE scan = 'bne') FROM leaf")
    kept = q("SELECT count(*) FROM word WHERE printed IS NOT NULL")[0]
    entries, sourced_, years_ = q(
        "SELECT count(*), count(*) FILTER (WHERE len(sources) > 0), "
        "count(DISTINCT year) FROM entry")
    docs, doc_words = q("SELECT count(*), sum(words) FROM document")
    notes, loose = q("SELECT count(*), count(*) FILTER (WHERE entry_id IS NULL "
                     "AND document_id IS NULL) FROM footnote")
    tables_, rows_ = q("SELECT count(DISTINCT table_id), count(*) FROM table_row")
    sigla_, glossed = q("SELECT count(*), count(*) FILTER (WHERE role IS NOT NULL) "
                        "FROM siglum")
    jurats_, jurats_typed = q(
        "SELECT count(*) FILTER (WHERE tier <> 'remark'), "
        "count(*) FILTER (WHERE source = 'typed') FROM jurat")
    # The decision log: what a reader with the facsimile on screen settled,
    # and how many of those positions no engine had read at all.
    decided: dict[str, dict] = {}
    path = PROJECT / "data" / "review" / "decisions.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            decided[row["key"]] = row
    typed = sum(1 for r in decided.values()
                if r.get("source") == "typed" and r.get("chose"))

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
        f"<td class='num'>{pct(p)}%</td></tr>"
        for f, t, n, p in sorted(adj, key=lambda r: (r[0] == 'documents', order.get(r[1], 9))))
    # The corpus itself, file by file.
    what = {"word": "cada paraula, amb el grau de certesa i la caixa al facsímil",
            "entry": "les notícies datades", "document": "els documents sencers",
            "footnote": "les notes de Campaner", "jurat": "els jurats, nom a nom",
            "siglum": "les fonts i el que en diu la introducció",
            "leaf": "els fulls i com s'ha llegit cadascun",
            "century": "l'obertura de cada segle",
            "piece": "les peces numerades dins els documents",
            "table_row": "les taules que Campaner imprimeix dins la prosa",
            "adjudication": "les lectures verificades contra el facsímil"}
    files = sorted((WEB / "data").glob("*.parquet"),
                   key=lambda p: -p.stat().st_size)
    data_rows = "".join(
        f'<tr><td><a href="data/{p.name}"><code>{p.stem}</code></a></td>'
        f"<td>{what.get(p.stem, '')}</td>"
        f"<td class='num'>{pct(p.stat().st_size / 1024)} KB</td></tr>"
        for p in files)
    size = pct(sum(p.stat().st_size for p in files) / 1048576)
    contested = tiers.get("contested", 0) + tiers.get("two-dissent", 0)

    sections = (("fonts", "D'on surt el text"), ("motors", "Els sis reconeixedors"),
                ("vot", "Com es vota"), ("acord", "Quant d'acord es posen"),
                ("encerts", "I quan encerten"), ("regles", "Què s'hi ha tocat"),
                ("facsimil", "Allò que s'ha llegit del facsímil"),
                ("estructura", "De text a llibre"), ("limits", "Què queda per fer"),
                ("dades", "Consultar-ho tot"))
    toc = " ".join(f'<li><a href="#{a}">{esc(t)}</a></li>' for a, t in sections)

    body = f"""<header class="page-head">
  <h1>El mètode i les xifres</h1>
  <p class="lede">Com s'ha obtingut aquesta transcripció, què se n'ha mesurat,
     on se'n pot refiar menys i com consultar-la sencera. Totes les xifres
     d'aquesta pàgina es calculen de les dades publicades cada vegada que es
     construeix l'edició.</p>
</header>
<nav class="jump method-toc" aria-label="Apartats"><ol>{toc}</ol></nav>
<div class="prose">
  <h2 id="fonts">D'on surt el text</h2>
  <p>De l'edició de 1881 se'n coneixen dos escanejos independents: el de la
     <strong>Biblioteca Nacional d'Espanya</strong>, un PDF a 200 punts per
     polzada, i el que <strong>Google</strong> va fer per a l'Internet Archive,
     de molta més resolució. Tots dos tenen defectes en llocs diferents —el de
     l'Archive té quatre fulls borrosos (93, 94, 97 i 98), i en el de la BNE la
     pàgina del davant es transparenta en algun full—, i per això es llegeixen
     tots dos. Els {num(leaves)} fulls amb text són els que es transcriuen; els
     altres són portades, làmines i pàgines en blanc.</p>

  <h2 id="motors">Els sis reconeixedors</h2>
  <p>Cada full el llegeixen sis programes de reconeixement de text (OCR), triats
     perquè s'equivoquin de maneres diferents:</p>
  <ul>
    <li><strong>ABBYY FineReader</strong>, la capa de text que l'Internet Archive
        ja publica amb el seu escaneig;</li>
    <li><strong>Tesseract</strong> amb els models de castellà antic, català i
        llatí alhora —el llibre cita documents en català medieval i en llatí, i
        els cognoms mallorquins duen ce trencada—;</li>
    <li><strong>Apple Vision</strong>, una vegada sobre cada escaneig;</li>
    <li><strong>PaddleOCR</strong>;</li>
    <li><strong>Kraken</strong>, amb un model entrenat expressament sobre
        aquest llibre a partir de les línies en què els altres ja coincidien.</li>
  </ul>
  <p>Que siguin sis i no més és una decisió mesurada. Afegir un setè motor es va
     provar dues vegades i les dues va empitjorar el resultat, encara que el
     motor nou fos més precís que alguns dels que ja hi eren: el que compta no
     és que un motor encerti molt, sinó que no s'equivoqui igual que els altres.
     Per la mateixa raó, mai no voten dues variants del mateix programa sobre la
     mateixa imatge.</p>

  <h2 id="vot">Com es vota</h2>
  <p>Abans de comparar res, totes les lectures s'ordenen igual: es detecten les
     columnes de cada full i s'imposa a tots els motors el mateix ordre de
     lectura. Després s'alineen paraula per paraula i cada posició es decideix
     per majoria. <strong>La paraula publicada és sempre una que algun motor va
     llegir</strong>: el vot tria, no escriu.</p>
  <p>Hi ha tres casos en què això no basta, i cadascun té la seva regla:</p>
  <ul>
    <li>en <strong>{line_aligned} fulls</strong> —taules, llistes en columnes—
        els motors no es posen d'acord ni en quantes columnes té la pàgina; allà
        s'alinea línia per línia, de manera que una línia impresa només es
        compara amb el text que hi cau a sobre;</li>
    <li>quan els motors tallen les paraules en llocs diferents
        (<em>cuartos.—J. V.—30.—Mataron</em>), es vota el tram sencer i no
        casella per casella; una lectura buida no compta com a vot en contra;</li>
    <li>els encapçalaments d'any i de mes són lletra gran, la que pitjor llegeixen
        tots: s'hi compta el que diuen els vuit motors disponibles, no només el
        guanyador, i s'exigeix que la crònica avanci en el temps.</li>
  </ul>

  <h2 id="acord">Quant d'acord es posen</h2>
  <div class="scroll"><table><thead><tr><th>grau</th><th class="num">paraules</th>
    <th class="num">%</th></tr></thead><tbody>{tier_rows}</tbody></table></div>
  <p>Cada paraula de l'edició porta el seu grau. Al text es marquen, amb un
     subratllat puntejat, les lectures en què discrepen dos reconeixedors o
     més; tocant-les es veu què més s'hi va llegir. Quan només en discrepa un,
     la majoria encerta gairebé sempre, i marcar-ho ompliria
     la pàgina per no res.</p>

  <h2 id="encerts">I quan encerten</h2>
  <p>El grau d'acord no és encara la mesura de l'error. Per saber-ho s'han
     triat a l'atzar {num(sum(adj_n.values()))} posicions, estratificades per
     grau, i s'han resolt una a una mirant el facsímil a resolució completa:
     {num(adj_n.get('sample', 0))} a la crònica i
     {num(adj_n.get('documents', 0))} als documents. Són dues mesures separades
     i no s'han de barrejar, perquè el llibre no és igual de fiable pertot.</p>
  <div class="scroll"><table><thead><tr><th>part</th><th>grau</th><th class="num">n</th>
    <th class="num">encerts</th></tr></thead><tbody>{adj_rows}</tbody></table></div>
  <p>D'aquí surt que la crònica en castellà va per <strong>1 paraula errada de
     cada 113</strong> i els documents en català medieval i llatí per
     <strong>1 de cada 39</strong>. Allà on els sis coincideixen, les 360
     posicions comprovades de la crònica eren totes correctes, cosa que fita
     l'error compartit per sota del 0,83% amb un 95% de confiança.</p>

  <h2 id="regles">Què s'hi ha tocat</h2>
  <p><strong>Res no es modernitza.</strong> <em>formacion</em>, <em>dia</em>,
     <em>Setiembre</em>, <em>mallorquin</em> i les errades del mateix Campaner i
     del seu impressor es queden com són. Les úniques intervencions són
     tipogràfiques o es fonamenten en el que van llegir els motors, i
     {num(kept)} paraules conserven al costat la lectura original del vot:</p>
  <ul>
    <li><strong>La essa llarga</strong> (<em>ſ</em>) de la reimpressió d'un
        opuscle de 1541 que Campaner inclou: cinc dels sis motors la llegeixen
        <em>f</em>, i es restitueix quan algun la va llegir i la forma amb
        <em>f</em> no és una paraula que el llibre faci servir.</li>
    <li><strong>Els guions de final de línia</strong> es cusen, i es tornen a
        unir les paraules que el salt de línia havia partit i el vot no havia
        refet (<em>Tarrago. na</em> → <em>Tarragona</em>), només quan els motors
        hi havien llegit el guió o el llibre fa servir la paraula sencera.</li>
    <li><strong>El que no és text</strong> se suprimeix: la capçalera i el número
        de cada pàgina i les signatures de plec del peu.</li>
  </ul>
  <p>Totes les regles estan escrites, amb el que s'ha mesurat de cadascuna, a
     <a href="{GITHUB}/blob/main/docs/EDITORIAL.md" rel="noopener">les normes
     editorials</a>.</p>

  <h2 id="facsimil">Allò que s'ha llegit del facsímil</h2>
  <p>En alguns llocs els motors llegeixen bé les paraules però no es posen
     d'acord en l'ordre de la pàgina, i el text que en surt és inservible
     encara que cada paraula sigui correcta. Allà el text s'ha llegit
     directament del facsímil, a resolució completa, amb ajuda d'un model de
     visió, i <strong>cada lectura s'ha comparat amb la dels motors</strong>:</p>
  <ul>
    <li><strong>Les sis sèries de jurats</strong>: {num(jurats_)} noms. Tots
        menys {jurats_typed} coincideixen lletra per lletra amb la lectura
        d'algun motor; els {jurats_typed} que no, porten una lletra volada
        (<em>B.ª</em>) que cap motor no reprodueix. La comparació va detectar
        dues normalitzacions del model —un accent posat per analogia i una
        <em>J</em> que la impremta no va entintar— i s'han desfet.</li>
    <li><strong>Les taules de comptes de 1307 a 1343</strong> (fulls 159–164),
        on el vot buidava les caselles de xifres.</li>
    <li><strong>Quatre caplletres</strong> que queien fora de les línies que
        els motors van llegir.</li>
  </ul>
  <p>Cada una d'aquestes decisions queda registrada amb la seva font. En total,
     <strong>{num(typed)} posicions</strong> del text publicat no les va llegir
     cap motor i descansen només en aquesta lectura del facsímil.</p>

  <h2 id="estructura">De text a llibre</h2>
  <p>Del text llegit se'n reconstrueix l'estructura que el llibre imprimeix:
     <strong>{num(entries)} notícies</strong> datades en {num(years_)} anys,
     {num(sourced_)} amb la sigla del manuscrit d'on surten; {num(docs)}
     documents reproduïts sencers ({num(doc_words)} mots); {num(notes)} notes
     de Campaner; {num(tables_)} taules ({num(rows_)} files) recuperades com a
     taules; i les sèries de jurats. L'ordre de les notícies és el del llibre,
     no el de les dates: on Campaner les desordena, l'edició ho manté.</p>
  <p>La introducció del llibre no es publica com a text, però d'ella s'ha tret
     a mà el glossari de les {num(sigla_)} sigles i, per a {num(glossed)} fonts,
     qui era l'autor i què és el seu manuscrit, cada dada amb el full d'on surt.</p>

  <h2 id="limits">Què queda per fer</h2>
  <ul>
    <li>Les <strong>{num(contested)} posicions</strong> en què discrepen dos
        motors o més no s'han revisat totes contra el facsímil. Van marcades.</li>
    <li>Els fulls alineats línia per línia no estan coberts per cap mostra de
        verificació, i el que s'hi publica com a unànime no s'ha comprovat.</li>
    <li>{num(loose)} notes de Campaner no es poden lligar a cap notícia, perquè
        la crida que hi remetia no es va llegir; es publiquen al peu de l'any.</li>
    <li>La columna de notes de les llistes de jurats dels segles XIII i XIV —quin
        manuscrit dona cada nom— encara no s'ha llegit.</li>
  </ul>

  <h2 id="dades">Consultar-ho tot</h2>
  <p>Tota l'edició és consultable en SQL directament des d'aquí, sense
     instal·lar res més que DuckDB, que llegeix els fitxers parquet per HTTP:</p>
  <pre>SELECT year, count(*) FROM '{SITE}/data/entry.parquet'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;</pre>
  <div class="scroll"><table><thead><tr><th>taula</th><th>què hi ha</th>
    <th class="num">mida</th></tr></thead><tbody>{data_rows}</tbody></table></div>
  <p>Són {size} MB en total. El codi que ho fa tot és al
     <a href="{GITHUB}" rel="noopener">repositori</a>.</p>
</div>"""
    return page("El mètode · Cronicón Mayoricense",
                "Com s'ha obtingut aquesta transcripció, què se n'ha mesurat i "
                "què queda per fer.",
                "metode.html", "metode.html", body, main="wrap column",
                trail=crumbs(("Inici", "./"), ("El mètode", None)))


def search_page(con) -> str:
    """The search, as a page of its own that every other page can reach.

    Search lived on the home page and nowhere else, could not be filtered, and
    its hits opened a year at its head -- a hundred notices away from the one
    that matched. Here it has a URL (`?q=…&s=16&f=G.+T.`), so a search can be
    linked, bookmarked and reached from the box in every page's header, and a
    hit lands on the notice.

    The form is real HTML with real controls. Without scripts it does nothing
    useful, and says so; with them `search.js` reads the same fields.
    """
    used = con.execute(
        "SELECT s, count(*) n FROM (SELECT unnest(sources) AS s FROM entry) "
        "GROUP BY 1 HAVING count(*) >= 3 ORDER BY n DESC, s").fetchall()
    names = read_sigla(con)
    sources = "".join(
        f'<option value="{esc(s)}">{esc(s)}'
        + (f" — {esc(names[s].rstrip('.'))}" if names.get(s) else "")
        + f" ({num(n)})</option>" for s, n in used)
    centuries = "".join(
        f'<label><input type="radio" name="s" value="{c}"> {roman}</label>'
        for c, (_f, _l, roman) in enumerate(CENTURIES, 13))
    body = f"""<header class="page-head">
  <h1>Cerca</h1>
</header>
<form class="searchform" id="sf" action="./" method="get" role="search">
  <div class="search big">
    <label class="vh" for="q">Cerca un mot, una frase o un any</label>
    <input type="search" id="q" name="q" autocomplete="off" spellcheck="false"
           placeholder="Cerca un mot, una frase, un any…">
    <button type="submit">Cerca</button>
  </div>
  <div class="facets">
    <fieldset>
      <legend>Segle</legend>
      <label><input type="radio" name="s" value="" checked> tots</label>
      {centuries}
    </fieldset>
    <fieldset>
      <legend>On</legend>
      <label><input type="radio" name="on" value="" checked> pertot</label>
      <label><input type="radio" name="on" value="cronica"> la crònica</label>
      <label><input type="radio" name="on" value="documents"> els documents</label>
      <label><input type="radio" name="on" value="jurats"> els jurats</label>
    </fieldset>
    <p class="field">
      <label for="f">Font</label>
      <select id="f" name="f"><option value="">totes</option>{sources}</select>
    </p>
  </div>
</form>
<p class="hint">Diversos mots es busquen tots alhora dins la mateixa notícia;
   entre cometes, la frase exacta. Sense accents també va: <em>germania</em>
   troba <em>Germanía</em>, i <em>senyor</em> troba <em>ſenyor</em>. Triant una
   font sense escriure res surten totes les seves notícies.</p>
<noscript><p class="caveat">La cerca es fa al navegador i necessita JavaScript.
   Sense, es pot entrar <a href="../anys/">per anys</a> o
   <a href="../temes/">per temes</a>.</p></noscript>
<p id="status" class="tally" role="status"></p>
<div id="results"></div>"""
    return page("Cerca · Cronicón Mayoricense",
                "Cerca dins les notícies, els documents i els jurats del "
                "Cronicón Mayoricense, per mot, per segle i per font.",
                "cerca/", "", body, scripts=("search.js",),
                trail=crumbs(("Inici", "../"), ("Cerca", None)))


EXCERPT_WHOLE = 420      # a notice this short is shown whole
EXCERPT_SIDE = 190       # otherwise, this much either side of the match


def theme_hits(con) -> dict[str, list]:
    """Every route's notices, in the order the book prints them."""
    rows = con.execute(
        "SELECT id, year, month, day, text FROM entry WHERE year IS NOT NULL "
        "ORDER BY id").fetchall()
    out: dict[str, list] = {t.slug: [] for t in themes.THEMES}
    for entry_id, year, month, day, text in rows:
        folded = themes.fold(text)
        assert len(folded) == len(text), "fold() must keep offsets"
        for theme in themes.THEMES:
            span = theme.find(text, folded)
            if span:
                # The pattern is a stem (`cautiv`); what is marked is the word.
                start, end = span
                while start and text[start - 1].isalnum():
                    start -= 1
                while end < len(text) and text[end].isalnum():
                    end += 1
                out[theme.slug].append((entry_id, year, month, day, text,
                                        start, end))
    return out


def excerpt(text: str, start: int, end: int) -> tuple[str, bool]:
    """The notice around its match, and whether anything was left out.

    Whole if it is short. Otherwise cut at word boundaries either side of the
    first match and marked with an ellipsis -- the route is a way to the
    notice, not a second copy of the book.
    """
    a, b = 0, len(text)
    if len(text) > EXCERPT_WHOLE:
        a = max(0, start - EXCERPT_SIDE)
        b = min(len(text), end + EXCERPT_SIDE)
        if a:
            a = text.find(" ", a) + 1
        if b < len(text):
            b = text.rfind(" ", 0, b)
    return ((("… " if a else "") + esc(text[a:start]) + "<mark>"
             + esc(text[start:end]) + "</mark>" + esc(text[end:b])
             + (" …" if b < len(text) else "")), a > 0 or b < len(text))


def sparkline(years: list[int]) -> str:
    """Notices per decade across the whole span, as bars."""
    per = Counter(y // 10 * 10 for y in years)
    decades = list(range(1220, 1801, 10))
    peak = max(per.values()) if per else 1
    step = 1000 / len(decades)
    bars = "".join(
        f'<rect class="vol" x="{i * step:.2f}" '
        f'y="{40 - 38 * per[d] / peak:.2f}" width="{step - 1:.2f}" '
        f'height="{38 * per[d] / peak:.2f}"><title>{d}s · {per[d]}</title></rect>'
        for i, d in enumerate(decades) if per[d])
    ticks = "".join(f"<span>{d if d % 100 == 0 else ''}</span>" for d in decades)
    return ('<figure class="chart spark">'
            '<svg viewBox="0 0 1000 40" preserveAspectRatio="none" role="img" '
            'aria-label="Notícies per dècada">' + bars + "</svg>"
            f'<div class="ticks" aria-hidden="true">{ticks}</div></figure>')


def theme_page(con, theme, hits: list) -> str:
    docs = {r[0]: r for r in con.execute(
        "SELECT id, numeral, title, words FROM document").fetchall()}
    pinned = "".join(
        f'<a class="card doc-card" href="../../documents/{esc(i)}/">'
        f'<span class="tag">document · secció {esc(docs[i][1])}</span> '
        f'<strong lang="{DOC_LANG.get(i, "es")}" translate="no">'
        f"{esc(docs[i][2])}</strong>"
        f'<span class="meta">{num(docs[i][3])} mots</span></a>'
        for i in theme.documents if i in docs)
    sections, running_c, running_y = [], None, None
    for entry_id, year, month, day, text, start, end in hits:
        c_num, roman = century_of(year)
        if c_num != running_c:
            if running_c is not None:
                sections.append("</section>")
            sections.append(f'<section class="century"><h2>Segle {roman}</h2>')
            running_c, running_y = c_num, None
        if year != running_y:
            sections.append(f'<h3 class="hit-year"><a href="../../anys/{year}/">'
                            f"{year}</a></h3>")
            running_y = year
        html_, cut = excerpt(text, start, end)
        date = " ".join(x for x in (str(day) if day else "",
                                    MONTHS[month].lower() if month else "") if x)
        link = f"../../anys/{year}/#n{entry_id}"
        sections.append(
            f'<article class="notice hit"><p class="when">'
            f'<a href="{link}">{esc(date) or "§"}</a></p><div class="said">'
            f'<div lang="es" translate="no"><p>{html_}</p></div>'
            + (f'<p class="prov"><a href="{link}">la notícia sencera</a></p>'
               if cut else "")
            + "</div></article>")
    if running_c is not None:
        sections.append("</section>")
    spread = len({h[1] for h in hits})
    body = f"""<header class="page-head">
  <p class="kicker">Tema</p>
  <h1>{esc(theme.title)}</h1>
  <p class="lede">{esc(theme.blurb)}</p>
</header>
<p class="year-sub">{num(len(hits))} notícies en {num(spread)} anys</p>
{sparkline([h[1] for h in hits])}
<p class="caveat">Això és una cerca automàtica, no una tria: recull les
   notícies on surt algun d'aquests mots —<span lang="es" translate="no">
   {esc(theme.terms)}</span>— en l'ordre del llibre. N'hi pot haver que no hi
   tinguin res a veure, i en poden faltar que en parlin amb altres paraules.</p>
{f'<section class="block"><h2>Documents sencers</h2><div class="cards">{pinned}</div></section>' if pinned else ''}
{"".join(sections)}"""
    return page(f"{theme.title} · Cronicón Mayoricense",
                f"{theme.title}: {num(len(hits))} notícies del Cronicón "
                "Mayoricense de Campaner (1881) que en parlen.",
                f"temes/{theme.slug}/", "temes/", body, main="wrap page",
                trail=crumbs(("Inici", "../../"), ("Els temes", "../"),
                             (theme.title, None)))


def themes_index(routes: dict) -> str:
    cards = "".join(
        f'<a class="card" href="{t.slug}/"><strong>{esc(t.title)}</strong> '
        f'<span class="meta">{esc(t.blurb)}</span> '
        f'<span class="n">{num(len(routes[t.slug]))} notícies · '
        f"{num(len({h[1] for h in routes[t.slug]}))} anys</span></a>"
        for t in themes.THEMES)
    body = f"""<header class="page-head">
  <h1>Els temes</h1>
  <p class="lede">Una crònica s'entra per la data, i qui no en té cap no sap
     per on començar. Aquests són deu camins per assumpte: pestes, corsaris,
     execucions, festes.</p>
</header>
<p class="hint">Cada tema és una cerca ja feta sobre el text de les notícies,
   amb els mots a la vista, i no una selecció: ningú no ha triat aquestes
   notícies ni n'ha escrit res. Per buscar qualsevol altra cosa hi ha
   <a href="../cerca/">la cerca</a>.</p>
<div class="cards">{cards}</div>"""
    return page("Els temes · Cronicón Mayoricense",
                "Deu camins per assumpte dins el Cronicón Mayoricense: pestes, "
                "corsaris, execucions, festes, bàndols, la Inquisició, la "
                "Germania.",
                "temes/", "temes/", body, main="wrap column",
                trail=crumbs(("Inici", "../"), ("Els temes", None)))


def not_found() -> str:
    """The page for a URL that is not one. Served from any depth, so its own
    links are rooted at `/` rather than relative."""
    body = """<header class="page-head">
  <h1>Aquesta pàgina no hi és</h1>
  <p class="lede">L'adreça no correspon a cap pàgina de l'edició. Pot ser un
     any fora del llibre —la crònica va de 1229 a 1800— o un enllaç antic.</p>
</header>
<p class="cta"><a class="button" href="/anys/">Els anys</a>
   <a href="/cerca/">o cerca un mot</a></p>"""
    return page("No s'ha trobat · Cronicón Mayoricense",
                "Aquesta adreça no correspon a cap pàgina del Cronicón "
                "Mayoricense.", "404.html", "", body, main="wrap column",
                noindex=True, root="/")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def dump(path: Path, data) -> None:
    write(path, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def themes_report(routes: dict) -> None:
    """Counts and a random sample per route. A route is a search and can be
    wrong; this is how it gets read before it is believed."""
    rng = random.Random(1881)
    for theme in themes.THEMES:
        hits = routes[theme.slug]
        print(f"\n== {theme.title}: {len(hits)} notices, "
              f"{len({h[1] for h in hits})} years")
        for _id, year, _m, _d, text, start, end in rng.sample(hits, min(8, len(hits))):
            a, b = max(0, start - 60), min(len(text), end + 60)
            print(f"  {year}  …{text[a:start]}[{text[start:end]}]{text[end:b]}…")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--themes-report", action="store_true",
                    help="print each route's hit count and a sample, and stop")
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    routes = theme_hits(con)
    if args.themes_report:
        themes_report(routes)
        return

    counts = dict(con.execute(
        "SELECT year, count(*) FROM entry WHERE year IS NOT NULL GROUP BY 1"
    ).fetchall())
    # Every year of the span gets a page, not only the ones with entries: a
    # year the chronicle is silent about is a fact about the book rather than
    # a missing file.
    years = list(range(min(counts), max(counts) + 1))
    sigla = read_sigla(con)
    doubt = Doubt(con)
    # The leaves a notice can be on: from the one it opens on to the one the
    # next notice opens on. A notice does not record where it ends, and a
    # stretch of the chronicle that never dates itself runs for twenty-eight.
    order = con.execute("SELECT id, pdf_page FROM entry ORDER BY id").fetchall()
    window = {eid: (leaf, max(leaf, order[i + 1][1] if i + 1 < len(order) else leaf))
              for i, (eid, leaf) in enumerate(order)}

    for year in years:
        write(WEB / "anys" / str(year) / "index.html",
              year_page(con, year, counts, sigla, doubt, window))

    documents = con.execute(
        "SELECT id, numeral, title, genre, first_leaf, last_leaf, words, "
        "contested, text, block_leaf FROM document "
        "ORDER BY block_leaf, first_leaf, id").fetchall()
    for i, doc in enumerate(documents):
        write(WEB / "documents" / doc[0] / "index.html",
              document_page(con, doc, sigla, doubt,
                            documents[i - 1] if i else None,
                            documents[i + 1] if i + 1 < len(documents) else None))

    # The searchable book, in shards. One file per century of the chronicle,
    # one for the documents and one for the Jurats, positional rather than
    # keyed because the keys would be a third of the bytes. A search confined
    # to a century fetches that century and nothing else; an open one fetches
    # them side by side and shows each century's hits as it arrives. The text
    # is shipped rather than an inverted index because a hit with no line of
    # context around it is barely a search at all.
    for stale in (WEB / "search.json",):
        stale.unlink(missing_ok=True)
    for c_num, (first, last, _roman) in enumerate(CENTURIES, 13):
        dump(WEB / "search" / f"c{c_num}.json", con.execute(
            "SELECT id, year, month, day, pdf_page, sources, text FROM entry "
            "WHERE year BETWEEN ? AND ? ORDER BY id", [first, last]).fetchall())
    dump(WEB / "search" / "docs.json",
         [[d[0], d[1], d[2], [p for p in d[8].split("\n") if p.strip()]]
          for d in documents])
    dump(WEB / "search" / "jurats.json", con.execute(
        "SELECT century, year, name FROM jurat WHERE tier <> 'remark' "
        "ORDER BY year, seat").fetchall())

    # "On this day": the dated notices short enough to show whole, by month.
    # The home page fetches the current month and nothing else.
    #
    # Only notices that open the way a notice opens -- a capital, a quotation
    # mark, a figure. One that opens in lower case is the tail of a sentence
    # the parse cut in two, and the home page is the wrong place to show the
    # edition's seams: the first one this drew was `hubo luminarias por tan
    # fausta noticia…`. They are all still on their year pages.
    for month in MONTHS:
        dump(WEB / "dies" / f"{month:02d}.json", [
            row for row in con.execute(
                "SELECT id, year, day, text, sources FROM entry "
                "WHERE month = ? AND day IS NOT NULL AND length(text) <= 700 "
                "ORDER BY day, id", [month]).fetchall()
            if re.match(r"[A-ZÁÉÍÓÚÑ«¡¿\d]", row[3])])

    dump(WEB / "data.json", {
        "years": [{"y": y, "n": counts.get(y, 0)} for y in years],
        "documents": [dict(zip(("id", "numeral", "title", "genre", "first_leaf",
                                "last_leaf", "words", "contested"), d[:8]))
                      for d in documents],
        "sigla": [dict(zip(("siglum", "expansion", "attributions"), row))
                  for row in con.execute(
            "SELECT siglum, expansion, attributions FROM siglum "
            "ORDER BY attributions DESC NULLS LAST, siglum").fetchall()],
        "stats": dict(zip(
            ("leaves", "words", "entries", "jurats", "documents", "adjudications"),
            con.execute("""SELECT (SELECT count(*) FROM leaf),
                                  (SELECT count(*) FROM word),
                                  (SELECT count(*) FROM entry),
                                  (SELECT count(*) FROM jurat),
                                  (SELECT count(*) FROM document),
                                  (SELECT count(*) FROM adjudication)""").fetchone())),
        "tiers": dict(con.execute(
            "SELECT tier, count(*) FROM word GROUP BY 1 ORDER BY 1").fetchall()),
    })

    centuries = [c for (c,) in con.execute(
        "SELECT DISTINCT century FROM jurat ORDER BY 1").fetchall()]
    write(WEB / "jurats" / "index.html", jurats_index(con))
    for century in centuries:
        write(WEB / "jurats" / str(century) / "index.html",
              jurats_century(con, century))

    write(WEB / "index.html", index_page(con, counts, routes))
    write(WEB / "metode.html", method_page(con))
    write(WEB / "404.html", not_found())
    write(WEB / "anys" / "index.html", years_page(con, counts))
    write(WEB / "documents" / "index.html", documents_page(con))
    write(WEB / "cerca" / "index.html", search_page(con))
    write(WEB / "abreviatures" / "index.html", abbreviations_page(con))
    # One page per source in the chart: where that manuscript is cited, year by
    # year. Years and counts only -- the notices themselves are a search away.
    for band in BANDS:
        row = con.execute("SELECT expansion FROM siglum WHERE siglum = ?",
                          [band]).fetchone()
        write(WEB / "abreviatures" / slug(band) / "index.html",
              source_page(con, band, row[0] if row else ""))
    write(WEB / "temes" / "index.html", themes_index(routes))
    for theme in themes.THEMES:
        write(WEB / "temes" / theme.slug / "index.html",
              theme_page(con, theme, routes[theme.slug]))

    # The years with nothing in them keep their page and stay out of the
    # sitemap: they say "no news", which is true and not worth indexing.
    paths = (["", "metode.html", "anys/", "temes/", "documents/",
              "abreviatures/", "jurats/", "cerca/"]
             + [f"jurats/{c}/" for c in centuries]
             + [f"temes/{t.slug}/" for t in themes.THEMES]
             + [f"anys/{y}/" for y in years if counts.get(y)]
             + [f"abreviatures/{slug(b)}/" for b in BANDS]
             + [f"documents/{d[0]}/" for d in documents])
    write(WEB / "sitemap.xml", "\n".join(
        ['<?xml version="1.0" encoding="UTF-8"?>',
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        + [f"<url><loc>{SITE}/{p}</loc></url>" for p in paths]
        + ["</urlset>"]))
    write(WEB / "robots.txt",
          f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")

    aligned, tokens, share = doubt.report()
    size = sum(p.stat().st_size for p in WEB.rglob("*") if p.is_file())
    search = sum(p.stat().st_size for p in (WEB / "search").glob("*.json"))
    print(f"{len(years)} year pages ({len(counts)} with news), "
          f"{len(documents)} documents, {len(themes.THEMES)} routes")
    print(f"doubt marks placed by alignment: {num(aligned)} of {num(tokens)} "
          f"text tokens found on their leaves ({share:.1%})")
    print(f"search index {search / 1024:.0f} KB in "
          f"{len(list((WEB / 'search').glob('*.json')))} shards; "
          f"web/ is {size / 1048576:.1f} MB in total")
    con.close()
    if share < MIN_ALIGNED:
        sys.exit(f"only {share:.1%} of the text could be placed on its leaves "
                 f"(minimum {MIN_ALIGNED:.0%}): the doubt marks cannot be trusted")


if __name__ == "__main__":
    main()
