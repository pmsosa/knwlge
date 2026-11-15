"""Learners flag what looks wrong: a part of a lesson, a question or its answer key, feedback they got, or a reading
item. Each flag gets a cheap AI second look straight away; the course's editors see a queue sorted by that verdict and
turn a confirmed flag into a fix (an AI draft to review, a re-mark, or taking a reading item out), or dismiss it with a
reply. The person who flagged sees what happened on their account page."""
from __future__ import annotations

import datetime as dt
import sqlite3

from . import audit, auth, changes, db, jobs, learning, prompts
from .pipeline import Problem

TARGETS = ("chunk", "item", "feedback", "reading")
PER_DAY = 30


def _course(c: sqlite3.Connection, course_id: str) -> sqlite3.Row:
    row = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if row is None:
        raise Problem("That course doesn't exist.")
    return row


def _what(c: sqlite3.Connection, target: str, tid: str, uid: int) -> tuple[str, str, str]:
    """(course id, what it is in words, its content for the second look). Checks it exists and is this person's to flag."""
    if target == "chunk":
        sid = changes._split_chunk(tid)[0]
        data = changes.current(c, "chunk", tid)
        course_id = changes._session(c, sid)["course_id"]
        return course_id, "part of a lesson", f"# {data['title']}\n\n{data['markdown']}\n\n{data['example_markdown']}".strip()
    if target == "item":
        i = c.execute("SELECT * FROM items WHERE id=? AND archived=0", (tid,)).fetchone()
        if i is None:
            raise Problem("That question doesn't exist.")
        opts = db.loads(i["options_json"], [])
        body = (f"Question ({i['qtype']}): {i['prompt']}\n" + (f"Options: {' | '.join(opts)}\n" if opts else "")
                + f"Answer key: {i['answer']}\nExplanation: {i['explanation']}")
        return i["course_id"], "question and its answer key", body
    if target == "feedback":
        a = c.execute("SELECT a.*, i.prompt, i.answer AS key, i.rubric_json, i.qtype FROM attempts a JOIN items i ON i.id=a.item_id "
                      "WHERE a.id=?", (int(tid) if str(tid).isdigit() else -1,)).fetchone()
        if a is None or a["user_id"] != uid or a["status"] != "marked" or a["qtype"] not in ("short", "long"):
            raise Problem("You can flag feedback on your own written answers.")
        return a["course_id"], "feedback on an answer", (
            f"Question: {a['prompt']}\nModel answer: {a['key']}\nRubric: {a['rubric_json']}\n"
            f"The learner's answer: {a['answer']}\nThe feedback they got (JSON): {a['feedback_json']}")
    if target == "reading":
        r = c.execute("SELECT * FROM reading WHERE id=?", (int(tid) if str(tid).isdigit() else -1,)).fetchone()
        if r is None or r["status"] != "verified":
            raise Problem("That reading item doesn't exist.")
        return r["course_id"], "further-reading suggestion", (
            f"{r['kind']}: {r['title']} by {r['creator']} ({r['year']}). Link: {r['url']}\nWhy it's suggested: {r['why']}")
    raise Problem("You can flag a part of a lesson, a question, feedback or a reading item.")


def create(c: sqlite3.Connection, user: dict, target: str, tid: str, note: str) -> int:
    if target not in TARGETS:
        raise Problem("You can flag a part of a lesson, a question, feedback or a reading item.")
    note = (note or "").strip()
    if len(note) > 2000:
        raise Problem("Keep the note under 2,000 characters.")
    course_id, what, content = _what(c, target, str(tid), user["id"])
    auth.check_view(user, _course(c, course_id))
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    if c.execute("SELECT count(*) AS n FROM flags WHERE user_id=? AND created_at >= ?", (user["id"], since)).fetchone()["n"] >= PER_DAY:
        raise Problem("That's a lot of flags for one day. Thank you! Try again tomorrow.")
    if c.execute("SELECT 1 FROM flags WHERE user_id=? AND target=? AND target_id=? AND status IN ('checking','open','fixing')",
                 (user["id"], target, str(tid))).fetchone():
        raise Problem("You've already flagged this. It's being looked at.")
    cur = c.execute("INSERT INTO flags(course_id, user_id, target, target_id, note, status, created_at) VALUES (?,?,?,?,?,?,?)",
                    (course_id, user["id"], target, str(tid), note, "checking", db.now()))
    fid = cur.lastrowid
    title = _course(c, course_id)["title"]
    jobs.enqueue(c, "flag_check", prompts.flag_check(title, what, content, note), course_id=course_id, ref=f"flag:{fid}",
                 priority=jobs.PRIORITY_NOW, user_id=user["id"])
    audit.log(c, "flag.created", target, str(tid), {"course": course_id, "flag": fid, "note": note[:500]})
    return fid


def _flag(c: sqlite3.Connection, job: sqlite3.Row) -> sqlite3.Row | None:
    ref = job["ref"] or ""
    return c.execute("SELECT * FROM flags WHERE id=?", (int(ref.split(":", 1)[1]),)).fetchone() if ref.startswith("flag:") else None


def _check_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    f = _flag(c, job)
    if f is not None and f["status"] == "checking":
        c.execute("UPDATE flags SET status='open', verdict='unsure', reason=? WHERE id=?",
                  (f"The AI couldn't take a second look: {err[:200]}", f["id"]))


@jobs.handler("flag_check", on_failed=_check_failed)
def _on_check(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    f = _flag(c, job)
    if f is None or f["status"] != "checking":
        return
    d = res.data
    verdict = d.get("verdict") if d.get("verdict") in ("right", "wrong", "unsure") else "unsure"
    c.execute("UPDATE flags SET status='open', verdict=?, reason=?, suggestion=? WHERE id=?",
              (verdict, str(d.get("reason", ""))[:1000], str(d.get("suggestion", ""))[:2000], f["id"]))


def _where(c: sqlite3.Connection, f: sqlite3.Row) -> str:
    if f["target"] in ("chunk", "item"):
        return changes.where(c, f["target"], f["target_id"])
    if f["target"] == "feedback":
        a = c.execute("SELECT item_id FROM attempts WHERE id=?", (int(f["target_id"]),)).fetchone()
        return "Feedback on " + (changes.where(c, "item", a["item_id"]).lower() if a else "an answer")
    r = c.execute("SELECT title FROM reading WHERE id=?", (int(f["target_id"]),)).fetchone()
    return f"Further reading: {r['title']}" if r else "Further reading"


def _session_of(c: sqlite3.Connection, f: sqlite3.Row) -> str | None:
    try:
        if f["target"] == "chunk":
            return changes._split_chunk(f["target_id"])[0]
        if f["target"] == "item":
            r = c.execute("SELECT session_id FROM items WHERE id=?", (f["target_id"],)).fetchone()
            return r["session_id"] if r else None
        if f["target"] == "feedback":
            r = c.execute("SELECT i.session_id FROM attempts a JOIN items i ON i.id=a.item_id WHERE a.id=?",
                          (int(f["target_id"]),)).fetchone()
            return r["session_id"] if r else None
    except Problem:
        return None
    return None


def view(c: sqlite3.Connection, f: sqlite3.Row, for_editor: bool) -> dict:
    out = {"id": f["id"], "target": f["target"], "target_id": f["target_id"], "status": f["status"], "verdict": f["verdict"],
           "reason": f["reason"], "suggestion": f["suggestion"] if for_editor else "", "reply": f["reply"], "note": f["note"],
           "created_at": f["created_at"], "decided_at": f["decided_at"], "where": _where(c, f), "session_id": _session_of(c, f),
           "course_id": f["course_id"], "change_id": f["change_id"]}
    if for_editor:
        u = c.execute("SELECT display_name FROM users WHERE id=?", (f["user_id"],)).fetchone()
        out["by"] = u["display_name"] if u else ""
    return out


ORDER = "CASE f.status WHEN 'open' THEN 0 WHEN 'checking' THEN 1 WHEN 'fixing' THEN 2 ELSE 3 END, " \
        "CASE f.verdict WHEN 'wrong' THEN 0 WHEN 'unsure' THEN 1 ELSE 2 END, f.id DESC"


def for_course(c: sqlite3.Connection, course_id: str, include_closed: bool = False) -> list[dict]:
    q = "SELECT f.* FROM flags f WHERE f.course_id=?" + ("" if include_closed else " AND f.status IN ('checking','open','fixing')")
    return [view(c, f, True) for f in c.execute(q + f" ORDER BY {ORDER} LIMIT 200", (course_id,)).fetchall()]


def mine(c: sqlite3.Connection, uid: int) -> list[dict]:
    out = []
    for f in c.execute("SELECT f.*, co.title AS course_title FROM flags f JOIN courses co ON co.id=f.course_id "
                       "WHERE f.user_id=? ORDER BY f.id DESC LIMIT 100", (uid,)).fetchall():
        out.append({**view(c, f, False), "course_title": f["course_title"]})
    return out


def open_count(c: sqlite3.Connection, course_id: str) -> int:
    return c.execute("SELECT count(*) AS n FROM flags WHERE course_id=? AND status IN ('checking','open')",
                     (course_id,)).fetchone()["n"]


def _editable_flag(c: sqlite3.Connection, user: dict, flag_id: int) -> tuple[sqlite3.Row, sqlite3.Row]:
    f = c.execute("SELECT * FROM flags WHERE id=?", (flag_id,)).fetchone()
    if f is None:
        raise Problem("That flag doesn't exist.")
    course = _course(c, f["course_id"])
    auth.check_edit(user, course)
    return f, course


def dismiss(c: sqlite3.Connection, user: dict, flag_id: int, reply: str = "") -> None:
    f, _ = _editable_flag(c, user, flag_id)
    if f["status"] in ("dismissed", "fixed"):
        raise Problem("That flag is already closed.")
    c.execute("UPDATE flags SET status='dismissed', reply=?, decided_by=?, decided_at=? WHERE id=?",
              ((reply or "").strip()[:1000], user["id"], db.now(), flag_id))
    audit.log(c, "flag.dismissed", f["target"], f["target_id"], {"course": f["course_id"], "flag": flag_id})


def fixed_by_hand(c: sqlite3.Connection, user: dict, flag_id: int, reply: str = "") -> None:
    f, _ = _editable_flag(c, user, flag_id)
    c.execute("UPDATE flags SET status='fixed', reply=?, decided_by=?, decided_at=? WHERE id=?",
              ((reply or "").strip()[:1000], user["id"], db.now(), flag_id))
    audit.log(c, "flag.fixed", f["target"], f["target_id"], {"course": f["course_id"], "flag": flag_id})


def fix(c: sqlite3.Connection, user: dict, flag_id: int, wish: str = "") -> dict:
    """One click from a confirmed flag to a fix: an AI draft for a part or question, a re-mark for feedback, or taking a
    reading suggestion out."""
    f, course = _editable_flag(c, user, flag_id)
    if f["status"] not in ("open",):
        raise Problem("That flag isn't open.")
    if f["target"] in ("chunk", "item"):
        ask = (wish or "").strip() or (
            f"A learner flagged this as wrong: {f['note'] or '(no note)'}. A second look found: {f['reason']} "
            + (f"Suggested fix: {f['suggestion']}" if f["suggestion"] else "Fix what's wrong and keep the rest."))
        cid = changes.ask_ai(c, user, f["target"], f["target_id"], ask[:2000], flag_id=flag_id)
        c.execute("UPDATE flags SET status='fixing', change_id=? WHERE id=?", (cid, flag_id))
        return {"change": cid}
    if f["target"] == "feedback":
        learning.remark(c, int(f["target_id"]))
        c.execute("UPDATE flags SET status='fixed', reply=?, decided_by=?, decided_at=? WHERE id=?",
                  ("Your answer is being marked again.", user["id"], db.now(), flag_id))
        audit.log(c, "flag.fixed", "feedback", f["target_id"], {"course": f["course_id"], "flag": flag_id, "how": "remark"})
        return {"remarked": True}
    c.execute("UPDATE reading SET status='dropped', verify_note=? WHERE id=?",
              ("Taken out after a learner flagged it.", int(f["target_id"])))
    c.execute("UPDATE flags SET status='fixed', reply=?, decided_by=?, decided_at=? WHERE id=?",
              ("Taken off the reading list. Thanks!", user["id"], db.now(), flag_id))
    audit.log(c, "flag.fixed", "reading", f["target_id"], {"course": f["course_id"], "flag": flag_id, "how": "dropped"})
    return {"dropped": True}
