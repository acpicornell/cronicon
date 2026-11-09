"""Thematic routes through the chronicle: a search someone has already typed.

Campaner says what the noticiaris record -- «ejecuciones capitales, calamidades
públicas, sequías, epidemias, tormentas marítimas…» -- and a first-time reader
has no way to find any of it without knowing a date. A route is a way in by
subject.

**A route is a search, not a selection, and the page says so.** Each one is a
pattern run over the text of every notice, with the terms printed on the page:
nobody chose these notices and nobody wrote a word about them. That is the same
licence the rest of the site works under -- nothing added to the book -- and it
is why a route can be wrong in both directions: it finds the `rayos` of a
wheel as well as the lightning, and it misses the plague a chronicler describes
without naming.

Three patterns were narrowed after reading their samples, which is what the
report is for. `bando` is an edict far more often than a faction in the
eighteenth century, and took half of "Bàndols" with it; `temporal` is the
Church's *porción temporal* and `incendio` a town burnt in war; and `Colom` is
Porto-Colom and a doctor of 1708 before it is the leader of the Germania. The hit counts are measured (`build_site.py --themes-report`
prints them with a random sample); precision has to be read.

The patterns run over *folded* text: lower case, accents stripped, `ſ` as `s`,
one character for one, so an offset in the folded string is an offset in the
text and the excerpt can be cut around the match. The JavaScript search folds
the same way.

The title and blurb are Catalan, as all interface copy is. The terms are 1881
Spanish, because that is the language of the chronicle.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def fold(text: str) -> str:
    """Lower case without accents, the same length as `text`."""
    out = []
    for ch in text:
        if ch == "ſ":
            out.append("s")
            continue
        base = unicodedata.normalize("NFD", ch)[0].lower()
        out.append(base if len(base) == 1 else ch.lower()[:1] or ch)
    return "".join(out)


@dataclass(frozen=True)
class Theme:
    slug: str
    title: str
    blurb: str
    terms: str                       # as shown to the reader
    pattern: str                     # over fold(text)
    documents: tuple[str, ...] = ()  # whole documents that belong to the route

    def search(self, text: str) -> re.Match | None:
        return re.search(self.pattern, fold(text))


THEMES = (
    Theme("pestes", "Pestes i contagis",
          "El morbo, les quarantenes i el llatzeret: quan l'illa es tancava.",
          "peste, pestilencia, contagio, morbo, morbería, lazareto, cuarentena, "
          "epidemia",
          r"\bpeste\b|pestilen|contagi|\bmorbo|morber|lazareto|cuarentena|epidemi"),
    Theme("corsaris", "Corsaris i captius",
          "Galiotes a la vista, desembarcaments, captius a Alger i renegats.",
          "corsario, pirata, galeota, fusta, cautivo, renegado, Argel",
          r"corsari|pirat|galeota|\bfustas?\b|cautiv|renegad|\bargel"),
    Theme("forca", "La forca i el botxí",
          "Penjats, esquarterats, degollats i assotats: la justícia a la plaça.",
          "ahorcado, ajusticiado, degollado, descuartizado, garrote, arrastrado, "
          "azotado",
          r"ahorc|ajustici|degoll|descuartiz|\bgarrote\b|arrastrad|azotad|azotes"),
    Theme("rogatives", "Rogatives, sequera i pluja",
          "Processons per demanar aigua, i les vegades que va arribar.",
          "rogativa, sequía, lluvia, falta de agua",
          r"rogativa|sequia|\blluvias?\b|falta de agua"),
    Theme("blat", "Blat, fam i carestia",
          "Collites, preus del blat i els anys que no n'hi va haver.",
          "hambre, carestía, trigo, cosecha",
          r"\bhambre|caresti|\btrigos?\b|cosecha"),
    Theme("festes", "Festes, lluminàries i Te-Deum",
          "Torneigs, toros, comèdies, màscares i tres nits de lluminàries.",
          "luminarias, Te-Deum, toros, torneo, justas, estandarte, comedia, "
          "máscara, sortija, estafermo",
          r"luminaria|te-? ?deum|\btoros?\b|torneo|\bjustas\b|estandarte|comedia"
          r"|mascara|sortija|estafermo"),
    Theme("bandols", "Bàndols i bandejats",
          "Canamunts i Canavalls, quadrilles de bandolers i treves trencades.",
          "bandido, bandolero, bandejado, Canamunt, Canavall, parcialidad, "
          "reyerta",
          r"bandidos?|bandolero|bandejad|canamunt|canavall|parcialidad|reyerta"),
    Theme("inquisicio", "La Inquisició",
          "Actes de fe, relaxats, penitenciats i sambenets.",
          "Inquisición, auto de fe, relajado, penitenciado, judaizante, "
          "sambenito, hereje",
          r"inquisi|auto de fe|relajad|penitenciad|judaiz|sambenito|herej"),
    Theme("temporals", "Llamps, terratrèmols i temporals",
          "Llamps al campanar, neu a ciutat, torrentades i la terra que tremola.",
          "terremoto, temblor, rayo, granizo, pedrisco, nieve, nevada, "
          "inundación, avenida, torrente, aguacero, tempestad, huracán, eclipse",
          r"terremoto|temblor|\brayos?\b|granizo|pedrisco|\bnieve|nevad|inundaci"
          r"|avenida|torrent|aguacero|tempestad|huracan|eclipse"),
    Theme("germania", "La Germania",
          "La revolta de 1521 a 1523: les notícies que la nomenen i els "
          "documents que Campaner en reprodueix sencers.",
          "Germanía, agermanado",
          r"germani|agermanad",
          documents=("0311-II-02", "0311-III-03", "0311-IV-04", "0311-V-05",
                     "0311-VI-06", "0311-VII-07")),
)
