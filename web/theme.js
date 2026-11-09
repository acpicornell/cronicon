/* Applies the reader's stored choices before the first paint.

   Loaded synchronously in <head>, as a file of its own: the site's
   Content-Security-Policy is `script-src 'self'` with no inline scripts, so
   this cannot be an inline block, and it cannot be deferred either or the page
   would flash light before turning dark.

   Two attributes on <html>:
     data-theme  "light" | "dark"   -- absent means "follow the system"
     data-doubt  "on" | "off" | "variants"   -- how disputed readings are shown

   Nothing else happens here. The controls that change them live in app.js. */
(function () {
  "use strict";
  var root = document.documentElement;
  try {
    var theme = localStorage.getItem("cronicon-theme");
    if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
    var doubt = localStorage.getItem("cronicon-doubt");
    root.setAttribute("data-doubt",
      doubt === "off" || doubt === "variants" ? doubt : "on");
  } catch (e) {
    root.setAttribute("data-doubt", "on");
  }
})();
