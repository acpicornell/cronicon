"""Lint the generated site against what its own security policy allows.

The Content-Security-Policy in `web/_headers` is `style-src 'self'` and
`script-src 'self'` with no `'unsafe-inline'`, and the only foreign origin it
admits is `https://iiif.archive.org`, for images. A page that needs anything
else does not fail the build -- it fails silently in the reader's browser. This
script is the build's way of finding out first.

Checked on every generated page:

  no `style="…"` attribute, no `on…="…"` handler, no `<style>` block
  no `<script>` without `src`, other than a JSON-LD data block
  every script, stylesheet, image and font is same-origin or the Archive's IIIF
  every external `<a>` carries `rel="noopener"`
  every internal link resolves to a file, and every `#fragment` to an id
  ids are unique; there is exactly one `<h1>`
  page weight under a ceiling

Usage:
  python scripts/check_site.py            # exit status 1 on any finding
  python scripts/check_site.py --weights  # also list the ten heaviest pages
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT = Path(__file__).resolve().parent.parent
WEB = PROJECT / "web"

IMG_ORIGINS = ("https://iiif.archive.org/",)
MAX_PAGE_KB = 700


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.findings: list[str] = []
        self.ids: Counter = Counter()
        self.links: list[str] = []
        self.h1 = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if "style" in a:
            self.findings.append(f"inline style on <{tag}>")
        for name in a:
            if name.startswith("on"):
                self.findings.append(f"inline handler {name} on <{tag}>")
        if tag == "style":
            self.findings.append("<style> block")
        if tag == "script":
            if "src" not in a and a.get("type") != "application/ld+json":
                self.findings.append("inline <script>")
            elif "src" in a and urlsplit(a["src"]).netloc:
                self.findings.append(f"foreign script {a['src']}")
        if tag == "link" and a.get("rel") in ("stylesheet", "preload", "icon"):
            if urlsplit(a.get("href", "")).netloc:
                self.findings.append(f"foreign <link> {a['href']}")
        if tag == "img":
            src = a.get("src", "")
            if urlsplit(src).netloc and not src.startswith(IMG_ORIGINS):
                self.findings.append(f"foreign image {src}")
        if tag == "a" and "href" in a:
            href = a["href"]
            if urlsplit(href).netloc:
                if "noopener" not in (a.get("rel") or ""):
                    self.findings.append(f"external link without noopener: {href}")
            else:
                self.links.append(href)
        if tag == "form" and "action" in a:
            self.links.append(a["action"])
        if "id" in a:
            self.ids[a["id"]] += 1
        if tag == "h1":
            self.h1 += 1


def target_of(page: Path, href: str) -> tuple[Path, str]:
    """The file an internal link points at, and its fragment."""
    parts = urlsplit(href)
    path = unquote(parts.path)
    if not path:
        return page, parts.fragment
    base = WEB if path.startswith("/") else page.parent
    target = (base / path.lstrip("/")).resolve()
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", action="store_true")
    args = ap.parse_args()

    pages = sorted(WEB.rglob("*.html"))
    parsed: dict[Path, Page] = {}
    for path in pages:
        page = Page()
        page.feed(path.read_text(encoding="utf-8"))
        parsed[path.resolve()] = page

    findings: Counter = Counter()
    examples: dict[str, str] = {}

    def report(kind: str, where: Path, detail: str = "") -> None:
        findings[kind] += 1
        examples.setdefault(kind, f"{where.relative_to(WEB)} {detail}".strip())

    for path, page in parsed.items():
        for finding in page.findings:
            kind = finding.split(":")[0].split(" on <")[0]
            report(kind, path, finding)
        for ident, n in page.ids.items():
            if n > 1:
                report("duplicate id", path, f"#{ident} ×{n}")
        if page.h1 != 1:
            report("h1 count", path, f"{page.h1} <h1>")
        size = path.stat().st_size / 1024
        if size > MAX_PAGE_KB:
            report("page too heavy", path, f"{size:.0f} KB")
        for href in page.links:
            if href.startswith(("mailto:", "data:")):
                continue
            target, fragment = target_of(path, href)
            if not target.exists():
                report("dead link", path, href)
            elif fragment and target in parsed and ":~:" not in fragment:
                if fragment not in parsed[target].ids:
                    report("dead fragment", path, href)

    print(f"{len(pages)} pages checked")
    if args.weights:
        for path in sorted(pages, key=lambda p: -p.stat().st_size)[:10]:
            print(f"  {path.stat().st_size / 1024:7.0f} KB  {path.relative_to(WEB)}")
    for kind, n in findings.most_common():
        print(f"  {n:6d}  {kind:34s} e.g. {examples[kind]}")
    if findings:
        sys.exit(1)
    print("  clean")


if __name__ == "__main__":
    main()
