"""Load the edition into DuckDB, so that all of it can be queried at once.

`data/` holds the edition as files, each shaped for the script that writes it:
the transcription per leaf, the entries as JSONL, the Jurats as rows, the
documents as texts. That is fine for building and useless for asking questions.
The interesting questions cross the files -- which manuscript reports the most
about the Germanía, which surnames hold a Jurat seat across two centuries, how
much of the Catalan is contested -- and none of them can be asked without a join.

Follows the convention of the sibling projects: `db/<name>.duckdb` built from
`db/schema.sql`, rebuilt from scratch every time, plus a parquet export the web
can query in the browser with DuckDB-WASM over range requests.

The one table that is *not* derived is `adjudication`: 870 positions settled
against the facsimile. Everything else can be rebuilt from the PDFs; that cannot.

Sizes, measured rather than hoped for: the per-word certainty is 100 MB as JSON,
14 MB as DuckDB and **4.7 MB as zstd parquet**. That is what makes it possible to
publish the doubt alongside the text instead of hiding it.

Usage:
  python scripts/build_db.py
  python scripts/build_db.py --parquet web/data
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import duckdb

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
DB = PROJECT / "db"


def rows_of(path: Path) -> list[dict]:
    """A JSONL file as a list of dicts."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def load_leaves(con: duckdb.DuckDBPyConnection, consensus: str) -> None:
    inventory = {leaf["pdf_page"]: leaf for leaf in
                 json.loads((DATA / "inventory.json").read_text())["leaves"]}
    sections = json.loads((DATA / "entries" / "sections.json").read_text())
    kind = {}
    for name, key in (("chronicle", "chronicle"), ("jurats_table", "jurats_tables"),
                      ("document", "document_excursus")):
        for page in sections.get(key, []):
            kind[page] = name

    rows = []
    for path in sorted((DATA / "ocr" / consensus).glob("p*.json")):
        leaf = json.loads(path.read_text())
        page = leaf["pdf_page"]
        meta = inventory.get(page, {})
        rows.append((page, meta.get("ia_leaf"), meta.get("printed"),
                     meta.get("page_class"), kind.get(page), meta.get("columns"),
                     leaf.get("scan", "default"), leaf.get("geometry", "tesseract"),
                     leaf.get("align", "page"),
                     bool(leaf.get("accept_unanimous", True)), leaf.get("tokens")))
    con.executemany("INSERT INTO leaf VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    print(f"  leaf          {len(rows):>8,}")


def load_words(con: duckdb.DuckDBPyConnection) -> None:
    """Every word of the edition, with its certainty and its box.

    Read by DuckDB straight off the per-leaf JSON rather than looped over in
    Python: 473 423 rows through `executemany` take five minutes, and this takes
    seconds. `unnest` turns each leaf's `words` array into rows, and the index
    within the leaf -- which is the reading order, and half the primary key --
    comes from the array position rather than being counted by hand.
    """
    con.execute(f"""
        INSERT INTO word
        SELECT pdf_page,
               CAST(pos - 1 AS INTEGER)                AS idx,
               w.text, w.tier, w.printed, w.variants,
               w.bbox[1], w.bbox[2], w.bbox[3], w.bbox[4]
        FROM (
            SELECT pdf_page,
                   unnest(words)                        AS w,
                   generate_subscripts(words, 1)        AS pos
            FROM read_json('{DATA / "text"}/p*.json',
                           columns = {{
                             pdf_page: 'SMALLINT',
                             words: 'STRUCT(text VARCHAR, tier VARCHAR,
                                            printed VARCHAR, variants VARCHAR[],
                                            bbox DOUBLE[], line DOUBLE[])[]'
                           }})
        )
    """)
    n = con.execute("SELECT count(*) FROM word").fetchone()[0]
    print(f"  word          {n:>8,}")


def load_entries(con: duckdb.DuckDBPyConnection) -> None:
    entries = rows_of(DATA / "entries" / "entries.jsonl")
    rows, notes = [], []
    for n, e in enumerate(entries, 1):
        rows.append((n, e.get("year"), e.get("month"), e.get("day"), e["text"],
                     e.get("sources") or [], e["pdf_page"], e.get("printed"),
                     None, None))
        for note in e.get("notes") or []:
            notes.append((len(notes) + 1, n, note.get("number"), note["text"],
                          note.get("pdf_page", e["pdf_page"])))
    con.executemany("INSERT INTO entry VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO footnote VALUES (?,?,?,?,?)", notes)
    print(f"  entry         {len(rows):>8,}")
    print(f"  footnote      {len(notes):>8,}")


def load_centuries(con: duckdb.DuckDBPyConnection) -> None:
    path = DATA / "entries" / "centuries.json"
    if not path.exists():
        return
    rows = [(c["numeral"], c["from_year"], c["to_year"], c["pdf_page"],
             c["banner"], c["text"])
            for c in json.loads(path.read_text())]
    con.executemany("INSERT INTO century VALUES (?,?,?,?,?,?)", rows)
    print(f"  century       {len(rows):>8,}")


def load_jurats(con: duckdb.DuckDBPyConnection) -> None:
    rows = [(n, j["century"], j["year"], j["seat"], j["name"], j.get("tier"),
             j["pdf_page"])
            for n, j in enumerate(rows_of(DATA / "jurats" / "jurats.jsonl"), 1)]
    con.executemany("INSERT INTO jurat VALUES (?,?,?,?,?,?,?)", rows)
    print(f"  jurat         {len(rows):>8,}")


def load_documents(con: duckdb.DuckDBPyConnection) -> None:
    sections = json.loads((DATA / "documents" / "sections.json").read_text())
    rows = []
    for s in sections:
        text = (DATA / "documents" / "sections" / f"{s['id']}.txt")
        rows.append((s["id"], s["block_leaf"], s["numeral"], s.get("number"),
                     s["title"], s.get("genre"), s["first_leaf"], s["last_leaf"],
                     s["words"], s["certainty"]["contested"],
                     text.read_text(encoding="utf-8") if text.exists() else None))
    con.executemany("INSERT INTO document VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    print(f"  document      {len(rows):>8,}")


def load_sigla(con: duckdb.DuckDBPyConnection) -> None:
    """The glossary, plus the dossier the introduction gives for each source.

    The unglossed sigla are loaded too when the introduction describes them.
    `L. V.` and `N. F.` attribute 183 notices between them and are simply not in
    the book's own abbreviation list, but Campaner devotes a paragraph to each
    eight leaves earlier -- so they get a row, with `expansion` taken from the
    dossier and `source` marked `described` to say where the name comes from.
    """
    sigla = json.loads((DATA / "sigla" / "sigla.json").read_text())

    def row(entry: dict, expansion: str, origin: str) -> tuple:
        who = entry.get("who") or {}
        return (entry["siglum"], expansion, origin, entry.get("attributions"),
                who.get("life"), who.get("role"), who.get("span"),
                who.get("work"), who.get("note"),
                int(who["leaf"]) if who.get("leaf") else None)

    rows = [row(g, g["expansion"], g.get("source")) for g in sigla["glossary"]]
    rows += [row(u, (u.get("who") or {}).get("name", ""), "described")
             for u in sigla.get("unglossed", [])
             if u["siglum"] in sigla.get("described_only", [])]
    con.executemany("INSERT INTO siglum VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    print(f"  siglum        {len(rows):>8,}")


def load_adjudications(con: duckdb.DuckDBPyConnection) -> None:
    """The ground truth. Two families, never merged: their strata differ."""
    truth: dict[int, str] = {}
    tsv = DATA / "ground_truth" / "adjudicated.tsv"
    if tsv.exists():
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if line.startswith(("#", "id\t")) or not line.strip():
                continue
            parts = line.split("\t")
            truth[int(parts[0])] = parts[1] if len(parts) > 1 else ""

    rows = []
    for path in sorted((DATA / "adjudication").glob("*.json")):
        if not path.name.startswith(("sample", "documents")):
            continue
        data = json.loads(path.read_text())
        if "sample" not in data:
            continue
        family = "documents" if path.name.startswith("documents") else "sample"
        panel = data.get("panel", [])
        for locus in data["sample"]:
            if locus["id"] not in truth:
                continue
            # The truth file stores only what the page prints. The panel's own
            # reading is recomputed here from the variants the sample recorded,
            # so the table can be asked "where was the vote wrong?" without
            # needing the sample JSON alongside it.
            votes = Counter(v for e, v in locus["variants"].items()
                            if e in panel and v is not None)
            winner = votes.most_common(1)[0][0] if votes else None
            rows.append((locus["id"], family, locus["pdf_page"],
                         locus.get("group"), winner, truth[locus["id"]],
                         "variant", "human", locus.get("context"),
                         *locus["bbox"]))

    # The round-3 decisions carry more: which reading was chosen, whether it came
    # from an engine or was typed, and who decided.
    seen = {r[0] for r in rows}
    decisions = DATA / "review" / "decisions.jsonl"
    if decisions.exists():
        for line in decisions.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("sample_id") is None:
                continue
            row = (d["sample_id"], "documents", d["pdf_page"], d.get("grade"),
                   d.get("winner"), d["chose"], d.get("source"),
                   d.get("by", "human"), d.get("context"), *d["bbox"])
            if d["sample_id"] in seen:
                con.execute("DELETE FROM adjudication WHERE sample_id = ?",
                            [d["sample_id"]])
            rows = [r for r in rows if r[0] != d["sample_id"]]
            rows.append(row)
    con.executemany(
        "INSERT INTO adjudication VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    print(f"  adjudication  {len(rows):>8,}")


def load_from_parquet(con: duckdb.DuckDBPyConnection, where: Path,
                      tables: tuple[str, ...]) -> None:
    """Reload tables from the parquet export instead of from `data/`.

    Two tables are derived from files that are not in the repository and cannot
    be: `word` needs the per-leaf sidecars, 100 MB of JSON, and `leaf` needs the
    consensus itself, ten thousand files. Their compact form -- 4.7 MB of zstd
    parquet -- **is** in the repository, because the site queries it in the
    browser, so a clone can rebuild the database and the whole site from what it
    has. That is what makes it possible to stop committing the rendered pages:
    they become derived again rather than being the only copy.
    """
    for table in tables:
        path = where / f"{table}.parquet"
        if not path.exists():
            raise SystemExit(f"{path} missing -- cannot rebuild {table}")
        con.execute(f"INSERT INTO {table} SELECT * FROM read_parquet('{path}')")
        n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<13} {n:>8,}  (from parquet)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--out", default="db/cronicon.duckdb")
    ap.add_argument("--parquet", default=None,
                    help="also export every table as zstd parquet into this "
                         "directory, for DuckDB-WASM in the browser")
    ap.add_argument("--from-parquet", default=None, metavar="DIR",
                    help="rebuild `leaf` and `word` from a parquet export "
                         "rather than from data/ocr and data/text, which are "
                         "not in the repository. Everything else still comes "
                         "from data/. This is how a fresh clone rebuilds the "
                         "site: --from-parquet web/data")
    args = ap.parse_args()

    out = PROJECT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()          # rebuilt from scratch; it is derived, not kept

    con = duckdb.connect(str(out))
    con.execute((DB / "schema.sql").read_text())
    print(f"building {out.relative_to(PROJECT)}")
    if args.from_parquet:
        load_from_parquet(con, PROJECT / args.from_parquet, ("leaf", "word"))
    else:
        load_leaves(con, args.consensus)
        load_words(con)
    load_entries(con)
    load_centuries(con)
    load_jurats(con)
    load_documents(con)
    load_sigla(con)
    load_adjudications(con)
    con.execute("CHECKPOINT")

    if args.parquet:
        target = PROJECT / args.parquet
        target.mkdir(parents=True, exist_ok=True)
        for (table,) in con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' ORDER BY 1").fetchall():
            con.execute(f"COPY {table} TO '{target / f'{table}.parquet'}' "
                        f"(FORMAT PARQUET, COMPRESSION ZSTD)")
        total = sum(p.stat().st_size for p in target.glob("*.parquet"))
        print(f"\nparquet -> {target.relative_to(PROJECT)}  "
              f"({total/1048576:.1f} MB)")

    size = out.stat().st_size / 1048576
    print(f"\n{out.relative_to(PROJECT)}  ({size:.1f} MB)")
    con.close()


if __name__ == "__main__":
    main()
