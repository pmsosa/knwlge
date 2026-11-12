"""Making a course: questions -> answers -> plan -> approve -> sessions written and checked, plus a reading list.

Course status: questions -> answering -> planning -> review -> building -> ready. Failures set `courses.error`
(or `sessions.error`) and leave the status alone, so Retry can pick up where it stopped.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import sqlite3

from . import auth, db, gemini, jobs, media, prompts
from .tiers import TIERS, skeleton


class Problem(Exception):
    """Something the learner should be told (shown as-is)."""


def _course_id(subject: str) -> str:
    slug = "-".join(re.findall(r"[a-z0-9]+", subject.lower()))[:40].strip("-") or "course"
    return f"{slug}-{secrets.token_hex(3)}"


def course_row(c: sqlite3.Connection, course_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if row is None:
        raise Problem("That course doesn't exist.")
    return row


def _set(c: sqlite3.Connection, course_id: str, **fields) -> None:
    fields["updated_at"] = db.now()
    cols = ", ".join(f"{k}=?" for k in fields)
    c.execute(f"UPDATE courses SET {cols} WHERE id=?", (*fields.values(), course_id))


def create(c: sqlite3.Connection, subject: str, notes: str, depth: str, options: dict | None = None) -> str:
    subject, notes = subject.strip(), notes.strip()
    if not subject:
        raise Problem("Name a subject first.")
    if len(subject) > 300 or len(notes) > 4000:
        raise Problem("That's a bit long; keep the subject short and the notes under 4,000 characters.")
    if depth not in TIERS:
        raise Problem("Pick a depth.")
    cid = _course_id(subject)
    now = db.now()
    author = auth.actor.get() or db.OWNER_ID
    # in team mode a new course is a draft until its author publishes it; personal courses are simply yours
    visibility = "draft" if auth.mode() == "team" else "published"
    c.execute("INSERT INTO courses(id, subject, notes, depth, title, status, options_json, created_at, updated_at, "
              "author_id, visibility, published_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (cid, subject, notes, depth, subject, "questions", db.dumps(media.clean_options(options)), now, now, author,
               visibility, now if visibility == "published" else None))
    c.execute("INSERT OR REPLACE INTO course_opens(user_id, course_id, at) VALUES (?,?,?)", (author, cid, now))
    db.course_dir(cid).mkdir(parents=True, exist_ok=True)
    jobs.enqueue(c, "questions", prompts.questions(subject, notes, depth), course_id=cid, priority=jobs.PRIORITY_SETUP)
    return cid


def answer(c: sqlite3.Connection, course_id: str, answers: dict) -> None:
    row = course_row(c, course_id)
    if row["status"] != "answering":
        raise Problem("This course isn't waiting for answers.")
    clean = {str(k)[:80]: str(v)[:2000] for k, v in (answers or {}).items()}
    _set(c, course_id, answers_json=db.dumps(clean), status="planning", error=None)
    _queue_plan(c, course_id)


def skip_questions(c: sqlite3.Connection, course_id: str) -> None:
    """Plan straight away without answering (the questions are optional)."""
    row = course_row(c, course_id)
    if row["status"] not in ("questions", "answering"):
        raise Problem("This course is already past the questions.")
    jobs.cancel_course(c, course_id)
    _set(c, course_id, answers_json=db.dumps({}), status="planning", error=None)
    _queue_plan(c, course_id)


def _queue_plan(c: sqlite3.Connection, course_id: str, change_request: str | None = None) -> None:
    row = course_row(c, course_id)
    req = prompts.plan(row["subject"], row["notes"], row["depth"], db.loads(row["questions_json"], []),
                       db.loads(row["answers_json"], {}), skeleton(row["depth"]), change_request,
                       db.loads(row["plan_json"]), live=media.options_of(row["options_json"])["research"])
    jobs.enqueue(c, "plan", req, course_id=course_id, priority=jobs.PRIORITY_SETUP)


def request_changes(c: sqlite3.Connection, course_id: str, text: str) -> None:
    row = course_row(c, course_id)
    text = text.strip()
    if row["status"] != "review":
        raise Problem("You can ask for changes while reviewing the plan.")
    if not text or len(text) > 2000:
        raise Problem("Say what you'd like changed (under 2,000 characters).")
    _set(c, course_id, status="planning", change_request=text, error=None)
    _queue_plan(c, course_id, text)


def approve(c: sqlite3.Connection, course_id: str) -> None:
    row = course_row(c, course_id)
    if row["status"] != "review":
        raise Problem("There's no plan waiting for approval.")
    plan = db.loads(row["plan_json"])
    slots = skeleton(row["depth"])
    c.execute("DELETE FROM sessions WHERE course_id=?", (course_id,))
    for slot, s in zip(slots, plan["sessions"]):
        c.execute("INSERT INTO sessions(id, course_id, seq, kind, title, topics_json, objectives_json, minutes) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (f"{course_id}-s{slot['slot']:02d}", course_id, slot["slot"], slot["kind"], s["title"],
                   db.dumps(s["topics"]), db.dumps(s["objectives"]), slot["minutes"]))
    _set(c, course_id, status="building", error=None)
    for s in sessions_of(c, course_id):
        queue_session(c, course_id, s["id"])
    jobs.enqueue(c, "reading", prompts.reading(course_dict(c, course_id), plan, sessions_of(c, course_id)),
                 course_id=course_id, priority=jobs.PRIORITY_LATER)


def course_dict(c: sqlite3.Connection, course_id: str) -> dict:
    row = course_row(c, course_id)
    return {"id": row["id"], "depth": row["depth"], "notes": row["notes"], "title": row["title"],
            "answers": db.loads(row["answers_json"], {}), "options": media.options_of(row["options_json"])}


def sessions_of(c: sqlite3.Connection, course_id: str) -> list[dict]:
    return [{"id": r["id"], "seq": r["seq"], "kind": r["kind"], "title": r["title"], "minutes": r["minutes"],
             "topics": db.loads(r["topics_json"], []), "objectives": db.loads(r["objectives_json"], []),
             "state": r["state"]}
            for r in c.execute("SELECT * FROM sessions WHERE course_id=? ORDER BY seq", (course_id,))]


def queue_session(c: sqlite3.Connection, course_id: str, session_id: str, feedback: str | None = None) -> None:
    row = course_row(c, course_id)
    plan = db.loads(row["plan_json"])
    all_s = sessions_of(c, course_id)
    s = next(x for x in all_s if x["id"] == session_id)
    req = prompts.session(course_dict(c, course_id), plan, all_s, s, feedback)
    c.execute("UPDATE sessions SET state='writing', error=NULL WHERE id=?", (session_id,))
    jobs.enqueue(c, "session", req, course_id=course_id, ref=session_id, priority=jobs.PRIORITY_BUILD)


def regenerate_session(c: sqlite3.Connection, session_id: str, wish: str = "") -> None:
    """Rewrite one session from scratch (its items and attempts are replaced)."""
    s = c.execute("SELECT course_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None:
        raise Problem("That session doesn't exist.")
    if c.execute("SELECT 1 FROM jobs WHERE ref=? AND kind IN ('session','check') AND status IN ('queued','running','waiting')",
                 (session_id,)).fetchone():
        raise Problem("That session is already being written.")
    wish = wish.strip()[:1000]
    queue_session(c, s["course_id"], session_id, f"The learner asked for a fresh version. Their wishes: {wish}" if wish else None)
    c.execute("UPDATE courses SET status='building' WHERE id=? AND status='ready'", (s["course_id"],))


def retry(c: sqlite3.Connection, course_id: str) -> int:
    row = course_row(c, course_id)
    n = jobs.retry_failed(c, course_id)
    c.execute("UPDATE sessions SET state='writing', error=NULL WHERE course_id=? AND state='failed'", (course_id,))
    _set(c, course_id, error=None)
    if n == 0 and row["status"] == "questions":
        jobs.enqueue(c, "questions", prompts.questions(row["subject"], row["notes"], row["depth"]), course_id=course_id,
                     priority=jobs.PRIORITY_SETUP)
        n = 1
    return n


def delete(c: sqlite3.Connection, course_id: str) -> None:
    course_row(c, course_id)
    jobs.cancel_course(c, course_id)
    c.execute("DELETE FROM courses WHERE id=?", (course_id,))
    d = db.course_dir(course_id)
    if d.is_dir():
        shutil.rmtree(d)


# ---------- storing what Gemini wrote ----------

def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def validate(content: dict, kind: str) -> list[str]:
    """Problems the app can find on its own (on top of the second reader's check)."""
    out = []
    if kind == "project":
        if not content.get("options"):
            out.append("The project has no options.")
        for i, o in enumerate(content.get("options", []), 1):
            if not o.get("rubric"):
                out.append(f"Project option {i} has no rubric.")
        return out
    qs = [(f"chunk {ci} check {qi}", q) for ci, ch in enumerate(content.get("chunks", []), 1)
          for qi, q in enumerate(ch.get("checks", []), 1)]
    qs += [(f"practice q{i}", q) for i, q in enumerate(content.get("practice", []), 1)]
    if not content.get("chunks"):
        out.append("The session has no lesson chunks.")
    for where, q in qs:
        if q["type"] == "mcq":
            if len(q.get("options", [])) < 2:
                out.append(f"{where}: a multiple-choice question needs options.")
            elif _norm(q["answer"]) not in {_norm(o) for o in q["options"]}:
                out.append(f"{where}: the answer '{q['answer']}' isn't one of the options.")
        elif q["type"] == "numeric" and _num(q["answer"]) is None:
            out.append(f"{where}: the answer '{q['answer']}' isn't a plain number.")
    for i, e in enumerate(content.get("exercises", []), 1):
        if not e.get("rubric"):
            out.append(f"exercise {i}: no rubric.")
    return out


def _num(s: str) -> float | None:
    try:
        return float(str(s).strip().replace(",", "").replace("−", "-"))
    except ValueError:
        return None


def store_session(c: sqlite3.Connection, session_id: str, kind: str, content: dict) -> None:
    """Split a written session into display content (no answers) and item rows (with answers)."""
    course_id = c.execute("SELECT course_id FROM sessions WHERE id=?", (session_id,)).fetchone()["course_id"]
    c.execute("DELETE FROM items WHERE session_id=?", (session_id,))
    c.execute("DELETE FROM reading WHERE session_id=?", (session_id,))
    seq = 0

    def add_item(section: str, qtype: str, prompt: str, *, chunk=None, title="", options=(), answer="", explanation="",
                 tolerance=0.0, rubric=(), topic="") -> str:
        nonlocal seq
        seq += 1
        iid = f"{session_id}-i{seq:02d}"
        c.execute("INSERT INTO items(id, course_id, session_id, seq, section, chunk, qtype, title, prompt, options_json, "
                  "answer, explanation, tolerance, rubric_json, topic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (iid, course_id, session_id, seq, section, chunk, qtype, title, prompt, db.dumps(list(options)),
                   str(answer), explanation, float(tolerance or 0), db.dumps(list(rubric)), topic))
        return iid

    def add_q(section: str, q: dict, chunk=None) -> str:
        return add_item(section, q["type"], q["prompt"], chunk=chunk, options=q.get("options", []) if q["type"] == "mcq" else [],
                        answer=q["answer"], explanation=q.get("explanation", ""), tolerance=q.get("tolerance", 0),
                        topic=q.get("topic", ""))

    if kind == "project":
        for o in content.get("options", []):
            add_item("project", "long", f"{o['brief_markdown']}\n\n**Hand in:** {o['deliverable']}", title=o["title"],
                     answer=o.get("model_answer", ""), rubric=o.get("rubric", []))
        display = {"goal": content.get("goal", ""), "intro_markdown": content.get("intro_markdown", ""),
                   "tips_markdown": content.get("tips_markdown", "")}
    else:
        opts = media.options_of(c.execute("SELECT options_json FROM courses WHERE id=?", (course_id,)).fetchone()["options_json"])
        notes = media.store(c, course_id, session_id, content.get("chunks", []), opts)
        if notes:
            old_w = db.loads(c.execute("SELECT warnings_json FROM sessions WHERE id=?", (session_id,)).fetchone()["warnings_json"], [])
            c.execute("UPDATE sessions SET warnings_json=? WHERE id=?", (db.dumps(old_w + notes), session_id))
        chunks = []
        for ci, ch in enumerate(content.get("chunks", [])):
            for q in ch.get("checks", []):
                add_q("check", q, chunk=ci)
            chunks.append({"title": ch["title"], "markdown": ch["markdown"], "example_markdown": ch.get("example_markdown", "")})
        for q in content.get("practice", []):
            add_q("practice", q)
        for e in content.get("exercises", []):
            add_item("exercise", "long", e["prompt"], title=e.get("title", ""), answer=e.get("model_answer", ""),
                     rubric=e.get("rubric", []))
        display = {"goal": content.get("goal", ""), "hook": content.get("hook", ""), "chunks": chunks,
                   "wrapup": content.get("wrapup", {"key_points": [], "teaser": ""})}
    c.execute("UPDATE sessions SET content_json=? WHERE id=?", (db.dumps(display), session_id))
    for r in content.get("reading", [])[:2]:
        add_reading(c, course_id, r, session_id)


def add_reading(c: sqlite3.Connection, course_id: str, r: dict, session_id: str | None = None) -> None:
    title = str(r.get("title", "")).strip()
    if not title:
        return
    c.execute("INSERT INTO reading(course_id, session_id, kind, title, creator, url, isbn, year, level, minutes, why, free, top) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (course_id, session_id, r.get("kind", "other"), title[:300], str(r.get("creator", ""))[:200],
               str(r.get("url", "")).strip()[:1000], str(r.get("isbn", "")).strip()[:20], str(r.get("year", ""))[:10],
               r.get("level", ""), r.get("minutes") or None, str(r.get("why", ""))[:500], 1 if r.get("free", True) else 0,
               1 if r.get("top") and session_id is None else 0))


def add_sources(c: sqlite3.Connection, course_id: str, session_id: str | None, res: gemini.Result) -> None:
    """Pages Gemini found with live research, kept as 'source' reading items (checked and resolved to the real page
    in the background: grounding returns Google redirect links)."""
    seen = set()
    for src in res.sources:
        uri = str(src.get("uri", "")).strip()
        if not uri.startswith("https://") or uri in seen:
            continue
        seen.add(uri)
        add_reading(c, course_id, {"kind": "source", "title": str(src.get("title") or "Source"), "url": uri, "free": True},
                    session_id)
        if len(seen) >= 10:
            break


def _refresh_course_status(c: sqlite3.Connection, course_id: str) -> None:
    left = c.execute("SELECT count(*) AS n FROM sessions WHERE course_id=? AND state!='ready'", (course_id,)).fetchone()["n"]
    if left == 0:
        c.execute("UPDATE courses SET status='ready', updated_at=? WHERE id=? AND status='building'", (db.now(), course_id))


# ---------- job handlers ----------

def _course_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    if job["course_id"]:
        _set(c, job["course_id"], error=f"{job['kind'].capitalize()} step failed: {err}")


@jobs.handler("questions", on_failed=_course_failed)
def _on_questions(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    qs = [q for q in res.data.get("questions", []) if q.get("id") and q.get("text")][:8]
    row = course_row(c, job["course_id"])
    if row["status"] != "questions":
        return  # skipped meanwhile
    _set(c, job["course_id"], questions_json=db.dumps(qs), status="answering")


@jobs.handler("plan", on_failed=_course_failed)
def _on_plan(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    row = course_row(c, job["course_id"])
    slots = skeleton(row["depth"])
    plan = res.data
    by_slot = {s.get("slot"): s for s in plan.get("sessions", [])}
    sessions = []
    for i, slot in enumerate(slots):
        s = by_slot.get(slot["slot"]) or (plan["sessions"][i] if i < len(plan.get("sessions", [])) else None)
        if not s or not s.get("title"):
            raise ValueError(f"the plan left session {slot['slot']} empty")
        sessions.append({"slot": slot["slot"], "kind": slot["kind"], "minutes": slot["minutes"], "title": s["title"][:200],
                         "topics": s.get("topics", [])[:8], "objectives": s.get("objectives", [])[:5]})
    plan["sessions"] = sessions
    _set(c, job["course_id"], plan_json=db.dumps(plan), title=plan.get("title") or row["subject"],
         summary=plan.get("summary", ""), status="review", change_request=None)


def _rewrites(c: sqlite3.Connection, session_id: str) -> int:
    return c.execute("SELECT count(*) AS n FROM jobs WHERE kind='session' AND ref=?", (session_id,)).fetchone()["n"]


def _session_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    c.execute("UPDATE sessions SET state='failed', error=? WHERE id=?", (err, job["ref"]))


@jobs.handler("session", on_failed=_session_failed)
def _on_session(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    s = c.execute("SELECT * FROM sessions WHERE id=?", (job["ref"],)).fetchone()
    if s is None:
        return
    content = res.data
    problems = validate(content, s["kind"])
    if problems and _rewrites(c, s["id"]) < 2:
        queue_session(c, s["course_id"], s["id"], "\n".join(f"- {p}" for p in problems))
        return
    c.execute("UPDATE sessions SET warnings_json='[]' WHERE id=?", (s["id"],))
    store_session(c, s["id"], s["kind"], content)   # may note media it left out
    add_sources(c, s["course_id"], s["id"], res)
    if res.search_note:
        problems = problems + [f"Live research wasn't available, so this session was written from Gemini's own knowledge "
                               f"({res.search_note})."]
    # a second draft that still has problems the app can see is kept, but says so
    warnings = db.loads(c.execute("SELECT warnings_json FROM sessions WHERE id=?", (s["id"],)).fetchone()["warnings_json"], []) + problems
    c.execute("UPDATE sessions SET state='checking', warnings_json=? WHERE id=?", (db.dumps(warnings), s["id"]))
    row = course_row(c, s["course_id"])
    jobs.enqueue(c, "check", prompts.check(row["title"], dict(s), _for_check(content)), course_id=s["course_id"],
                 ref=s["id"], priority=jobs.PRIORITY_BUILD)


def _for_check(content: dict) -> dict:
    """The second reader checks the teaching, not media code: long code is trimmed to keep the call small."""
    out = json.loads(json.dumps(content))
    for ch in out.get("chunks", []):
        for m in ch.get("media", []) or []:
            if len(m.get("code", "")) > 400:
                m["code"] = m["code"][:400] + " …(trimmed)"
    return out


def _check_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    # the check is a bonus: if it can't run, the session is still usable
    c.execute("UPDATE sessions SET state='ready', warnings_json=? WHERE id=?",
              (db.dumps([f"The second read-through couldn't run: {err}"]), job["ref"]))
    _refresh_course_status(c, job["course_id"])


@jobs.handler("check", on_failed=_check_failed)
def _on_check(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    s = c.execute("SELECT * FROM sessions WHERE id=?", (job["ref"],)).fetchone()
    if s is None:
        return
    issues = res.data.get("issues", [])
    major = [i for i in issues if i.get("severity") == "major"]
    if major and _rewrites(c, s["id"]) < 2:
        queue_session(c, s["course_id"], s["id"], "\n".join(f"- {i['where']}: {i['problem']}" for i in major))
        return
    warnings = db.loads(s["warnings_json"], []) + [f"{i['where']}: {i['problem']}" for i in major]
    c.execute("UPDATE sessions SET state='ready', warnings_json=? WHERE id=?", (db.dumps(warnings), s["id"]))
    _refresh_course_status(c, s["course_id"])


@jobs.handler("reading")
def _on_reading(c: sqlite3.Connection, job: sqlite3.Row, res: gemini.Result) -> None:
    c.execute("DELETE FROM reading WHERE course_id=? AND session_id IS NULL", (job["course_id"],))
    items = res.data.get("items", [])
    if items and not any(i.get("top") for i in items):
        items[0]["top"] = True
    for r in items[:20]:
        add_reading(c, job["course_id"], r)
