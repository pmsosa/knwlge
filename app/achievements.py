"""Achievements: a built-in set every course has, plus 2-3 course-themed ones written with the plan.

They reward exploring and finishing, never speed or scores. The app checks them (the model never decides who earned
what): after a session is finished, an answer is sent or the tutor is asked something.
"""
from __future__ import annotations

import re
import sqlite3

from . import activity, db

RULES = ("finish_session", "practice_session", "written_session")

# key -> (title, description, icon). Checked in `_builtin_earned`.
BUILTIN = {
    "first_steps": ("First steps", "Finished your first session.", "footprints"),
    "halfway": ("Halfway there", "Finished half of the sessions.", "flag"),
    "finished": ("Course complete", "Finished every session.", "trophy"),
    "practised": ("Practice makes progress", "Tried every practice and check question.", "dumbbell"),
    "writer": ("In your own words", "Sent every written exercise.", "pen-line"),
    "warm": ("Kept it fresh", "Answered 10 questions in warm-ups.", "flame"),
    "curious": ("Curious mind", "Asked the tutor 5 questions.", "message-circle-question"),
    "notes": ("Note taker", "Wrote notes in 3 sessions.", "notebook-pen"),
}
THEMED_ICON = "sparkles"


def _key(title: str, seq: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "achievement"
    return f"c{seq}-{slug}"


def store_planned(c: sqlite3.Connection, course_id: str, planned: list[dict], slots: list[int]) -> None:
    """Replace the course's themed achievements with the plan's (each new plan draft rewrites them)."""
    c.execute("DELETE FROM achievements WHERE course_id=?", (course_id,))
    seq = 0
    for a in planned[:3]:
        title = str(a.get("title", "")).strip()[:60]
        rule = a.get("rule")
        slot = a.get("slot")
        if not title or rule not in RULES or slot not in slots:
            continue
        seq += 1
        c.execute("INSERT OR IGNORE INTO achievements(course_id, key, title, description, rule_json, seq) VALUES (?,?,?,?,?,?)",
                  (course_id, _key(title, seq), title, str(a.get("description", "")).strip()[:200],
                   db.dumps({"rule": rule, "slot": slot}), seq))


def themed(c: sqlite3.Connection, course_id: str) -> list[dict]:
    return [{"key": r["key"], "title": r["title"], "description": r["description"], "rule": db.loads(r["rule_json"], {}),
             "seq": r["seq"]} for r in c.execute("SELECT * FROM achievements WHERE course_id=? ORDER BY seq", (course_id,))]


def edit_themed(c: sqlite3.Connection, course_id: str, items: list[dict], slots: list[int]) -> None:
    """An author's edit of the course-themed list (title, description, rule, slot). Keeps keys people already earned."""
    old = {a["key"] for a in themed(c, course_id)}
    keep: set[str] = set()
    for seq, a in enumerate(items[:5], start=1):
        title = str(a.get("title", "")).strip()[:60]
        rule, slot = a.get("rule"), a.get("slot")
        if not title or rule not in RULES or slot not in slots:
            continue
        key = a.get("key") if a.get("key") in old else _key(title, seq)
        keep.add(key)
        c.execute("INSERT INTO achievements(course_id, key, title, description, rule_json, seq) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(course_id, key) DO UPDATE SET title=excluded.title, description=excluded.description, "
                  "rule_json=excluded.rule_json, seq=excluded.seq",
                  (course_id, key, title, str(a.get("description", "")).strip()[:200], db.dumps({"rule": rule, "slot": slot}), seq))
    for key in old - keep:
        c.execute("DELETE FROM achievements WHERE course_id=? AND key=?", (course_id, key))


def _sessions(c: sqlite3.Connection, course_id: str, uid: int) -> list[sqlite3.Row]:
    return c.execute("SELECT s.id, s.seq, p.done_at, p.note FROM sessions s LEFT JOIN session_progress p ON p.session_id=s.id "
                     "AND p.user_id=? WHERE s.course_id=? ORDER BY s.seq", (uid, course_id)).fetchall()


def _items(c: sqlite3.Connection, where: str, args: tuple, uid: int) -> tuple[int, int]:
    """(items, items this person has answered) for a filter on items."""
    rows = c.execute(f"SELECT i.id, EXISTS(SELECT 1 FROM attempts a WHERE a.item_id=i.id AND a.user_id=? "
                     f"AND a.status != 'failed') AS tried FROM items i WHERE {where}", (uid, *args)).fetchall()
    return len(rows), sum(1 for r in rows if r["tried"])


def _builtin_earned(c: sqlite3.Connection, course_id: str, uid: int) -> set[str]:
    ss = _sessions(c, course_id, uid)
    total, done = len(ss), sum(1 for s in ss if s["done_at"])
    got: set[str] = set()
    if done >= 1:
        got.add("first_steps")
    if total >= 2 and done * 2 >= total:
        got.add("halfway")
    if total and done == total:
        got.add("finished")
    n, tried = _items(c, "i.course_id=? AND i.qtype != 'long'", (course_id,), uid)
    if n and tried == n:
        got.add("practised")
    n, tried = _items(c, "i.course_id=? AND i.qtype = 'long'", (course_id,), uid)
    if n and tried == n:
        got.add("writer")
    if c.execute("SELECT count(*) AS n FROM attempts WHERE course_id=? AND user_id=? AND context='warmup'",
                 (course_id, uid)).fetchone()["n"] >= 10:
        got.add("warm")
    if c.execute("SELECT count(*) AS n FROM chat_messages WHERE course_id=? AND user_id=? AND role='learner'",
                 (course_id, uid)).fetchone()["n"] >= 5:
        got.add("curious")
    if sum(1 for s in ss if (s["note"] or "").strip()) >= 3:
        got.add("notes")
    return got


def _themed_earned(c: sqlite3.Connection, course_id: str, uid: int) -> set[str]:
    by_seq = {s["seq"]: s for s in _sessions(c, course_id, uid)}
    got: set[str] = set()
    for a in themed(c, course_id):
        s = by_seq.get(a["rule"].get("slot"))
        if s is None:
            continue
        rule = a["rule"].get("rule")
        if rule == "finish_session" and s["done_at"]:
            got.add(a["key"])
        elif rule in ("practice_session", "written_session"):
            where = "i.session_id=? AND i.qtype " + ("!= 'long'" if rule == "practice_session" else "= 'long'")
            n, tried = _items(c, where, (s["id"],), uid)
            if n and tried == n:
                got.add(a["key"])
    return got


def check(c: sqlite3.Connection, course_id: str, uid: int) -> list[dict]:
    """Award anything newly earned on this course. Returns the new ones (for a toast). Earned ones are kept."""
    have = {r["key"] for r in c.execute("SELECT key FROM user_achievements WHERE user_id=? AND course_id=?", (uid, course_id))}
    new = (_builtin_earned(c, course_id, uid) | _themed_earned(c, course_id, uid)) - have
    out = []
    names = {a["key"]: a for a in listing(c, course_id, uid, earned_only=False)}
    for key in sorted(new):
        c.execute("INSERT OR IGNORE INTO user_achievements(user_id, course_id, key, earned_at) VALUES (?,?,?,?)",
                  (uid, course_id, key, db.now()))
        a = names.get(key)
        if a:
            out.append(a)
            activity.record(c, uid, "achievement", course_id, {"key": key, "title": a["title"]})
    return out


def listing(c: sqlite3.Connection, course_id: str, uid: int, earned_only: bool = False) -> list[dict]:
    """Every achievement on a course, with whether (and when) this person earned it."""
    earned = {r["key"]: r["earned_at"] for r in c.execute(
        "SELECT key, earned_at FROM user_achievements WHERE user_id=? AND course_id=?", (uid, course_id))}
    out = [{"key": k, "title": t, "description": d, "icon": i, "themed": False, "earned_at": earned.get(k)}
           for k, (t, d, i) in BUILTIN.items()]
    out += [{"key": a["key"], "title": a["title"], "description": a["description"], "icon": THEMED_ICON, "themed": True,
             "earned_at": earned.get(a["key"])} for a in themed(c, course_id)]
    return [a for a in out if a["earned_at"]] if earned_only else out


def profile(c: sqlite3.Connection, uid: int, visible_course) -> list[dict]:
    """Everything this person has earned, newest first, on courses they can still open."""
    out = []
    for r in c.execute("SELECT ua.course_id, ua.key, ua.earned_at, co.title AS course_title FROM user_achievements ua "
                       "JOIN courses co ON co.id=ua.course_id WHERE ua.user_id=? ORDER BY ua.earned_at DESC", (uid,)).fetchall():
        if not visible_course(r["course_id"]):
            continue
        if r["key"] in BUILTIN:
            title, desc, icon = BUILTIN[r["key"]]
        else:
            t = c.execute("SELECT title, description FROM achievements WHERE course_id=? AND key=?",
                          (r["course_id"], r["key"])).fetchone()
            if t is None:
                continue
            title, desc, icon = t["title"], t["description"], THEMED_ICON
        out.append({"course_id": r["course_id"], "course_title": r["course_title"], "key": r["key"], "title": title,
                    "description": desc, "icon": icon, "themed": r["key"] not in BUILTIN, "earned_at": r["earned_at"]})
    return out
