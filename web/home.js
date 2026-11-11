/* Cronicón Mayoricense — the home page: "tal dia com avui".

   The page arrives with one notice already in it, chosen at build time. This
   script replaces it with the notices the chronicle gives for today's day and
   month in other centuries, and adds a button for one at random. If it does
   not run, or the fetch fails, the notice that was there stays.

   The data is `dies/MM.json` -- the dated notices short enough to show whole,
   one file per month, from this origin -- so the page asks for the current
   month and nothing else. Nothing is inserted as markup that was not escaped
   here. */
(function () {
  "use strict";

  var root = document.documentElement.getAttribute("data-root") || "";
  var body = document.getElementById("avui-body");
  var title = document.getElementById("avui-title");
  var button = document.getElementById("atzar");
  if (!body || !title) return;

  var MONTHS = ["", "de gener", "de febrer", "de març", "d'abril", "de maig",
                "de juny", "de juliol", "d'agost", "de setembre", "d'octubre",
                "de novembre", "de desembre"];
  var SHORT = ["", "gen.", "febr.", "març", "abr.", "maig", "juny", "jul.",
               "ag.", "set.", "oct.", "nov.", "des."];
  var SHOWN = 4;   // notices of the day shown before "totes"

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function getJson(path) {
    return fetch(root + path).then(function (r) {
      if (!r.ok) throw new Error(path);
      return r.json();
    });
  }

  var months = {};
  function month(m) {
    if (!months[m]) months[m] = getJson("dies/" + (m < 10 ? "0" : "") + m + ".json");
    return months[m];
  }
  var names = getJson("data.json").then(function (data) {
    var out = {};
    data.sigla.forEach(function (s) { if (s.expansion) out[s.siglum] = s.expansion; });
    return out;
  }).catch(function () { return {}; });

  // The same chip the build writes: a button that gives up the source's name.
  // `app.js` handles the click for these as for any other.
  function chip(siglum, sigla) {
    var name = sigla[siglum] || "La introducció no diu de qui són aquestes inicials.";
    return '<span class="cite"><button class="sig' + (sigla[siglum] ? "" : " unglossed") +
      '" type="button" aria-expanded="false">' + escapeHtml(siglum) +
      '</button><span class="sig-name">' + escapeHtml(name) + "</span></span>";
  }

  // row: [id, year, day, text, [sigla]]
  function notice(row, m, sigla) {
    var chips = (row[4] || []).map(function (s) { return chip(s, sigla); }).join(" ");
    return '<article class="notice"><p class="when"><a href="' + root + "anys/" +
      row[1] + "/#n" + row[0] + '">' + row[1] + "</a> <small>" + row[2] + " " +
      escapeHtml(SHORT[m]) + '</small></p><div class="said"><div lang="es" ' +
      'translate="no"><p>' + escapeHtml(row[3]) + "</p></div>" +
      (chips ? '<p class="prov">' + chips + "</p>" : "") + "</div></article>";
  }

  function show(heading, rows, m, sigla) {
    title.textContent = heading;
    var html = rows.slice(0, SHOWN).map(function (r) { return notice(r, m, sigla); }).join("");
    body.innerHTML = html;
    if (rows.length > SHOWN) {
      var all = document.createElement("button");
      all.type = "button";
      all.className = "button ghost";
      all.textContent = "Totes " + rows.length + " d'aquest dia";
      all.addEventListener("click", function () {
        body.innerHTML = rows.map(function (r) { return notice(r, m, sigla); }).join("");
      });
      body.appendChild(all);
    }
  }

  var now = new Date();
  var m = now.getMonth() + 1, d = now.getDate();
  Promise.all([month(m), names]).then(function (got) {
    var rows = got[0], sigla = got[1];
    var today = rows.filter(function (r) { return r[2] === d; });
    var heading = "Tal dia com avui, " + d + " " + MONTHS[m];
    if (!today.length) {
      // No notice dated today: the nearest day before it, said as such.
      var earlier = rows.filter(function (r) { return r[2] < d; });
      if (!earlier.length) return;
      var day = earlier[earlier.length - 1][2];
      today = earlier.filter(function (r) { return r[2] === day; });
      heading = "Per aquests dies, el " + day + " " + MONTHS[m];
    }
    today.sort(function (a, b) { return a[1] - b[1]; });
    show(heading, today, m, sigla);
  }).catch(function () { /* the notice in the HTML stays */ });

  if (button) {
    button.hidden = false;
    button.addEventListener("click", function () {
      var pick = 1 + Math.floor(Math.random() * 12);
      Promise.all([month(pick), names]).then(function (got) {
        var rows = got[0];
        if (!rows.length) return;
        show("Una notícia a l'atzar",
             [rows[Math.floor(Math.random() * rows.length)]], pick, got[1]);
      }).catch(function () {});
    });
  }
})();
