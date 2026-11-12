"""The job queue. Every Gemini call is a row, run one at a time by a background thread, so work survives restarts,
rate limits and the budget cap. Handlers registered per job kind store results and queue what comes next."""
from __future__ import annotations

import datetime as dt
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

from . import auth, budget, db, gemini, pricing

log = logging.getLogger("knwlge.jobs")

PRIORITY_NOW = 30      # the learner is waiting: marking, chat
PRIORITY_SETUP = 20    # questions and plan
PRIORITY_BUILD = 10    # writing sessions
PRIORITY_LATER = 0     # reading list, checks

MAX_FAILURES = 3
INLINE_LIMIT = 18 * 1024 * 1024   # Gemini's inline request limit is about 20 MB

TEXT_MIME = ("text/", "application/json")

# kind -> (on_done(conn, job_row, result), on_failed(conn, job_row, error_message))
Handler = tuple[Callable[[sqlite3.Connection, sqlite3.Row, gemini.Result], None],
                Callable[[sqlite3.Connection, sqlite3.Row, str], None]]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str, on_failed: Callable | None = None):
    def wrap(fn):
        HANDLERS[kind] = (fn, on_failed or (lambda c, job, err: None))
        return fn
    return wrap


def enqueue(c: sqlite3.Connection, kind: str, request: dict, *, course_id: str | None = None, ref: str | None = None,
            priority: int = PRIORITY_BUILD, user_id: int | None = None) -> int:
    """request: role (pro|flash|lite), system, prompt, schema, search, materials (bool), files (paths in the course folder)."""
    now = db.now()
    uid = user_id if user_id is not None else auth.actor.get()   # who started it, for spend by person
    cur = c.execute(
        "INSERT INTO jobs(course_id, kind, ref, priority, request_json, user_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (course_id, kind, ref, priority, db.dumps(request), uid, now, now),
    )
    return cur.lastrowid


def pending(c: sqlite3.Connection, course_id: str | None = None) -> list[dict]:
    q = "SELECT id, course_id, kind, ref, status, attempts, error, wait_reason, next_attempt_at FROM jobs " \
        "WHERE status IN ('queued','running','waiting')"
    args: tuple = ()
    if course_id:
        q += " AND course_id=?"
        args = (course_id,)
    return [dict(r) for r in c.execute(q + " ORDER BY priority DESC, id", args)]


def cancel_course(c: sqlite3.Connection, course_id: str) -> None:
    c.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE course_id=? AND status IN ('queued','waiting')",
              (db.now(), course_id))


def requeue_interrupted(c: sqlite3.Connection) -> None:
    c.execute("UPDATE jobs SET status='queued', updated_at=? WHERE status='running'", (db.now(),))


def resume_waiting(c: sqlite3.Connection) -> int:
    """Try paused work now (after a key or budget change, or the Resume button)."""
    return c.execute("UPDATE jobs SET status='queued', next_attempt_at=NULL, wait_reason=NULL, updated_at=? "
                     "WHERE status='waiting'", (db.now(),)).rowcount


def _claim(c: sqlite3.Connection) -> sqlite3.Row | None:
    now = db.now()
    # A wait for a rate limit or a Gemini hiccup ends on its own; a budget wait ends when spend allows it.
    c.execute("UPDATE jobs SET status='queued', wait_reason=NULL WHERE status='waiting' AND wait_reason!='budget' "
              "AND next_attempt_at IS NOT NULL AND next_attempt_at <= ?", (now,))
    row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC, id LIMIT 1").fetchone()
    if row is None:
        return None
    c.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated_at=? WHERE id=?", (now, row["id"]))
    return c.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()


def _safe_path(course_id: str, rel: str) -> Path | None:
    base = db.course_dir(course_id).resolve()
    p = (base / rel).resolve()
    return p if p.is_relative_to(base) and p.is_file() else None


def build_parts(c: sqlite3.Connection, job: sqlite3.Row, req: dict) -> list[dict]:
    parts = [gemini.text_part(req["prompt"])]
    used = len(req["prompt"].encode())
    skipped: list[str] = []
    course_id = job["course_id"]
    attachments: list[tuple[str, str, Path]] = []   # (label, mime, path)
    if course_id and req.get("files"):
        for rel in req["files"]:
            p = _safe_path(course_id, rel)
            if p:
                attachments.append((f"Learner's uploaded file: {p.name}", _mime(p), p))
    if course_id and req.get("materials"):
        for m in c.execute("SELECT name, mime, filename FROM materials WHERE course_id=? ORDER BY added_at", (course_id,)):
            p = _safe_path(course_id, f"materials/{m['filename']}")
            if p:
                attachments.append((f"Learner's own course material: {m['name']}", m["mime"], p))
    for label, mime, p in attachments:
        size = p.stat().st_size
        if used + size > INLINE_LIMIT:
            skipped.append(p.name)
            continue
        data = p.read_bytes()
        used += size
        if mime.startswith(TEXT_MIME):
            parts.append(gemini.text_part(f"\n\n--- {label} ---\n{data.decode('utf-8', 'replace')}\n--- end ---"))
        else:
            parts.append(gemini.text_part(f"\n\n{label}:"))
            parts.append(gemini.file_part(data, mime))
    if skipped:
        parts.append(gemini.text_part(f"\n\n(Left out for size: {', '.join(skipped)}.)"))
    return parts


def _mime(p: Path) -> str:
    ext = p.suffix.lower().lstrip(".")
    return {"pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif", "heic": "image/heic"}.get(ext, "text/plain")


def model_for(c: sqlite3.Connection, role: str) -> str:
    return db.get_setting(c, f"model_{role}") or pricing.DEFAULT_MODELS[role]


def _backoff(attempts: int) -> dt.timedelta:
    return dt.timedelta(minutes=min(60, [1, 5, 15, 30, 60][min(attempts - 1, 4)]))


def run_one() -> bool:
    """Run the next runnable job, if any. Returns True if one ran."""
    with db.tx() as c:
        if budget.over_cap(c):
            c.execute("UPDATE jobs SET status='waiting', wait_reason='budget', updated_at=? WHERE status='queued'", (db.now(),))
            return False
        # under the cap again (it was raised, or a new month began): budget waits are over
        c.execute("UPDATE jobs SET status='queued', wait_reason=NULL WHERE status='waiting' AND wait_reason='budget'")
        job = _claim(c)
        if job is None:
            return False
        req = db.loads(job["request_json"], {})
        key = db.get_setting(c, "gemini_api_key") or ""
        model = model_for(c, req.get("role", "flash"))
        try:
            parts = [] if req.get("image") else build_parts(c, job, req)
        except Exception as e:  # unreadable attachment etc.
            parts, early = None, f"Couldn't prepare the request: {e}"
        else:
            early = None
    if early:
        _fail(job, early)
        return True

    try:
        if req.get("image"):
            res = gemini.generate_image(key, model, req["prompt"], req.get("aspect", "16:9"))
        else:
            res = _generate(key, model, req, parts)
        err = None
    except gemini.GeminiError as e:
        res, err = None, e

    with db.tx() as c:
        if res is not None:
            for call in res.calls:
                budget.log_call(c, job_id=job["id"], course_id=job["course_id"], kind=job["kind"], model=call["model"],
                                input_tokens=call["input"], output_tokens=call["output"], search_queries=call["search"],
                                outcome="ok", user_id=job["user_id"])
            stored = {"image": True} if req.get("image") else res.data   # picture bytes go to a file, not the database
            c.execute("UPDATE jobs SET status='done', result_json=?, error=NULL, updated_at=? WHERE id=?",
                      (db.dumps(stored), db.now(), job["id"]))
            on_done, _ = HANDLERS.get(job["kind"], (None, None))
            if on_done:
                try:
                    with_savepoint(c, lambda: on_done(c, job, res))
                except Exception as e:  # the answer didn't fit what the next step needs
                    log.exception("handler for job %s failed", job["id"])
                    c.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                              (f"Couldn't use Gemini's answer: {e}", db.now(), job["id"]))
                    _on_failed(c, job, f"Couldn't use Gemini's answer: {e}")
            return True

        budget.log_call(c, job_id=job["id"], course_id=job["course_id"], kind=job["kind"], model=model,
                        input_tokens=0, output_tokens=0, search_queries=0, outcome=err.kind, user_id=job["user_id"])
        attempts = job["attempts"]
        if err.kind == "rate_limit":
            c.execute("UPDATE jobs SET status='waiting', wait_reason='rate_limit', error=?, next_attempt_at=?, updated_at=? "
                      "WHERE id=?", (str(err), _ts(dt.datetime.now(dt.timezone.utc) + _backoff(attempts)), db.now(), job["id"]))
        elif err.kind in ("auth", "quota"):
            # Won't fix itself: pause everything until the key or account is sorted, then Resume.
            c.execute("UPDATE jobs SET status='waiting', wait_reason=?, error=?, next_attempt_at=NULL, updated_at=? WHERE id=?",
                      (err.kind, str(err), db.now(), job["id"]))
        elif (err.retryable or err.kind == "bad_output") and attempts < MAX_FAILURES:
            c.execute("UPDATE jobs SET status='waiting', wait_reason='retry', error=?, next_attempt_at=?, updated_at=? WHERE id=?",
                      (str(err), _ts(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=20 * attempts)), db.now(), job["id"]))
        else:
            c.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?", (str(err), db.now(), job["id"]))
            _on_failed(c, job, str(err))
    return True


def _generate(key: str, model: str, req: dict, parts: list[dict]) -> gemini.Result:
    """A text call. When search is optional (live research) and Gemini won't search (free-tier keys can't, some models
    refuse), write without it instead of failing, and say why on the result."""
    search = bool(req.get("search"))
    try:
        return gemini.generate(key, model, req["system"], parts, schema=req.get("schema"), search=search)
    except gemini.GeminiError as e:
        if not (search and req.get("search_optional") and e.kind in ("bad_request", "auth", "blocked")):
            raise
        res = gemini.generate(key, model, req["system"], parts, schema=req.get("schema"), search=False)
        res.search_note = str(e)[:200]
        return res


def with_savepoint(c: sqlite3.Connection, fn: Callable[[], None]) -> None:
    c.execute("SAVEPOINT handler")
    try:
        fn()
        c.execute("RELEASE handler")
    except BaseException:
        c.execute("ROLLBACK TO handler")
        c.execute("RELEASE handler")
        raise


def _on_failed(c: sqlite3.Connection, job: sqlite3.Row, msg: str) -> None:
    _, on_failed = HANDLERS.get(job["kind"], (None, None))
    if on_failed:
        try:
            on_failed(c, job, msg)
        except Exception:
            log.exception("failure handler for job %s failed", job["id"])


def _fail(job: sqlite3.Row, msg: str) -> None:
    with db.tx() as c:
        c.execute("UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?", (msg, db.now(), job["id"]))
        _on_failed(c, job, msg)


def retry_failed(c: sqlite3.Connection, course_id: str) -> int:
    return c.execute("UPDATE jobs SET status='queued', attempts=0, error=NULL, updated_at=? WHERE course_id=? AND status='failed'",
                     (db.now(), course_id)).rowcount


def _ts(t: dt.datetime) -> str:
    return t.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Worker:
    """One background thread. Also runs non-Gemini background work registered in `idle_tasks`."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.idle_tasks: list[Callable[[], bool]] = []

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="knwlge-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            did = False
            try:
                did = run_one()
                if not did:
                    did = any(task() for task in self.idle_tasks)
            except Exception:
                log.exception("worker step failed")
            if not did:
                self._stop.wait(1.5)
            else:
                time.sleep(0.05)
