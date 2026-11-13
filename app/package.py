"""A `.knwlge` course package: one zip with everything a course is made of, for sharing it or moving it to another
install. Personal progress is left out unless the exporter asks for their own.

Import treats the file as untrusted: size and count limits, no paths taken from the archive (files are looked up by
names this module builds), every field checked and clipped, media re-checked the way new lessons are, reading links
checked again, new ids throughout. The course arrives owned by the importer (a draft in team mode).
"""
from __future__ import annotations

import io
import json
import re
import sqlite3
import zipfile

from . import achievements, auth, db, library, media
from .pipeline import Problem, _course_id
from .tiers import KIND_LABEL, TIERS

FORMAT = "knwlge-course"
VERSION = 1
MAX_PACKAGE = 200 * 1024 * 1024        # the upload
MAX_UNPACKED = 400 * 1024 * 1024       # everything inside, uncompressed
MAX_JSON = 30 * 1024 * 1024
MAX_ENTRIES = 3000
MAX_SESSIONS = 60
MAX_ITEMS = 3000
MAX_MEDIA = 600
MAX_READING = 600

REL_SESSION = re.compile(r"^s\d{2}$")
REL_ITEM = re.compile(r"^s\d{2}-i\d{2,3}$")
REL_MEDIA = re.compile(r"^s\d{2}-m\d{2}$")
SESSION_KINDS = set(KIND_LABEL)
MEDIA_KINDS = ("mermaid", "svg", "image", "illustration", "video", "audio", "widget", "experiment")
SECTIONS = ("check", "practice", "exercise", "project")
QTYPES = ("mcq", "numeric", "short", "long")
READING_KINDS = ("book", "video", "article", "course", "podcast", "other", "source")
MEDIA_FILE_TYPES = {   # kind -> {extension: mime}
    "image": {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"},
    "illustration": {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"},
    "audio": {"mp3": "audio/mpeg", "ogg": "audio/ogg", "webm": "audio/webm", "wav": "audio/wav", "flac": "audio/flac"},
    "video": {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"},   # the thumbnail
    "svg": {"svg": "image/svg+xml"},
    "experiment": {"html": "text/html"},
}


def _rel(full: str, course_id: str) -> str:
    return full[len(course_id) + 1:] if full.startswith(course_id + "-") else full


# ---------- export ----------

def export(c: sqlite3.Connection, course_id: str, uid: int, with_progress: bool = False) -> tuple[str, bytes]:
    co = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if co is None:
        raise Problem("That course doesn't exist.")
    if co["status"] not in ("building", "ready"):
        raise Problem("Approve the plan first: a package holds a written course.")
    rel = lambda full: _rel(full, course_id)   # noqa: E731
    course = {"subject": co["subject"], "notes": co["notes"], "depth": co["depth"], "title": co["title"], "summary": co["summary"],
              "plan": db.loads(co["plan_json"], {}), "questions": db.loads(co["questions_json"], []),
              "answers": db.loads(co["answers_json"], {}), "options": media.options_of(co["options_json"]),
              "tags": library.tags_of(co), "created_at": co["created_at"]}
    sessions = [{"key": rel(s["id"]), "seq": s["seq"], "kind": s["kind"], "title": s["title"],
                 "topics": db.loads(s["topics_json"], []), "objectives": db.loads(s["objectives_json"], []),
                 "minutes": s["minutes"], "ready": s["state"] == "ready", "content": db.loads(s["content_json"]),
                 "warnings": db.loads(s["warnings_json"], [])}
                for s in c.execute("SELECT * FROM sessions WHERE course_id=? ORDER BY seq", (course_id,))]
    items = [{"key": rel(i["id"]), "session": rel(i["session_id"]), "seq": i["seq"], "section": i["section"], "chunk": i["chunk"],
              "qtype": i["qtype"], "title": i["title"], "prompt": i["prompt"], "options": db.loads(i["options_json"], []),
              "answer": i["answer"], "explanation": i["explanation"], "tolerance": i["tolerance"],
              "rubric": db.loads(i["rubric_json"], []), "topic": i["topic"]}
             for i in c.execute("SELECT * FROM items WHERE course_id=? ORDER BY session_id, seq", (course_id,))]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        media_out = []
        for m in c.execute("SELECT * FROM media WHERE course_id=? ORDER BY session_id, chunk, seq", (course_id,)):
            entry = {"key": rel(m["id"]), "session": rel(m["session_id"]), "chunk": m["chunk"], "seq": m["seq"], "kind": m["kind"],
                     "caption": m["caption"], "spec": db.loads(m["spec_json"], {}), "ready": m["status"] == "ready",
                     "credit": m["credit"], "source_url": m["source_url"], "file": None}
            p = media._path(course_id, m["file"])
            if m["status"] == "ready" and p and p.is_file():
                ext = p.suffix.lstrip(".").lower()
                entry["file"] = f"media/{entry['key']}.{ext}"
                z.write(p, entry["file"])
            media_out.append(entry)
        reading = [{"session": rel(r["session_id"]) if r["session_id"] else None, "kind": r["kind"], "title": r["title"],
                    "creator": r["creator"], "url": r["url"], "isbn": r["isbn"], "year": r["year"], "level": r["level"],
                    "minutes": r["minutes"], "why": r["why"], "free": bool(r["free"]), "top": bool(r["top"])}
                   for r in c.execute("SELECT * FROM reading WHERE course_id=? AND status='verified' ORDER BY id", (course_id,))]
        themed = [{"key": a["key"], "title": a["title"], "description": a["description"], **a["rule"]}
                  for a in achievements.themed(c, course_id)]
        manifest = {"format": FORMAT, "version": VERSION, "exported_at": db.now(), "title": co["title"],
                    "sessions": len(sessions), "progress": with_progress}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr("course.json", json.dumps({"course": course, "sessions": sessions, "items": items, "media": media_out,
                                               "reading": reading, "achievements": themed}, ensure_ascii=False))
        if with_progress:
            z.writestr("progress.json", json.dumps(_progress(c, course_id, uid), ensure_ascii=False))
    safe = re.sub(r"[^\w .()-]+", "-", co["title"]).strip(" .-")[:70] or "course"
    return f"{safe}.knwlge", buf.getvalue()


def _progress(c: sqlite3.Connection, course_id: str, uid: int) -> dict:
    rel = lambda full: _rel(full, course_id)   # noqa: E731
    return {
        "sessions": [{"session": rel(p["session_id"]), "started_at": p["started_at"], "done_at": p["done_at"],
                      "summary_note": p["summary_note"], "note": p["note"]}
                     for p in c.execute("SELECT p.* FROM session_progress p JOIN sessions s ON s.id=p.session_id "
                                        "WHERE s.course_id=? AND p.user_id=?", (course_id, uid))],
        "attempts": [{"item": rel(a["item_id"]), "created_at": a["created_at"], "answer": a["answer"], "score": a["score"],
                      "feedback": db.loads(a["feedback_json"]), "context": a["context"]}
                     for a in c.execute("SELECT * FROM attempts WHERE course_id=? AND user_id=? AND status='marked' ORDER BY id",
                                        (course_id, uid))],
        "reveals": [{"item": rel(r["item_id"]), "at": r["at"]}
                    for r in c.execute("SELECT r.* FROM item_reveals r JOIN items i ON i.id=r.item_id WHERE i.course_id=? "
                                       "AND r.user_id=?", (course_id, uid))],
        "reviews": [{"item": rel(r["item_id"]), "due_at": r["due_at"], "interval_days": r["interval_days"], "misses": r["misses"],
                     "last_seen_at": r["last_seen_at"]}
                    for r in c.execute("SELECT * FROM review_queue WHERE course_id=? AND user_id=?", (course_id, uid))],
    }


# ---------- import ----------

def _s(v, limit: int) -> str:
    return str(v if v is not None else "")[:limit]


def _strs(v, n: int, limit: int) -> list[str]:
    return [_s(x, limit) for x in (v if isinstance(v, list) else [])][:n]


def _ts(v) -> str | None:
    v = _s(v, 40)
    return v if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z?", v) else None


def _read(z: zipfile.ZipFile, name: str, limit: int) -> bytes | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        raise Problem(f"{name} in the package is too big.")
    with z.open(info) as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise Problem(f"{name} in the package is too big.")
    return data


def _json(z: zipfile.ZipFile, name: str) -> dict | None:
    data = _read(z, name, MAX_JSON)
    if data is None:
        return None
    try:
        out = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise Problem(f"{name} in the package isn't valid JSON.") from e
    if not isinstance(out, dict):
        raise Problem(f"{name} in the package isn't what Knwlge expects.")
    return out


def _clean_content(content, kind: str) -> dict | None:
    """Display content as the app stores it: only known keys, all strings."""
    if not isinstance(content, dict):
        return None
    if kind == "project":
        return {k: _s(content.get(k), 20_000) for k in ("goal", "intro_markdown", "tips_markdown")}
    chunks = [{"title": _s(ch.get("title"), 300), "markdown": _s(ch.get("markdown"), 50_000),
               "example_markdown": _s(ch.get("example_markdown"), 50_000)}
              for ch in (content.get("chunks") if isinstance(content.get("chunks"), list) else [])[:12] if isinstance(ch, dict)]
    wrap = content.get("wrapup") if isinstance(content.get("wrapup"), dict) else {}
    return {"goal": _s(content.get("goal"), 2000), "hook": _s(content.get("hook"), 4000), "chunks": chunks,
            "wrapup": {"key_points": _strs(wrap.get("key_points"), 8, 1000), "teaser": _s(wrap.get("teaser"), 1000)}}


def _clean_rubric(v) -> list[dict]:
    out = []
    for r in (v if isinstance(v, list) else [])[:8]:
        if isinstance(r, dict):
            try:
                pts = max(0, min(100, int(r.get("points") or 0)))
            except (TypeError, ValueError):
                pts = 0
            out.append({"criterion": _s(r.get("criterion"), 200), "points": pts, "description": _s(r.get("description"), 1000)})
    return out


def _media_item(m: dict, data: bytes | None, ext: str) -> tuple[dict | None, str | None, str | None]:
    """(clean media, file bytes to keep, mime) or (None, ...) if it's dropped. Reuses the checks new lessons get."""
    kind = m.get("kind")
    caption = _s(m.get("caption"), 400)
    spec = m.get("spec") if isinstance(m.get("spec"), dict) else {}
    if kind == "mermaid":
        item, _ = media.check_item({"kind": kind, "caption": caption, "code": _s(spec.get("code"), 7000)})
        return item, None, None
    if kind == "widget":
        item, _ = media.check_item({"kind": kind, "caption": caption, "spec": json.dumps(spec)})
        return item, None, None
    if kind in ("svg", "experiment"):
        if data is None:
            return None, None, None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return None, None, None
        item, _ = media.check_item({"kind": kind, "caption": caption, "code": text})
        if not item:
            return None, None, None
        return item, (item["svg"] if kind == "svg" else item["html"]).encode("utf-8"), MEDIA_FILE_TYPES[kind][ext]
    if kind in ("image", "audio", "illustration", "video"):
        if kind == "video":
            vid = media.youtube_id(f"https://www.youtube.com/watch?v={_s(spec.get('id'), 20)}")
            if not vid:
                return None, None, None
            try:
                start = max(0, min(int(spec.get("start") or 0), 6 * 3600))
            except (TypeError, ValueError):
                start = 0
            item = {"kind": kind, "caption": caption, "spec": {"id": vid, "start": start}}
        else:
            q = _s(spec.get("query"), 600).strip()
            item = {"kind": kind, "caption": caption, "spec": {"query": q}}
        if data is None or ext not in MEDIA_FILE_TYPES[kind]:
            return item, None, None   # kept without its file: fetched again (pictures, recordings) or shown as a link
        limit = media.MAX_AUDIO if kind == "audio" else media.MAX_IMAGE
        if len(data) > limit or not _looks_like(data, ext):
            return item, None, None
        return item, data, MEDIA_FILE_TYPES[kind][ext]
    return None, None, None


def _looks_like(data: bytes, ext: str) -> bool:
    sig = {"jpg": [b"\xff\xd8\xff"], "png": [b"\x89PNG\r\n\x1a\n"], "gif": [b"GIF87a", b"GIF89a"], "webp": [b"RIFF"],
           "mp3": [b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"], "ogg": [b"OggS"], "webm": [b"\x1a\x45\xdf\xa3"],
           "wav": [b"RIFF"], "flac": [b"fLaC"]}.get(ext, [])
    if ext == "webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return False
    return any(data.startswith(s) for s in sig)


def import_package(c: sqlite3.Connection, data: bytes, uid: int, with_progress: bool = True) -> str:
    if len(data) > MAX_PACKAGE:
        raise Problem("That package is too big (200 MB at most).")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise Problem("That isn't a Knwlge course package.") from e
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES or sum(i.file_size for i in infos) > MAX_UNPACKED:
        raise Problem("That package holds too much.")
    manifest = _json(z, "manifest.json")
    if not manifest or manifest.get("format") != FORMAT:
        raise Problem("That isn't a Knwlge course package.")
    if not isinstance(manifest.get("version"), int) or manifest["version"] > VERSION:
        raise Problem("That package was made by a newer Knwlge. Update this one first.")
    body = _json(z, "course.json")
    if not body or not isinstance(body.get("course"), dict):
        raise Problem("The package has no course in it.")
    co = body["course"]
    depth = co.get("depth") if co.get("depth") in TIERS else None
    if not depth:
        raise Problem("The package's course has a depth this Knwlge doesn't know.")
    subject = _s(co.get("subject"), 300).strip() or "Imported course"
    cid = _course_id(subject)
    new = lambda rel_id: f"{cid}-{rel_id}"   # noqa: E731
    now = db.now()
    team = auth.mode() == "team"

    # sessions
    sessions, seen = [], set()
    for s in (body.get("sessions") if isinstance(body.get("sessions"), list) else [])[:MAX_SESSIONS]:
        if not isinstance(s, dict) or not REL_SESSION.match(str(s.get("key", ""))) or s["key"] in seen:
            continue
        if s.get("kind") not in SESSION_KINDS:
            continue
        seen.add(s["key"])
        content = _clean_content(s.get("content"), s["kind"]) if s.get("ready") else None
        try:
            minutes = max(5, min(600, int(s.get("minutes") or 45)))
        except (TypeError, ValueError):
            minutes = 45
        sessions.append((s, content, minutes))
    if not sessions:
        raise Problem("The package's course has no sessions.")
    sessions.sort(key=lambda t: t[0]["key"])

    plan = co.get("plan") if isinstance(co.get("plan"), dict) else {}
    plan_clean = {"title": _s(plan.get("title"), 300), "summary": _s(plan.get("summary"), 4000),
                  "prerequisites": _strs(plan.get("prerequisites"), 12, 500),
                  "readiness": {k: _s((plan.get("readiness") or {}).get(k), 1000) for k in ("teaching", "feedback", "safety_note")}
                  | {"weak_spots": _strs((plan.get("readiness") or {}).get("weak_spots"), 10, 500)},
                  "sessions": [{"slot": int(s["key"][1:]), "kind": s["kind"], "minutes": m, "title": _s(s.get("title"), 200),
                                "topics": _strs(s.get("topics"), 8, 300), "objectives": _strs(s.get("objectives"), 5, 500)}
                               for s, _, m in sessions]}
    title = _s(co.get("title"), 200).strip() or subject
    all_ready = all(content is not None for _, content, _ in sessions)
    c.execute("INSERT INTO courses(id, subject, notes, depth, title, summary, status, questions_json, answers_json, plan_json, "
              "options_json, tags_json, created_at, updated_at, author_id, visibility, published_at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (cid, subject, _s(co.get("notes"), 4000), depth, title, _s(co.get("summary"), 4000),
               "ready" if all_ready else "building", "[]", "{}", db.dumps(plan_clean),
               db.dumps(media.clean_options(co.get("options") if isinstance(co.get("options"), dict) else None)),
               db.dumps(library.clean_tags(co.get("tags"))), now, now, uid, "draft" if team else "published",
               None if team else now))
    folder = db.course_dir(cid)
    folder.mkdir(parents=True, exist_ok=True)
    for s, content, minutes in sessions:
        ready = content is not None
        c.execute("INSERT INTO sessions(id, course_id, seq, kind, title, topics_json, objectives_json, minutes, state, content_json, "
                  "warnings_json, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (new(s["key"]), cid, int(s["key"][1:]), s["kind"], _s(s.get("title"), 200) or f"Session {s['key'][1:]}",
                   db.dumps(_strs(s.get("topics"), 8, 300)), db.dumps(_strs(s.get("objectives"), 5, 500)), minutes,
                   "ready" if ready else "failed", db.dumps(content) if ready else None,
                   db.dumps(_strs(s.get("warnings"), 20, 500)),
                   None if ready else "This session wasn't written in the package. Try again writes it."))

    ready_keys = {s["key"] for s, content, _ in sessions if content is not None}
    # items
    item_keys = set()
    for i in (body.get("items") if isinstance(body.get("items"), list) else [])[:MAX_ITEMS]:
        if not isinstance(i, dict) or not REL_ITEM.match(str(i.get("key", ""))) or i["key"] in item_keys:
            continue
        if i.get("session") not in ready_keys or not i["key"].startswith(i["session"] + "-"):
            continue
        if i.get("section") not in SECTIONS or i.get("qtype") not in QTYPES:
            continue
        item_keys.add(i["key"])
        try:
            tol = float(i.get("tolerance") or 0)
            chunk = None if i.get("chunk") is None else max(0, min(20, int(i["chunk"])))
        except (TypeError, ValueError):
            tol, chunk = 0.0, None
        c.execute("INSERT INTO items(id, course_id, session_id, seq, section, chunk, qtype, title, prompt, options_json, answer, "
                  "explanation, tolerance, rubric_json, topic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (new(i["key"]), cid, new(i["session"]), int(i["key"].rsplit("-i", 1)[1]), i["section"], chunk, i["qtype"],
                   _s(i.get("title"), 300), _s(i.get("prompt"), 20_000), db.dumps(_strs(i.get("options"), 8, 1000)),
                   _s(i.get("answer"), 20_000), _s(i.get("explanation"), 10_000), tol, db.dumps(_clean_rubric(i.get("rubric"))),
                   _s(i.get("topic"), 200)))

    # media, with files re-checked; pictures and recordings without a usable file are fetched again
    media_keys = set()
    for m in (body.get("media") if isinstance(body.get("media"), list) else [])[:MAX_MEDIA]:
        if not isinstance(m, dict) or not REL_MEDIA.match(str(m.get("key", ""))) or m["key"] in media_keys:
            continue
        if m.get("session") not in ready_keys or not m["key"].startswith(m["session"] + "-") or m.get("kind") not in MEDIA_KINDS:
            continue
        media_keys.add(m["key"])
        ext = ""
        data = None
        f = m.get("file")
        if isinstance(f, str) and re.fullmatch(r"media/s\d{2}-m\d{2}\.[a-z0-9]{2,5}", f) and f.startswith(f"media/{m['key']}."):
            ext = f.rsplit(".", 1)[1]
            data = _read(z, f, max(media.MAX_AUDIO, media.MAX_IMAGE, media.MAX_EXPERIMENT))
        item, keep, mime = _media_item(m, data, ext)
        if not item:
            continue
        mid = new(m["key"])
        status, rel_file = "pending", None
        if keep is not None:
            (folder / "media").mkdir(parents=True, exist_ok=True)
            rel_file = f"media/{mid}.{ext}"
            (folder / rel_file).write_bytes(keep)
            status = "ready"
        elif item["kind"] in ("mermaid", "widget"):
            status = "ready"
        elif item["kind"] in ("svg", "experiment", "illustration"):
            continue   # nothing usable to show (an illustration isn't redrawn: that costs money)
        try:
            chunk, seq = max(0, min(20, int(m.get("chunk") or 0))), max(0, min(9, int(m.get("seq") or 0)))
        except (TypeError, ValueError):
            chunk, seq = 0, 0
        c.execute("INSERT INTO media(id, course_id, session_id, chunk, seq, kind, caption, spec_json, status, file, mime, credit, "
                  "source_url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, cid, new(m["session"]), chunk, seq, item["kind"], item["caption"], db.dumps(item["spec"]), status, rel_file,
                   mime, _s(m.get("credit"), 300) if status == "ready" else "",
                   _s(m.get("source_url"), 500) if status == "ready" and str(m.get("source_url", "")).startswith("https://") else ""))

    # reading: checked again before anyone sees it
    for r in (body.get("reading") if isinstance(body.get("reading"), list) else [])[:MAX_READING]:
        if not isinstance(r, dict) or r.get("kind") not in READING_KINDS or not _s(r.get("title"), 300).strip():
            continue
        sess = r.get("session")
        if sess is not None and sess not in seen:
            continue
        url = _s(r.get("url"), 1000).strip()
        if url and not url.startswith(("https://", "http://")):
            url = ""
        try:
            minutes = int(r["minutes"]) if r.get("minutes") not in (None, "") else None
        except (TypeError, ValueError):
            minutes = None
        c.execute("INSERT INTO reading(course_id, session_id, kind, title, creator, url, isbn, year, level, minutes, why, free, top) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (cid, new(sess) if sess else None, r["kind"], _s(r.get("title"), 300), _s(r.get("creator"), 200), url,
                   _s(r.get("isbn"), 20), _s(r.get("year"), 10), _s(r.get("level"), 40), minutes, _s(r.get("why"), 500),
                   1 if r.get("free", True) else 0, 1 if r.get("top") and not sess else 0))

    # themed achievements
    planned = [{"title": a.get("title"), "description": a.get("description"), "rule": a.get("rule"), "slot": a.get("slot")}
               for a in (body.get("achievements") if isinstance(body.get("achievements"), list) else []) if isinstance(a, dict)]
    achievements.store_planned(c, cid, planned, [int(s["key"][1:]) for s, _, _ in sessions])

    # the exporter's own progress, as the importer's
    prog = _json(z, "progress.json") if with_progress else None
    if prog:
        _import_progress(c, cid, uid, prog, ready_keys, item_keys)
    c.execute("INSERT OR REPLACE INTO course_opens(user_id, course_id, at) VALUES (?,?,?)", (uid, cid, now))
    library.shelve(c, cid, uid, "mine")
    achievements.check(c, cid, uid)
    return cid


def _import_progress(c: sqlite3.Connection, cid: str, uid: int, prog: dict, sessions: set[str], items: set[str]) -> None:
    new = lambda rel_id: f"{cid}-{rel_id}"   # noqa: E731
    lst = lambda k: (prog.get(k) if isinstance(prog.get(k), list) else [])[:MAX_ITEMS * 3]   # noqa: E731
    for p in lst("sessions"):
        if isinstance(p, dict) and p.get("session") in sessions:
            c.execute("INSERT OR IGNORE INTO session_progress(user_id, session_id, started_at, done_at, summary_note, note) "
                      "VALUES (?,?,?,?,?,?)", (uid, new(p["session"]), _ts(p.get("started_at")), _ts(p.get("done_at")),
                                               _s(p.get("summary_note"), 5000), _s(p.get("note"), 20_000)))
    for a in lst("attempts"):
        if not isinstance(a, dict) or a.get("item") not in items:
            continue
        try:
            score = None if a.get("score") is None else max(0.0, min(1.0, float(a["score"])))
        except (TypeError, ValueError):
            continue
        fb = a.get("feedback") if isinstance(a.get("feedback"), dict) else None
        c.execute("INSERT INTO attempts(item_id, course_id, created_at, answer, files_json, status, score, feedback_json, context, "
                  "user_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (new(a["item"]), cid, _ts(a.get("created_at")) or db.now(), _s(a.get("answer"), 20_000), "[]", "marked", score,
                   db.dumps(_clip(fb)) if fb else None, "warmup" if a.get("context") == "warmup" else "session", uid))
    for r in lst("reveals"):
        if isinstance(r, dict) and r.get("item") in items:
            c.execute("INSERT OR IGNORE INTO item_reveals(user_id, item_id, at) VALUES (?,?,?)",
                      (uid, new(r["item"]), _ts(r.get("at")) or db.now()))
    for r in lst("reviews"):
        if isinstance(r, dict) and r.get("item") in items and _ts(r.get("due_at")):
            try:
                interval, misses = max(0.1, min(400.0, float(r.get("interval_days") or 1))), max(0, min(50, int(r.get("misses") or 0)))
            except (TypeError, ValueError):
                continue
            c.execute("INSERT OR IGNORE INTO review_queue(user_id, item_id, course_id, due_at, interval_days, misses, last_seen_at) "
                      "VALUES (?,?,?,?,?,?,?)", (uid, new(r["item"]), cid, _ts(r["due_at"]), interval, misses, _ts(r.get("last_seen_at"))))


def _clip(v, depth: int = 0):
    """Feedback as plain JSON of strings, numbers and lists, clipped (it's only ever shown as text)."""
    if depth > 4:
        return None
    if isinstance(v, dict):
        return {str(k)[:60]: _clip(x, depth + 1) for k, x in list(v.items())[:30]}
    if isinstance(v, list):
        return [_clip(x, depth + 1) for x in v[:30]]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    return str(v)[:5000]

