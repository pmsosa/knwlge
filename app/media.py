"""Pictures, diagrams, video, audio, interactive widgets and experiments inside lessons.

Gemini proposes media per lesson chunk; the app checks every proposal and fetches what it can itself, so nothing
loads from outside while you study:
- mermaid, widget: kept as data, drawn in the browser (widgets are a fixed set the app ships; Gemini fills in data).
- svg, experiment: saved as files and served in a sandbox (an <img> for SVG, a locked-down frame for experiments).
- image, audio: found on Wikimedia Commons (free licences), downloaded, served from here with a credit line.
- video: a YouTube video checked to exist; its thumbnail is downloaded, and the player loads only when you press play.
- illustration: drawn by Gemini's image model (a paid call, so it goes through the job queue and the budget).
"""
from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from urllib.parse import parse_qs, quote, urlparse

import httpx

from . import db, jobs, verify

log = logging.getLogger("knwlge.media")

# Extras a course can have; all on unless switched off when the course is created (or later, on its Course tab).
OPTIONS = {
    "research": {"label": "Live research", "hint": "Gemini checks the web while planning, writing and answering, and lists "
                 "its sources. Paid-tier key; free up to 5,000 searches a month.", "kinds": []},
    "diagrams": {"label": "Diagrams", "hint": "Flowcharts, timelines and drawn figures.", "kinds": ["mermaid", "svg"]},
    "images": {"label": "Real pictures", "hint": "Artworks, maps, photos and manuscripts from Wikimedia Commons (free licences).",
               "kinds": ["image"]},
    "illustrations": {"label": "AI illustrations", "hint": "Pictures drawn by Gemini (Nano Banana) where no real one exists. About 3¢ each.",
                      "kinds": ["illustration"]},
    "video": {"label": "Videos", "hint": "YouTube clips inside lessons. Nothing loads from YouTube until you press play.",
              "kinds": ["video"]},
    "audio": {"label": "Audio", "hint": "Free recordings from Wikimedia Commons: music, speeches, bird song, pronunciation.",
              "kinds": ["audio"]},
    "widgets": {"label": "Interactive exercises", "hint": "Flashcards, put-in-order, matching, fill-the-gaps, timelines, plots with sliders.",
                "kinds": ["widget"]},
    "experiments": {"label": "Experiments", "hint": "Small simulations Gemini writes, run in a locked-down frame with no network.",
                    "kinds": ["experiment"]},
}
DEFAULTS = {k: True for k in OPTIONS}

MAX_PER_SESSION = 5
MAX_ILLUSTRATIONS = 2
MAX_EXPERIMENTS = 1
MAX_SVG = 12_000
MAX_EXPERIMENT = 60_000
MAX_IMAGE = 8 * 1024 * 1024
MAX_AUDIO = 15 * 1024 * 1024
WIDGETS = ("flashcards", "order", "match", "cloze", "timeline", "plot")
PLOT_FUNCS = {"sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "exp", "log", "ln", "log10", "log2",
              "sqrt", "abs", "floor", "ceil", "round", "min", "max", "pow", "sign"}
PLOT_CONSTS = {"pi", "e", "x"}
UA = "Knwlge/1.0 (self-hosted learning app; personal use)"


def options_of(raw: str | dict | None) -> dict:
    o = raw if isinstance(raw, dict) else (db.loads(raw, {}) or {})
    return {k: bool(o.get(k, DEFAULTS[k])) for k in OPTIONS}


def clean_options(given: dict | None) -> dict:
    return {k: bool((given or {}).get(k, DEFAULTS[k])) for k in OPTIONS}


def allowed_kinds(options: dict) -> list[str]:
    return [kind for key, o in OPTIONS.items() if options.get(key) for kind in o["kinds"]]


# ---------- what Gemini is told ----------

GUIDE = {
    "mermaid": "mermaid: code = Mermaid source (flowchart, timeline, sequenceDiagram, mindmap, pie, xychart-beta, "
               "stateDiagram, classDiagram). Short labels, no HTML, no click handlers, at most ~20 nodes.",
    "svg": "svg: code = one self-contained <svg> with a viewBox (under 8 KB): a clear figure such as a geometry construction, "
           "a graph, a circuit or a wave. Black or dark strokes on a transparent background, readable labels "
           "(font-family sans-serif), no scripts, no links, no external references, no embedded images.",
    "image": "image: query = Wikimedia Commons search words naming one specific real thing (an artwork with its artist, a "
             "named map, a building, a manuscript, a species, a historical photo), e.g. 'Bayeux Tapestry Halley comet scene'. "
             "Only real things that certainly have a photo on Commons.",
    "illustration": "illustration: query = a detailed description of an explanatory illustration for something no real "
                    "picture shows well (a cut-away, a process, an imagined scene). Plain, clear, no text in the picture. "
                    "NEVER for real artworks, real people, maps or documents: use image for those.",
    "video": "video: url = a real YouTube watch URL you are confident exists (well-known channels: Khan Academy, "
             "3Blue1Brown, Crash Course, Smarthistory, TED-Ed, museums, universities); start_seconds = where the relevant "
             "part starts (0 for the beginning).",
    "audio": "audio: query = Wikimedia Commons search words for a public-domain or freely licensed recording (an early "
             "jazz record with artist and year, a composer's piece, a bird's song, a famous speech, a pronunciation).",
    "widget": "widget: spec = a JSON string for one of these interactive exercises:\n"
              '  {"type":"flashcards","cards":[{"front":"...","back":"..."}]} (4-12 cards)\n'
              '  {"type":"order","prompt":"...","items":["first","second","..."]} (3-8 items, in the CORRECT order)\n'
              '  {"type":"match","prompt":"...","pairs":[{"left":"...","right":"..."}]} (3-8 pairs)\n'
              '  {"type":"cloze","text":"The capital of France is {{Paris}}."} (blanks in {{...}}, alternatives as {{colour|color}})\n'
              '  {"type":"timeline","events":[{"date":"1066","label":"...","detail":"..."}]} (3-12 events, in order)\n'
              '  {"type":"plot","expression":"a*sin(k*x)","x_min":-6.3,"x_max":6.3,"y_min":-3,"y_max":3,'
              '"params":[{"name":"a","min":0,"max":3,"step":0.1,"value":1}]} (explicit * for multiplication; functions '
              'sin cos tan exp log sqrt abs and pi, e; 0-3 sliders)',
    "experiment": "experiment: code = one complete small HTML document (inline <style> and <script> only; no external "
                  "files, fonts, images or network; under 40 KB) with an interactive simulation the learner controls "
                  "(sliders, buttons, a canvas): e.g. a pendulum, supply and demand, predator and prey, a sorting "
                  "algorithm. It must work at full width and about 420 px high, label its controls, and explain in one "
                  "line what to try.",
}


def prompt_rules(options: dict) -> str:
    kinds = allowed_kinds(options)
    if not kinds:
        return ""
    lines = [f"MEDIA: each chunk may have a 'media' list (0-2 items, at most {MAX_PER_SESSION} in the whole session"
             + (f", at most {MAX_ILLUSTRATIONS} illustrations" if "illustration" in kinds else "")
             + (f", at most {MAX_EXPERIMENTS} experiment" if "experiment" in kinds else "")
             + "). Add media only where it helps understanding (a picture of the artwork being discussed, a diagram of "
               "a process, a recording to listen to, an exercise to try); never decoration. Every item needs a caption "
               "saying what to look at, listen for or do. Unused fields are empty strings (start_seconds 0). Kinds:"]
    lines += [f"- {GUIDE[k]}" for k in kinds]
    return "\n".join(lines)


def item_schema(options: dict) -> dict | None:
    kinds = allowed_kinds(options)
    if not kinds:
        return None
    props = {"kind": {"type": "string", "enum": kinds}, "caption": {"type": "string"}, "code": {"type": "string"},
             "query": {"type": "string"}, "url": {"type": "string"}, "start_seconds": {"type": "integer"},
             "spec": {"type": "string"}}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# ---------- checking what Gemini proposed ----------

def youtube_id(url: str) -> str | None:
    try:
        p = urlparse(url.strip())
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    vid = None
    if host in ("youtu.be",):
        vid = p.path.lstrip("/").split("/")[0]
    elif host in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        if p.path == "/watch":
            vid = (parse_qs(p.query).get("v") or [None])[0]
        elif p.path.startswith(("/embed/", "/shorts/", "/live/")):
            vid = p.path.split("/")[2]
    return vid if vid and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid) else None


def _plot_ok(spec: dict) -> str | None:
    expr = str(spec.get("expression", ""))
    if not expr or len(expr) > 200 or not re.fullmatch(r"[0-9A-Za-z_+\-*/^(). ,]+", expr):
        return "the plot expression has unexpected characters"
    params = spec.get("params") or []
    if len(params) > 3:
        return "a plot has at most 3 sliders"
    names = set()
    for prm in params:
        n = str(prm.get("name", ""))
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,11}", n) or n in PLOT_FUNCS or n in PLOT_CONSTS:
            return f"bad slider name {n!r}"
        try:
            lo, hi, val = float(prm["min"]), float(prm["max"]), float(prm.get("value", prm["min"]))
        except (KeyError, TypeError, ValueError):
            return "a slider needs numeric min, max and value"
        if not lo < hi or not lo <= val <= hi:
            return "a slider's value must sit between its min and max"
        names.add(n)
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr):
        if word not in PLOT_FUNCS and word not in PLOT_CONSTS and word not in names:
            return f"the plot uses an unknown name {word!r}"
    try:
        x0, x1 = float(spec.get("x_min", -10)), float(spec.get("x_max", 10))
    except (TypeError, ValueError):
        return "plot ranges must be numbers"
    if not x0 < x1:
        return "x_min must be below x_max"
    return None


def check_widget(spec: dict) -> str | None:
    t = spec.get("type")
    s = lambda v, n=300: isinstance(v, str) and 0 < len(v.strip()) <= n
    if t == "flashcards":
        cards = spec.get("cards") or []
        if not 2 <= len(cards) <= 20 or not all(s(c.get("front")) and s(c.get("back"), 600) for c in cards):
            return "flashcards need 2-20 cards with a front and a back"
    elif t == "order":
        items = spec.get("items") or []
        if not 3 <= len(items) <= 10 or not all(s(i, 200) for i in items) or len(set(items)) != len(items):
            return "an ordering exercise needs 3-10 different items"
    elif t == "match":
        pairs = spec.get("pairs") or []
        if not 3 <= len(pairs) <= 10 or not all(s(p.get("left"), 200) and s(p.get("right"), 200) for p in pairs):
            return "a matching exercise needs 3-10 pairs"
        if len({p["right"] for p in pairs}) != len(pairs):
            return "matching answers must all differ"
    elif t == "cloze":
        text = spec.get("text", "")
        if not s(text, 3000) or not re.search(r"\{\{[^{}]+\}\}", text):
            return "a fill-the-gaps exercise needs {{blanks}}"
    elif t == "timeline":
        ev = spec.get("events") or []
        if not 2 <= len(ev) <= 20 or not all(s(e.get("date"), 40) and s(e.get("label"), 200) for e in ev):
            return "a timeline needs 2-20 events with a date and a label"
    elif t == "plot":
        return _plot_ok(spec)
    else:
        return f"unknown widget type {t!r}"
    return None


def check_item(m: dict) -> tuple[dict | None, str | None]:
    """Returns (clean item, None) or (None, why it was dropped)."""
    kind = m.get("kind")
    caption = str(m.get("caption", "")).strip()[:400]
    code = str(m.get("code", ""))
    if kind == "mermaid":
        code = code.strip()
        if code.startswith("```"):
            code = re.sub(r"^```\w*\s*|\s*```$", "", code)
        if not code or len(code) > 6000 or "<script" in code.lower():
            return None, "a diagram was empty or too long"
        return {"kind": kind, "caption": caption, "spec": {"code": code}}, None
    if kind == "svg":
        code = code.strip()
        if not code.lstrip().startswith("<svg") or len(code) > MAX_SVG:
            return None, "a drawing wasn't a single small SVG"
        return {"kind": kind, "caption": caption, "spec": {}, "svg": code}, None
    if kind in ("image", "audio", "illustration"):
        q = str(m.get("query", "")).strip()
        if not q or len(q) > 600:
            return None, f"an {kind} had no description"
        return {"kind": kind, "caption": caption, "spec": {"query": q}}, None
    if kind == "video":
        vid = youtube_id(str(m.get("url", "")))
        if not vid:
            return None, "a video link wasn't a YouTube video"
        start = max(0, min(int(m.get("start_seconds") or 0), 6 * 3600))
        return {"kind": kind, "caption": caption, "spec": {"id": vid, "start": start}}, None
    if kind == "widget":
        try:
            spec = json.loads(m.get("spec") or "")
        except ValueError:
            return None, "an exercise's data wasn't valid JSON"
        if not isinstance(spec, dict):
            return None, "an exercise's data wasn't an object"
        why = check_widget(spec)
        if why:
            return None, why
        return {"kind": kind, "caption": caption, "spec": spec}, None
    if kind == "experiment":
        code = code.strip()
        if "<script" not in code.lower() or len(code) > MAX_EXPERIMENT:
            return None, "an experiment wasn't a small HTML page with a script"
        return {"kind": kind, "caption": caption, "spec": {}, "html": code}, None
    return None, f"unknown media kind {kind!r}"


def store(c: sqlite3.Connection, course_id: str, session_id: str, chunks: list[dict], options: dict) -> list[str]:
    """Replace a session's media with what its chunks propose. Returns notes about anything dropped."""
    for old in c.execute("SELECT file FROM media WHERE session_id=? AND file IS NOT NULL", (session_id,)):
        p = _path(course_id, old["file"])
        if p and p.exists():
            p.unlink()
    c.execute("DELETE FROM media WHERE session_id=?", (session_id,))
    allowed = set(allowed_kinds(options))
    notes: list[str] = []
    count = {"total": 0, "illustration": 0, "experiment": 0}
    folder = db.course_dir(course_id) / "media"
    for ci, ch in enumerate(chunks):
        for mi, raw in enumerate((ch.get("media") or [])[:3]):
            if raw.get("kind") not in allowed:
                continue
            item, why = check_item(raw)
            if not item:
                notes.append(f"chunk {ci + 1}: left out media ({why})")
                continue
            k = item["kind"]
            if count["total"] >= MAX_PER_SESSION or (k in ("illustration", "experiment")
                                                     and count[k] >= (MAX_ILLUSTRATIONS if k == "illustration" else MAX_EXPERIMENTS)):
                continue
            count["total"] += 1
            if k in count:
                count[k] += 1
            mid = f"{session_id}-m{ci + 1}{mi + 1}"
            status, file, mime = "pending", None, None
            if k in ("mermaid", "widget"):
                status = "ready"
            elif k in ("svg", "experiment"):
                folder.mkdir(parents=True, exist_ok=True)
                ext, mime = ("svg", "image/svg+xml") if k == "svg" else ("html", "text/html")
                file = f"media/{mid}.{ext}"
                (folder / f"{mid}.{ext}").write_text(item["svg"] if k == "svg" else item["html"], encoding="utf-8")
                status = "ready"
            c.execute("INSERT INTO media(id, course_id, session_id, chunk, seq, kind, caption, spec_json, status, file, mime) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (mid, course_id, session_id, ci, mi, k, item["caption"], db.dumps(item["spec"]), status, file, mime))
            if k == "illustration":
                jobs.enqueue(c, "illustration", {"role": "image", "image": True, "aspect": "16:9", "prompt":
                             "An educational illustration, clear and uncluttered, flat colours, no text or lettering in the "
                             f"picture: {item['spec']['query']}"}, course_id=course_id, ref=mid, priority=jobs.PRIORITY_LATER)
                c.execute("UPDATE media SET status='working' WHERE id=?", (mid,))
    return notes


def _path(course_id: str, rel: str | None):
    if not rel:
        return None
    base = db.course_dir(course_id).resolve()
    p = (base / rel).resolve()
    return p if p.is_relative_to(base) else None


def file_of(c: sqlite3.Connection, media_id: str):
    m = c.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
    if m is None or m["status"] != "ready" or not m["file"]:
        return None, None
    p = _path(m["course_id"], m["file"])
    return (m, p) if p and p.is_file() else (None, None)


def public(m: sqlite3.Row) -> dict:
    return {"id": m["id"], "chunk": m["chunk"], "kind": m["kind"], "caption": m["caption"], "status": m["status"],
            "spec": db.loads(m["spec_json"], {}), "credit": m["credit"], "source_url": m["source_url"],
            "has_file": bool(m["file"]), "error": m["error"] if m["status"] == "failed" else None}


# ---------- illustrations (paid: through the job queue) ----------

def _on_illustration(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    m = c.execute("SELECT * FROM media WHERE id=?", (job["ref"],)).fetchone()
    if m is None:
        return
    data, mime = res.data["bytes"], res.data["mime"]
    ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "webp" if data[:4] == b"RIFF" else "png"
    folder = db.course_dir(m["course_id"]) / "media"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{m['id']}.{ext}").write_bytes(data)
    c.execute("UPDATE media SET status='ready', file=?, mime=?, credit=? WHERE id=?",
              (f"media/{m['id']}.{ext}", {"jpg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png"),
               "AI illustration (Gemini)", m["id"]))


def _on_illustration_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    c.execute("UPDATE media SET status='failed', error=? WHERE id=?", (err[:300], job["ref"]))


jobs.handler("illustration", on_failed=_on_illustration_failed)(_on_illustration)


# ---------- fetching from Wikimedia Commons and YouTube (free: a background task) ----------

def fetch_bytes(url: str, limit: int) -> tuple[int, bytes, str]:
    """GET a public URL (same address checks as link verification) and return (status, body, content type)."""
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), transport=verify.transport, follow_redirects=False,
                      headers={"User-Agent": UA}) as client:
        for _ in range(6):
            verify._check_host(url)
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = str(httpx.URL(url).join(r.headers["location"]))
                    continue
                if r.status_code != 200:
                    return r.status_code, b"", ""
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > limit:
                        raise verify.Blocked("file too big")
                return 200, body, r.headers.get("content-type", "").split(";")[0].strip()
    raise verify.Blocked("too many redirects")


COMMONS = "https://commons.wikimedia.org/w/api.php"
AUDIO_TYPES = {"audio/mpeg": "mp3", "audio/ogg": "ogg", "audio/webm": "webm", "audio/wav": "wav", "audio/x-wav": "wav",
               "audio/flac": "flac", "application/ogg": "ogg"}
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def _strip_html(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def commons_search(query: str, audio: bool) -> list[dict]:
    q = f"{query} filetype:{'audio' if audio else 'bitmap'}"
    url = (f"{COMMONS}?action=query&format=json&formatversion=2&generator=search&gsrnamespace=6&gsrlimit=6"
           f"&gsrsearch={quote(q)}&prop=videoinfo&viprop=url|mime|size|extmetadata|derivatives&viurlwidth=1280")
    status, body, _ = fetch_bytes(url, 2_000_000)
    if status != 200:
        raise verify.Blocked(f"Commons answered {status}")
    pages = (json.loads(body).get("query") or {}).get("pages") or []
    pages.sort(key=lambda p: p.get("index", 99))
    return pages


def _credit(info: dict, title: str) -> str:
    meta = info.get("extmetadata") or {}
    artist = _strip_html((meta.get("Artist") or {}).get("value", ""))[:120]
    lic = _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))[:60]
    name = title.removeprefix("File:")
    return " · ".join(x for x in (artist or name, lic or "see source", "Wikimedia Commons") if x)


def resolve_commons(m: sqlite3.Row) -> tuple[str, bytes, str, str]:
    """Returns (ext, bytes, credit, source url) for an image or audio item."""
    audio = m["kind"] == "audio"
    query = db.loads(m["spec_json"], {}).get("query", "")
    for page in commons_search(query, audio):
        info = (page.get("videoinfo") or [{}])[0]
        mime = info.get("mime", "")
        if audio:
            pick = None
            for d in info.get("derivatives") or []:
                if "audio/mpeg" in d.get("type", "") and d.get("src"):
                    pick = (d["src"], "mp3")
                    break
            if not pick and mime in AUDIO_TYPES and info.get("url"):
                pick = (info["url"], AUDIO_TYPES[mime])
            if not pick:
                continue
            src, ext = pick
            limit = MAX_AUDIO
        else:
            if not mime.startswith("image/"):
                continue
            src = info.get("thumburl") or info.get("url")
            ext = IMAGE_TYPES.get(mime) or ("png" if mime == "image/svg+xml" or mime == "image/tiff" else None)
            if not src or not ext:
                continue
            limit = MAX_IMAGE
        status, data, ctype = fetch_bytes(src, limit)
        if status != 200 or not data:
            continue
        if not audio:
            ext = IMAGE_TYPES.get(ctype, ext)
        return ext, data, _credit(info, page.get("title", "")), info.get("descriptionurl", "")
    raise verify.Blocked("nothing suitable on Wikimedia Commons")


def resolve_video(m: sqlite3.Row) -> tuple[str, bytes, str, str]:
    spec = db.loads(m["spec_json"], {})
    url = f"https://www.youtube.com/watch?v={spec['id']}"
    ok, note, info = verify.check_youtube(url)
    if not ok:
        raise verify.Blocked(note)
    status, data, ctype = fetch_bytes(f"https://i.ytimg.com/vi/{spec['id']}/hqdefault.jpg", 2_000_000)
    credit = f"{info.get('title', 'YouTube video')} · {info.get('author_name', 'YouTube')}"
    if status != 200:
        return "", b"", credit, url
    return "jpg", data, credit, url


def step() -> bool:
    """Fetch one pending picture, recording or video thumbnail. Returns True if it did one (a worker idle task)."""
    with db.tx() as c:
        m = c.execute("SELECT * FROM media WHERE status='pending' AND kind IN ('image','audio','video') ORDER BY rowid LIMIT 1").fetchone()
        if m is None:
            return False
        c.execute("UPDATE media SET status='working' WHERE id=?", (m["id"],))
    try:
        ext, data, credit, source = resolve_video(m) if m["kind"] == "video" else resolve_commons(m)
        err = None
    except (verify.Blocked, httpx.HTTPError, ValueError, KeyError) as e:
        ext, data, credit, source, err = "", b"", "", "", str(e) or type(e).__name__
    except Exception as e:  # never let one odd item stop the worker
        log.exception("fetching media %s failed", m["id"])
        ext, data, credit, source, err = "", b"", "", "", str(e)
    with db.tx() as c:
        if err:
            c.execute("UPDATE media SET status='failed', error=? WHERE id=?", (err[:300], m["id"]))
            return True
        rel = None
        mime = None
        if data:
            folder = db.course_dir(m["course_id"]) / "media"
            folder.mkdir(parents=True, exist_ok=True)
            rel = f"media/{m['id']}.{ext}"
            (folder / f"{m['id']}.{ext}").write_bytes(data)
            mime = {**{v: k for k, v in IMAGE_TYPES.items()}, "mp3": "audio/mpeg", "ogg": "audio/ogg", "webm": "audio/webm",
                    "wav": "audio/wav", "flac": "audio/flac"}.get(ext, "application/octet-stream")
        c.execute("UPDATE media SET status='ready', file=?, mime=?, credit=?, source_url=? WHERE id=?",
                  (rel, mime, credit[:300], source[:500], m["id"]))
    return True


def reset_stuck() -> None:
    with db.tx() as c:
        c.execute("UPDATE media SET status='pending' WHERE status='working' AND kind IN ('image','audio','video')")
