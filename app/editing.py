"""Changing a generated course by hand, and exporting a course as a folder of Markdown files (in a zip)."""
from __future__ import annotations

import io
import re
import sqlite3
import zipfile

from . import db
from .pipeline import Problem
from .tiers import KIND_LABEL

LIMIT = 50_000


def _session(c: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    s = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if s is None:
        raise Problem("That session doesn't exist.")
    return s


def remove_item(c: sqlite3.Connection, item_id: str) -> None:
    """Take a question out of its session. It's archived, not deleted, so answers people gave are kept."""
    if c.execute("UPDATE items SET archived=1 WHERE id=? AND archived=0", (item_id,)).rowcount == 0:
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
                             "LEFT JOIN session_progress p ON p.session_id=s.id AND p.user_id=? WHERE s.course_id=? AND s.archived=0 ORDER BY s.seq",
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
    items = c.execute("SELECT * FROM items WHERE session_id=? AND archived=0 ORDER BY seq", (s["id"],)).fetchall()
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
