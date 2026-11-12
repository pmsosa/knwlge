"""Changing a generated course by hand, and exporting a course as a folder of Markdown files (in a zip)."""
from __future__ import annotations

import io
import re
import sqlite3
import zipfile

from . import audit, db, jobs, media, prompts
from .pipeline import Problem, _num
from .tiers import KIND_LABEL

LIMIT = 50_000


def _session(c: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    s = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None:
        raise Problem("That session doesn't exist.")
    return s


def edit_chunk(c: sqlite3.Connection, session_id: str, index: int, title: str, markdown: str, example: str) -> None:
    s = _session(c, session_id)
    content = db.loads(s["content_json"], {}) or {}
    chunks = content.get("chunks", [])
    if not 0 <= index < len(chunks):
        raise Problem("That part of the lesson doesn't exist.")
    if len(markdown) > LIMIT or len(example) > LIMIT:
        raise Problem("That's too long for one part.")
    chunks[index] = {"title": title.strip()[:200] or chunks[index]["title"], "markdown": markdown, "example_markdown": example}
    c.execute("UPDATE sessions SET content_json=? WHERE id=?", (db.dumps(content), session_id))


REVISE_MODES = ("rewrite", "add")


def _ref(session_id: str, index: int) -> str:
    return f"{session_id}:{index}"


def revisions(c: sqlite3.Connection, session_id: str) -> list[int]:
    """Parts of a session that Gemini is rewriting right now."""
    out = []
    for r in c.execute("SELECT ref FROM jobs WHERE kind='revise' AND ref LIKE ? AND status IN ('queued','running','waiting')",
                       (session_id + ":%",)):
        out.append(int(r["ref"].rsplit(":", 1)[1]))
    return sorted(set(out))


def queue_revision(c: sqlite3.Connection, session_id: str, index: int, mode: str, wish: str, focus: str = "") -> None:
    s = _session(c, session_id)
    if s["state"] != "ready":
        raise Problem("Wait until the session is ready.")
    content = db.loads(s["content_json"], {}) or {}
    chunks = content.get("chunks", [])
    if not 0 <= index < len(chunks):
        raise Problem("That part of the lesson doesn't exist.")
    if mode not in REVISE_MODES:
        raise Problem("Choose rewrite or add.")
    wish = (wish or "").strip()
    if not wish:
        raise Problem("Say what you'd like changed." if mode == "rewrite" else "Say what you'd like added.")
    if len(wish) > 2000 or len(focus or "") > 8000:
        raise Problem("That's too long.")
    if index in revisions(c, session_id):
        raise Problem("That part is already being rewritten.")
    course = c.execute("SELECT title, options_json FROM courses WHERE id=?", (s["course_id"],)).fetchone()
    req = prompts.revise_chunk(course["title"], s["title"], content.get("goal", ""), chunks, index, mode, wish, focus or "",
                               live=media.options_of(course["options_json"])["research"])
    jobs.enqueue(c, "revise", req, course_id=s["course_id"], ref=_ref(session_id, index), priority=jobs.PRIORITY_NOW)


def _on_revise_failed(c: sqlite3.Connection, job: sqlite3.Row, err: str) -> None:
    session_id, index = job["ref"].rsplit(":", 1)
    s = c.execute("SELECT warnings_json FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is not None:
        w = db.loads(s["warnings_json"], []) + [f"Rewriting part {int(index) + 1} didn't work: {err}"]
        c.execute("UPDATE sessions SET warnings_json=? WHERE id=?", (db.dumps(w), session_id))


@jobs.handler("revise", on_failed=_on_revise_failed)
def _on_revise(c: sqlite3.Connection, job: sqlite3.Row, res) -> None:
    session_id, index = job["ref"].rsplit(":", 1)
    index = int(index)
    s = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None:
        return
    content = db.loads(s["content_json"], {}) or {}
    chunks = content.get("chunks", [])
    if not 0 <= index < len(chunks):
        return
    d = res.data
    md = str(d.get("markdown", "")).strip()
    if not md:
        raise ValueError("the rewritten part came back empty")
    before = dict(chunks[index])
    chunks[index] = {**chunks[index], "title": str(d.get("title", "")).strip()[:200] or before.get("title", ""),
                     "markdown": md[:LIMIT], "example_markdown": str(d.get("example_markdown", "")).strip()[:LIMIT]}
    c.execute("UPDATE sessions SET content_json=? WHERE id=?", (db.dumps(content), session_id))
    audit.log(c, "session.chunk_revised", "session", session_id,
              {"course": s["course_id"], "chunk": index, "before": before,
               "after": {k: chunks[index][k] for k in ("title", "markdown", "example_markdown")}},
              user_id=job["user_id"])


def edit_item(c: sqlite3.Connection, item_id: str, prompt: str, options: list[str], answer: str, explanation: str) -> None:
    row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise Problem("That question doesn't exist.")
    prompt = prompt.strip()
    if not prompt:
        raise Problem("The question can't be empty.")
    options = [o.strip() for o in options if o.strip()] if row["qtype"] == "mcq" else []
    if row["qtype"] == "mcq":
        if len(options) < 2:
            raise Problem("Give at least two options.")
        if answer.strip() not in options:
            raise Problem("The answer must be one of the options, written exactly the same.")
    if row["qtype"] == "numeric" and _num(answer) is None:
        raise Problem("The answer to a number question must be a number.")
    c.execute("UPDATE items SET prompt=?, options_json=?, answer=?, explanation=? WHERE id=?",
              (prompt[:LIMIT], db.dumps(options), answer.strip()[:LIMIT], explanation.strip()[:LIMIT], item_id))


def delete_item(c: sqlite3.Connection, item_id: str) -> None:
    if c.execute("DELETE FROM items WHERE id=?", (item_id,)).rowcount == 0:
        raise Problem("That question doesn't exist.")


def rename_course(c: sqlite3.Connection, course_id: str, title: str) -> None:
    title = title.strip()[:200]
    if not title:
        raise Problem("Give the course a title.")
    if c.execute("UPDATE courses SET title=?, updated_at=? WHERE id=?", (title, db.now(), course_id)).rowcount == 0:
        raise Problem("That course doesn't exist.")


def _fname(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", s).strip(" .")[:70] or "untitled"


def export_zip(c: sqlite3.Connection, course_id: str, uid: int = db.OWNER_ID) -> tuple[str, bytes]:
    """The course as Markdown, with the exporting person's own answers, feedback and notes."""
    course = c.execute("SELECT * FROM courses WHERE id=?", (course_id,)).fetchone()
    if course is None:
        raise Problem("That course doesn't exist.")
    plan = db.loads(course["plan_json"], {}) or {}
    root = _fname(course["title"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        sessions = c.execute("SELECT s.*, p.done_at AS my_done, p.summary_note AS my_summary, p.note AS my_note FROM sessions s "
                             "LEFT JOIN session_progress p ON p.session_id=s.id AND p.user_id=? WHERE s.course_id=? ORDER BY s.seq",
                             (uid, course_id)).fetchall()
        head = [f"# {course['title']}", "", plan.get("summary", ""), ""]
        if plan.get("prerequisites"):
            head += ["## Before you start", ""] + [f"- {p}" for p in plan["prerequisites"]] + [""]
        head += ["## Sessions", ""] + [f"{s['seq']}. {s['title']} ({KIND_LABEL[s['kind']]})" + (" ✓" if s["my_done"] else "")
                                       for s in sessions]
        z.writestr(f"{root}/00 Course.md", "\n".join(head) + "\n")
        for s in sessions:
            z.writestr(f"{root}/{s['seq']:02d} {_fname(s['title'])}.md", _session_md(c, s, uid))
        reading = c.execute("SELECT * FROM reading WHERE course_id=? AND status='verified' ORDER BY session_id IS NOT NULL, id",
                            (course_id,)).fetchall()
        lines = ["# Further reading", ""]
        for r in reading:
            link = f"[{r['title']}]({r['url']})" if r["url"] else r["title"]
            lines.append(f"- {'⭐ ' if r['top'] else ''}{link}, {r['creator']} ({r['kind']}{', paid' if not r['free'] else ''}). {r['why']}")
        z.writestr(f"{root}/99 Further reading.md", "\n".join(lines) + "\n")
    return f"{root}.zip", buf.getvalue()


def _session_md(c: sqlite3.Connection, s: sqlite3.Row, uid: int) -> str:
    content = db.loads(s["content_json"], {}) or {}
    out = [f"# {s['seq']}. {s['title']}", "", f"*{KIND_LABEL[s['kind']]}, about {s['minutes']} minutes*", ""]
    if content.get("goal"):
        out += [f"**Goal:** {content['goal']}", ""]
    for key in ("hook", "intro_markdown"):
        if content.get(key):
            out += [content[key], ""]
    for ch in content.get("chunks", []):
        out += [f"## {ch['title']}", "", ch["markdown"], ""]
        if ch.get("example_markdown"):
            out += ["### Example", "", ch["example_markdown"], ""]
    if content.get("tips_markdown"):
        out += ["## Tips", "", content["tips_markdown"], ""]
    items = c.execute("SELECT * FROM items WHERE session_id=? ORDER BY seq", (s["id"],)).fetchall()
    if items:
        out += ["## Questions and exercises", ""]
    for i in items:
        out += [f"### {i['title'] or i['section'].capitalize()}", "", i["prompt"], ""]
        for o in db.loads(i["options_json"], []):
            out.append(f"- {o}")
        if i["answer"]:
            out += ["", f"**Answer:** {i['answer']}", ""]
        if i["explanation"]:
            out += [i["explanation"], ""]
        a = c.execute("SELECT * FROM attempts WHERE item_id=? AND user_id=? AND status='marked' ORDER BY id DESC LIMIT 1",
                      (i["id"], uid)).fetchone()
        if a:
            fb = db.loads(a["feedback_json"], {}) or {}
            out += ["**Your answer:**", "", a["answer"] or "(files)", ""]
            if fb.get("overall"):
                out += [f"**Feedback ({fb.get('level', '')}):** {fb['overall']}", ""]
            elif fb.get("comment"):
                out += [f"**Feedback:** {fb['comment']}", ""]
    wrap = content.get("wrapup") or {}
    if wrap.get("key_points"):
        out += ["## Key points", ""] + [f"- {k}" for k in wrap["key_points"]] + [""]
    if s["my_summary"]:
        out += ["## My summary", "", s["my_summary"], ""]
    if s["my_note"]:
        out += ["## My notes", "", s["my_note"], ""]
    return "\n".join(out)
