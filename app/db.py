"""SQLite storage. One file under the data folder; a fresh connection per unit of work (WAL mode)."""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 4

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS courses (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    depth TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    -- questions -> answering -> planning -> review -> building -> ready
    status TEXT NOT NULL,
    error TEXT,
    questions_json TEXT,
    answers_json TEXT,
    plan_json TEXT,
    change_request TEXT,
    options_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- lesson | review | checkpoint | project | wrapup
    title TEXT NOT NULL,
    topics_json TEXT NOT NULL DEFAULT '[]',
    objectives_json TEXT NOT NULL DEFAULT '[]',
    minutes INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',   -- pending | writing | checking | ready | failed
    content_json TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    note TEXT NOT NULL DEFAULT '',
    summary_note TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    done_at TEXT
);
CREATE INDEX IF NOT EXISTS sessions_course ON sessions(course_id, seq);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    section TEXT NOT NULL,         -- check | practice | exercise | project
    chunk INTEGER,                 -- for check questions: which chunk they follow
    qtype TEXT NOT NULL,           -- mcq | numeric | short | long
    title TEXT NOT NULL DEFAULT '',
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '[]',
    answer TEXT NOT NULL DEFAULT '',
    explanation TEXT NOT NULL DEFAULT '',
    tolerance REAL NOT NULL DEFAULT 0,
    rubric_json TEXT NOT NULL DEFAULT '[]',
    topic TEXT NOT NULL DEFAULT '',
    revealed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_session ON items(session_id, seq);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    files_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,          -- marked | queued | failed
    score REAL,                    -- 0..1 once marked
    feedback_json TEXT,
    context TEXT NOT NULL DEFAULT 'session'   -- session | warmup
);
CREATE INDEX IF NOT EXISTS attempts_item ON attempts(item_id, id);

CREATE TABLE IF NOT EXISTS review_queue (
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL,
    due_at TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 1,
    misses INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT,
    PRIMARY KEY (user_id, item_id)
);

-- ---------- people (schema v3) ----------
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,               -- admin | author | learner
    password_hash TEXT,               -- NULL: no password (the personal-mode owner, open)
    must_change INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    prefs_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE IF NOT EXISTS login_sessions (
    token_hash TEXT PRIMARY KEY,      -- sha256 of the cookie value; the value itself is never stored
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    cost_usd REAL
);
CREATE INDEX IF NOT EXISTS audit_at ON audit_log(at);

CREATE TABLE IF NOT EXISTS session_progress (
    user_id INTEGER NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    started_at TEXT,
    done_at TEXT,
    summary_note TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, session_id)
);

CREATE TABLE IF NOT EXISTS course_opens (
    user_id INTEGER NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id)
);

-- per person and course: Reading mode hides questions, practice, written work and warm-ups (they still exist)
CREATE TABLE IF NOT EXISTS course_prefs (
    user_id INTEGER NOT NULL,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    reading INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, course_id)
);

CREATE TABLE IF NOT EXISTS item_reveals (
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    filename TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reading (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    session_id TEXT,
    kind TEXT NOT NULL,            -- book | video | article | course | podcast | other
    title TEXT NOT NULL,
    creator TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    isbn TEXT NOT NULL DEFAULT '',
    year TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT '',
    minutes INTEGER,
    why TEXT NOT NULL DEFAULT '',
    free INTEGER NOT NULL DEFAULT 1,
    top INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | verified | dropped
    verify_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,           -- 'course', a session id or an item id
    role TEXT NOT NULL,            -- learner | tutor | note
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id TEXT,
    kind TEXT NOT NULL,
    ref TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | waiting | done | failed | cancelled
    attempts INTEGER NOT NULL DEFAULT 0,
    request_json TEXT NOT NULL,
    result_json TEXT,
    error TEXT,
    wait_reason TEXT,
    next_attempt_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, priority, id);

CREATE TABLE IF NOT EXISTS media (
    id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    chunk INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,            -- mermaid | svg | image | illustration | video | audio | widget | experiment
    caption TEXT NOT NULL DEFAULT '',
    spec_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | working | ready | failed
    file TEXT,                     -- relative to the course folder
    mime TEXT,
    credit TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    error TEXT
);
CREATE INDEX IF NOT EXISTS media_session ON media(session_id, chunk, seq);

CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER,
    course_id TEXT,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    thinking_tokens INTEGER NOT NULL DEFAULT 0,
    search_queries INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    outcome TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS llm_calls_at ON llm_calls(at);
"""


def data_dir() -> Path:
    return Path(os.environ.get("KNWLGE_DATA", "data"))


def db_path() -> Path:
    return data_dir() / "knwlge.db"


def course_dir(course_id: str) -> Path:
    """Folder for one course's files. Ids are generated by the app (letters, digits, dashes) and checked here too."""
    if not course_id or not all(c.isalnum() or c == "-" for c in course_id):
        raise ValueError("bad course id")
    return data_dir() / "courses" / course_id


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def connect() -> sqlite3.Connection:
    db_path().parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path(), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """A connection inside one transaction (committed on success, rolled back on error)."""
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


OWNER_ID = 1   # the personal-mode owner; existing single-user data belongs to this account


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _backup_before(conn: sqlite3.Connection, version: int) -> Path | None:
    """A full copy of the database before a schema upgrade (only when there is something to lose)."""
    if not conn.execute("SELECT count(*) FROM sqlite_master WHERE name='courses'").fetchone()[0]:
        return None
    if not conn.execute("SELECT count(*) FROM courses").fetchone()[0]:
        return None
    folder = data_dir() / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"knwlge-v{version}-before-upgrade-{stamp}.db"
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def _migrate_to_v3(conn: sqlite3.Connection) -> None:
    """Single-user data becomes the owner's (user 1): progress, notes, reveals, chats and authorship."""
    now_s = now()
    conn.execute("INSERT OR IGNORE INTO users(id, username, display_name, role, created_at) VALUES (?,?,?,?,?)",
                 (OWNER_ID, "owner", "Me", "admin", now_s))
    for table, col, ddl in (
        ("attempts", "user_id", f"INTEGER NOT NULL DEFAULT {OWNER_ID}"),
        ("chat_messages", "user_id", f"INTEGER NOT NULL DEFAULT {OWNER_ID}"),
        ("jobs", "user_id", "INTEGER"),
        ("llm_calls", "user_id", "INTEGER"),
        ("courses", "author_id", f"INTEGER NOT NULL DEFAULT {OWNER_ID}"),
        ("courses", "visibility", "TEXT NOT NULL DEFAULT 'published'"),   # draft | published
        ("courses", "published_at", "TEXT"),
    ):
        if col not in _cols(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    if "user_id" not in _cols(conn, "review_queue"):
        conn.execute("ALTER TABLE review_queue RENAME TO review_queue_v2")
        conn.execute("""CREATE TABLE review_queue (
            user_id INTEGER NOT NULL, item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE, course_id TEXT NOT NULL,
            due_at TEXT NOT NULL, interval_days REAL NOT NULL DEFAULT 1, misses INTEGER NOT NULL DEFAULT 0, last_seen_at TEXT,
            PRIMARY KEY (user_id, item_id))""")
        conn.execute(f"INSERT INTO review_queue SELECT {OWNER_ID}, item_id, course_id, due_at, interval_days, misses, last_seen_at "
                     "FROM review_queue_v2")
        conn.execute("DROP TABLE review_queue_v2")
    # per-person state that used to live on shared rows (the old columns stay, unused)
    conn.execute(f"""INSERT OR IGNORE INTO session_progress(user_id, session_id, started_at, done_at, summary_note, note)
        SELECT {OWNER_ID}, id, started_at, done_at, summary_note, note FROM sessions
        WHERE started_at IS NOT NULL OR done_at IS NOT NULL OR summary_note != '' OR note != ''""")
    conn.execute(f"INSERT OR IGNORE INTO item_reveals(user_id, item_id, at) SELECT {OWNER_ID}, id, ? FROM items WHERE revealed=1", (now_s,))
    conn.execute(f"INSERT OR IGNORE INTO course_opens(user_id, course_id, at) SELECT {OWNER_ID}, id, last_opened_at FROM courses "
                 "WHERE last_opened_at IS NOT NULL")
    conn.execute("UPDATE courses SET published_at=coalesce(published_at, created_at) WHERE visibility='published'")


# v4: course tags, pins and shelves on the home page, AI providers, the activity feed and achievements
SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,               -- gemini | openai | anthropic | compatible
    label TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    api_key TEXT NOT NULL DEFAULT '', -- server-side only; never sent to browsers or logged
    models_json TEXT NOT NULL DEFAULT '[]',
    tested_at TEXT,
    test_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,               -- session_done | course_done | achievement
    course_id TEXT REFERENCES courses(id) ON DELETE CASCADE,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS activity_at ON activity(at);

-- course-themed achievements written with the plan (the built-in ones live in code)
CREATE TABLE IF NOT EXISTS achievements (
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    rule_json TEXT NOT NULL DEFAULT '{}',
    seq INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (course_id, key)
);

CREATE TABLE IF NOT EXISTS user_achievements (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    earned_at TEXT NOT NULL,
    PRIMARY KEY (user_id, course_id, key)
);
"""


def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_V4)
    for table, col, ddl in (
        ("courses", "tags_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("course_prefs", "pinned", "INTEGER NOT NULL DEFAULT 0"),
        ("course_prefs", "shelf", "TEXT"),          # NULL: automatic (started = mine) | mine | aside
        ("llm_calls", "provider", "TEXT"),
    ):
        if col not in _cols(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


POST_SCHEMA = """
CREATE INDEX IF NOT EXISTS attempts_user ON attempts(user_id, item_id, id);
CREATE INDEX IF NOT EXISTS chat_user ON chat_messages(course_id, scope, user_id, id);
CREATE INDEX IF NOT EXISTS llm_calls_user ON llm_calls(user_id, at);
"""


def init() -> None:
    conn = connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if 0 < version < SCHEMA_VERSION:
            _backup_before(conn, version)
        conn.executescript(SCHEMA)
        if "options_json" not in _cols(conn, "courses"):  # v1 -> v2: per-course choice of media and extras
            conn.execute("ALTER TABLE courses ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}'")
        conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_to_v3(conn)   # idempotent: also creates the owner on a fresh database
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        _migrate_to_v4(conn)
        conn.executescript(POST_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()
    (data_dir() / "courses").mkdir(parents=True, exist_ok=True)


def get_setting(c: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(c: sqlite3.Connection, key: str, value: str | None) -> None:
    if value is None:
        c.execute("DELETE FROM settings WHERE key=?", (key,))
    else:
        c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))


def loads(s: str | None, default: Any = None) -> Any:
    if s is None or s == "":
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)
