"""The home page's order: each person's own courses (started, added or pinned) above everything else they can open,
and shared tags on courses for finding them."""
from __future__ import annotations

import re
import sqlite3

from . import db
from .pipeline import Problem

MAX_TAGS = 8
SHELVES = (None, "mine", "aside")


def clean_tags(tags) -> list[str]:
    """Lower-case, short, unique, in the order given."""
    out: list[str] = []
    for t in tags or []:
        t = re.sub(r"\s+", " ", str(t)).strip().lower().lstrip("#")[:30]
        t = "".join(ch for ch in t if ch.isalnum() or ch in " -&+'.")
        if t and t not in out:
            out.append(t)
    return out[:MAX_TAGS]


def tags_of(row) -> list[str]:
    try:
        return clean_tags(db.loads(row["tags_json"], []))
    except (IndexError, KeyError):
        return []


def set_tags(c: sqlite3.Connection, course_id: str, tags) -> list[str]:
    clean = clean_tags(tags)
    c.execute("UPDATE courses SET tags_json=? WHERE id=?", (db.dumps(clean), course_id))
    return clean


def all_tags(c: sqlite3.Connection, course_ids: list[str]) -> list[dict]:
    """Tags in use on the given courses, most used first."""
    count: dict[str, int] = {}
    for cid in course_ids:
        r = c.execute("SELECT tags_json FROM courses WHERE id=?", (cid,)).fetchone()
        for t in tags_of(r) if r else []:
            count[t] = count.get(t, 0) + 1
    return [{"tag": t, "count": n} for t, n in sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))]


def prefs(c: sqlite3.Connection, course_id: str, uid: int) -> dict:
    r = c.execute("SELECT pinned, shelf FROM course_prefs WHERE user_id=? AND course_id=?", (uid, course_id)).fetchone()
    return {"pinned": bool(r and r["pinned"]), "shelf": r["shelf"] if r else None}


def _upsert(c: sqlite3.Connection, course_id: str, uid: int, col: str, value) -> None:
    c.execute(f"INSERT INTO course_prefs(user_id, course_id, {col}) VALUES (?,?,?) "
              f"ON CONFLICT(user_id, course_id) DO UPDATE SET {col}=excluded.{col}", (uid, course_id, value))


def pin(c: sqlite3.Connection, course_id: str, uid: int, on: bool) -> None:
    _upsert(c, course_id, uid, "pinned", 1 if on else 0)
    if on:   # a pinned course is one of mine
        _upsert(c, course_id, uid, "shelf", "mine")


def shelve(c: sqlite3.Connection, course_id: str, uid: int, shelf: str | None) -> None:
    if shelf not in SHELVES:
        raise Problem("Pick mine or aside.")
    _upsert(c, course_id, uid, "shelf", shelf)
    if shelf == "aside":
        _upsert(c, course_id, uid, "pinned", 0)


def started(progress: dict) -> bool:
    return bool(progress.get("done") or progress.get("answered") or progress.get("started"))


def is_mine(p: dict, progress: dict, can_edit_draft: bool = False) -> bool:
    """Mine: pinned, added by hand, or started and not set aside. A course still being made by its author is theirs."""
    if p["pinned"] or p["shelf"] == "mine":
        return True
    if p["shelf"] == "aside":
        return False
    return started(progress) or can_edit_draft
