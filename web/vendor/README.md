# Vendored third-party assets

The fonts are self-hosted, not loaded from any CDN at runtime, so the site has
no external code or style dependency and can enforce a strict
Content-Security-Policy (`font-src 'self'`, `style-src 'self'`). They are
redistributed here under their own licence, whose full text sits beside them.

| Asset | Source | Licence | Licence file |
|-------|--------|---------|--------------|
| EB Garamond (font) | Google Fonts | SIL OFL 1.1 | `fonts/ebgaramond-OFL.txt` |
| Cinzel (font) | Google Fonts | SIL OFL 1.1 | `fonts/cinzel-OFL.txt` |

## What is here and why

- `ebgaramond-normal-latin.woff2`, `ebgaramond-normal-latin-ext.woff2` — the
  upright face, a variable font (`wght` 400–800), so one file per subset covers
  every weight.
- `ebgaramond-italic-latin.woff2`, `ebgaramond-italic-latin-ext.woff2` — the
  italic, weight 400 only.
- `cinzel-latin.woff2` — variable (`wght` 400–900). Used for the masthead and
  the year numerals, which are Catalan interface text, so `latin-ext` is not
  needed.

`latin-ext` is what carries the **long s** (`ſ`, U+017F) the 1542 booklet is
set in; its presence in both Garamond files was checked with fontTools before
the family was adopted. The browser fetches that subset only on a page that
uses a glyph in its `unicode-range`.

## Regenerating

The `latin` and `latin-ext` `woff2` subsets of the Google Fonts CSS for
`EB+Garamond:ital,wght@0,400..800;1,400` and `Cinzel:wght@400..900`, with
`fonts/fonts.css` written by hand to point at the local files. The same files
are vendored by the sibling `mapes/mut` project.
