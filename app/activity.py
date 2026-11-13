"""The opt-in activity feed (team mode): "Sam finished session 4 of Watercolour Basics".

Nothing is recorded for someone who hasn't turned sharing on, so switching it on later never exposes the past.
An admin can turn the feed off for everyone; then nothing is recorded or shown.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from . import auth, db

KINDS = ("session_done", "course_done", "achievement")
KEEP_DAYS = 90


def feed_on(c: sqlite3.Connection) -> bool:
    return auth.mode() == "team" and db.get_setting(c, "feed_off") != "1"


def sharing(c: sqlite3.Connection, uid: int) -> bool:
    r = c.execute("SELECT prefs_json FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and db.loads(r["prefs_json"], {}).get("share_activity"))


def set_sharing(c: sqlite3.Connection, uid: int, on: bool) -> None:
    r = c.execute("SELECT prefs_json FROM users WHERE id=?", (uid,)).fetchone()
    prefs = db.loads(r["prefs_json"], {}) if r else {}
    prefs["share_activity"] = bool(on)
    c.execute("UPDATE users SET prefs_json=? WHERE id=?", (db.dumps(prefs), uid))
    if not on:   # stopping sharing takes what was shared off the feed too
        c.execute("DELETE FROM activity WHERE user_id=?", (uid,))


def record(c: sqlite3.Connection, uid: int, kind: str, course_id: str | None, details: dict) -> None:
    if kind not in KINDS or not feed_on(c) or not sharing(c, uid):
        return
    if course_id:   # only published courses appear: a draft is the author's business
        r = c.execute("SELECT visibility FROM courses WHERE id=?", (course_id,)).fetchone()
        if not r or r["visibility"] != "published":
            return
    c.execute("INSERT INTO activity(at, user_id, kind, course_id, details_json) VALUES (?,?,?,?,?)",
              (db.now(), uid, kind, course_id, db.dumps(details)))


def feed(c: sqlite3.Connection, viewer: dict, limit: int = 50) -> list[dict]:
    if not feed_on(c):
        return []
    rows = c.execute("SELECT a.*, u.display_name, u.prefs_json, u.active, co.title AS course_title, co.visibility FROM activity a "
                     "JOIN users u ON u.id=a.user_id LEFT JOIN courses co ON co.id=a.course_id ORDER BY a.id DESC LIMIT ?",
                     (limit * 2,)).fetchall()
    out = []
    for r in rows:
        if not r["active"] or not db.loads(r["prefs_json"], {}).get("share_activity"):
            continue
        if r["course_id"] and r["visibility"] != "published":
            continue
        out.append({"id": r["id"], "at": r["at"], "kind": r["kind"], "user_id": r["user_id"], "who": r["display_name"],
                    "me": r["user_id"] == viewer["id"], "course_id": r["course_id"], "course_title": r["course_title"] or "",
                    "details": db.loads(r["details_json"], {})})
        if len(out) >= limit:
            break
    return out


def prune(c: sqlite3.Connection) -> None:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=KEEP_DAYS)
    c.execute("DELETE FROM activity WHERE at < ?", (cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z"),))
