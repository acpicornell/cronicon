"""Serve `web/` locally with the headers production will send.

`python -m http.server` ignores `web/_headers`, and that hid a broken site for
weeks: the Content-Security-Policy forbids inline styles, the year index drew
its 572 bars with `style="height:…"`, and locally everything looked fine. This
server reads `_headers` and applies it the way Cloudflare does, so a CSP
violation shows up in the browser console here rather than after a deploy.

Two headers are dropped unless `--exact` is given, because they are about
HTTPS and this is plain HTTP on localhost: `Strict-Transport-Security`, and the
`upgrade-insecure-requests` directive, which would make the browser fetch the
stylesheet over a TLS port that is not listening.

Usage:
  python scripts/dev_server.py            # http://127.0.0.1:8788
  python scripts/dev_server.py --exact    # send every header verbatim
"""
from __future__ import annotations

import argparse
import functools
import http.server
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
WEB = PROJECT / "web"
PORT = 8788


def read_rules(path: Path) -> list[tuple[re.Pattern, list[tuple[str, str]]]]:
    """`_headers` as (pattern, headers): a path line, then indented headers."""
    rules: list[tuple[re.Pattern, list[tuple[str, str]]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            pattern = "".join(".*" if c == "*" else re.escape(c)
                              for c in line.strip())
            rules.append((re.compile(f"^{pattern}$"), []))
        elif rules and ":" in line:
            name, value = line.strip().split(":", 1)
            rules[-1][1].append((name.strip(), value.strip()))
    return rules


def localise(name: str, value: str) -> tuple[str, str] | None:
    """A header as plain-HTTP localhost can honour it, or None to drop it."""
    if name.lower() == "strict-transport-security":
        return None
    if name.lower() == "content-security-policy":
        value = "; ".join(d.strip() for d in value.split(";")
                          if d.strip() != "upgrade-insecure-requests")
    return name, value


class Handler(http.server.SimpleHTTPRequestHandler):
    rules: list = []
    exact = False

    def end_headers(self) -> None:
        path = self.path.split("?", 1)[0]
        # Cloudflare serves `/anys/` from `/anys/index.html` and matches the
        # header rules against the URL as requested, so `/*.html` does not
        # cover a directory URL but `/*` does.
        seen: set[str] = set()
        for pattern, headers in self.rules:
            if not pattern.match(path):
                continue
            for name, value in headers:
                pair = (name, value) if self.exact else localise(name, value)
                if pair and pair[0].lower() not in seen:
                    seen.add(pair[0].lower())
                    self.send_header(*pair)
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # quiet: errors only
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--exact", action="store_true",
                    help="send HSTS and upgrade-insecure-requests too")
    args = ap.parse_args()

    Handler.rules = read_rules(WEB / "_headers")
    Handler.exact = args.exact
    handler = functools.partial(Handler, directory=str(WEB))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"cronicon → http://127.0.0.1:{args.port}/  "
              f"({len(Handler.rules)} header rules from web/_headers)")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
