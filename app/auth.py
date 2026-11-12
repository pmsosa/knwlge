"""Accounts, sign-in and permissions.

Two modes (KNWLGE_MODE): `personal` (default) has one owner with every permission; it's open unless the owner sets a
password. `team` has accounts made by admins, each with a role (learner < author < admin), and everyone signs in.
Passwords are scrypt-hashed; a sign-in is a random token in an HttpOnly cookie, stored server-side only as a hash.
"""
from __future__ import annotations

import base64
import contextvars
import datetime as dt
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time

from . import db

COOKIE = "knwlge_session"
ROLES = ("learner", "author", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}
SESSION_IDLE_DAYS = 30
MIN_PASSWORD = 10
MAX_PASSWORD = 256

# who is acting, for job and audit attribution (set per request by the sign-in check)
actor: contextvars.ContextVar[int | None] = contextvars.ContextVar("actor", default=None)


class AuthError(Exception):
    """code: signin (not signed in), change_password (must choose a new one first), forbidden."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.status = code, status


def mode() -> str:
    return "team" if os.environ.get("KNWLGE_MODE", "personal").strip().lower() == "team" else "personal"


# ---------- passwords ----------

def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    h = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        kind, n, r, p, salt, h = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(secrets.token_hex(8))   # so unknown usernames take as long as wrong passwords


def check_new_password(pw: str, username: str = "") -> None:
    from .pipeline import Problem
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD:
        raise Problem(f"Use at least {MIN_PASSWORD} characters.")
    if len(pw) > MAX_PASSWORD:
        raise Problem("That password is too long.")
    if username and pw.strip().lower() == username.strip().lower():
        raise Problem("The password can't be the username.")


def generate_password() -> str:
    """A first password to hand over: easy to type, about 75 bits."""
    words = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
    return f"{words[:4]}-{words[4:8]}-{words[8:12]}-{words[12:16]}"


# ---------- throttling failed sign-ins (per account, in memory) ----------

_fail_lock = threading.Lock()
_fails: dict[str, tuple[int, float]] = {}   # username -> (failures in a row, locked until)


def _locked_for(username: str) -> float:
    with _fail_lock:
        n, until = _fails.get(username.lower(), (0, 0.0))
    return max(0.0, until - time.time())


def _record(username: str, ok: bool) -> None:
    key = username.lower()
    with _fail_lock:
        if ok:
            _fails.pop(key, None)
            return
        n, _ = _fails.get(key, (0, 0.0))
        n += 1
        wait = 0 if n < 5 else min(15 * 60, 30 * 2 ** (n - 5))   # 5 free tries, then 30 s, 60 s, ... up to 15 min
        _fails[key] = (n, time.time() + wait)


def reset_throttle() -> None:
    with _fail_lock:
        _fails.clear()


# ---------- sign-in sessions ----------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_in(c: sqlite3.Connection, username: str, password: str, user_agent: str = "") -> tuple[sqlite3.Row, str]:
    """Returns (user, cookie token). Raises AuthError on failure (same message for unknown user and wrong password)."""
    username = (username or "").strip()
    wait = _locked_for(username)
    if wait > 0:
        raise AuthError("throttled", f"Too many tries. Wait {int(wait) + 1} seconds and try again.", 429)
    u = c.execute("SELECT * FROM users WHERE username=? AND active=1", (username,)).fetchone()
    ok = verify_password(password or "", u["password_hash"] if u else _DUMMY) and u is not None
    _record(username, ok)
    if not ok:
        time.sleep(0.25)
        raise AuthError("signin", "That username and password don't match.", 401)
    token = secrets.token_urlsafe(32)
    now = db.now()
    c.execute("INSERT INTO login_sessions(token_hash, user_id, created_at, last_used_at, user_agent) VALUES (?,?,?,?,?)",
              (_token_hash(token), u["id"], now, now, (user_agent or "")[:200]))
    c.execute("UPDATE users SET last_seen_at=? WHERE id=?", (now, u["id"]))
    return u, token


def sign_out(c: sqlite3.Connection, token: str | None) -> None:
    if token:
        c.execute("DELETE FROM login_sessions WHERE token_hash=?", (_token_hash(token),))


def revoke_all(c: sqlite3.Connection, user_id: int, keep_token: str | None = None) -> None:
    if keep_token:
        c.execute("DELETE FROM login_sessions WHERE user_id=? AND token_hash!=?", (user_id, _token_hash(keep_token)))
    else:
        c.execute("DELETE FROM login_sessions WHERE user_id=?", (user_id,))


def _user_for_token(c: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    s = c.execute("SELECT * FROM login_sessions WHERE token_hash=?", (_token_hash(token),)).fetchone()
    if s is None:
        return None
    last = db.parse_ts(s["last_used_at"])
    now = dt.datetime.now(dt.timezone.utc)
    if last and now - last > dt.timedelta(days=SESSION_IDLE_DAYS):
        c.execute("DELETE FROM login_sessions WHERE token_hash=?", (s["token_hash"],))
        return None
    u = c.execute("SELECT * FROM users WHERE id=? AND active=1", (s["user_id"],)).fetchone()
    if u is None:
        return None
    if not last or now - last > dt.timedelta(minutes=5):   # don't write on every request
        c.execute("UPDATE login_sessions SET last_used_at=? WHERE token_hash=?", (db.now(), s["token_hash"]))
        c.execute("UPDATE users SET last_seen_at=? WHERE id=?", (db.now(), u["id"]))
    return u


def owner(c: sqlite3.Connection) -> sqlite3.Row:
    return c.execute("SELECT * FROM users WHERE id=?", (db.OWNER_ID,)).fetchone()


def needs_signin(c: sqlite3.Connection) -> bool:
    """Personal mode is open unless the owner set a password; team mode always needs a sign-in."""
    return mode() == "team" or bool(owner(c)["password_hash"])


def current(c: sqlite3.Connection, token: str | None, allow_must_change: bool = False) -> dict:
    if not needs_signin(c):
        u = owner(c)
    else:
        u = _user_for_token(c, token)
        if u is None:
            raise AuthError("signin", "Please sign in.", 401)
        if mode() == "personal" and u["id"] != db.OWNER_ID:
            raise AuthError("signin", "Please sign in.", 401)
    user = public_user(u)
    if mode() == "personal":
        user["role"] = "admin"   # the owner can do everything
    if u["must_change"] and not allow_must_change:
        raise AuthError("change_password", "Choose a new password first.", 403)
    return user


def public_user(u: sqlite3.Row) -> dict:
    return {"id": u["id"], "username": u["username"], "display_name": u["display_name"], "role": u["role"],
            "must_change": bool(u["must_change"]), "active": bool(u["active"]), "created_at": u["created_at"],
            "last_seen_at": u["last_seen_at"], "has_password": bool(u["password_hash"])}


# ---------- permissions ----------

def at_least(user: dict, role: str) -> bool:
    return RANK.get(user["role"], -1) >= RANK[role]


def require(user: dict, role: str) -> None:
    if not at_least(user, role):
        raise AuthError("forbidden", "You don't have permission to do that.", 403)


def can_view(user: dict, course: sqlite3.Row) -> bool:
    return course["visibility"] == "published" or course["author_id"] == user["id"] or at_least(user, "admin")


def can_edit(user: dict, course: sqlite3.Row) -> bool:
    return at_least(user, "admin") or (at_least(user, "author") and course["author_id"] == user["id"])


def check_view(user: dict, course: sqlite3.Row) -> None:
    if not can_view(user, course):
        # don't reveal that a draft exists
        from .pipeline import Problem
        raise Problem("That course doesn't exist.")


def check_edit(user: dict, course: sqlite3.Row) -> None:
    check_view(user, course)
    if not can_edit(user, course):
        raise AuthError("forbidden", "Only the course's author or an admin can change it.", 403)


# ---------- account management (admins, and the command line) ----------

def _clean_username(name: str) -> str:
    from .pipeline import Problem
    name = (name or "").strip()
    if not 2 <= len(name) <= 64 or not all(ch.isalnum() or ch in "._-@+" for ch in name):
        raise Problem("Usernames are 2-64 letters, digits or . _ - @ +")
    return name


def create_user(c: sqlite3.Connection, username: str, display_name: str, role: str, password: str | None) -> tuple[int, str]:
    """Returns (user id, the first password: given or generated). The user must change it at first sign-in."""
    from .pipeline import Problem
    username = _clean_username(username)
    if role not in ROLES:
        raise Problem("Pick a role: learner, author or admin.")
    if c.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise Problem("That username is taken.")
    pw = password or generate_password()
    check_new_password(pw, username)
    cur = c.execute("INSERT INTO users(username, display_name, role, password_hash, must_change, created_at) VALUES (?,?,?,?,?,?)",
                    (username, (display_name or username).strip()[:80], role, hash_password(pw), 1, db.now()))
    return cur.lastrowid, pw


def active_admins(c: sqlite3.Connection) -> int:
    return c.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1 AND password_hash IS NOT NULL").fetchone()[0]


def set_password(c: sqlite3.Connection, user_id: int, pw: str, must_change: bool) -> None:
    c.execute("UPDATE users SET password_hash=?, must_change=? WHERE id=?", (hash_password(pw), 1 if must_change else 0, user_id))
