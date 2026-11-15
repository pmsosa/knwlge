"""Drafts, review and versions for everything editable in a written course.

Four kinds of target: a part of a lesson (`chunk`, id '<session>@<gen>:<index>'), a question or exercise (`item`), a whole
session (`session`), and the course plan (`plan`, id = the course id).

- Every change that lands is a new row in `versions` (the first change also records the original), so any earlier
  version can be restored. Versions are kept forever.
- AI changes are always drafts in `changes`: the editor sees before and after and accepts or discards them (or ticks
  "publish straight away" when asking). Hand edits go live at once.
- With review switched on (an admin setting, team mode), an author changing a course that isn't theirs makes a
  draft too, and only the course's owner or an admin can accept it.
- Rewriting a whole session never deletes anything: its questions and media are archived with everyone's answers,
  and the new ones get ids of their own (`gen`). A plan change archives sessions it removes.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import audit, auth, budget, db, jobs, media, prompts
from .pipeline import Problem, _num
from .tiers import TIERS

LIMIT = 50_000
TARGETS = ("chunk", "item", "session", "plan")
OPEN = ("working", "pending")


# ---------- who may do what ----------

def review_on(c: sqlite3.Connection) -> bool:
    return auth.mode() == "team" and db.get_setting(c, "review_required") == "1"


def can_publish(c: sqlite3.Connection, user: dict, course: sqlite3.Row) -> bool:
    """Make a change live. Everyone who can edit, unless review is on: then the course's owner and admins."""
    if not auth.can_edit(user, course):
        return False
    return not review_on(c) or auth.at_least(user, "admin") or auth.owns(user, course)


def _course(c: sqlite3.Connection, course_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if row is None:
        raise Problem("That course doesn't exist.")
    return row


def _bump(c: sqlite3.Connection, course_id: str, uid: int | None) -> None:
    c.execute("UPDATE courses SET version=version+1, updated_at=?, updated_by=? WHERE id=?", (db.now(), uid, course_id))


# ---------- reading and writing each kind of target ----------

def chunk_id(session_id: str, gen: int, index: int) -> str:
    return f"{session_id}@{gen}:{index}"


def _split_chunk(tid: str) -> tuple[str, int, int]:
    try:
        sid, rest = tid.rsplit("@", 1)
        gen, idx = rest.split(":")
        return sid, int(gen), int(idx)
    except ValueError:
        raise Problem("That part of the lesson doesn't exist.") from None


def _session(c: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    s = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None:
        raise Problem("That session doesn't exist.")
    return s


def course_of(c: sqlite3.Connection, target: str, tid: str) -> str:
    if target == "plan":
        return _course(c, tid)["id"]
    if target == "item":
        r = c.execute("SELECT course_id FROM items WHERE id=?", (tid,)).fetchone()
        if r is None:
            raise Problem("That question doesn't exist.")
        return r["course_id"]
    sid = _split_chunk(tid)[0] if target == "chunk" else tid
    return _session(c, sid)["course_id"]


def current(c: sqlite3.Connection, target: str, tid: str) -> Any:
    """The live state of a target, in the shape versions store."""
    if target == "chunk":
        sid, gen, idx = _split_chunk(tid)
        s = _session(c, sid)
        chunks = (db.loads(s["content_json"], {}) or {}).get("chunks", [])
        if s["gen"] != gen or not 0 <= idx < len(chunks):
            raise Problem("That part belongs to an earlier version of the session.")
        ch = chunks[idx]
        return {"title": ch.get("title", ""), "markdown": ch.get("markdown", ""), "example_markdown": ch.get("example_markdown", "")}
    if target == "item":
        i = c.execute("SELECT * FROM items WHERE id=?", (tid,)).fetchone()
        if i is None:
            raise Problem("That question doesn't exist.")
        return {"title": i["title"], "prompt": i["prompt"], "options": db.loads(i["options_json"], []), "answer": i["answer"],
                "explanation": i["explanation"], "rubric": db.loads(i["rubric_json"], []), "qtype": i["qtype"],
                "archived": bool(i["archived"])}
    if target == "session":
        s = _session(c, tid)
        return {"gen": s["gen"], "title": s["title"], "content": db.loads(s["content_json"], {}),
                "items": [r["id"] for r in c.execute("SELECT id FROM items WHERE session_id=? AND archived=0 ORDER BY seq", (tid,))],
                "media": [r["id"] for r in c.execute("SELECT id FROM media WHERE session_id=? AND archived=0", (tid,))]}
    if target == "plan":
        co = _course(c, tid)
        return {"title": co["title"], "summary": co["summary"],
                "sessions": [{"id": s["id"], "seq": s["seq"], "kind": s["kind"], "title": s["title"], "minutes": s["minutes"],
                              "topics": db.loads(s["topics_json"], []), "objectives": db.loads(s["objectives_json"], []),
                              "archived": bool(s["archived"])}
                             for s in c.execute("SELECT * FROM sessions WHERE course_id=? ORDER BY archived, seq", (tid,))]}
    raise Problem("Unknown kind of change.")


def _clean_chunk(d: dict, old: dict) -> dict:
    md, ex = str(d.get("markdown", "")), str(d.get("example_markdown", "") or "")
    if not md.strip():
        raise Problem("A part of a lesson can't be empty.")
    if len(md) > LIMIT or len(ex) > LIMIT:
        raise Problem("That's too long for one part.")
    return {"title": str(d.get("title", "")).strip()[:200] or old.get("title", ""), "markdown": md, "example_markdown": ex}


def _clean_item(d: dict, old: dict) -> dict:
    qtype = old["qtype"]
    prompt = str(d.get("prompt", "")).strip()
    if not prompt:
        raise Problem("The question can't be empty.")
    options = [str(o).strip() for o in (d.get("options") or []) if str(o).strip()] if qtype == "mcq" else []
    answer = str(d.get("answer", "")).strip()
    if qtype == "mcq":
        if len(options) < 2:
            raise Problem("Give at least two options.")
        if answer not in options:
            match = [o for o in options if o.lower() == answer.lower()]
            if not match:
                raise Problem("The answer must be one of the options, written exactly the same.")
            answer = match[0]
    if qtype == "numeric" and _num(answer) is None:
        raise Problem("The answer to a number question must be a number.")
    rubric = old.get("rubric") or []
    if qtype == "long" and d.get("rubric"):
        rubric = [{"criterion": str(r.get("criterion", ""))[:200], "points": max(0, min(100, int(r.get("points") or 0))),
                   "description": str(r.get("description", ""))[:1000]} for r in d["rubric"][:10] if r.get("criterion")]
    title = d.get("title") if d.get("title") is not None else old.get("title", "")
    return {"title": str(title).strip()[:200], "prompt": prompt[:LIMIT], "options": options,
            "answer": answer[:LIMIT], "explanation": str(d.get("explanation", "")).strip()[:LIMIT], "rubric": rubric,
            "qtype": qtype, "archived": old.get("archived", False)}


def _write(c: sqlite3.Connection, target: str, tid: str, data: Any) -> None:
    """Put a version's data live (already checked)."""
    if target == "chunk":
        sid, gen, idx = _split_chunk(tid)
        s = _session(c, sid)
        content = db.loads(s["content_json"], {}) or {}
        chunks = content.get("chunks", [])
        if s["gen"] != gen or not 0 <= idx < len(chunks):
            raise Problem("That part belongs to an earlier version of the session.")
        chunks[idx] = {**chunks[idx], **{k: data[k] for k in ("title", "markdown", "example_markdown")}}
        c.execute("UPDATE sessions SET content_json=? WHERE id=?", (db.dumps(content), sid))
    elif target == "item":
        old = c.execute("SELECT * FROM items WHERE id=?", (tid,)).fetchone()
        if old["archived"]:
            raise Problem("That question belongs to an earlier version of its session.")
        key_changed = (old["prompt"] != data["prompt"] or db.loads(old["options_json"], []) != data["options"]
                       or old["answer"] != data["answer"])
        newest = c.execute("SELECT coalesce(max(id), 0) AS n FROM attempts").fetchone()["n"]
        c.execute("UPDATE items SET title=?, prompt=?, options_json=?, answer=?, explanation=?, rubric_json=?, "
                  "changed_at=CASE WHEN ? THEN ? ELSE changed_at END, changed_after=CASE WHEN ? THEN ? ELSE changed_after END "
                  "WHERE id=?",
                  (data["title"], data["prompt"], db.dumps(data["options"]), data["answer"], data["explanation"],
                   db.dumps(data["rubric"]), 1 if key_changed else 0, db.now(), 1 if key_changed else 0, newest, tid))
    elif target == "session":
        _restore_session(c, tid, data)
    elif target == "plan":
        _apply_plan(c, tid, data, restore=True)


# ---------- versions ----------

def _next_n(c: sqlite3.Connection, target: str, tid: str) -> int:
    return (c.execute("SELECT max(n) AS n FROM versions WHERE target=? AND target_id=?", (target, tid)).fetchone()["n"] or 0) + 1


def record(c: sqlite3.Connection, course_id: str, target: str, tid: str, data: Any, source: str, why: str = "",
           uid: int | None = None, change_id: int | None = None) -> None:
    c.execute("INSERT INTO versions(course_id, target, target_id, n, data_json, source, why, user_id, change_id, at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?)", (course_id, target, tid, _next_n(c, target, tid), db.dumps(data), source,
                                               why[:500], uid, change_id, db.now()))


def _ensure_original(c: sqlite3.Connection, course_id: str, target: str, tid: str) -> None:
    if not c.execute("SELECT 1 FROM versions WHERE target=? AND target_id=?", (target, tid)).fetchone():
        record(c, course_id, target, tid, current(c, target, tid), "original", "As first written")


def history(c: sqlite3.Connection, target: str, tid: str) -> list[dict]:
    rows = c.execute("SELECT v.*, u.display_name AS who FROM versions v LEFT JOIN users u ON u.id=v.user_id "
                     "WHERE v.target=? AND v.target_id=? ORDER BY v.n DESC", (target, tid)).fetchall()
    return [{"id": r["id"], "n": r["n"], "source": r["source"], "why": r["why"], "who": r["who"] or "", "at": r["at"],
             "data": _summary(target, db.loads(r["data_json"])), "latest": i == 0} for i, r in enumerate(rows)]


def _summary(target: str, data: Any) -> Any:
    """What the history list shows: full text for parts and questions, an outline for sessions and plans."""
    if target == "session":
        content = data.get("content") or {}
        return {"title": data.get("title"), "chunks": [ch.get("title") for ch in content.get("chunks", [])],
                "questions": len(data.get("items", []))}
    if target == "plan":
        return {"title": data.get("title"), "sessions": [f"{s['seq']}. {s['title']}" for s in data.get("sessions", [])
                                                         if not s.get("archived")]}
    return data


def course_history(c: sqlite3.Connection, course_id: str, limit: int = 200) -> list[dict]:
    rows = c.execute("SELECT v.id, v.target, v.target_id, v.n, v.source, v.why, v.at, u.display_name AS who FROM versions v "
                     "LEFT JOIN users u ON u.id=v.user_id WHERE v.course_id=? AND v.source != 'original' ORDER BY v.id DESC LIMIT ?",
                     (course_id, limit)).fetchall()
    return [{**dict(r), "where": where(c, r["target"], r["target_id"])} for r in rows]


def where(c: sqlite3.Connection, target: str, tid: str) -> str:
    """A human label for a target: 'Session 3, part 2', 'Session 3, question 4', 'Session 3', 'The plan'."""
    try:
        if target == "plan":
            return "The plan"
        if target == "item":
            i = c.execute("SELECT i.seq, i.section, s.seq AS sseq FROM items i JOIN sessions s ON s.id=i.session_id WHERE i.id=?",
                          (tid,)).fetchone()
            label = {"check": "question", "practice": "practice question", "exercise": "exercise", "project": "project option"}
            return f"Session {i['sseq']}, {label.get(i['section'], 'question')} {i['seq']}" if i else "A question"
        sid = _split_chunk(tid)[0] if target == "chunk" else tid
        s = c.execute("SELECT seq FROM sessions WHERE id=?", (sid,)).fetchone()
        base = f"Session {s['seq']}" if s else "A session"
        return f"{base}, part {_split_chunk(tid)[2] + 1}" if target == "chunk" else base
    except Problem:
        return target


def restore(c: sqlite3.Connection, user: dict, version_id: int) -> dict:
    v = c.execute("SELECT * FROM versions WHERE id=?", (version_id,)).fetchone()
    if v is None:
        raise Problem("That version doesn't exist.")
    course = _course(c, v["course_id"])
    auth.check_edit(user, course)
    data = db.loads(v["data_json"])
    if not can_publish(c, user, course):
        cid = _new_change(c, course["id"], v["target"], v["target_id"], "hand", user["id"],
                          wish=f"Go back to version {v['n']}", proposed=data)
        c.execute("UPDATE changes SET status='pending' WHERE id=?", (cid,))
        return {"applied": False, "change": cid}
    _ensure_original(c, course["id"], v["target"], v["target_id"])
    _write(c, v["target"], v["target_id"], data)
    record(c, course["id"], v["target"], v["target_id"], current(c, v["target"], v["target_id"]), "rollback",
           f"Back to version {v['n']}", user["id"])
    _bump(c, course["id"], user["id"])
    _close_flags(c, v["target"], v["target_id"], None)
    audit.log(c, "change.rolled_back", v["target"], v["target_id"], {"course": course["id"], "to_version": v["n"]})
    return {"applied": True}


# ---------- changes (drafts) ----------

def _new_change(c: sqlite3.Connection, course_id: str, target: str, tid: str, kind: str, uid: int | None, *,
                wish: str = "", proposed: Any = None, auto: bool = False, flag_id: int | None = None) -> int:
    base = current(c, target, tid)
    cur = c.execute("INSERT INTO changes(course_id, target, target_id, kind, status, wish, base_json, proposed_json, user_id, "
                    "auto_publish, flag_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (course_id, target, tid, kind, "working" if kind == "ai" else "pending", wish[:2000], db.dumps(base),
                     db.dumps(proposed) if proposed is not None else None, uid, 1 if auto else 0, flag_id, db.now()))
    return cur.lastrowid


def busy(c: sqlite3.Connection, target: str, tid: str) -> bool:
    return c.execute("SELECT 1 FROM changes WHERE target=? AND target_id=? AND status='working'", (target, tid)).fetchone() is not None


def hand_edit(c: sqlite3.Connection, user: dict, target: str, tid: str, data: dict, why: str = "") -> dict:
    """An edit typed by a person: live at once for those who can publish, otherwise a draft for review."""
    course = _course(c, course_of(c, target, tid))
    auth.check_edit(user, course)
    if target not in ("chunk", "item"):
        raise Problem("Only parts and questions are edited by hand.")
    old = current(c, target, tid)
    clean = _clean_chunk(data, old) if target == "chunk" else _clean_item(data, old)
    if not can_publish(c, user, course):
        cid = _new_change(c, course["id"], target, tid, "hand", user["id"], wish=why or "Edited by hand", proposed=clean)
        audit.log(c, "change.proposed", target, tid, {"course": course["id"], "change": cid})
        return {"applied": False, "change": cid}
    _ensure_original(c, course["id"], target, tid)
    _write(c, target, tid, clean)
    record(c, course["id"], target, tid, current(c, target, tid), "hand", why or "Edited by hand", user["id"])
    _bump(c, course["id"], user["id"])
    audit.log(c, "change.edited", target, tid, {"course": course["id"], "before": old, "after": clean})
    return {"applied": True}


def ask_ai(c: sqlite3.Connection, user: dict, target: str, tid: str, wish: str, *, mode: str = "rewrite", focus: str = "",
           publish_now: bool = False, flag_id: int | None = None) -> int:
    """Queue an AI change. It arrives as a draft (or goes live straight away if asked by someone who can publish)."""
    course = _course(c, course_of(c, target, tid))
    auth.check_edit(user, course)
    wish = (wish or "").strip()
    if not wish:
        raise Problem("Say what you'd like changed.")
    if len(wish) > 2000 or len(focus or "") > 8000:
        raise Problem("That's too long.")
    if busy(c, target, tid):
        raise Problem("The AI is already working on that.")
    budget.check_learner(c, user["id"])
    if course["status"] not in ("ready", "building"):
        raise Problem("Finish the plan first.")
    req, kind = _request(c, course, target, tid, wish, mode, focus or "")
    auto = bool(publish_now) and can_publish(c, user, course)
    cid = _new_change(c, course["id"], target, tid, "ai", user["id"], wish=(f"[add] {wish}" if mode == "add" else wish),
                      auto=auto, flag_id=flag_id)
    jobs.enqueue(c, kind, req, course_id=course["id"], ref=f"change:{cid}", priority=jobs.PRIORITY_NOW, user_id=user["id"])
    audit.log(c, "change.asked", target, tid, {"course": course["id"], "change": cid, "wish": wish[:500], "mode": mode})
    return cid


def _lesson_text(content: dict, upto: int | None = None) -> str:
    chunks = content.get("chunks", [])
    if upto is not None:
        chunks = chunks[:upto + 1]
    return "\n\n".join(f"## {ch.get('title', '')}\n{ch.get('markdown', '')}" for ch in chunks)


def _request(c: sqlite3.Connection, course: sqlite3.Row, target: str, tid: str, wish: str, mode: str, focus: str):
    live = media.options_of(course["options_json"])["research"]
    if target == "chunk":
        if mode not in ("rewrite", "add"):
            raise Problem("Choose rewrite or add.")
        sid, _gen, idx = _split_chunk(tid)
        s = _session(c, sid)
        if s["state"] != "ready":
            raise Problem("Wait until the session is ready.")
        content = db.loads(s["content_json"], {}) or {}
        current(c, target, tid)   # still the live version
        return prompts.revise_chunk(course["title"], s["title"], content.get("goal", ""), content.get("chunks", []), idx, mode,
                                    wish, focus, live=live), "revise"
    if target == "item":
        old = current(c, target, tid)
        if old["archived"]:
            raise Problem("That question belongs to an earlier version of its session.")
        i = c.execute("SELECT session_id, chunk FROM items WHERE id=?", (tid,)).fetchone()
        s = _session(c, i["session_id"])
        content = db.loads(s["content_json"], {}) or {}
        lesson = _lesson_text(content, i["chunk"]) or content.get("intro_markdown", "")
        return prompts.revise_item(course["title"], s["title"], content.get("goal", ""), old, wish, lesson, live=live), "revise_item"
    if target == "session":
        s = _session(c, tid)
        if s["state"] != "ready":
            raise Problem("Wait until the session is ready.")
        from . import pipeline
        plan = db.loads(course["plan_json"], {}) or {}
        all_s = pipeline.sessions_of(c, course["id"])
        me = next(x for x in all_s if x["id"] == tid)
        req = prompts.session(pipeline.course_dict(c, course["id"]), plan, all_s, me,
                              f"The author asked for a new version of this session. Their wishes: {wish}")
        return req, "redo_session"
    if target == "plan":
        if course["status"] != "ready":
            raise Problem("Change the plan once every session is written.")
        sessions = [s for s in current(c, "plan", tid)["sessions"] if not s["archived"]]
        return prompts.replan(course["title"], course["summary"], course["depth"], sessions, wish), "replan"
    raise Problem("Unknown kind of change.")


def change_row(c: sqlite3.Connection, change_id: int) -> sqlite3.Row:
    ch = c.execute("SELECT * FROM changes WHERE id=?", (change_id,)).fetchone()
    if ch is None:
        raise Problem("That change doesn't exist.")
    return ch


def view(c: sqlite3.Connection, ch: sqlite3.Row, user: dict | None = None) -> dict:
    """A change as the review screen shows it: what it was based on, what it proposes, and what's live now."""
    try:
        now = current(c, ch["target"], ch["target_id"])
    except Problem:
        now = None
    base = db.loads(ch["base_json"])
    who = c.execute("SELECT display_name FROM users WHERE id=?", (ch["user_id"],)).fetchone() if ch["user_id"] else None
    out = {"id": ch["id"], "target": ch["target"], "target_id": ch["target_id"], "kind": ch["kind"], "status": ch["status"],
           "wish": ch["wish"], "where": where(c, ch["target"], ch["target_id"]), "by": who["display_name"] if who else "",
           "by_me": user is not None and ch["user_id"] == user["id"], "created_at": ch["created_at"], "error": ch["error"],
           "notes": db.loads(ch["notes_json"], []), "auto_publish": bool(ch["auto_publish"]), "flag_id": ch["flag_id"],
           "stale": now is not None and base is not None and now != base and ch["status"] == "pending",
           "gone": now is None}
    proposed = db.loads(ch["proposed_json"])
    if ch["target"] == "session":
        out["before"] = _lesson_text((base or {}).get("content") or {})
        out["after"] = _lesson_text(proposed or {}) if proposed else None
        out["after_questions"] = _count_questions(proposed or {})
        out["before_questions"] = len((base or {}).get("items", []))
    elif ch["target"] == "plan":
        out["before"] = [s for s in (base or {}).get("sessions", []) if not s.get("archived")]
        out["after"] = _plan_view(base, proposed) if proposed else None
    else:
        out["before"], out["after"] = base, proposed
    return out


def _count_questions(content: dict) -> int:
    return (sum(len(ch.get("checks", [])) for ch in content.get("chunks", [])) + len(content.get("practice", []))
            + len(content.get("exercises", [])) + len(content.get("options", [])))


def _plan_view(base: dict | None, proposed: dict) -> list[dict]:
    known = {s["id"]: s for s in (base or {}).get("sessions", [])}
    out = []
    for i, s in enumerate(proposed.get("sessions", []), 1):
        old = known.get(s.get("id") or "")
        out.append({"seq": i, "id": s.get("id") or "", "kind": s.get("kind"), "title": s.get("title"), "topics": s.get("topics", []),
                    "new": old is None, "moved": bool(old and old["seq"] != i), "renamed": bool(old and old["title"] != s.get("title")),
                    "rewrite": bool(s.get("rewrite") and old)})
    kept = {s.get("id") for s in proposed.get("sessions", [])}
    for s in (base or {}).get("sessions", []):
        if not s.get("archived") and s["id"] not in kept:
            out.append({"seq": None, "id": s["id"], "kind": s["kind"], "title": s["title"], "topics": s["topics"], "removed": True})
    return out


def listing(c: sqlite3.Connection, course_id: str, user: dict, open_only: bool = True) -> list[dict]:
    q = "SELECT * FROM changes WHERE course_id=?" + (" AND status IN ('working','pending','failed')" if open_only else "")
    rows = c.execute(q + " ORDER BY id DESC LIMIT 100", (course_id,)).fetchall()
    return [view(c, r, user) for r in rows]


def open_for_session(c: sqlite3.Connection, session_id: str, user: dict) -> list[dict]:
    """Drafts and work in progress on a session, its parts and its questions (for its editors)."""
    rows = c.execute("SELECT * FROM changes WHERE status IN ('working','pending','failed') AND ("
                     "(target='session' AND target_id=?) OR (target='chunk' AND target_id LIKE ?) OR "
                     "(target='item' AND target_id IN (SELECT id FROM items WHERE session_id=?))) ORDER BY id",
                     (session_id, session_id + "@%", session_id)).fetchall()
    return [view(c, r, user) for r in rows]


def accept(c: sqlite3.Connection, user: dict | None, change_id: int, force: bool = False) -> dict:
    """Make a draft live. `user` None: the system, publishing a draft its asker said to publish straight away."""
    ch = change_row(c, change_id)
    course = _course(c, ch["course_id"])
    if user is not None:
        auth.check_edit(user, course)
        if not can_publish(c, user, course):
            raise Problem("With review switched on, the course's owner or an admin accepts changes.")
    if ch["status"] != "pending":
        raise Problem("That change isn't waiting for review.")
    proposed = db.loads(ch["proposed_json"])
    base = db.loads(ch["base_json"])
    try:
        now = current(c, ch["target"], ch["target_id"])
    except Problem:
        raise Problem("What this change was for has been replaced since. Discard it and ask again.") from None
    if now != base and not force:
        raise Problem("This has changed since the draft was made. Look again, then accept anyway or discard it.")
    uid = user["id"] if user else ch["user_id"]
    target, tid = ch["target"], ch["target_id"]
    why = ch["wish"] or "Edited"
    _ensure_original(c, course["id"], target, tid)
    if target == "session":
        _apply_session(c, tid, proposed)
    elif target == "plan":
        _apply_plan(c, tid, proposed, restore=False, uid=uid, auto=bool(ch["auto_publish"]))
    else:
        clean = _clean_chunk(proposed, now) if target == "chunk" else _clean_item(proposed, now)
        _write(c, target, tid, clean)
    record(c, course["id"], target, tid, current(c, target, tid), ch["kind"] if ch["kind"] == "ai" else "hand", why, uid, change_id)
    c.execute("UPDATE changes SET status='accepted', decided_by=?, decided_at=? WHERE id=?", (uid, db.now(), change_id))
    _bump(c, course["id"], uid)
    _close_flags(c, target, tid, change_id)
    audit.log(c, "change.accepted", target, tid, {"course": course["id"], "change": change_id, "auto": user is None}, user_id=uid)
    return {"applied": True}


def discard(c: sqlite3.Connection, user: dict, change_id: int) -> None:
    ch = change_row(c, change_id)
    course = _course(c, ch["course_id"])
    auth.check_edit(user, course)
    if ch["user_id"] != user["id"] and not can_publish(c, user, course):
        raise Problem("Only whoever asked for it, the course's owner or an admin can discard this.")
    if ch["status"] not in ("pending", "working", "failed"):
        raise Problem("That change is already decided.")
    if ch["status"] == "working":
        c.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE ref=? AND status IN ('queued','waiting')",
                  (db.now(), f"change:{change_id}"))
    c.execute("UPDATE changes SET status='discarded', decided_by=?, decided_at=? WHERE id=?", (user["id"], db.now(), change_id))
    if ch["flag_id"]:
        c.execute("UPDATE flags SET status='open', change_id=NULL WHERE id=? AND status='fixing'", (ch["flag_id"],))
    audit.log(c, "change.discarded", ch["target"], ch["target_id"], {"course": course["id"], "change": change_id})


def _close_flags(c: sqlite3.Connection, target: str, tid: str, change_id: int | None) -> None:
    """A change that lands on something learners flagged closes those flags as fixed."""
    c.execute("UPDATE flags SET status='fixed', change_id=coalesce(?, change_id), decided_at=? WHERE status IN ('open','fixing') "
              "AND ((target=? AND target_id=?) OR id IN (SELECT flag_id FROM changes WHERE id=?))",
              (change_id, db.now(), target, tid, change_id or -1))


# ---------- applying whole sessions and plans ----------

def _next_gen(c: sqlite3.Connection, session_id: str) -> int:
    rows = [db.loads(r["data_json"], {}).get("gen", 0) for r in
            c.execute("SELECT data_json FROM versions WHERE target='session' AND target_id=?", (session_id,))]
    return max(rows + [_session(c, session_id)["gen"]]) + 1


def _archive_live(c: sqlite3.Connection, session_id: str) -> None:
    c.execute("UPDATE items SET archived=1 WHERE session_id=? AND archived=0", (session_id,))
    c.execute("UPDATE media SET archived=1 WHERE session_id=? AND archived=0", (session_id,))


def _apply_session(c: sqlite3.Connection, session_id: str, content: dict) -> None:
    """A rewritten session goes live: the old questions and media are archived (answers kept), the new ones stored."""
    from . import pipeline
    s = _session(c, session_id)
    gen = _next_gen(c, session_id)
    _archive_live(c, session_id)
    c.execute("UPDATE sessions SET warnings_json='[]' WHERE id=?", (session_id,))
    pipeline.store_session(c, session_id, s["kind"], content, gen)


def _restore_session(c: sqlite3.Connection, session_id: str, data: dict) -> None:
    """Back to an earlier version: its questions and media come back from the archive (with everyone's answers)."""
    _archive_live(c, session_id)
    for iid in data.get("items", []):
        c.execute("UPDATE items SET archived=0 WHERE id=? AND session_id=?", (iid, session_id))
    for mid in data.get("media", []):
        c.execute("UPDATE media SET archived=0 WHERE id=? AND session_id=?", (mid, session_id))
    c.execute("UPDATE sessions SET content_json=?, gen=?, title=? WHERE id=?",
              (db.dumps(data.get("content") or {}), int(data.get("gen", 0)), data.get("title") or _session(c, session_id)["title"],
               session_id))


def _new_session_id(c: sqlite3.Connection, course_id: str) -> str:
    nums = [int(r["id"].rsplit("-s", 1)[1]) for r in c.execute("SELECT id FROM sessions WHERE course_id=?", (course_id,))
            if r["id"].rsplit("-s", 1)[-1].isdigit()]
    return f"{course_id}-s{(max(nums) if nums else 0) + 1:02d}"


def _apply_plan(c: sqlite3.Connection, course_id: str, data: dict, *, restore: bool, uid: int | None = None,
                auto: bool = False) -> None:
    """A new plan (from the AI, or an earlier version): sessions renamed, moved, added; removed ones archived."""
    from . import achievements, pipeline
    co = _course(c, course_id)
    existing = {r["id"]: r for r in c.execute("SELECT * FROM sessions WHERE course_id=?", (course_id,))}
    old_seq = {sid: r["seq"] for sid, r in existing.items() if not r["archived"]}
    wanted = [s for s in data.get("sessions", []) if not s.get("archived")]
    if not wanted:
        raise Problem("A plan needs at least one session.")
    if len(wanted) > 60:
        raise Problem("That's too many sessions.")
    keep: set[str] = set()
    new_ids: list[str] = []
    redo: list[str] = []
    t = TIERS[co["depth"]]
    for seq, s in enumerate(wanted, 1):
        sid = s.get("id") or ""
        title = str(s.get("title", "")).strip()[:200] or "Untitled session"
        topics = [str(x)[:200] for x in (s.get("topics") or [])][:8]
        objectives = [str(x)[:300] for x in (s.get("objectives") or [])][:5]
        if sid in existing:
            keep.add(sid)
            c.execute("UPDATE sessions SET seq=?, title=?, topics_json=?, objectives_json=?, archived=0 WHERE id=?",
                      (seq, title, db.dumps(topics), db.dumps(objectives), sid))
            if s.get("rewrite") and not restore and existing[sid]["state"] == "ready":
                redo.append(sid)
        elif restore:
            continue   # a version can only bring back sessions that still exist (archived ones do)
        else:
            kind = s.get("kind") if s.get("kind") in prompts.SESSION_KINDS else "lesson"
            minutes = max(10, min(180, int(s.get("minutes") or t["minutes"])))
            sid = _new_session_id(c, course_id)
            c.execute("INSERT INTO sessions(id, course_id, seq, kind, title, topics_json, objectives_json, minutes, state) "
                      "VALUES (?,?,?,?,?,?,?,?,?)", (sid, course_id, seq, kind, title, db.dumps(topics), db.dumps(objectives),
                                                     minutes, "pending"))
            keep.add(sid)
            new_ids.append(sid)
    for sid, r in existing.items():
        if sid not in keep and not r["archived"]:
            c.execute("UPDATE sessions SET archived=1, seq=? WHERE id=?", (1000 + r["seq"], sid))
    # themed achievements follow their session; ones whose session left the course go
    new_seq = {r["id"]: r["seq"] for r in c.execute("SELECT id, seq FROM sessions WHERE course_id=? AND archived=0", (course_id,))}
    by_old = {v: k for k, v in old_seq.items()}
    for a in c.execute("SELECT key, rule_json FROM achievements WHERE course_id=?", (course_id,)).fetchall():
        rule = db.loads(a["rule_json"], {})
        sid = by_old.get(rule.get("slot"))
        if sid in new_seq:
            rule["slot"] = new_seq[sid]
            c.execute("UPDATE achievements SET rule_json=? WHERE course_id=? AND key=?", (db.dumps(rule), course_id, a["key"]))
        else:
            c.execute("DELETE FROM achievements WHERE course_id=? AND key=?", (course_id, a["key"]))
    plan = db.loads(co["plan_json"], {}) or {}
    plan["sessions"] = [{"slot": r["seq"], "kind": r["kind"], "minutes": r["minutes"], "title": r["title"],
                         "topics": db.loads(r["topics_json"], []), "objectives": db.loads(r["objectives_json"], [])}
                        for r in c.execute("SELECT * FROM sessions WHERE course_id=? AND archived=0 ORDER BY seq", (course_id,))]
    title = str(data.get("title") or co["title"]).strip()[:200]
    summary = str(data.get("summary") if data.get("summary") is not None else co["summary"]).strip()[:2000]
    plan["title"], plan["summary"] = title, summary
    c.execute("UPDATE courses SET plan_json=?, title=?, summary=? WHERE id=?", (db.dumps(plan), title, summary, course_id))
    for sid in new_ids:
        pipeline.queue_session(c, course_id, sid)
    if new_ids:
        c.execute("UPDATE courses SET status='building' WHERE id=? AND status='ready'", (course_id,))
    for sid in redo:   # content that no longer matches its new topics: a draft rewrite each, to review
        if not busy(c, "session", sid):
            try:
                req, kind = _request(c, _course(c, course_id), "session", sid,
                                     "The plan changed: rewrite this session to teach its new topics and objectives.", "rewrite", "")
            except Problem:
                continue
            cid = _new_change(c, course_id, "session", sid, "ai", uid,
                              wish="The plan changed: rewrite this session to match its new topics", auto=auto)
            jobs.enqueue(c, kind, req, course_id=course_id, ref=f"change:{cid}", priority=jobs.PRIORITY_BUILD, user_id=uid)


# ---------- the AI's answers ----------

def _change_of(c: sqlite3.Connection, job: sqlite3.Row) -> sqlite3.Row | None:
    ref = job["ref"] or ""
    if not ref.startswith("change:"):
        return None
    ch = c.execute("SELECT * FROM changes WHERE id=?", (int(ref.split(":", 1)[1]),)).fetchone()
    return ch if ch is not None and ch["status"] == "working" else None


def _failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    ch = _change_of(c, job)
    if ch is not None:
        c.execute("UPDATE changes SET status='failed', error=? WHERE id=?", (err[:500], ch["id"]))
        if ch["flag_id"]:
            c.execute("UPDATE flags SET status='open', change_id=NULL WHERE id=? AND status='fixing'", (ch["flag_id"],))


def _ready(c: sqlite3.Connection, ch: sqlite3.Row, proposed: Any, notes: list[str]) -> None:
    c.execute("UPDATE changes SET status='pending', proposed_json=?, notes_json=? WHERE id=?",
              (db.dumps(proposed), db.dumps(notes), ch["id"]))
    if ch["auto_publish"]:
        try:
            accept(c, None, ch["id"], force=True)
        except Problem as e:   # stays a draft, with the reason
            c.execute("UPDATE changes SET notes_json=? WHERE id=?",
                      (db.dumps(notes + [f"Couldn't publish it straight away: {e}"]), ch["id"]))


def _search_note(res) -> list[str]:
    return [f"Written without live research ({res.search_note})."] if getattr(res, "search_note", "") else []


@jobs.handler("revise", on_failed=_failed)
def _on_revise(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    ch = _change_of(c, job)
    if ch is None:
        return
    d = res.data
    md = str(d.get("markdown", "")).strip()
    if not md:
        raise ValueError("the rewritten part came back empty")
    old = db.loads(ch["base_json"], {}) or {}
    proposed = {"title": str(d.get("title", "")).strip()[:200] or old.get("title", ""), "markdown": md[:LIMIT],
                "example_markdown": str(d.get("example_markdown", "")).strip()[:LIMIT]}
    _ready(c, ch, proposed, _search_note(res))


@jobs.handler("revise_item", on_failed=_failed)
def _on_revise_item(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    ch = _change_of(c, job)
    if ch is None:
        return
    old = db.loads(ch["base_json"], {}) or {}
    try:
        proposed = _clean_item(res.data, old)
    except Problem as e:
        raise ValueError(str(e)) from None
    _ready(c, ch, proposed, _search_note(res))


@jobs.handler("redo_session", on_failed=_failed)
def _on_redo_session(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    from . import pipeline
    ch = _change_of(c, job)
    if ch is None:
        return
    s = _session(c, ch["target_id"])
    content = res.data
    problems = pipeline.validate(content, s["kind"])
    tries = c.execute("SELECT count(*) AS n FROM jobs WHERE kind='redo_session' AND ref=?", (job["ref"],)).fetchone()["n"]
    if problems and tries < 2:
        req = db.loads(job["request_json"], {})
        req["prompt"] += "\n\nA reviewer found these problems in your previous draft; fix them all:\n" + "\n".join(
            f"- {p}" for p in problems)
        jobs.enqueue(c, "redo_session", req, course_id=job["course_id"], ref=job["ref"], priority=jobs.PRIORITY_NOW,
                     user_id=job["user_id"])
        return
    _ready(c, ch, content, [f"Still to fix: {p}" for p in problems] + _search_note(res))


@jobs.handler("replan", on_failed=_failed)
def _on_replan(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    ch = _change_of(c, job)
    if ch is None:
        return
    d = res.data
    base = db.loads(ch["base_json"], {}) or {}
    known = {s["id"] for s in base.get("sessions", []) if not s.get("archived")}
    sessions = []
    for s in d.get("sessions", []):
        sid = str(s.get("id") or "")
        if sid and sid not in known:
            sid = ""   # an id the model made up: treat it as a new session
        if not str(s.get("title", "")).strip():
            continue
        sessions.append({"id": sid, "kind": s.get("kind"), "title": str(s["title"]).strip()[:200],
                         "topics": [str(x)[:200] for x in (s.get("topics") or [])][:8],
                         "objectives": [str(x)[:300] for x in (s.get("objectives") or [])][:5],
                         "minutes": s.get("minutes"), "rewrite": bool(s.get("rewrite"))})
    if not sessions:
        raise ValueError("the new plan had no sessions")
    if len({s["id"] for s in sessions if s["id"]}) != len([s for s in sessions if s["id"]]):
        raise ValueError("the new plan listed a session twice")
    proposed = {"title": str(d.get("title") or base.get("title", "")).strip()[:200],
                "summary": str(d.get("summary") or base.get("summary", "")).strip()[:2000], "sessions": sessions}
    notes = [str(d["note"])[:500]] if d.get("note") else []
    removed = [s for s in base.get("sessions", []) if not s.get("archived") and s["id"] not in {x["id"] for x in sessions}]
    started = [s["title"] for s in removed if c.execute(
        "SELECT 1 FROM session_progress WHERE session_id=? UNION SELECT 1 FROM attempts a JOIN items i ON i.id=a.item_id "
        "WHERE i.session_id=? LIMIT 1", (s["id"], s["id"])).fetchone()]
    if started:
        notes.append("People have started " + ", ".join(started) + ": they keep it under Earlier sessions.")
    _ready(c, ch, proposed, notes)
