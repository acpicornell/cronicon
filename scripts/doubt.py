"""Which words of a published text the panel argued about -- by position.

The site used to mark doubt by *word form*: a word was underlined wherever it
appeared if that form had been doubtful anywhere on the same leaves. `de`, `la`
and `el` are doubtful somewhere on almost every leaf, so `/anys/1715/` carried
4 161 underlined words where 437 are in dispute -- 40% of the page dotted, the
mark meaning nothing, and those spans were 70% of the page's bytes.

It was done that way because a notice does not record which word records it was
assembled from (`entry.word_from` and `word_to` are NULL): the text has been
hyphen-stitched, re-joined, had its sigla lifted and its footnotes separated.
But the notice *is* those words in that order, so the position can be recovered
by aligning the two sequences. That is what this module does:

  stream   the word records of a run of leaves, in reading order, as their
           runs of letters and digits, with a break hyphen stitched to the
           word it continues
  align    `difflib.SequenceMatcher` over normalised keys, text against stream
  mark     a text token is doubtful if the stream token it aligned to is

Two guards, both about not lying:

- **A stray match is dropped.** A block of one or two tokens that sits far off
  the diagonal its neighbours agree on is `de` matching some other `de`.
- **An unaligned stretch is doubtful if what it failed to align with was.** Where
  the text and the stream part company, any doubtful word in the stream's side
  of the gap marks the text's side whole. A failed alignment must never present
  a disputed reading as a settled one.

The rival readings are those of *that* position. The old marking could only
offer them where every doubtful occurrence of the form agreed, and 9% did not.

`Doubt.report()` says how much of the text aligned; the build fails below a
threshold rather than publish marks it cannot place.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# The tiers shown as disputed. One dissenter is right 99% of the time on the
# chronicle, and marking it would paint the page for nothing.
DOUBTFUL = ("two-dissent", "contested")

WORD = re.compile(r"[^\W_]+")
BREAK_HYPHEN = re.compile("[-\u2010\u2011\u00ad]$")
# How far off its neighbours' diagonal a one- or two-token match may sit.
STRAY = 40
# How much of the stream a text's unmatched head or tail is checked against.
SLACK = 3


def key(token: str) -> str:
    """A token as the alignment compares it: lower case."""
    return token.lower()


def pieces(text: str) -> list[tuple[int, int]]:
    """(start, end) of each token of `text`: its runs of letters and digits.

    Punctuation is not a token. The engines disagree about a dash or a stop far
    more often than about a word, and the published text has moved both about
    -- the day lifted off the head of a notice, the siglum off its tail -- so a
    token that carried its punctuation matched nothing: `21.--Rogativas` is one
    record on the leaf and `Rogativas` in the notice. It also means the mark
    sits under the word and not under the comma after it.
    """
    return [m.span() for m in WORD.finditer(text)]


@dataclass
class Tok:
    key: str
    doubtful: bool
    variants: tuple[str, ...] | None
    hyphen: bool = False          # ends in a line-break hyphen


@dataclass
class Marked:
    """A text with the character spans of its disputed words."""
    text: str
    spans: list[tuple[int, int, tuple[str, ...] | None]]
    _cursor: int = field(default=0, repr=False)

    def html(self, piece: str | None = None) -> str:
        """`piece` -- a stretch of this text, or all of it -- escaped and marked.

        Pieces are found by searching forward from the last one, so the same
        sentence occurring twice in a long notice gets its own marks each time.
        A piece that is not a stretch of the text at all is returned unmarked;
        callers only pass what they cut out of it.
        """
        if piece is None:
            start, end = 0, len(self.text)
        else:
            piece = " ".join(piece.split())
            start = self.text.find(piece, self._cursor)
            if start < 0:
                start = self.text.find(piece)
            if start < 0:
                return html.escape(piece, quote=True)
            end = start + len(piece)
            self._cursor = end
        out, at = [], start
        for a, b, variants in self.spans:
            if b <= start or a >= end:
                continue
            a, b = max(a, start), min(b, end)
            out.append(html.escape(self.text[at:a], quote=True))
            rivals = (f' data-v="{html.escape(" · ".join(variants), quote=True)}"'
                      if variants else "")
            out.append(f'<span class="d"{rivals}>'
                       f"{html.escape(self.text[a:b], quote=True)}</span>")
            at = b
        out.append(html.escape(self.text[at:end], quote=True))
        return "".join(out)

    @property
    def count(self) -> int:
        return len(self.spans)


class Doubt:
    def __init__(self, con) -> None:
        self.pages: dict[int, list[Tok]] = {}
        for page, text, tier, variants in con.execute(
                "SELECT pdf_page, text, tier, variants FROM word "
                "ORDER BY pdf_page, idx").fetchall():
            doubtful = tier in DOUBTFUL
            parts = [text[a:b] for a, b in pieces(text)]
            # The rivals describe the whole record, so they are offered only
            # where the record is one token: `Que sean` against `Quesean` says
            # nothing about `sean` on its own.
            rivals = tuple(variants) if doubtful and variants and len(parts) == 1 else None
            # A record of several tokens is a run the engines cut differently,
            # and its tier is the run's, not each word's: `1.°—Refriega` is
            # contested because of the day, and marking `Refriega` for it put a
            # dotted line under the first word of four notices in ten. So each
            # token of such a run is graded on its own, from the rival readings
            # the record keeps: it is disputed if two or more of them do not
            # have it -- the same line the tiers draw, where one dissenter is
            # not marked. Where the rivals were not recorded nothing can be
            # said, and the whole run stays marked.
            settled: set[str] = set()
            if doubtful and variants and len(parts) > 1:
                rival_keys = [{key(v[a:b]) for a, b in pieces(v)} for v in variants]
                settled = {key(part) for part in parts
                           if sum(key(part) not in keys for keys in rival_keys) < 2}
            hyphen = bool(BREAK_HYPHEN.search(text.rstrip()))
            self.pages.setdefault(page, []).extend(
                Tok(key(part), doubtful and key(part) not in settled, rivals,
                    hyphen and n == len(parts) - 1)
                for n, part in enumerate(parts))
        self._streams: dict[tuple[int, int], list[Tok]] = {}
        self.tokens = 0
        self.aligned = 0

    def stream(self, first: int, last: int) -> list[Tok]:
        """The leaves `first`..`last` as one token stream, break hyphens joined.

        `altera-` at the end of a line and `cion` at the head of the next are
        one word in the published text, so they are one token here; otherwise
        every hyphenated line break would be two tokens that match nothing.
        """
        span = (first, last)
        if span not in self._streams:
            out: list[Tok] = []
            for page in range(first, last + 1):
                for tok in self.pages.get(page, []):
                    if out and out[-1].hyphen:
                        head = out.pop()
                        tok = Tok(head.key + tok.key,
                                  head.doubtful or tok.doubtful, None, tok.hyphen)
                    out.append(tok)
            self._streams[span] = out
        return self._streams[span]

    def mark(self, text: str, first: int, last: int) -> Marked:
        return self.mark_many([text], first, last)[0]

    def mark_many(self, texts: list[str], first: int, last: int) -> list[Marked]:
        """Several texts that follow one another on the same leaves, aligned once.

        A document's paragraphs are aligned as a single sequence against the
        document's leaves: paragraph by paragraph each would have to find its
        own place among forty thousand tokens, and a short one cannot.
        """
        texts = [" ".join(t.split()) for t in texts]
        spans_of = [pieces(t) for t in texts]
        a = [key(texts[n][s:e]) for n, spans in enumerate(spans_of)
             for s, e in spans]
        owner = [(n, i) for n, spans in enumerate(spans_of)
                 for i in range(len(spans))]
        b = self.stream(first, last)
        flags = self._align(a, b)
        self.tokens += len(a)
        out = [Marked(t, []) for t in texts]
        for (n, i), flag in zip(owner, flags):
            if flag is not None:
                s, e = spans_of[n][i]
                out[n].spans.append((s, e, flag or None))
        return out

    def _align(self, a: list[str], b: list[Tok]) -> list[tuple | None]:
        """Per text token: None if settled, else its rivals (`()` if unknown)."""
        flags: list[tuple | None] = [None] * len(a)
        if not a or not b:
            return flags
        blocks = [m for m in SequenceMatcher(
            None, a, [t.key for t in b], autojunk=False).get_matching_blocks()
            if m.size]
        anchors = [m for m in blocks if m.size >= 3]
        if anchors:
            kept = []
            for m in blocks:
                if m.size >= 3:
                    kept.append(m)
                    continue
                before = [x for x in anchors if x.a < m.a]
                after = [x for x in anchors if x.a > m.a]
                near = ([before[-1]] if before else []) + ([after[0]] if after else [])
                if any(abs((m.b - m.a) - (x.b - x.a)) <= STRAY for x in near):
                    kept.append(m)
            blocks = kept
        at_a = at_b = 0
        for n, m in enumerate(blocks):
            self._fill(flags, at_a, m.a, b,
                       max(0, m.b - (m.a - at_a) - SLACK) if n == 0 else at_b, m.b)
            for k in range(m.size):
                tok = b[m.b + k]
                if tok.doubtful:
                    flags[m.a + k] = tok.variants or ()
            self.aligned += m.size
            at_a, at_b = m.a + m.size, m.b + m.size
        if blocks:
            self._fill(flags, at_a, len(a), b, at_b,
                       min(len(b), at_b + (len(a) - at_a) + SLACK))
        return flags

    @staticmethod
    def _fill(flags: list, a0: int, a1: int, b: list[Tok], b0: int, b1: int) -> None:
        """Mark an unaligned stretch of the text if its side of the stream was
        in dispute."""
        if a1 > a0 and any(t.doubtful for t in b[b0:b1]):
            for k in range(a0, a1):
                flags[k] = ()

    def report(self) -> tuple[int, int, float]:
        share = self.aligned / self.tokens if self.tokens else 1.0
        return self.aligned, self.tokens, share
