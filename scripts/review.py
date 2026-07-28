"""The review tool: settle the positions the panel could not, with the page on screen.

23 647 positions are contested, and another 11 114 sit on leaves aligned line by
line that no adjudication covers. Both need a human, and this is what a human uses.

Four things it must do, each of them learned the hard way:

  native resolution   Round 2 of the pilot recorded one shared error -- every
                      engine read `así` where the review sheet appeared to print
                      `asi`. Re-cropped at full resolution the acute accent is
                      unmistakable; the engines were right and the adjudication
                      was wrong. Accent-versus-dot is what most disagreements turn
                      on, and a 78-pixel line is not enough to see it. Crops here
                      are cut from the largest scan held and never downscaled.

  the panel's words   The readings are offered as numbered choices, because the
                      pipeline's guarantee is that every accepted word is one some
                      recogniser actually produced.

  and a way out       But a person looking at the page is exactly the authority
                      that outranks that rule, and sometimes every engine is
                      wrong. Typing the printed form is allowed and is recorded
                      as `typed`, so that the share of the edition resting on a
                      reading no engine produced can be counted rather than
                      assumed.

  replayable          Decisions append to a JSONL keyed by leaf and word box --
                      not by index, which renumbers whenever a leaf's geometry
                      changes. Re-running picks up where you left off, and a
                      rebuilt consensus does not orphan the work.

Priority order: figures and dates first, then capitalised words, then the rest.
That is where a chronicle's value is and where OCR is worst, so an interrupted
review is still worth the most it can be.

Usage:
  python scripts/review.py                 # http://127.0.0.1:8000
  python scripts/review.py --pages 93,94,97,98
  python scripts/review.py --stats
"""
from __future__ import annotations

import argparse
import html
import io
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from PIL import Image, ImageDraw

import targets

PROJECT = Path(__file__).resolve().parent.parent
OCR = PROJECT / "data" / "ocr"
PAGES = PROJECT / "data" / "pages"
OUT = PROJECT / "data" / "review"
DECISIONS = OUT / "decisions.jsonl"

IA_OFFSET = -2
PAD_X = 0.010          # context kept around the word, in page widths
PAD_Y = 0.006
BOX_PLACES = 5


# --- the queue ---------------------------------------------------------------

DIGIT = re.compile(r"\d")


def priority(locus: dict) -> int:
    """0 figures and dates, 1 proper nouns, 2 everything else.

    A chronicle is worth reading for its names, dates and sums, and those are
    exactly what OCR gets wrong -- so a review that stops halfway should have
    spent its time on them.
    """
    readings = [locus["winner"], *(v or "" for v in locus["variants"].values())]
    if any(DIGIT.search(r) for r in readings):
        return 0
    if any(r[:1].isupper() for r in readings if r):
        return 1
    return 2


def key_of(pdf_page: int, bbox) -> str:
    return f"{pdf_page}:" + ",".join(f"{v:.{BOX_PLACES}f}" for v in bbox)


def decided() -> dict[str, dict]:
    """Every decision made so far, last one winning.

    Append-only: a correction is a second line, not an edit, so the record of
    what was thought at the time survives.
    """
    out: dict[str, dict] = {}
    if DECISIONS.exists():
        for line in DECISIONS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["key"]] = row
    return out


def leaf_scan(consensus: Path, pdf_page: int) -> str:
    """Which scan this leaf's word boxes are normalised to."""
    path = consensus / f"p{pdf_page:04d}.json"
    if not path.exists():
        return "ia"
    leaf = json.loads(path.read_text())
    return GEOMETRY_SCAN.get(leaf.get("geometry", "tesseract"), "ia")


def queue_from_sample(path: Path, consensus: Path) -> list[dict]:
    """A drawn sample as the queue, so a round is adjudicated at full resolution.

    The contact sheets `sample_loci.py` used to build scale every crop to 78
    pixels, and the one shared error round 2 recorded turned out to be the
    adjudication being wrong because at that size the acute accent on `así` is
    not visible. Same positions, same ids, shown properly.
    """
    data = json.loads(path.read_text())
    panel = data.get("panel", [])
    done = decided()
    queue: list[dict] = []
    for locus in data["sample"]:
        key = key_of(locus["pdf_page"], locus["bbox"])
        if key in done:
            continue
        queue.append({
            "key": key,
            "sample_id": locus["id"],
            "pdf_page": locus["pdf_page"],
            "index": locus["index"],
            "bbox": locus["bbox"],
            "line_bbox": locus["line_bbox"],
            "grade": locus.get("group", locus.get("grade", "")),
            "held": False,
            "winner": Counter(
                v for e, v in locus["variants"].items()
                if e in panel and v is not None).most_common(1)[0][0]
            if panel else "",
            "context": locus["context"],
            "variants": locus["variants"],
            "panel": panel,
            "scan": leaf_scan(consensus, locus["pdf_page"]),
            "priority": 0,
        })
    # Adjudication is a sample, not a queue: it is drawn to be representative and
    # reordering it by what looks interesting would undo that. Kept as drawn.
    queue.sort(key=lambda x: x["sample_id"])
    return queue


def build_queue(consensus: Path, pages: list[int], include_held: bool
                ) -> list[dict]:
    done = decided()
    queue: list[dict] = []
    for pdf_page in pages:
        path = consensus / f"p{pdf_page:04d}.json"
        if not path.exists():
            continue
        leaf = json.loads(path.read_text())
        held = include_held and not leaf.get("accept_unanimous", True)
        scan = GEOMETRY_SCAN.get(leaf.get("geometry", "tesseract"), "ia")
        for locus in leaf["loci"]:
            if locus["grade"] != "contested" and not held:
                continue
            key = key_of(pdf_page, locus["bbox"])
            if key in done:
                continue
            queue.append({
                "key": key,
                "pdf_page": pdf_page,
                "index": locus["index"],
                "bbox": locus["bbox"],
                "line_bbox": locus["line_bbox"],
                "grade": locus["grade"],
                "held": held and locus["grade"] != "contested",
                "winner": locus["winner"],
                "context": locus["context"],
                "variants": locus["variants"],
                "panel": leaf["panel"],
                "scan": scan,
                "priority": priority(locus),
            })
    queue.sort(key=lambda x: (x["priority"], x["pdf_page"], x["index"]))
    return queue


def choices(item: dict) -> list[dict]:
    """The distinct readings the panel offered, commonest first.

    One line per distinct string, with the engines that read it, because seeing
    that four engines agree and two do not is itself evidence -- and seeing that
    the four are all reading the same scan is evidence of a different kind.
    """
    by_text: dict[str, list[str]] = {}
    for engine in item["panel"]:
        reading = item["variants"].get(engine)
        if reading is None:
            continue
        by_text.setdefault(unicodedata.normalize("NFC", reading), []).append(engine)
    rows = [{"text": text, "engines": sorted(engines), "n": len(engines)}
            for text, engines in by_text.items()]
    rows.sort(key=lambda r: (-r["n"], r["text"]))
    return rows


# --- the crop ----------------------------------------------------------------

# Which scan each geometry provider reads. A box is normalised to *its own*
# image, and the two scans are cropped differently -- the running head sits at
# y≈0.082 on a BNE leaf and 0.094 on an IA one -- so a box from one is simply
# wrong on the other. Showing the largest image available put the highlight two
# words off, which would have made every adjudication made from it wrong.
GEOMETRY_SCAN = {"tesseract": "ia", "tesseract-bne": "bne",
                 "abbyy-ia": "ia", "abbyy-bne": "bne"}


def source_image(pdf_page: int, scan: str = "ia") -> Path | None:
    """The most detailed image of this leaf *from the scan the boxes came from*."""
    if scan == "bne":
        candidates = list((PAGES / "bne").glob(f"p{pdf_page:04d}_*dpi.png"))
    else:
        candidates = list(
            (PAGES / "ia").glob(f"leaf{pdf_page + IA_OFFSET:04d}_*dpi.png"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: int(p.stem.split("_")[-1][:-3]))


def crop(pdf_page: int, bbox, line_bbox, wide: bool,
         scan: str = "ia") -> bytes | None:
    """The word in its line, at native resolution, with the word marked.

    Never resized: the whole point is to see the difference between an acute
    accent and the dot of an i, and any resampling is exactly what destroys it.
    """
    path = source_image(pdf_page, scan)
    if path is None:
        return None
    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        x0, y0, x1, y1 = line_bbox
        if wide:                       # three lines of context above and below
            span = y1 - y0
            y0, y1 = y0 - 3 * span, y1 + 3 * span
        box = (max(0, int((x0 - PAD_X) * width)),
               max(0, int((y0 - PAD_Y) * height)),
               min(width, int((x1 + PAD_X) * width)),
               min(height, int((y1 + PAD_Y) * height)))
        cut = image.crop(box)

        draw = ImageDraw.Draw(cut, "RGBA")
        wx0 = int(bbox[0] * width) - box[0]
        wx1 = int(bbox[2] * width) - box[0]
        wy0 = int(bbox[1] * height) - box[1]
        wy1 = int(bbox[3] * height) - box[1]
        draw.rectangle([wx0 - 2, wy0 - 2, wx1 + 2, wy1 + 2],
                       fill=(255, 210, 0, 60), outline=(220, 120, 0, 255), width=2)

        buffer = io.BytesIO()
        cut.save(buffer, format="PNG")
        return buffer.getvalue()


# --- the page ----------------------------------------------------------------

PAGE = """<!doctype html><meta charset=utf-8>
<title>Cronicón — revisió</title>
<style>
 body{margin:0;font:15px/1.5 -apple-system,system-ui,sans-serif;background:#faf8f4;color:#221}
 header{padding:.6rem 1rem;border-bottom:1px solid #ddd6c8;display:flex;gap:1.5rem;
   align-items:baseline;background:#fff;position:sticky;top:0}
 header b{font-size:1.05rem} header span{color:#776}
 main{padding:1rem;max-width:1100px;margin:0 auto}
 .crop{background:#fff;border:1px solid #ddd6c8;padding:.5rem;overflow-x:auto;
   border-radius:4px}
 .crop img{display:block;max-width:none}
 .ctx{margin:.8rem 0;color:#554;font-style:italic}
 .ctx mark{background:#ffe08a;font-style:normal;font-weight:600}
 ol{list-style:none;padding:0;margin:.5rem 0}
 li{display:flex;gap:.7rem;align-items:baseline;padding:.3rem .5rem;border-radius:3px}
 li:hover{background:#f0ece2}
 kbd{background:#332;color:#fff;border-radius:3px;padding:.05rem .45rem;font:600 13px ui-monospace}
 .rd{font:600 17px ui-monospace,Menlo,monospace}
 .eng{color:#887;font-size:12px}
 .typed input{font:600 17px ui-monospace;padding:.25rem .5rem;border:1px solid #bbb;border-radius:3px}
 footer{color:#887;font-size:13px;margin-top:1.5rem;border-top:1px solid #e6e0d4;padding-top:.6rem}
 .held{color:#a60;font-weight:600}
</style>
<header>
  <b id=pos></b><span id=leaf></span><span id=grade></span>
  <span style=margin-left:auto id=done></span>
</header>
<main>
  <div class=crop><img id=img alt=""></div>
  <p class=ctx id=ctx></p>
  <ol id=opts></ol>
  <p class=typed><kbd>t</kbd> el que hi ha imprès:
     <input id=typed size=28 autocomplete=off spellcheck=false></p>
  <footer><kbd>1</kbd>–<kbd>9</kbd> triar &nbsp; <kbd>t</kbd> escriure el que veus
    &nbsp; <kbd>c</kbd> més context &nbsp; <kbd>s</kbd> ajornar
    &nbsp; <kbd>u</kbd> desfer</footer>
</main>
<script>
let q=[],i=0,wide=false,total=0,doneCount=0,last=null;
async function load(){
  const r=await fetch('/api/queue');const d=await r.json();
  q=d.queue;total=d.total;doneCount=d.done;show();
}
function show(){
  if(i>=q.length){document.querySelector('main').innerHTML=
    '<h2>Res més a la cua.</h2><p>Les decisions són a data/review/decisions.jsonl</p>';return;}
  const it=q[i];
  pos.textContent=(i+1)+' / '+q.length;
  leaf.textContent='full '+it.pdf_page;
  grade.innerHTML=it.held?'<span class=held>no mesurat</span>':it.grade;
  done.textContent=doneCount+' decidides de '+total;
  img.src='/crop?key='+encodeURIComponent(it.key)+(wide?'&wide=1':'')+'&t='+Date.now();
  const c=it.context.split(' ');
  ctx.innerHTML=c.map(w=>w===it.winner?'<mark>'+esc(w)+'</mark>':esc(w)).join(' ');
  opts.innerHTML=it.choices.map((o,n)=>
    '<li><kbd>'+(n+1)+'</kbd><span class=rd>'+esc(o.text||'(res)')+
    '</span><span class=eng>'+o.n+' — '+o.engines.join(', ')+'</span></li>').join('');
  typed.value='';
}
function esc(s){return s.replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));}
async function decide(text,source,engines){
  const it=q[i];
  await fetch('/api/decide',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:it.key,pdf_page:it.pdf_page,index:it.index,bbox:it.bbox,
      grade:it.grade,held:it.held,winner:it.winner,chose:text,source:source,
      engines:engines||[],context:it.context})});
  last=i;doneCount++;i++;wide=false;show();
}
addEventListener('keydown',e=>{
  if(document.activeElement===typed){
    if(e.key==='Enter'&&typed.value.trim())decide(typed.value.trim(),'typed');
    if(e.key==='Escape')typed.blur();
    return;}
  const it=q[i];
  if(e.key>='1'&&e.key<='9'){const o=it&&it.choices[+e.key-1];
    if(o)decide(o.text,'variant',o.engines);}
  else if(e.key==='t'){e.preventDefault();typed.focus();}
  else if(e.key==='c'){wide=!wide;show();}
  else if(e.key==='s'){i++;wide=false;show();}
  else if(e.key==='u'&&last!==null){i=last;last=null;doneCount--;wide=false;show();}
});
load();
</script>
"""


# --- the server --------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    queue: list[dict] = []
    total: int = 0

    def log_message(self, *args):        # one line per decision is enough
        pass

    def _send(self, code: int, body: bytes, kind: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlparse(self.path)
        if route.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if route.path == "/api/queue":
            # Filtered against the decisions on every request, not once at
            # startup: otherwise reloading the page brings back everything
            # already settled, and "re-running replays your work" -- the reason
            # the file is keyed by word box at all -- would only be true across
            # runs and not within one.
            done = decided()
            payload = {"total": Handler.total, "done": len(done),
                       "queue": [{**item, "choices": choices(item)}
                                 for item in Handler.queue
                                 if item["key"] not in done]}
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode(),
                              "application/json; charset=utf-8")
        if route.path == "/crop":
            params = parse_qs(route.query)
            key = params.get("key", [""])[0]
            item = next((x for x in Handler.queue if x["key"] == key), None)
            if item is None:
                return self._send(404, b"no such position", "text/plain")
            png = crop(item["pdf_page"], item["bbox"], item["line_bbox"],
                       params.get("wide", ["0"])[0] == "1",
                       item.get("scan", "ia"))
            if png is None:
                return self._send(404, b"no image for this leaf", "text/plain")
            return self._send(200, png, "image/png")
        self._send(404, b"", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/decide":
            return self._send(404, b"", "text/plain")
        length = int(self.headers.get("Content-Length", 0))
        row = json.loads(self.rfile.read(length) or b"{}")
        row["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        OUT.mkdir(parents=True, exist_ok=True)
        with DECISIONS.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        mark = "typed" if row.get("source") == "typed" else ""
        print(f"  p{row['pdf_page']:<5} {row['winner']!r:>24} -> "
              f"{row['chose']!r} {mark}")
        self._send(200, b'{"ok":true}', "application/json")


SHEET_GAP = 34
SHEET_MAX_WIDTH = 2400


def batch_sheet(items: list[dict], path: Path) -> dict:
    """Several positions on one image, each at native resolution.

    The pilot's contact sheets scaled every crop to a constant 78-pixel line and
    that is what made one adjudication wrong -- but the fault was the *scaling*,
    not the stacking. Crops here are pasted at the size they were cut, so a sheet
    is simply several native-resolution crops in a column, and one look settles
    ten positions instead of one.
    """
    from PIL import ImageFont
    crops, kept = [], []
    for n, item in enumerate(items, 1):
        png = crop(item["pdf_page"], item["bbox"], item["line_bbox"],
                    wide=False, scan=item.get("scan", "ia"))
        if png is None:
            continue
        image = Image.open(io.BytesIO(png))
        if image.width > SHEET_MAX_WIDTH:
            image = image.crop((0, 0, SHEET_MAX_WIDTH, image.height))
        crops.append(image)
        kept.append({**item, "n": len(kept) + 1})

    width = max((c.width for c in crops), default=100)
    height = sum(c.height + SHEET_GAP for c in crops) + 8
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 22)
    except OSError:
        font = None
    y = 4
    for item, image in zip(kept, crops):
        draw.text((8, y + 6), f"[{item['n']}] p{item['pdf_page']}",
                  fill=(170, 30, 30), font=font)
        y += SHEET_GAP
        sheet.paste(image, (0, y))
        y += image.height
        draw.line([(0, y - 1), (width, y - 1)], fill=(200, 200, 200))
    sheet.save(path)
    return {"sheet": str(path), "positions": kept}


def report(consensus: Path, pages: list[int]) -> None:
    queue = build_queue(consensus, pages, include_held=True)
    done = decided()
    kinds = {0: "figures and dates", 1: "capitalised", 2: "the rest"}
    print(f"{len(queue):,} positions waiting, {len(done):,} already decided")
    for level, name in kinds.items():
        n = sum(1 for x in queue if x["priority"] == level)
        print(f"  {name:20} {n:8,}")
    held = sum(1 for x in queue if x["held"])
    print(f"\n  of which held back, not contested: {held:,}")
    if done:
        typed = sum(1 for r in done.values() if r.get("source") == "typed")
        print(f"\n  decided by choosing a reading the panel produced: "
              f"{len(done)-typed:,}")
        print(f"  decided by typing what is printed:                 {typed:,}"
              f"  ({typed/len(done):.1%})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consensus", default="consensus6_swap_swapk")
    ap.add_argument("--pages", default="all")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-held", action="store_true",
                    help="only the contested positions, leaving out the leaves "
                         "held back for want of an adjudication")
    ap.add_argument("--sample", default=None,
                    help="adjudicate a drawn sample instead of the review queue, "
                         "e.g. documents.json. Same positions and ids as the "
                         "contact sheets, shown at native resolution")
    ap.add_argument("--export-truth", type=Path, default=None,
                    help="write the adjudicated sample positions as id<TAB>text "
                         "and exit")
    ap.add_argument("--batch", type=int, default=0,
                    help="render the next N positions onto one sheet at native "
                         "resolution, with their variants, and exit")
    ap.add_argument("--tag", default="",
                    help="suffix for the sheet, so several can be prepared and "
                         "looked at together")
    ap.add_argument("--skip", type=int, default=0,
                    help="start the batch this far into the queue")
    ap.add_argument("--by", default="human",
                    help="who is adjudicating. Recorded on every decision, "
                         "because a measurement made by whoever built the "
                         "pipeline is weaker evidence than an independent one "
                         "and the difference has to be visible in the data")
    ap.add_argument("--decide", default=None,
                    help="apply decisions to the last batch: a comma-separated "
                         "list of n=choice, where choice is a variant number or "
                         "=text to record what is printed")
    ap.add_argument("--stats", action="store_true",
                    help="report the queue and exit")
    args = ap.parse_args()

    consensus = OCR / args.consensus
    if not consensus.exists():
        raise SystemExit(f"{consensus} missing -- run scripts/consensus.py first")
    pages = targets.resolve(args.pages)

    if args.decide:
        manifest = json.loads((OUT / f"batch{args.tag}.json").read_text())
        by_n = {item["n"]: item for item in manifest["positions"]}
        written = 0
        with (OUT / "decisions.jsonl").open("a", encoding="utf-8") as fh:
            for part in args.decide.split(","):
                n, _, pick = part.strip().partition("=")
                item = by_n.get(int(n))
                if item is None:
                    raise SystemExit(f"no position {n} on the current sheet")
                if pick.startswith("'") or not pick.isdigit():
                    # `n==text` records what is printed when no engine has it
                    text, src, engines = pick.strip("'"), "typed", []
                else:
                    choice = item["choices"][int(pick) - 1]
                    text, src, engines = choice["text"], "variant", choice["engines"]
                fh.write(json.dumps({
                    "key": item["key"], "sample_id": item.get("sample_id"),
                    "pdf_page": item["pdf_page"], "index": item["index"],
                    "bbox": item["bbox"], "grade": item["grade"],
                    "held": item.get("held", False), "winner": item["winner"],
                    "chose": text, "source": src, "engines": engines,
                    "context": item["context"], "by": args.by,
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }, ensure_ascii=False) + "\n")
                written += 1
        print(f"{written} decisions appended to {DECISIONS}")
        return

    if args.batch:
        source = (queue_from_sample(
            PROJECT / "data" / "adjudication" / args.sample, consensus)
            if args.sample else
            build_queue(consensus, pages, include_held=not args.no_held))
        items = source[args.skip:args.skip + args.batch]
        if not items:
            print("nothing left")
            return
        OUT.mkdir(parents=True, exist_ok=True)
        sheet = OUT / f"batch{args.tag}.png"
        manifest = batch_sheet(items, sheet)
        for item in manifest["positions"]:
            item["choices"] = choices(item)
        (OUT / f"batch{args.tag}.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        for item in manifest["positions"]:
            opts = "  ".join(f"{n}:{c['text']!r}×{c['n']}"
                             for n, c in enumerate(item["choices"], 1))
            print(f"[{item['n']}] id={item.get('sample_id','-')} "
                  f"p{item['pdf_page']} {item['grade']:11} {opts}")
            print(f"     …{item['context']}…")
        print(f"\n{sheet}")
        return

    if args.export_truth:
        rows = sorted(((r["sample_id"], r["chose"]) for r in decided().values()
                       if r.get("sample_id") is not None))
        args.export_truth.write_text(
            "id\ttext\n" + "".join(f"{i}\t{t}\n" for i, t in rows),
            encoding="utf-8")
        print(f"{len(rows)} adjudicated positions -> {args.export_truth}")
        return

    if args.sample:
        path = PROJECT / "data" / "adjudication" / args.sample
        if not path.exists():
            raise SystemExit(f"{path} not found -- draw it with sample_loci.py")
        Handler.queue = queue_from_sample(path, consensus)
        drawn = len(json.loads(path.read_text())["sample"])
        Handler.total = drawn
        print(f"adjudicating {args.sample}: {len(Handler.queue)} of {drawn} left")
        print(f"decisions append to {DECISIONS}\n")
        print(f"  http://127.0.0.1:{args.port}\n")
        return ThreadingHTTPServer(("127.0.0.1", args.port),
                                   Handler).serve_forever()

    if args.stats:
        return report(consensus, pages)

    Handler.queue = build_queue(consensus, pages, include_held=not args.no_held)
    Handler.total = len(Handler.queue) + len(decided())
    if not Handler.queue:
        print("nothing left in the queue for those leaves")
        return
    print(f"{len(Handler.queue):,} positions to review "
          f"({sum(1 for x in Handler.queue if x['priority'] == 0):,} carry a "
          f"figure, {sum(1 for x in Handler.queue if x['priority'] == 1):,} "
          f"are capitalised)")
    print(f"decisions append to {DECISIONS}")
    print(f"\n  http://127.0.0.1:{args.port}\n")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
