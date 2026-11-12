-- The database schema of Knwlge v0.1.0 (schema version 2), for testing the upgrade.
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
    item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    course_id TEXT NOT NULL,
    due_at TEXT NOT NULL,
    interval_days REAL NOT NULL DEFAULT 1,
    misses INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT
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
