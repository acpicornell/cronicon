// Cronicón Mayoricense — vanilla JS, no build step, no dependencies.
//
// Three things happen here: full-text search over the whole edition, the
// toggle that hides the uncertainty marks for anyone who would rather just
// read, and nothing else.
//
// The search corpus is the book's own text — 2.4 MB of it, 659 KB over the
// wire — and it is fetched on the FIRST KEYSTROKE, never on load. Someone who
// arrived to read what happened in 1521 does not pay for a feature they did
// not ask for. An inverted index would have been 276 KB, but it can only say
// *which* entry matched, not show the line it matched on, and a chronicle
// search that cannot show you the sentence is barely a search.
//
// This still is not the whole apparatus. Every word's certainty, every engine's
// reading, the adjudications — those live in the parquet, where SQL is a better
// tool than a text box:
//
//   SELECT year, text FROM 'https://cronicon.corpusbalear.org/data/entry.parquet'
//   WHERE text ILIKE '%germania%';

const $ = (id) => document.getElementById(id);
const MAX_HITS = 40;      // shown; the count reported is the true total
const PAD = 110;          // characters of context each side of a hit

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Accent-insensitive folding, done with an explicit table rather than
// `normalize("NFD")`, and the reason is not style. A hit is found in the folded
// text but the snippet must be cut from the ORIGINAL, so the two strings have
// to agree character for character. NFD does not guarantee that — one input
// character can come back as two, or as none — and when it slips the snippet
// silently shifts and the highlight lands on the wrong word. A one-to-one table
// cannot slip. The book is Spanish, Catalan and Latin; this covers it.
const ACCENTED = "áàâäãåéèêëíìîïóòôöõøúùûüñçýÿÁÀÂÄÃÅÉÈÊËÍÌÎÏÓÒÔÖÕØÚÙÛÜÑÇÝ";
const PLAIN    = "aaaaaaeeeeiiiioooooouuuuncyyaaaaaaeeeeiiiioooooouuuuncy";
const FOLD = new Map();
for (let i = 0; i < ACCENTED.length; i++) FOLD.set(ACCENTED[i], PLAIN[i]);

function fold(s) {
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c < 128) {                       // the fast path: most of the book
      out += (c >= 65 && c <= 90) ? String.fromCharCode(c + 32) : s[i];
    } else {
      out += FOLD.get(s[i]) ?? s[i].toLowerCase();
    }
  }
  // Belt and braces: if some character we did not anticipate changed the
  // length, fall back to the original so the offsets stay truthful. Matching
  // suffers; the snippet never lies.
  return out.length === s.length ? out : s;
}

let meta = null;          // data.json — years, documents, sigla, stats
let corpus = null;        // search.json, folded and ready
let corpusPromise = null;

async function loadMeta() {
  if (!meta) meta = await (await fetch("data.json")).json();
  return meta;
}

function loadCorpus() {
  if (corpusPromise) return corpusPromise;
  corpusPromise = fetch("search.json")
    .then((r) => r.json())
    .then((j) => {
      corpus = {
        entries: j.e.map(([y, page, text]) => ({ y, page, text, f: fold(text) })),
        docs: j.d.map(([id, title, text]) => ({ id, title, text, f: fold(text) })),
      };
      return corpus;
    });
  return corpusPromise;
}

// One snippet per hit, cut from the original text around the match. Callers get
// escaped HTML, so the raw text never reaches the page unescaped.
function snippet(text, at, len) {
  const from = Math.max(0, at - PAD);
  const to = Math.min(text.length, at + len + PAD);
  const head = (from > 0 ? "…" : "") + text.slice(from, at);
  const tail = text.slice(at + len, to) + (to < text.length ? "…" : "");
  return esc(head) + "<mark>" + esc(text.slice(at, at + len)) + "</mark>" +
         esc(tail);
}

function scan(records, needle) {
  const hits = [];
  let total = 0;
  for (const r of records) {
    const at = r.f.indexOf(needle);
    if (at < 0) continue;
    total++;
    if (hits.length < MAX_HITS) hits.push({ r, at });
  }
  return { hits, total };
}

// Years, sigla and document titles answer instantly from the small payload,
// before the corpus has finished arriving.
function quickAnswers(needle, raw) {
  const out = [];
  if (!meta) return out;

  if (/^\d{3,4}$/.test(needle)) {
    const y = Number(needle);
    const found = meta.years.find((v) => v.y === y);
    if (found && found.n) {
      out.push(`<p class="quick">Any <a href="anys/${y}/"><strong>${y}</strong></a>
                — ${found.n} ${found.n === 1 ? "notícia" : "notícies"}.</p>`);
    } else if (found) {
      out.push(`<p class="quick">L'any <a href="anys/${y}/"><strong>${y}</strong></a>
                no duu cap notícia datada.</p>`);
    }
  }

  const sigla = meta.sigla.filter(
    (s) => fold(s.siglum).includes(needle) || fold(s.expansion).includes(needle));
  if (sigla.length && raw.length >= 2) {
    out.push('<p class="quick"><strong>Fonts manuscrites</strong></p><ul>' +
      sigla.slice(0, 6).map((s) =>
        `<li><code>${esc(s.siglum)}</code> ${esc(s.expansion)} ` +
        `<small>(${s.attributions ?? 0} notícies)</small></li>`).join("") +
      "</ul>");
  }

  const docs = meta.documents.filter(
    (d) => fold(d.title).includes(needle) || fold(d.genre || "").includes(needle));
  if (docs.length) {
    out.push('<p class="quick"><strong>Documents</strong></p><ul>' +
      docs.map((d) =>
        `<li><a href="documents/${esc(d.id)}/">${esc(d.numeral)}. ` +
        `${esc(d.title)}</a> <small>(fulls ${d.first_leaf}–${d.last_leaf})</small>` +
        "</li>").join("") + "</ul>");
  }
  return out;
}

let seq = 0;   // guards against a slow corpus load overwriting a newer query

async function search(raw) {
  const box = $("results");
  const mine = ++seq;
  const trimmed = raw.trim();
  if (trimmed.length < 2) { box.innerHTML = ""; return; }

  // Quoted input is a phrase and is searched verbatim; unquoted is too, in
  // fact — the difference is only that the quotes make that explicit rather
  // than leaving the reader to guess whether the words are ANDed.
  const phrase = /^["«].*["»]$/.test(trimmed);
  const needle = fold(phrase ? trimmed.slice(1, -1).trim() : trimmed);
  if (!needle) { box.innerHTML = ""; return; }

  await loadMeta();
  if (mine !== seq) return;
  const quick = quickAnswers(needle, trimmed);

  if (!corpus) {
    box.innerHTML = quick.join("") +
      '<p class="loading">Cercant dins el text del llibre…</p>';
    await loadCorpus();
    if (mine !== seq) return;
  }

  const inEntries = scan(corpus.entries, needle);
  const inDocs = scan(corpus.docs, needle);
  const total = inEntries.total + inDocs.total;

  if (!total) {
    box.innerHTML = quick.join("") || (
      `<p>Cap resultat per <strong>${esc(trimmed)}</strong>. El llibre és de
       1881 i no s'ha modernitzat: prova <em>Setiembre</em>, no <em>Septiembre</em>.</p>`);
    return;
  }

  const parts = quick.slice();
  parts.push(`<p class="tally">${total.toLocaleString("ca")} ` +
    `${total === 1 ? "passatge" : "passatges"}` +
    (total > MAX_HITS ? `, en mostram ${MAX_HITS}` : "") + ".</p>");

  if (inEntries.hits.length) {
    parts.push('<p class="quick"><strong>A la crònica</strong> ' +
      `<small>(${inEntries.total.toLocaleString("ca")})</small></p><ol class="hits">` +
      inEntries.hits.map(({ r, at }) =>
        `<li><a href="anys/${r.y}/">${r.y}</a> ` +
        `<span class="leaf">full ${r.page}</span>` +
        `<q>${snippet(r.text, at, needle.length)}</q></li>`).join("") + "</ol>");
  }
  if (inDocs.hits.length) {
    parts.push('<p class="quick"><strong>Als documents</strong> ' +
      `<small>(${inDocs.total.toLocaleString("ca")})</small></p><ol class="hits">` +
      inDocs.hits.map(({ r, at }) =>
        `<li><a href="documents/${esc(r.id)}/">${esc(r.title)}</a>` +
        `<q>${snippet(r.text, at, needle.length)}</q></li>`).join("") + "</ol>");
  }
  box.innerHTML = parts.join("");
}

function init() {
  const q = $("q");
  if (q) {
    let timer = null;
    q.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => search(q.value), 120);
    });
    // Start fetching as soon as the box is touched, so the corpus is usually
    // there by the time the second character is typed.
    q.addEventListener("focus", loadCorpus, { once: true });
    loadMeta().then(() => { if (q.value) search(q.value); });
  }

  const plain = $("plain");
  if (plain) {
    // Remembered, because someone who wants to read rather than audit should
    // not have to say so on every page.
    const saved = localStorage.getItem("cronicon-plain") === "1";
    plain.checked = saved;
    document.body.classList.toggle("plain", saved);
    plain.addEventListener("change", () => {
      document.body.classList.toggle("plain", plain.checked);
      localStorage.setItem("cronicon-plain", plain.checked ? "1" : "0");
    });
  }
}

// The year and document pages carry the same toggle without the search box.
document.addEventListener("DOMContentLoaded", init);
