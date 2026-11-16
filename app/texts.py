"""Words an admin can change: the welcome a person sees once, and the reminder under upload and send buttons."""
from __future__ import annotations

import sqlite3

from . import db
from .pipeline import Problem

WELCOME = """## Welcome to Knwlge

Courses here are written by AI and worked through at your own pace. There are no deadlines and no grades.

- **Sessions** are short: read a part, try the quick questions, and move on when you're ready.
- **Written answers** get feedback on what's good and what's missing, never a score.
- **The tutor** answers questions about what you're reading: select any text and ask.
- **Warm-ups** bring back a few things worth revisiting at the start of a session.
- **Something looks wrong?** Flag it. AI makes mistakes, and an author will take a look.
"""

UPLOAD_NOTE = ("Don't send passwords, other people's personal details or confidential work files: "
               "what you upload or type here goes to the AI provider.")

LIMITS = {"welcome_text": 4000, "upload_note": 300}
DEFAULTS = {"welcome_text": WELCOME, "upload_note": UPLOAD_NOTE}


def get(c: sqlite3.Connection, key: str) -> str:
    return db.get_setting(c, key) or DEFAULTS[key]


def put(c: sqlite3.Connection, key: str, value: str) -> bool:
    """Empty, or the same as the built-in text, goes back to the built-in text. True if it changed."""
    value = value.strip()
    if len(value) > LIMITS[key]:
        raise Problem(f"Keep it under {LIMITS[key]} characters.")
    if value == DEFAULTS[key].strip():
        value = ""
    old = db.get_setting(c, key) or ""
    db.set_setting(c, key, value or None)
    return old != value


def _prefs(c: sqlite3.Connection, uid: int) -> dict:
    r = c.execute("SELECT prefs_json FROM users WHERE id=?", (uid,)).fetchone()
    return db.loads(r["prefs_json"], {}) if r else {}


def welcomed(c: sqlite3.Connection, uid: int) -> bool:
    return bool(_prefs(c, uid).get("welcomed_at"))


def mark_welcomed(c: sqlite3.Connection, uid: int, seen: bool = True) -> None:
    prefs = _prefs(c, uid)
    if seen:
        prefs["welcomed_at"] = db.now()
    else:
        prefs.pop("welcomed_at", None)
    c.execute("UPDATE users SET prefs_json=? WHERE id=?", (db.dumps(prefs), uid))
