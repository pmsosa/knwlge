"""Doing the work: attempts, instant checks, feedback on written work, warm-ups (spaced review), progress, chat.

There's deliberately no score for how well someone knows a course: the app shows what they've done and what's coming
back in warm-ups, never a grade."""
from __future__ import annotations

import datetime as dt
import random
import re
import sqlite3

from . import db, gemini, jobs, media, prompts
from .pipeline import Problem, _norm, _num

UPLOAD_TYPES = {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "webp": "image/webp", "gif": "image/gif", "heic": "image/heic", "txt": "text/plain", "md": "text/markdown"}
MATERIAL_TYPES = UPLOAD_TYPES | {"csv": "text/csv", "json": "application/json", "tex": "text/plain", "py": "text/plain",
                                 "html": "text/plain", "xml": "text/plain", "yaml": "text/plain", "yml": "text/plain"}
MAX_FILE = 15 * 1024 * 1024
MAX_MATERIALS = 12
MAX_ANSWER = 20_000


def safe_name(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "-", base).strip(" .")[:80]
    return base or "file"


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def item_row(c: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise Problem("That question doesn't exist.")
    return row


def latest_attempt(c: sqlite3.Connection, item_id: str, uid: int) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM attempts WHERE item_id=? AND user_id=? ORDER BY id DESC LIMIT 1", (item_id, uid)).fetchone()


def revealed(c: sqlite3.Connection, item_id: str, uid: int) -> bool:
    return c.execute("SELECT 1 FROM item_reveals WHERE item_id=? AND user_id=?", (item_id, uid)).fetchone() is not None


def public_item(c: sqlite3.Connection, row: sqlite3.Row, uid: int) -> dict:
    """What this person's browser may see. Answers only once they revealed it, or after they got it right."""
    last = latest_attempt(c, row["id"], uid)
    got_it = last is not None and last["status"] == "marked" and (last["score"] or 0) >= 0.999 and row["qtype"] != "long"
    was_revealed = revealed(c, row["id"], uid)
    show = was_revealed or got_it
    out = {"id": row["id"], "section": row["section"], "chunk": row["chunk"], "qtype": row["qtype"], "title": row["title"],
           "prompt": row["prompt"], "options": db.loads(row["options_json"], []), "topic": row["topic"],
           "rubric": [{"criterion": r.get("criterion"), "points": r.get("points"), "description": r.get("description")}
                      for r in db.loads(row["rubric_json"], [])],
           "revealed": was_revealed,
           "answer": row["answer"] if show else None,
           "explanation": row["explanation"] if show else None,
           "attempts": c.execute("SELECT count(*) AS n FROM attempts WHERE item_id=? AND user_id=?", (row["id"], uid)).fetchone()["n"],
           "last": attempt_view(last) if last else None}
    return out


def attempt_view(a: sqlite3.Row) -> dict:
    return {"id": a["id"], "created_at": a["created_at"], "answer": a["answer"], "files": db.loads(a["files_json"], []),
            "status": a["status"], "score": a["score"], "feedback": db.loads(a["feedback_json"])}


def is_right(row: sqlite3.Row, answer: str) -> bool:
    if row["qtype"] == "mcq":
        return _norm(answer) == _norm(row["answer"])
    if row["qtype"] == "numeric":
        g, a = _num(answer), _num(row["answer"])
        if g is None or a is None:
            return False
        return abs(g - a) <= max(float(row["tolerance"] or 0), 1e-9 * max(abs(a), 1.0))
    return False


def _course_title(c: sqlite3.Connection, course_id: str) -> str:
    return c.execute("SELECT title FROM courses WHERE id=?", (course_id,)).fetchone()["title"]


def attempt(c: sqlite3.Connection, item_id: str, answer: str, files: list[tuple[str, bytes]] = (),
            context: str = "session", uid: int = db.OWNER_ID) -> dict:
    row = item_row(c, item_id)
    answer = (answer or "").strip()
    if len(answer) > MAX_ANSWER:
        raise Problem("That answer is very long; keep it under 20,000 characters.")
    if not answer and not files:
        raise Problem("Write an answer first.")
    if files and row["qtype"] != "long":
        raise Problem("Files can only be added to written exercises and projects.")
    if c.execute("SELECT 1 FROM attempts WHERE item_id=? AND user_id=? AND status='queued'", (item_id, uid)).fetchone():
        raise Problem("Your last answer is still being looked at.")
    now = db.now()
    context = "warmup" if context == "warmup" else "session"

    if row["qtype"] in ("mcq", "numeric"):
        right = is_right(row, answer)
        fb = {"correct": right}
        c.execute("INSERT INTO attempts(item_id, course_id, created_at, answer, status, score, feedback_json, context, user_id) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (item_id, row["course_id"], now, answer, "marked", 1.0 if right else 0.0,
                                                  db.dumps(fb), context, uid))
        schedule_review(c, row, right, uid)
        _touch_session(c, row["session_id"], uid)
        return public_item(c, item_row(c, item_id), uid)

    stored: list[str] = []
    files = [(safe_name(n), d) for n, d in files[:5]]
    for name, data in files:
        if ext_of(name) not in UPLOAD_TYPES:
            raise Problem(f"{name}: add photos (PNG, JPG, WebP, GIF, HEIC), PDFs or text files.")
        if len(data) > MAX_FILE:
            raise Problem(f"{name} is over 15 MB.")
    if sum(len(d) for _, d in files) > 18 * 1024 * 1024:
        raise Problem("Files are limited to 18 MB together.")
    cur = c.execute("INSERT INTO attempts(item_id, course_id, created_at, answer, status, context, user_id) VALUES (?,?,?,?,?,?,?)",
                    (item_id, row["course_id"], now, answer, "queued", context, uid))
    attempt_id = cur.lastrowid
    if files:
        folder = db.course_dir(row["course_id"]) / "uploads" / str(attempt_id)
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in files:
            (folder / name).write_bytes(data)
            stored.append(f"uploads/{attempt_id}/{name}")
        c.execute("UPDATE attempts SET files_json=? WHERE id=?", (db.dumps(stored), attempt_id))
    title = _course_title(c, row["course_id"])
    if row["qtype"] == "short":
        req = prompts.mark_short(title, dict(row), answer)
    else:
        s_title = c.execute("SELECT title FROM sessions WHERE id=?", (row["session_id"],)).fetchone()["title"]
        req = prompts.mark_long(title, s_title, {**dict(row), "rubric": db.loads(row["rubric_json"], [])}, answer, bool(stored))
        req["files"] = stored
    jobs.enqueue(c, "mark", req, course_id=row["course_id"], ref=str(attempt_id), priority=jobs.PRIORITY_NOW, user_id=uid)
    _touch_session(c, row["session_id"], uid)
    return public_item(c, item_row(c, item_id), uid)


def _touch_session(c: sqlite3.Connection, session_id: str, uid: int) -> None:
    c.execute("INSERT INTO session_progress(user_id, session_id, started_at) VALUES (?,?,?) "
              "ON CONFLICT(user_id, session_id) DO UPDATE SET started_at=coalesce(started_at, excluded.started_at)",
              (uid, session_id, db.now()))


def level(score: float) -> str:
    if score >= 0.85:
        return "Strong"
    if score >= 0.6:
        return "Solid"
    if score >= 0.35:
        return "Getting there"
    return "Worth another look"


def score_long(rubric: list[dict], result: dict) -> dict:
    """Points come from the rubric, not from the model: every criterion counts, each capped at its points."""
    given = {}
    for line in result.get("criteria", []):
        try:
            given[int(line.get("index"))] = line
        except (TypeError, ValueError):
            continue
    lines, got, total = [], 0.0, 0.0
    for i, r in enumerate(rubric):
        pts = float(r.get("points") or 0)
        g = given.get(i, {})
        try:
            awarded = float(g.get("awarded", 0))
        except (TypeError, ValueError):
            awarded = 0.0
        awarded = min(max(awarded, 0.0), pts)
        lines.append({"criterion": r.get("criterion", f"Criterion {i + 1}"), "points": pts, "awarded": awarded,
                      "comment": str(g.get("comment", "") or "(no comment)")})
        got += awarded
        total += pts
    score = got / total if total > 0 else 0.0
    return {"lines": lines, "overall": str(result.get("overall", "")), "revisit": [str(x) for x in result.get("revisit", [])][:5],
            "score": score, "level": level(score)}


def _on_mark(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    a = c.execute("SELECT * FROM attempts WHERE id=?", (int(job["ref"]),)).fetchone()
    if a is None:
        return
    row = item_row(c, a["item_id"])
    if row["qtype"] == "short":
        right = bool(res.data.get("correct"))
        fb = {"correct": right, "comment": str(res.data.get("comment", ""))}
        score = 1.0 if right else 0.0
        schedule_review(c, row, right, a["user_id"])
    else:
        fb = score_long(db.loads(row["rubric_json"], []), res.data)
        score = fb["score"]
    c.execute("UPDATE attempts SET status='marked', score=?, feedback_json=? WHERE id=?", (score, db.dumps(fb), a["id"]))


def _on_mark_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    c.execute("UPDATE attempts SET status='failed', feedback_json=? WHERE id=?", (db.dumps({"error": err}), int(job["ref"])))


jobs.handler("mark", on_failed=_on_mark_failed)(_on_mark)


def reveal(c: sqlite3.Connection, item_id: str, uid: int = db.OWNER_ID) -> dict:
    row = item_row(c, item_id)
    c.execute("INSERT OR IGNORE INTO item_reveals(user_id, item_id, at) VALUES (?,?,?)", (uid, item_id, db.now()))
    if row["qtype"] != "long":
        # seeing the answer before getting it means it should come back soon
        last = latest_attempt(c, item_id, uid)
        if last is None or (last["score"] or 0) < 1:
            schedule_review(c, row, False, uid)
    return public_item(c, item_row(c, item_id), uid)


# ---------- spaced review ----------

def schedule_review(c: sqlite3.Connection, row: sqlite3.Row, right: bool, uid: int) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    q = c.execute("SELECT * FROM review_queue WHERE item_id=? AND user_id=?", (row["id"], uid)).fetchone()
    interval = q["interval_days"] if q else 1.0
    misses = q["misses"] if q else 0
    if right:
        interval = max(2.0, interval * 2.5)
        due = now + dt.timedelta(days=interval)
    else:
        interval, misses = 1.0, misses + 1
        due = now  # back in the very next warm-up
    ts = lambda t: t.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    c.execute("INSERT INTO review_queue(user_id, item_id, course_id, due_at, interval_days, misses, last_seen_at) VALUES (?,?,?,?,?,?,?) "
              "ON CONFLICT(user_id, item_id) DO UPDATE SET due_at=excluded.due_at, interval_days=excluded.interval_days, "
              "misses=excluded.misses, last_seen_at=excluded.last_seen_at",
              (uid, row["id"], row["course_id"], ts(due), interval, misses, ts(now)))


def warmup(c: sqlite3.Connection, session_id: str, uid: int, n: int = 4) -> list[dict]:
    """3-4 questions from earlier sessions: ones that are due (missed ones first), then ones from the previous session,
    then older ones not seen in a while."""
    s = c.execute("SELECT course_id, seq FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None or s["seq"] == 1:
        return []
    base = ("SELECT i.* FROM items i JOIN sessions s ON s.id=i.session_id WHERE i.course_id=? AND s.seq < ? "
            "AND i.qtype IN ('mcq','numeric','short') AND i.section IN ('check','practice')")
    picked: list[sqlite3.Row] = []
    seen: set[str] = set()

    def take(rows):
        for r in rows:
            if len(picked) >= n:
                return
            if r["id"] not in seen:
                picked.append(r)
                seen.add(r["id"])

    take(c.execute(base + " AND i.id IN (SELECT item_id FROM review_queue WHERE user_id=? AND due_at <= ?) "
                   "ORDER BY (SELECT misses FROM review_queue q WHERE q.item_id=i.id AND q.user_id=?) DESC, i.seq",
                   (s["course_id"], s["seq"], uid, db.now(), uid)).fetchall())
    rng = random.Random(f"{session_id}:{uid}:{dt.date.today()}")  # stable for the day, so a reload doesn't reshuffle
    prev = c.execute(base + " AND s.seq = ? AND i.id NOT IN (SELECT item_id FROM review_queue WHERE user_id=? AND due_at > ?)",
                     (s["course_id"], s["seq"], s["seq"] - 1, uid, db.now())).fetchall()
    rng.shuffle(prev)
    take(prev[:2])
    older = c.execute(base + " AND s.seq < ? AND i.id NOT IN (SELECT item_id FROM review_queue WHERE user_id=? AND due_at > ?)",
                      (s["course_id"], s["seq"], s["seq"] - 1, uid, db.now())).fetchall()
    rng.shuffle(older)
    take(older)
    out = []
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    for r in picked:
        item = public_item(c, r, uid)
        last = latest_attempt(c, r["id"], uid)
        # a warm-up is fresh recall: hide earlier tries unless this warm-up's own (made today)
        if not (last and last["context"] == "warmup" and last["created_at"][:10] == today):
            item.update(last=None, answer=None, explanation=None, revealed=False)
        item["from_session"] = c.execute("SELECT title FROM sessions WHERE id=?", (r["session_id"],)).fetchone()["title"]
        out.append(item)
    return out


# ---------- progress ----------

def session_progress(c: sqlite3.Connection, session_id: str, uid: int) -> dict:
    rows = c.execute("SELECT i.id, i.qtype, i.section, (SELECT score FROM attempts a WHERE a.item_id=i.id AND a.user_id=? "
                     "AND a.status='marked' ORDER BY a.id DESC LIMIT 1) AS score FROM items i WHERE i.session_id=?",
                     (uid, session_id)).fetchall()
    quick = [r for r in rows if r["qtype"] != "long"]
    written = [r for r in rows if r["qtype"] == "long"]
    right = sum(1 for r in quick if (r["score"] or 0) >= 0.999)
    tried = sum(1 for r in quick if r["score"] is not None)
    return {"questions": len(quick), "right": right, "tried": tried, "written": len(written),
            "written_done": sum(1 for r in written if r["score"] is not None)}


def progress_of(c: sqlite3.Connection, session_id: str, uid: int) -> sqlite3.Row | None:
    return c.execute("SELECT * FROM session_progress WHERE session_id=? AND user_id=?", (session_id, uid)).fetchone()


def reading_mode(c: sqlite3.Connection, course_id: str, uid: int) -> bool:
    """Reading mode: this person reads the course without questions, practice, written work or warm-ups."""
    r = c.execute("SELECT reading FROM course_prefs WHERE user_id=? AND course_id=?", (uid, course_id)).fetchone()
    return bool(r and r["reading"])


def set_reading_mode(c: sqlite3.Connection, course_id: str, uid: int, on: bool) -> None:
    c.execute("INSERT INTO course_prefs(user_id, course_id, reading) VALUES (?,?,?) "
              "ON CONFLICT(user_id, course_id) DO UPDATE SET reading=excluded.reading", (uid, course_id, 1 if on else 0))


def course_progress(c: sqlite3.Connection, course_id: str, uid: int) -> dict:
    ss = c.execute("SELECT s.id, s.state, p.done_at, p.started_at FROM sessions s LEFT JOIN session_progress p "
                   "ON p.session_id=s.id AND p.user_id=? WHERE s.course_id=? ORDER BY s.seq", (uid, course_id)).fetchall()
    done = sum(1 for s in ss if s["done_at"])
    nxt = next((s["id"] for s in ss if not s["done_at"] and s["state"] == "ready"), None)
    per = [session_progress(c, s["id"], uid) for s in ss]
    return {"sessions": len(ss), "done": done, "next": nxt,
            "answered": sum(p["tried"] for p in per), "written_done": sum(p["written_done"] for p in per),
            "due_reviews": c.execute("SELECT count(*) AS n FROM review_queue WHERE course_id=? AND user_id=? AND due_at <= ?",
                                     (course_id, uid, db.now())).fetchone()["n"]}


def opened(c: sqlite3.Connection, course_id: str, uid: int) -> None:
    c.execute("INSERT INTO course_opens(user_id, course_id, at) VALUES (?,?,?) "
              "ON CONFLICT(user_id, course_id) DO UPDATE SET at=excluded.at", (uid, course_id, db.now()))


def finish_session(c: sqlite3.Connection, session_id: str, summary: str, uid: int = db.OWNER_ID) -> None:
    s = c.execute("SELECT course_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None:
        raise Problem("That session doesn't exist.")
    now = db.now()
    c.execute("INSERT INTO session_progress(user_id, session_id, started_at, done_at, summary_note) VALUES (?,?,?,?,?) "
              "ON CONFLICT(user_id, session_id) DO UPDATE SET done_at=coalesce(done_at, excluded.done_at), "
              "summary_note=excluded.summary_note, started_at=coalesce(started_at, excluded.started_at)",
              (uid, session_id, now, now, (summary or "").strip()[:5000]))
    opened(c, s["course_id"], uid)


def reopen_session(c: sqlite3.Connection, session_id: str, uid: int = db.OWNER_ID) -> None:
    c.execute("UPDATE session_progress SET done_at=NULL WHERE session_id=? AND user_id=?", (session_id, uid))


def set_note(c: sqlite3.Connection, session_id: str, note: str, uid: int) -> None:
    if c.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is None:
        raise Problem("That session doesn't exist.")
    c.execute("INSERT INTO session_progress(user_id, session_id, note) VALUES (?,?,?) "
              "ON CONFLICT(user_id, session_id) DO UPDATE SET note=excluded.note", (uid, session_id, (note or "").strip()[:50_000]))


# ---------- ask about it ----------

HISTORY = 16


def chat_messages(c: sqlite3.Connection, course_id: str, scope: str, uid: int) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT id, role, text, created_at FROM chat_messages WHERE course_id=? AND scope=? "
                                       "AND user_id=? ORDER BY id", (course_id, scope, uid))]


def chat_context(c: sqlite3.Connection, course_id: str, scope: str, uid: int) -> str:
    course = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    plan = db.loads(course["plan_json"], {}) or {}
    if scope == "course":
        lines = [plan.get("title", course["title"]), plan.get("summary", "")]
        for s in c.execute("SELECT seq, title, topics_json FROM sessions WHERE course_id=? ORDER BY seq", (course_id,)):
            lines.append(f"{s['seq']}. {s['title']}: {', '.join(db.loads(s['topics_json'], []))}")
        return "\n".join(lines)
    item = c.execute("SELECT * FROM items WHERE id=? AND course_id=?", (scope, course_id)).fetchone()
    session_id = item["session_id"] if item else scope
    s = c.execute("SELECT * FROM sessions WHERE id=? AND course_id=?", (session_id, course_id)).fetchone()
    if s is None:
        raise Problem("Nothing to ask about there.")
    content = db.loads(s["content_json"], {}) or {}
    parts = [f"SESSION {s['seq']}: {s['title']}", content.get("goal", "")]
    for ch in content.get("chunks", []):
        parts.append(f"## {ch['title']}\n{ch['markdown']}\n{ch.get('example_markdown', '')}")
    if content.get("intro_markdown"):
        parts.append(content["intro_markdown"])
    if item:
        last = latest_attempt(c, item["id"], uid)
        parts.append(f"\nTHE QUESTION THEY'RE ASKING ABOUT:\n{item['prompt']}\nOptions: {item['options_json']}\n"
                     f"Correct/model answer: {item['answer']}\nExplanation: {item['explanation']}\n"
                     f"Rubric: {item['rubric_json']}")
        if last:
            parts.append(f"THEIR LATEST ANSWER:\n{last['answer']}\nFEEDBACK THEY GOT: {last['feedback_json']}")
    return "\n\n".join(p for p in parts if p)


def ask(c: sqlite3.Connection, course_id: str, scope: str, text: str, uid: int = db.OWNER_ID) -> None:
    text = (text or "").strip()
    if not text:
        raise Problem("Write a question first.")
    if len(text) > 4000:
        raise Problem("Keep it under 4,000 characters.")
    if chat_pending(c, course_id, scope, uid):
        raise Problem("Wait for the answer to your last question first.")
    context = chat_context(c, course_id, scope, uid)
    history = chat_messages(c, course_id, scope, uid)[-HISTORY:]
    c.execute("INSERT INTO chat_messages(course_id, scope, role, text, created_at, user_id) VALUES (?,?,?,?,?,?)",
              (course_id, scope, "learner", text, db.now(), uid))
    opts = c.execute("SELECT options_json FROM courses WHERE id=?", (course_id,)).fetchone()["options_json"]
    req = prompts.chat(_course_title(c, course_id), context, [m for m in history if m["role"] != "note"], text,
                       live=media.options_of(opts)["research"])
    jobs.enqueue(c, "chat", req, course_id=course_id, ref=scope, priority=jobs.PRIORITY_NOW, user_id=uid)


def chat_pending(c: sqlite3.Connection, course_id: str, scope: str, uid: int) -> sqlite3.Row | None:
    return c.execute("SELECT status, error FROM jobs WHERE kind='chat' AND course_id=? AND ref=? AND user_id=? "
                     "AND status IN ('queued','running','waiting') ORDER BY id DESC LIMIT 1", (course_id, scope, uid)).fetchone()


def _on_chat(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    reply = str(res.data.get("reply", "")).strip() or "(no reply)"
    names = []
    for src in res.sources:
        t = str(src.get("title") or "").strip()
        if t and t not in names:
            names.append(t)
    if names:
        reply += "\n\n*Sources looked at: " + ", ".join(names[:8]) + "*"
    if res.search_note:
        reply += "\n\n*Live research wasn't available for this answer, so it's from Gemini's own knowledge.*"
    c.execute("INSERT INTO chat_messages(course_id, scope, role, text, created_at, user_id) VALUES (?,?,?,?,?,?)",
              (job["course_id"], job["ref"], "tutor", reply, db.now(), job["user_id"] or db.OWNER_ID))


def _on_chat_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    c.execute("INSERT INTO chat_messages(course_id, scope, role, text, created_at, user_id) VALUES (?,?,?,?,?,?)",
              (job["course_id"], job["ref"], "note", f"Couldn't get an answer: {err}", db.now(), job["user_id"] or db.OWNER_ID))


jobs.handler("chat", on_failed=_on_chat_failed)(_on_chat)


# ---------- your own materials ----------

def add_material(c: sqlite3.Connection, course_id: str, name: str, data: bytes) -> None:
    name = safe_name(name)
    ext = ext_of(name)
    if ext not in MATERIAL_TYPES:
        raise Problem(f"{name}: add PDFs, images or text files (notes, code, CSV).")
    if len(data) > MAX_FILE:
        raise Problem(f"{name} is over 15 MB.")
    if not data:
        raise Problem(f"{name} is empty.")
    n = c.execute("SELECT count(*) AS n FROM materials WHERE course_id=?", (course_id,)).fetchone()["n"]
    if n >= MAX_MATERIALS:
        raise Problem(f"A course can hold {MAX_MATERIALS} materials.")
    folder = db.course_dir(course_id) / "materials"
    folder.mkdir(parents=True, exist_ok=True)
    fname, k = name, 2
    while (folder / fname).exists():
        stem, dot, e = name.rpartition(".")
        fname = f"{stem} ({k}).{e}" if dot else f"{name} ({k})"
        k += 1
    (folder / fname).write_bytes(data)
    mid = f"m{dt.datetime.now().strftime('%y%m%d%H%M%S%f')}"
    c.execute("INSERT INTO materials(id, course_id, name, mime, filename, bytes, added_at) VALUES (?,?,?,?,?,?,?)",
              (mid, course_id, name, MATERIAL_TYPES[ext], fname, len(data), db.now()))


def add_note(c: sqlite3.Connection, course_id: str, title: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        raise Problem("The note is empty.")
    title = (title or "Note").strip()[:80] or "Note"
    add_material(c, course_id, f"{title}.md", f"# {title}\n\n{text}\n".encode())


def remove_material(c: sqlite3.Connection, material_id: str) -> None:
    m = c.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
    if m is None:
        raise Problem("That material is gone.")
    p = (db.course_dir(m["course_id"]) / "materials" / m["filename"]).resolve()
    if p.is_relative_to(db.course_dir(m["course_id"]).resolve()) and p.is_file():
        p.unlink()
    c.execute("DELETE FROM materials WHERE id=?", (material_id,))
