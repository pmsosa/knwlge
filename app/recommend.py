"""Recommending a published course to chosen people or to everyone: a nudge on their home page, no deadline.

It shows until the person starts the course (it moves to their courses) or dismisses it; a newer recommendation
of the same course shows again."""
from __future__ import annotations

import sqlite3

from . import audit, auth, db
from .pipeline import Problem

NOTE_MAX = 300


def _check(user: dict, course: sqlite3.Row) -> None:
    if auth.mode() != "team":
        raise Problem("Recommending is for team mode.")
    auth.require(user, "author")
    auth.check_view(user, course)
    if course["visibility"] != "published":
        raise Problem("Publish the course first: only published courses can be recommended.")


def people(c: sqlite3.Connection, user: dict) -> list[dict]:
    return [{"id": r["id"], "name": r["display_name"], "role": r["role"]} for r in c.execute(
        "SELECT id, display_name, role FROM users WHERE active=1 AND id<>? ORDER BY display_name COLLATE NOCASE", (user["id"],))]


def listing(c: sqlite3.Connection, course_id: str, user: dict) -> list[dict]:
    rows = c.execute("SELECT r.*, b.display_name AS by_name, t.display_name AS to_name FROM recommendations r "
                     "JOIN users b ON b.id=r.by_user LEFT JOIN users t ON t.id=r.to_user WHERE r.course_id=? "
                     "ORDER BY r.to_user IS NOT NULL, t.display_name COLLATE NOCASE", (course_id,)).fetchall()
    return [{"id": r["id"], "everyone": r["to_user"] is None, "to": r["to_name"] or "Everyone", "to_id": r["to_user"],
             "by": r["by_name"], "note": r["note"], "at": r["created_at"],
             "can_remove": r["by_user"] == user["id"] or auth.at_least(user, "admin")} for r in rows]


def create(c: sqlite3.Connection, user: dict, course: sqlite3.Row, everyone: bool, to: list[int], note: str) -> int:
    _check(user, course)
    note = " ".join((note or "").split())[:NOTE_MAX]
    targets: list[int | None]
    if everyone:
        targets = [None]
    else:
        ids = sorted({int(x) for x in to if int(x) != user["id"]})
        if not ids:
            raise Problem("Pick at least one person, or everyone.")
        found = {r["id"] for r in c.execute(f"SELECT id FROM users WHERE active=1 AND id IN ({','.join('?' * len(ids))})", ids)}
        if found != set(ids):
            raise Problem("Someone on that list isn't an active account.")
        targets = list(ids)
    now = db.now()
    for t in targets:
        # one recommendation per person (or one for everyone) per course: a new one replaces it, and shows again
        c.execute("DELETE FROM recommendations WHERE course_id=? AND to_user IS ?", (course["id"], t))
        c.execute("INSERT INTO recommendations(course_id, to_user, by_user, note, created_at) VALUES (?,?,?,?,?)",
                  (course["id"], t, user["id"], note, now))
    audit.log(c, "course.recommended", "course", course["id"], {"everyone": everyone, "to": [t for t in targets if t]})
    return len(targets)


def remove(c: sqlite3.Connection, user: dict, rec_id: int) -> str:
    r = c.execute("SELECT * FROM recommendations WHERE id=?", (rec_id,)).fetchone()
    if r is None:
        raise Problem("That recommendation is gone already.")
    if r["by_user"] != user["id"] and not auth.at_least(user, "admin"):
        raise Problem("Only whoever recommended it, or an admin, can take it back.")
    c.execute("DELETE FROM recommendations WHERE id=?", (rec_id,))
    audit.log(c, "course.unrecommended", "course", r["course_id"], {"to": r["to_user"]})
    return r["course_id"]


def for_user(c: sqlite3.Connection, uid: int) -> dict[str, dict]:
    """Course id -> the newest recommendation this person hasn't dismissed (someone else's, to them or everyone)."""
    out: dict[str, dict] = {}
    for r in c.execute("SELECT r.*, b.display_name AS by_name FROM recommendations r JOIN users b ON b.id=r.by_user "
                       "LEFT JOIN rec_dismissed d ON d.course_id=r.course_id AND d.user_id=? "
                       "WHERE (r.to_user=? OR r.to_user IS NULL) AND r.by_user<>? AND (d.at IS NULL OR r.created_at > d.at) "
                       "ORDER BY r.created_at DESC", (uid, uid, uid)):
        if r["course_id"] not in out:
            out[r["course_id"]] = {"by": r["by_name"], "note": r["note"], "at": r["created_at"],
                                   "everyone": r["to_user"] is None}
    return out


def dismiss(c: sqlite3.Connection, uid: int, course_id: str) -> None:
    c.execute("INSERT INTO rec_dismissed(user_id, course_id, at) VALUES (?,?,?) "
              "ON CONFLICT(user_id, course_id) DO UPDATE SET at=excluded.at", (uid, course_id, db.now()))
