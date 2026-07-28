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
import re
import shutil
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


def masthead(depth: int = 0) -> str:
    up = "../" * depth
    return f"""<header>
  <div class="wrap">
    <p class="eyebrow"><a href="https://corpusbalear.org/">Corpus Balear</a></p>
    <h1><a href="{up}">Cronicón Mayoricense</a></h1>
    <p class="sub">Álvaro Campaner i Fuertes · Palma, 1881 · notícies de Mallorca
       de 1229 a 1800</p>
  </div>
</header>
"""


FOOT = """<footer>
  <div class="wrap">
    <p>Transcripció obtinguda pel consens de sis reconeixedors independents.
       <strong>Cap model generatiu ha escrit ni un caràcter del text.</strong>
       Cada paraula duu el seu grau de certesa; les dubtoses van marcades.</p>
    <p><a href="metode.html">El mètode i les xifres</a> ·
       <a href="https://archive.org/details/CroniconMayoricenseCampaner">Facsímil
       a l'Internet Archive</a> ·
       <a href="data/">Dades en parquet</a></p>
  </div>
</footer>
</body>
</html>
"""


def mark_doubt(text: str, doubtful: set[str]) -> str:
    """Underline the words the panel argued about, leaving the rest clean.

    Matched on the word as published, not on position: the entry text has been
    hyphen-stitched and re-joined, so the word index no longer lines up with the
    leaf's. Approximate, and honest about it -- it can only ever mark a word that
    really was doubtful somewhere on that leaf.
    """
    out = []
    for token in text.split(" "):
        bare = token.strip(".,;:»«()¿?¡!—-")
        if bare and bare in doubtful:
            out.append(f'<span class="d" title="lectura discutida pel panell">'
                       f'{esc(token)}</span>')
        else:
            out.append(esc(token))
    return " ".join(out)


LONG_ENTRY = 1500     # characters before an entry is broken up to be read
PARAGRAPH = 900       # rough target for each piece


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
    pages = {e[5] for e in entries}
    doubtful = set()
    if pages:
        doubtful = {r[0] for r in con.execute(
            f"SELECT DISTINCT text FROM word WHERE pdf_page IN "
            f"({','.join(str(p) for p in pages)}) AND tier IN {DOUBTFUL}"
        ).fetchall()}

    i = years.index(year)
    prev_y = years[i - 1] if i else None
    next_y = years[i + 1] if i + 1 < len(years) else None

    parts = [head(f"{year} · Cronicón Mayoricense",
                  f"Notícies de Mallorca de l'any {year} segons el Cronicón "
                  f"Mayoricense de Campaner (1881).",
                  f"{SITE}/anys/{year}/", depth=2),
             masthead(depth=2),
             '<main class="wrap">',
             f'<nav class="yearnav">',
             f'<a href="../{prev_y}/">← {prev_y}</a>' if prev_y else "<span></span>",
             f'<h2>{year}</h2>',
             f'<a href="../{next_y}/">{next_y} →</a>' if next_y else "<span></span>",
             "</nav>"]

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
    for _id, month, day, text, sources, page, printed in entries:
        when = MONTHS.get(month, "")
        if day:
            when = f"{day} {when.lower()}" if when else str(day)
        cites = " ".join(cite(s, sigla) for s in (sources or []))
        leaf_url = ("https://archive.org/details/CroniconMayoricenseCampaner/"
                    f"page/n{page - 2}/mode/2up")
        parts.append(
            '<article class="entry">'
            + (f"<h3>{esc(when)}</h3>" if when else "")
            + "".join(f"<p>{mark_doubt(para, doubtful)}</p>"
                      for para in paragraphs(text))
            + f'<p class="prov">{cites}'
            + f'<a class="facs" href="{leaf_url}" rel="noopener">full {page}</a>'
            + "</p></article>")
    parts.append("</main>")
    # The year pages are where the uncertainty marks actually are, so they are
    # the pages that most need the script that hides them. They shipped without
    # it: the preference was stored on the index and then never applied.
    parts.append(FOOT.replace("</body>",
                              '<script src="../../app.js"></script>\n</body>'))
    return "\n".join(parts)


def document_page(con, doc) -> str:
    """One of the 23 pieces Campaner reprints in full.

    These are 21% of the edition and had nowhere to live: the index listed them
    in a table of dead rows, so a search hit inside the Centellas letters could
    only be reported, never opened. They are also the part measured worst --
    1 wrong word in 96 against the chronicle's 1 in 706 -- so the page says so
    at the top rather than leaving the reader to assume the two are alike.
    """
    _id, numeral, title, genre, first, last, words, contested, text = doc
    doubtful = {r[0] for r in con.execute(
        "SELECT DISTINCT text FROM word WHERE pdf_page BETWEEN ? AND ? "
        f"AND tier IN {DOUBTFUL}", [first, last]).fetchall()}

    paras = [p for p in text.split("\n") if p.strip()]
    body = "".join(f'<p id="p{i}">{mark_doubt(p, doubtful)}</p>'
                   for i, p in enumerate(paras))
    leaf_url = ("https://archive.org/details/CroniconMayoricenseCampaner/"
                f"page/n{first - 2}/mode/2up")
    return (head(f"{numeral}. {title} · Cronicón Mayoricense",
                 f"{title} — {genre or 'document'} reproduït sencer al Cronicón "
                 f"Mayoricense de Campaner (1881), fulls {first}–{last}.",
                 f"{SITE}/documents/{_id}/", depth=2)
            + masthead(depth=2) + f"""
<main class="wrap">
  <nav class="yearnav"><h2 class="doctitle">{esc(title)}</h2></nav>
  <p class="prov">{esc(genre or '')} · secció {esc(numeral)} ·
     {num(words)} mots · {pct(100*contested/words if words else 0)}% discutits ·
     <a href="{leaf_url}" rel="noopener">fulls {first}–{last} al facsímil</a></p>
  <p class="caveat">Els documents són la part del llibre pitjor mesurada:
     <strong>un mot errat de cada 96</strong>, contra un de cada 706 a la
     crònica. Són en català medieval i llatí, i els reconeixedors hi van pitjor.
     <a href="../../metode.html">Com se sap</a>.</p>
  <div class="doc">{body}</div>
</main>
""" + FOOT.replace("</body>", '<script src="../../app.js"></script>\n</body>'))


def index_page(con, years: list[int], counts: dict) -> str:
    stats = con.execute("""SELECT (SELECT count(*) FROM entry),
                                  (SELECT count(DISTINCT year) FROM entry
                                   WHERE year IS NOT NULL),
                                  (SELECT count(*) FROM jurat),
                                  (SELECT count(*) FROM document),
                                  (SELECT count(*) FROM word)""").fetchone()
    first, last = years[0], years[-1]
    grid = "".join(
        f'<a href="anys/{y}/" class="{"" if counts.get(y) else "void"}">{y}'
        f'<span class="n">{counts.get(y, 0) or "—"}</span></a>'
        for y in range(first, last + 1) if y in counts or True)

    docs = con.execute("SELECT id, numeral, title, genre, first_leaf, last_leaf, "
                       "words FROM document ORDER BY block_leaf, number").fetchall()
    rows = "".join(
        f"<tr><td>{esc(n)}</td>"
        f'<td><a href="documents/{esc(i)}/">{esc(t)}</a></td><td>{esc(g or "")}</td>'
        f'<td class="num">{a}–{b}</td><td class="num">{num(w)}</td></tr>'
        for i, n, t, g, a, b, w in docs)

    # The sigla, browsable at last. They were reachable only by guessing a
    # search term that happened to trigger the quick answer, which is no way to
    # offer the one key the chronicle cannot be read without: the introduction
    # that glosses them is the section this edition drops.
    used = dict(con.execute(
        "SELECT s, count(*) FROM (SELECT unnest(sources) AS s FROM entry) "
        "GROUP BY 1").fetchall())
    glossed = con.execute(
        "SELECT siglum, expansion FROM siglum ORDER BY siglum").fetchall()
    fonts = "".join(
        f"<tr><td><code>{esc(g)}</code></td><td>{esc(x)}</td>"
        f'<td class="num">{num(used.get(g, 0))}</td></tr>'
        for g, x in glossed if used.get(g))
    # Cited but never glossed. Named, with their counts, rather than left out:
    # `L. V.` alone attributes 102 notices, and a reader who meets it on a year
    # page and finds no entry here would reasonably think the list is broken.
    bare = sorted(((g, n) for g, n in used.items()
                   if g not in {x[0] for x in glossed}),
                  key=lambda r: -r[1])
    missing = ", ".join(f"<code>{esc(g)}</code> ({num(n)})" for g, n in bare)

    return (head("Cronicón Mayoricense · Campaner, 1881",
                 "Edició digital del Cronicón Mayoricense de Campaner (Palma, "
                 "1881): 2.503 notícies datades de Mallorca entre 1229 i 1800, "
                 "amb el grau de certesa de cada paraula.",
                 f"{SITE}/") + masthead() + f"""
<main class="wrap">
  <div class="stats">
    <div><strong>{num(stats[0])}</strong>notícies datades</div>
    <div><strong>{stats[1]}</strong>anys</div>
    <div><strong>{num(stats[2])}</strong>jurats</div>
    <div><strong>{stats[3]}</strong>documents</div>
    <div><strong>{num(stats[4])}</strong>paraules</div>
  </div>

  <div class="tools">
    <input type="search" id="q" placeholder="Cerca un mot, una frase, un any…"
           autocomplete="off" spellcheck="false">
    <label class="toggle"><input type="checkbox" id="plain"> amaga la incertesa</label>
  </div>
  <p class="hint">Cerca dins les {num(stats[0])} notícies i els 23 documents
     sencers. Sense accents també va: <em>germania</em> troba
     <em>Germanía</em>. Entre cometes, cerca la frase exacta.</p>
  <div id="results"></div>

  <h2 class="section">Els anys</h2>
  <div class="grid">{grid}</div>

  <h2 class="section">Les fonts</h2>
  <p class="hint">Campaner atribueix cada notícia al manuscrit d'on la treu.
     Aquestes són les sigles que glossa a la introducció; a les pàgines d'any
     es pot clicar qualsevol sigla per veure'n el nom.</p>
  <div class="scroll"><table>
    <thead><tr><th>sigla</th><th>font</th>
      <th class="num">notícies</th></tr></thead>
    <tbody>{fonts}</tbody>
  </table></div>
  <p class="hint">La crònica en cita {len(bare)} més que la introducció no
     glossa: {missing}. Les d'una sola inicial són sigles de dues que el
     facsímil no deixa llegir senceres.</p>

  <h2 class="section">Els documents que Campaner reprodueix sencers</h2>
  <div class="scroll"><table>
    <thead><tr><th>núm.</th><th>títol</th><th>gènere</th><th>fulls</th>
      <th class="num">mots</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</main>
""" + FOOT.replace("</body>", '<script src="app.js"></script>\n</body>'))


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
                 f"{SITE}/metode.html") + masthead() + f"""
<main class="wrap">
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
""" + FOOT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = duckdb.connect(args.db, read_only=True)
    WEB.mkdir(exist_ok=True)
    (WEB / "anys").mkdir(exist_ok=True)
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

    (WEB / "index.html").write_text(index_page(con, years, counts),
                                    encoding="utf-8")
    (WEB / "metode.html").write_text(method_page(con), encoding="utf-8")

    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
               f"<url><loc>{SITE}/</loc><priority>1.0</priority></url>",
               f"<url><loc>{SITE}/metode.html</loc></url>"]
    sitemap += [f"<url><loc>{SITE}/anys/{y}/</loc></url>" for y in years]
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
