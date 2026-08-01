-- Schema for the cronicon project: Álvaro Campaner y Fuertes, *Cronicón
-- Mayoricense* (Palma, 1881), a chronicle of Mallorca from 1229 to 1800.
--
-- Everything here is derived from `data/` by scripts/build_db.py, and `data/`
-- is derived from the facsimiles by the pipeline. Nothing is entered by hand
-- except `adjudication`, which is the human (or facsimile-verified) ground
-- truth and the only table that cannot be regenerated.
--
-- The organising idea is that **certainty travels with the text**. Every word
-- carries the tier its consensus landed in, so a query can ask for the
-- confident part of the book, or for exactly the doubtful part, and a reader
-- can be shown which is which. A transcription that cannot say how sure it is
-- is not much use for research, and this book is 21% medieval Catalan and Latin
-- where the panel is measurably weaker than on the Spanish prose.

-- Leaves ----------------------------------------------------------------

-- One row per leaf that carries running text (614 of the 671 in the PDF).
-- `scan`, `geometry` and `align` record how that leaf was read: four leaves are
-- voted on the BNE images because the Internet Archive ones are out of focus,
-- and 25 are aligned line-by-line because the engines cannot agree how many
-- columns the page has. `accept_unanimous` is false on those 25 -- their
-- unanimity is not covered by any adjudication and must not be accepted unread.
CREATE TABLE IF NOT EXISTS leaf (
    pdf_page          SMALLINT PRIMARY KEY,  -- page in data/raw/*.pdf
    ia_leaf           SMALLINT,              -- Internet Archive leaf = pdf_page - 2
    printed_page      VARCHAR,               -- as printed, where legible
    section           VARCHAR,               -- front_matter | introduction | body | …
    kind              VARCHAR,               -- chronicle | jurats_table | document
    columns           SMALLINT,
    scan              VARCHAR,               -- ia | bne | default
    geometry          VARCHAR,               -- which engine gave the word boxes
    align             VARCHAR,               -- page | line
    accept_unanimous  BOOLEAN NOT NULL DEFAULT TRUE,
    words             INTEGER
);

-- The transcription ------------------------------------------------------

-- One row per word position, in reading order. `text` is what the edition
-- publishes; `printed` is what the panel voted for where an editorial rule
-- changed it, so every change is reversible from the database alone.
-- `variants` holds the readings the panel rejected, on the 18% of positions
-- where it was not unanimous: a doubtful word can then show what it was
-- argued about instead of only that it was.
-- The box is normalised to the scan named in leaf.scan, which is what makes a
-- facsimile crop reproducible -- and getting that wrong once put every
-- highlight two words off.
CREATE TABLE IF NOT EXISTS word (
    pdf_page  SMALLINT NOT NULL,
    idx       INTEGER  NOT NULL,   -- position in the leaf's reading order
    text      VARCHAR  NOT NULL,
    tier      VARCHAR  NOT NULL,   -- unanimous | one-dissent | two-dissent | contested
    printed   VARCHAR,             -- the panel's reading, when an editorial rule differs
    variants  VARCHAR[],           -- what the engines read here and the edition did not
    x0 REAL, y0 REAL, x1 REAL, y1 REAL,
    PRIMARY KEY (pdf_page, idx)
);

CREATE INDEX IF NOT EXISTS idx_word_tier ON word(tier);

-- The chronicle ----------------------------------------------------------

-- `Mes día.—texto…—SIGLA`. 2 503 entries over 521 distinct years. `sources`
-- holds the sigla naming the manuscript the entry comes from, which is the
-- most interesting thing about this book: you can ask which source reports what.
CREATE TABLE IF NOT EXISTS entry (
    id         INTEGER PRIMARY KEY,
    year       SMALLINT,
    month      SMALLINT,
    day        SMALLINT,
    text       VARCHAR NOT NULL,
    sources    VARCHAR[],          -- ['G. T.', 'B. J.', …]
    pdf_page   SMALLINT NOT NULL,
    printed_page VARCHAR,
    word_from  INTEGER,            -- span into word(pdf_page, idx), inclusive
    word_to    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_entry_year ON entry(year);
CREATE INDEX IF NOT EXISTS idx_entry_page ON entry(pdf_page);

-- Footnotes interrupt the entries; they are separated so that a note's own
-- dates do not read as chronicle. 245 over 178 leaves, 175 of them called by a
-- notice. A note's address is (leaf, column, number), never the number alone:
-- Campaner restarts the numbering at the head of every column, so leaf 74
-- prints (1) and (2) twice.
CREATE TABLE IF NOT EXISTS footnote (
    id        INTEGER PRIMARY KEY,
    entry_id  INTEGER,             -- the entry printing its number, where known
    document_id VARCHAR,           -- …or the document, for the 62 on those leaves
    number    SMALLINT,
    text      VARCHAR NOT NULL,
    pdf_page  SMALLINT NOT NULL
);

-- The six century openings: `SIGLO XIV. / DE 1301 Á 1400.`, then Campaner's
-- list of every manuscript that reports the hundred years to follow. The
-- closest thing the book has to a bibliography, and it used to be published as
-- a chronicle notice of the previous century's last year.
CREATE TABLE IF NOT EXISTS century (
    numeral    VARCHAR PRIMARY KEY,
    from_year  SMALLINT NOT NULL,
    to_year    SMALLINT NOT NULL,
    pdf_page   SMALLINT NOT NULL,
    banner     VARCHAR NOT NULL,
    sources    VARCHAR NOT NULL
);

-- The tables Campaner sets inside the prose: the harvest of a year, the dead
-- of a plague week by week, the census of 1784, who lent how much for the
-- armada of 1343. The transcription had every word and had lost the fact that
-- the figures were in a column. One row per printed row, `label` and `figure`
-- split where the geometry splits them; nothing is added or changed.
CREATE TABLE IF NOT EXISTS table_row (
    table_id  INTEGER NOT NULL,     -- rows of one table share it
    seq       SMALLINT NOT NULL,    -- position in the table, from 0
    pdf_page  SMALLINT NOT NULL,
    text      VARCHAR NOT NULL,    -- the row as the panel read it, unaltered
    label     VARCHAR,              -- the same row cut in two for display
    figure    VARCHAR,
    tier      VARCHAR,              -- worst certainty in the row
    PRIMARY KEY (table_id, seq)
);

-- The Jurats -------------------------------------------------------------

-- Six series, one per century, printed as appendices inside the body.
-- 1 949 names over 356 years, one row per (year, seat, name). `tier` is the
-- worst certainty in the name, and it matters: these are the hardest leaves in
-- the book and only a quarter of the names are unanimous.
CREATE TABLE IF NOT EXISTS jurat (
    id        INTEGER PRIMARY KEY,
    century   SMALLINT NOT NULL,
    year      SMALLINT NOT NULL,
    seat      SMALLINT NOT NULL,  -- 1..6, as printed where the list numbers them
    name      VARCHAR NOT NULL,
    tier      VARCHAR,
    pdf_page  SMALLINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jurat_year ON jurat(year);
CREATE INDEX IF NOT EXISTS idx_jurat_name ON jurat(name);

-- The documents ----------------------------------------------------------

-- The letters, edicts and reprinted booklets Campaner prints in full between
-- the centuries. 23 sections over 159 leaves. `genre` is the noun he opens the
-- title with -- Cartas, Sentencia, Relacion, Memorial -- which is better
-- evidence than any classification of ours.
CREATE TABLE IF NOT EXISTS document (
    id           VARCHAR PRIMARY KEY,   -- e.g. '0114-II-02'
    block_leaf   SMALLINT NOT NULL,
    numeral      VARCHAR,
    number       SMALLINT,
    title        VARCHAR NOT NULL,
    genre        VARCHAR,
    first_leaf   SMALLINT NOT NULL,
    last_leaf    SMALLINT NOT NULL,
    words        INTEGER,
    contested    INTEGER,
    text         VARCHAR
);

-- Campaner numbers the pieces inside two of the documents and sets the number
-- alone over each: the 21 letters Gilaberto de Centellas wrote to Pedro IV in
-- 1343, and the 21 pieces of the `Nota de varias ejecuciones` of June 1523.
-- That numbering is the only thing that delimits a letter -- the salutation
-- `Molt alt e molt poderos princep e Senyor` recurs inside them as often as at
-- their head -- so without it a fourteen-leaf section is one wall of prose.
-- `paragraph` is the index into the document's text, counted in paragraphs.
CREATE TABLE IF NOT EXISTS piece (
    document_id VARCHAR NOT NULL,
    number      SMALLINT NOT NULL,
    paragraph   INTEGER NOT NULL,
    pdf_page    SMALLINT NOT NULL,
    PRIMARY KEY (document_id, number)
);

-- The sources ------------------------------------------------------------

-- Campaner's glossary of manuscript sigla, from leaf 25. `source` is 'parsed'
-- or 'adjudicated': eight entries are set in a swash italic every engine
-- mangles and were read off the facsimile by eye.
-- The dossier columns come from the eight leaves of introduction *before* the
-- list, where Campaner says who each man was, what his manuscript physically
-- is, the years it covers and where it was in 1881. `leaf` is which of those
-- leaves says so, because a claim about a source should be checkable against
-- the facsimile like everything else here.
CREATE TABLE IF NOT EXISTS siglum (
    siglum       VARCHAR PRIMARY KEY,   -- 'G. T.'
    expansion    VARCHAR NOT NULL,      -- 'Guillermo Terrassa.'
    source       VARCHAR,               -- parsed | adjudicated | described
    attributions INTEGER,
    life         VARCHAR,               -- '1709–1778'
    role         VARCHAR,               -- 'prevere i paborde de la Seu'
    span         VARCHAR,               -- what years the manuscript covers
    work         VARCHAR,               -- its title, as Campaner prints it
    note         VARCHAR,
    leaf         SMALLINT
);

-- The evidence -----------------------------------------------------------

-- The only table not derived from anything: 870 positions settled against the
-- facsimile. `chose` is what the page prints; `winner` is what the panel voted.
-- `source` is 'variant' when the reading came from an engine and 'typed' when
-- no engine had it -- 11 of the document positions are typed, mostly the long
-- s. `by` records who adjudicated, because a measurement made by whoever built
-- the pipeline is weaker evidence than an independent one.
CREATE TABLE IF NOT EXISTS adjudication (
    sample_id  INTEGER PRIMARY KEY,
    family     VARCHAR NOT NULL,     -- 'sample' (chronicle) | 'documents'
    pdf_page   SMALLINT NOT NULL,
    tier       VARCHAR,
    winner     VARCHAR,
    chose      VARCHAR NOT NULL,
    source     VARCHAR,              -- variant | typed
    adjudged_by VARCHAR,           -- who settled it
    context    VARCHAR,
    x0 REAL, y0 REAL, x1 REAL, y1 REAL
);

CREATE INDEX IF NOT EXISTS idx_adj_family ON adjudication(family, tier);
