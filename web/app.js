/* Cronicón Mayoricense — what every page can do.

   Vanilla JavaScript, no dependencies, no build step, and no request to any
   origin but this one -- with a single exception that only ever happens on a
   click: an image of a page of the facsimile, from the Internet Archive.

   Everything here is an enhancement. The text is in the HTML; the links to the
   facsimile are real links; the search box is a real form. With scripts off
   the site still reads, it just does not open a leaf in place or remember how
   the reader likes the disputed readings shown.

   The page-specific scripts are separate files: `search.js` on /cerca/ and
   `home.js` on the home page. `theme.js` runs earlier, in <head>, to set the
   theme before the first paint. */
(function () {
  "use strict";

  var root = document.documentElement;
  var $ = function (id) { return document.getElementById(id); };

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }

  /* --- Sigla ------------------------------------------------------------
     Campaner attributes each notice to its manuscript by an abbreviation that
     only the introduction explains, and this edition does not publish the
     introduction. So every siglum is a button that gives up its name. One
     delegated listener: a year page carries a hundred of them, and the home
     page adds more after load. */
  document.addEventListener("click", function (event) {
    var chip = event.target.closest && event.target.closest("button.sig");
    if (chip) {
      chip.setAttribute("aria-expanded",
        chip.getAttribute("aria-expanded") === "true" ? "false" : "true");
      return;
    }
    /* A disputed word shows what else was read there. Touch and keyboard have
       no hover, so this is a click -- and the "amb les variants" mode shows
       them all at once for a reader who wants every one. */
    var doubt = event.target.closest && event.target.closest(".d[data-v]");
    if (doubt && root.getAttribute("data-doubt") !== "off") {
      doubt.classList.toggle("open");
    }
  });

  /* --- How disputed readings are shown ---------------------------------- */
  var radios = document.querySelectorAll('input[name="doubt"]');
  Array.prototype.forEach.call(radios, function (radio) {
    radio.checked = radio.value === (root.getAttribute("data-doubt") || "on");
    radio.addEventListener("change", function () {
      if (!radio.checked) return;
      root.setAttribute("data-doubt", radio.value);
      store("cronicon-doubt", radio.value);
    });
  });

  /* --- Theme ------------------------------------------------------------
     With no stored choice the page follows the system. The button flips
     whatever is showing and remembers that. */
  var themeButton = $("theme");
  if (themeButton) {
    themeButton.addEventListener("click", function () {
      var showing = root.getAttribute("data-theme") ||
        (window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark" : "light");
      var next = showing === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      store("cronicon-theme", next);
    });
  }

  /* --- The facsimile, in place ------------------------------------------
     Every reference to a leaf is a link to the Internet Archive's reader with
     the leaf number in `data-leaf`. A plain click opens that page's image here
     instead; any modified click (new tab, new window) is left alone, and so is
     everything if <dialog> is not supported.

     The image element is created on the click and not before, so a reader who
     never opens a leaf never makes a request to the Archive. `no-referrer`
     keeps the page they were reading out of that request. */
  var ARCHIVE = "https://archive.org/details/CroniconMayoricenseCampaner/page/n";
  var IIIF = "https://iiif.archive.org/iiif/CroniconMayoricenseCampaner%24";
  var FIRST_LEAF = 2, LAST_LEAF = 670;
  var dialog = $("facs");
  var showing = 0;

  function showLeaf(leaf) {
    showing = Math.min(LAST_LEAF, Math.max(FIRST_LEAF, leaf));
    var stage = $("facs-stage");
    $("facs-n").textContent = showing;
    $("facs-ext").href = ARCHIVE + (showing - 2) + "/mode/2up";
    stage.textContent = "";
    var wait = document.createElement("p");
    wait.textContent = "Carregant el full…";
    stage.appendChild(wait);
    var img = new Image();
    img.referrerPolicy = "no-referrer";
    img.alt = "Full " + showing + " del facsímil del Cronicón Mayoricense";
    img.onload = function () {
      if (img.dataset.leaf !== String(showing)) return;
      stage.textContent = "";
      stage.appendChild(img);
    };
    img.onerror = function () {
      if (img.dataset.leaf !== String(showing)) return;
      wait.textContent = "L'Internet Archive no ha servit la imatge. " +
        "L'enllaç de dalt obre el full al seu lector.";
    };
    img.dataset.leaf = String(showing);
    img.src = IIIF + (showing - 2) + "/full/1200,/0/default.jpg";
  }

  if (dialog && typeof dialog.showModal === "function") {
    document.addEventListener("click", function (event) {
      var link = event.target.closest && event.target.closest("a[data-leaf]");
      if (!link || event.defaultPrevented || event.button !== 0 ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      showLeaf(parseInt(link.getAttribute("data-leaf"), 10));
      if (!dialog.open) dialog.showModal();
    });
    $("facs-prev").addEventListener("click", function () { showLeaf(showing - 1); });
    $("facs-next").addEventListener("click", function () { showLeaf(showing + 1); });
    /* A click on the backdrop closes it, as readers expect of an overlay. */
    dialog.addEventListener("click", function (event) {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", function () { $("facs-stage").textContent = ""; });
  }

  /* --- "/" goes to the search box --------------------------------------- */
  document.addEventListener("keydown", function (event) {
    if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
    var el = document.activeElement;
    if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return;
    var box = $("q") || $("hq");
    if (box) { event.preventDefault(); box.focus(); box.select(); }
  });

  /* --- Filter the Jurats of a century by name ---------------------------
     The names are already on the page; this only hides the years that have no
     seat matching. Accents are folded so `perayre` finds `Perayre`. */
  var filter = $("jf");
  if (filter) {
    var fold = function (s) {
      return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    };
    var cards = Array.prototype.map.call(
      document.querySelectorAll(".serie-year"), function (card) {
        return { card: card, text: fold(card.querySelector(".seats").textContent) };
      });
    filter.addEventListener("input", function () {
      var needle = fold(filter.value.trim());
      var shown = 0;
      cards.forEach(function (item) {
        var hit = !needle || item.text.indexOf(needle) >= 0;
        item.card.hidden = !hit;
        if (hit) shown += 1;
      });
      $("jf-n").textContent = needle
        ? (shown === 1 ? "1 any" : shown + " anys") + " amb aquest nom" : "";
    });
  }
})();
