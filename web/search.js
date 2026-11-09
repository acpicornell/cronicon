/* Cronicón Mayoricense — the search page.

   The whole text is searched in the browser: there is no server to ask. The
   index is the text itself, in shards -- one per century of the chronicle, one
   for the documents, one for the Jurats -- fetched from this origin the first
   time they are needed and never before the reader has asked for something.
   A search confined to a century fetches that century only.

   The state lives in the URL (`?q=pesta&s=17&f=G.+T.&on=cronica`) so a search
   can be linked and the back button works. Every string that reaches the page
   is escaped; the only markup inserted is this file's own. */
(function () {
  "use strict";

  var root = document.documentElement.getAttribute("data-root") || "";
  var form = document.getElementById("sf");
  var out = document.getElementById("results");
  var status = document.getElementById("status");
  if (!form || !out) return;

  var CENTURIES = { 13: "XIII", 14: "XIV", 15: "XV", 16: "XVI", 17: "XVII", 18: "XVIII" };
  var MONTHS = ["", "gen.", "febr.", "març", "abr.", "maig", "juny", "jul.",
                "ag.", "set.", "oct.", "nov.", "des."];
  var PER_GROUP = 50;      // hits shown per group before "mostra'n més"
  var CONTEXT = 110;       // characters of context either side of a hit

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Fold case and accents **one character for one**, so an offset in the
     folded string is an offset in the text and the snippet can be cut around
     the hit. The long s of the 1541 reprint folds to s: `senyor` finds
     `ſenyor`. `scripts/themes.py` folds the same way for the thematic routes. */
  var folded = {};
  function foldChar(c) {
    if (c === "ſ") return "s";
    var base = c.normalize("NFD").charAt(0).toLowerCase();
    return base.length === 1 ? base : c;
  }
  function fold(s) {
    var lower = s.toLowerCase();
    if (lower.length !== s.length) lower = s;       // a letter that grows; rare
    return lower.replace(/[^\x00-\x7f]/g, function (c) {
      return folded[c] || (folded[c] = foldChar(c));
    });
  }

  /* --- Shards ----------------------------------------------------------- */
  var cache = {};
  function shard(name) {
    if (!cache[name]) {
      cache[name] = fetch(root + "search/" + name + ".json")
        .then(function (r) {
          if (!r.ok) throw new Error(name);
          return r.json();
        })
        .then(function (rows) {
          // Fold once, when the shard arrives; every later keystroke reuses it.
          if (name === "docs") {
            rows.forEach(function (d) { d.push(d[3].map(fold)); });
          } else if (name === "jurats") {
            rows.forEach(function (j) { j.push(fold(j[2])); });
          } else {
            rows.forEach(function (e) { e.push(fold(e[6])); });
          }
          return rows;
        });
    }
    return cache[name];
  }

  /* --- The query -------------------------------------------------------- */
  function parse(q) {
    // "exact phrase" other words  ->  every term must occur in the notice
    var terms = [];
    q.replace(/"([^"]+)"|(\S+)/g, function (_m, phrase, word) {
      var t = fold((phrase || word).trim());
      if (t) terms.push(t);
    });
    return terms;
  }

  function firstHit(text, terms) {
    // Position of the first term, or -1 unless every term is present.
    var at = -1;
    for (var i = 0; i < terms.length; i++) {
      var p = text.indexOf(terms[i]);
      if (p < 0) return -1;
      if (i === 0) at = p;
    }
    return at;
  }

  function snippet(text, at, len) {
    if (at < 0 || !len) {
      return escapeHtml(text.length > 2 * CONTEXT + 40
        ? text.slice(0, 2 * CONTEXT + 40).replace(/\s+\S*$/, "") + " …" : text);
    }
    var a = Math.max(0, at - CONTEXT), b = Math.min(text.length, at + len + CONTEXT);
    if (a > 0) a = text.indexOf(" ", a) + 1;
    if (b < text.length) b = text.lastIndexOf(" ", b);
    if (b <= at + len) b = Math.min(text.length, at + len);
    return (a > 0 ? "… " : "") + escapeHtml(text.slice(a, at)) +
      "<mark>" + escapeHtml(text.slice(at, at + len)) + "</mark>" +
      escapeHtml(text.slice(at + len, b)) + (b < text.length ? " …" : "");
  }

  function state() {
    var data = new FormData(form);
    return { q: (data.get("q") || "").trim(), s: data.get("s") || "",
             f: data.get("f") || "", on: data.get("on") || "" };
  }

  function writeUrl(st) {
    var params = new URLSearchParams();
    ["q", "s", "f", "on"].forEach(function (k) { if (st[k]) params.set(k, st[k]); });
    var qs = params.toString();
    history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  }

  function readUrl() {
    var params = new URLSearchParams(location.search);
    form.elements.q.value = params.get("q") || "";
    ["s", "on"].forEach(function (name) {
      var want = params.get(name) || "";
      Array.prototype.forEach.call(form.elements[name], function (radio) {
        radio.checked = radio.value === want;
      });
    });
    form.elements.f.value = params.get("f") || "";
  }

  /* --- Rendering -------------------------------------------------------- */
  function group(id, title, hits, render) {
    var section = document.createElement("section");
    section.className = "group";
    section.id = id;
    var h = document.createElement("h2");
    h.innerHTML = escapeHtml(title) + " <small>" +
      (hits.length === 1 ? "1 resultat" : hits.length.toLocaleString("ca") + " resultats") +
      "</small>";
    section.appendChild(h);
    var list = document.createElement("div");
    section.appendChild(list);
    var shown = 0;
    function more() {
      var html = "";
      hits.slice(shown, shown + PER_GROUP).forEach(function (hit) { html += render(hit); });
      list.insertAdjacentHTML("beforeend", html);
      shown += PER_GROUP;
      if (button) button.hidden = shown >= hits.length;
    }
    var button = null;
    if (hits.length > PER_GROUP) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost more";
      button.textContent = "Mostra'n més";
      button.addEventListener("click", more);
      section.appendChild(button);
    }
    more();
    return section;
  }

  function fragment(matched) {
    // A text fragment makes the browser highlight the match on arrival, with
    // no script on the page it lands on; where unsupported it is ignored.
    if (!matched || matched.length > 60 || /[-,&\n]/.test(matched)) return "";
    return ":~:text=" + encodeURIComponent(matched);
  }

  function entryHit(hit) {
    var e = hit.row, date = (e[3] ? e[3] + " " : "") + (e[2] ? MONTHS[e[2]] : "");
    var matched = hit.at >= 0 ? e[6].slice(hit.at, hit.at + hit.len) : "";
    var href = root + "anys/" + e[1] + "/#n" + e[0] + fragment(matched);
    return '<article class="notice hit"><p class="when"><a href="' + href + '">' +
      e[1] + "</a> <small>" + escapeHtml(date) + '</small></p><div class="said">' +
      '<div lang="es" translate="no"><p>' + snippet(e[6], hit.at, hit.len) + "</p></div>" +
      (e[5] && e[5].length
        ? '<p class="prov">' + escapeHtml(e[5].join(" · ")) + "</p>" : "") +
      "</div></article>";
  }

  function docHit(hit) {
    var d = hit.doc, text = d[3][hit.para];
    var href = root + "documents/" + d[0] + "/#p" + hit.para;
    return '<article class="notice hit"><p class="when"><a href="' + href + '">' +
      escapeHtml(d[1]) + '</a></p><div class="said"><p class="prov">' +
      escapeHtml(d[2]) + '</p><div translate="no"><p>' +
      snippet(text, hit.at, hit.len) + "</p></div></div></article>";
  }

  function juratHit(hit) {
    var j = hit.row;
    return '<article class="notice hit"><p class="when"><a href="' + root + "jurats/" +
      j[0] + "/#y" + j[1] + '">' + j[1] + '</a></p><div class="said"><p lang="es" ' +
      'translate="no">' + snippet(j[2], hit.at, hit.len) + "</p></div></article>";
  }

  /* --- Running a search ------------------------------------------------- */
  var seq = 0;
  function run() {
    var st = state();
    writeUrl(st);
    var terms = parse(st.q);
    var my = ++seq;
    out.textContent = "";
    if (!terms.length && !st.f) { status.textContent = ""; return; }
    status.textContent = "Cercant…";

    var len = terms.length ? terms[0].length : 0;
    var total = 0, pending = 0;
    function done() {
      if (my !== seq) return;
      pending -= 1;
      if (pending > 0) return;
      status.textContent = total
        ? (total === 1 ? "1 resultat" : total.toLocaleString("ca") + " resultats")
        : "Cap resultat. Prova amb menys mots, o sense el filtre.";
    }
    function place(section, order) {
      // Shards arrive in any order; the groups keep the book's.
      section.dataset.order = order;
      var next = Array.prototype.filter.call(out.children, function (el) {
        return Number(el.dataset.order) > order;
      })[0];
      out.insertBefore(section, next || null);
    }

    // A year typed on its own is a place to go, not only a word to find.
    var year = /^\d{4}$/.test(st.q) ? Number(st.q) : 0;
    if (year >= 1229 && year <= 1800) {
      var go = document.createElement("p");
      go.className = "hint";
      go.dataset.order = 0;
      go.innerHTML = 'Vols anar a l\'any <a href="' + root + "anys/" + year + '/">' +
        year + "</a>?";
      out.appendChild(go);
    }

    if (st.on === "" || st.on === "cronica") {
      (st.s ? [st.s] : Object.keys(CENTURIES)).forEach(function (c) {
        pending += 1;
        shard("c" + c).then(function (rows) {
          if (my !== seq) return;
          var hits = [];
          rows.forEach(function (e) {
            if (st.f && (!e[5] || e[5].indexOf(st.f) < 0)) return;
            var at = terms.length ? firstHit(e[7], terms) : -2;
            if (at === -1) return;
            hits.push({ row: e, at: at, len: len });
          });
          if (hits.length) {
            total += hits.length;
            place(group("g" + c, "Segle " + CENTURIES[c], hits, entryHit), Number(c));
          }
        }).catch(function () {
          if (my === seq) status.textContent = "No s'ha pogut carregar l'índex.";
        }).then(done);
      });
    }
    // A source or a century says nothing about the documents or the Jurats'
    // names, so those are searched only when neither filter is set.
    if (terms.length && !st.f && (st.on === "" || st.on === "documents")) {
      pending += 1;
      shard("docs").then(function (docs) {
        if (my !== seq) return;
        var hits = [];
        docs.forEach(function (d) {
          d[4].forEach(function (text, i) {
            var at = firstHit(text, terms);
            if (at >= 0) hits.push({ doc: d, para: i, at: at, len: len });
          });
        });
        if (hits.length) {
          total += hits.length;
          place(group("gd", "Documents sencers", hits, docHit), 50);
        }
      }).catch(function () {}).then(done);
    }
    if (terms.length && !st.f && (st.on === "" || st.on === "jurats")) {
      pending += 1;
      shard("jurats").then(function (rows) {
        if (my !== seq) return;
        var hits = [];
        rows.forEach(function (j) {
          if (st.s && String(j[0]) !== st.s) return;
          var at = firstHit(j[3], terms);
          if (at >= 0) hits.push({ row: j, at: at, len: len });
        });
        if (hits.length) {
          total += hits.length;
          place(group("gj", "Jurats", hits, juratHit), 60);
        }
      }).catch(function () {}).then(done);
    }
    if (!pending) { pending = 1; done(); }
  }

  var timer = 0;
  function soon() { clearTimeout(timer); timer = setTimeout(run, 160); }

  form.addEventListener("submit", function (event) { event.preventDefault(); run(); });
  form.addEventListener("input", soon);
  form.addEventListener("change", run);
  form.elements.q.addEventListener("keydown", function (event) {
    if (event.key === "Escape") { form.elements.q.value = ""; run(); }
  });
  window.addEventListener("popstate", function () { readUrl(); run(); });

  readUrl();
  run();
  if (!form.elements.q.value) form.elements.q.focus();
})();
