"""The admin dashboard (team mode): who is taking what, where people get stuck, and what it costs.

No scores here either: sessions done, questions answered, how often answers were missed or revealed per session, and
when someone was last active.
"""
from __future__ import annotations

import sqlite3

from . import activity, budget, db, learning
from .tiers import KIND_LABEL


def people(c: sqlite3.Connection) -> list[dict]:
    out = []
    for u in c.execute("SELECT * FROM users ORDER BY active DESC, coalesce(last_seen_at, '') DESC, display_name").fetchall():
        courses = []
        for r in c.execute(
                "SELECT co.id, co.title, max(coalesce(p.done_at, p.started_at)) AS last FROM session_progress p "
                "JOIN sessions s ON s.id=p.session_id JOIN courses co ON co.id=s.course_id WHERE p.user_id=? "
                "GROUP BY co.id ORDER BY last DESC", (u["id"],)).fetchall():
            pr = learning.course_progress(c, r["id"], u["id"])
            courses.append({"id": r["id"], "title": r["title"], "done": pr["done"], "sessions": pr["sessions"],
                            "answered": pr["answered"], "last": r["last"]})
        earned = c.execute("SELECT count(*) AS n FROM user_achievements WHERE user_id=?", (u["id"],)).fetchone()["n"]
        out.append({"id": u["id"], "name": u["display_name"], "username": u["username"], "role": u["role"],
                    "active": bool(u["active"]), "last_seen_at": u["last_seen_at"], "courses": courses,
                    "in_progress": sum(1 for x in courses if x["done"] < x["sessions"]),
                    "finished": sum(1 for x in courses if x["sessions"] and x["done"] == x["sessions"]),
                    "achievements": earned, "sharing": bool(db.loads(u["prefs_json"], {}).get("share_activity"))})
    return out


def courses(c: sqlite3.Connection) -> list[dict]:
    month = budget.month_start_utc()
    out = []
    for co in c.execute("SELECT * FROM courses ORDER BY coalesce(published_at, created_at) DESC").fetchall():
        sessions = c.execute("SELECT id, seq, title, kind FROM sessions WHERE course_id=? ORDER BY seq", (co["id"],)).fetchall()
        takers = {r["user_id"] for r in c.execute(
            "SELECT DISTINCT p.user_id FROM session_progress p JOIN sessions s ON s.id=p.session_id WHERE s.course_id=?",
            (co["id"],))}
        funnel, stuck = [], []
        for s in sessions:
            done = c.execute("SELECT count(*) AS n FROM session_progress WHERE session_id=? AND done_at IS NOT NULL",
                             (s["id"],)).fetchone()["n"]
            tries = c.execute("SELECT count(*) AS n, sum(CASE WHEN a.score < 0.999 THEN 1 ELSE 0 END) AS missed FROM attempts a "
                              "JOIN items i ON i.id=a.item_id WHERE i.session_id=? AND a.status='marked' AND i.qtype != 'long'",
                              (s["id"],)).fetchone()
            reveals = c.execute("SELECT count(*) AS n FROM item_reveals r JOIN items i ON i.id=r.item_id WHERE i.session_id=?",
                                (s["id"],)).fetchone()["n"]
            n, missed = tries["n"] or 0, tries["missed"] or 0
            funnel.append({"seq": s["seq"], "title": s["title"], "kind": KIND_LABEL[s["kind"]], "done": done})
            if n >= 3 and (missed + reveals) / max(n, 1) >= 0.4:
                stuck.append({"seq": s["seq"], "title": s["title"], "answers": n, "missed": missed, "revealed": reveals})
        spend = c.execute("SELECT coalesce(sum(cost_usd),0) AS all_time, coalesce(sum(CASE WHEN at >= ? THEN cost_usd END),0) AS month "
                          "FROM llm_calls WHERE course_id=?", (month, co["id"])).fetchone()
        author = c.execute("SELECT display_name FROM users WHERE id=?", (co["author_id"],)).fetchone()
        out.append({"id": co["id"], "title": co["title"], "status": co["status"], "visibility": co["visibility"],
                    "author": author["display_name"] if author else "", "sessions": len(sessions), "takers": len(takers),
                    "finished": sum(1 for u in takers if len(sessions) and c.execute(
                        "SELECT count(*) AS n FROM session_progress p JOIN sessions s ON s.id=p.session_id WHERE s.course_id=? "
                        "AND p.user_id=? AND p.done_at IS NOT NULL", (co["id"], u)).fetchone()["n"] == len(sessions)),
                    "funnel": funnel, "stuck": stuck, "spend_month": spend["month"], "spend_all": spend["all_time"]})
    return out


def spend_by_provider(c: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in c.execute(
        "SELECT coalesce(l.provider, 'gemini') AS provider_id, coalesce(p.label, CASE WHEN l.provider IS NULL THEN 'Gemini' "
        "ELSE l.provider END) AS label, sum(l.cost_usd) AS cost, count(*) AS calls FROM llm_calls l LEFT JOIN providers p "
        "ON p.id=l.provider WHERE l.at >= ? GROUP BY coalesce(l.provider, 'gemini') ORDER BY cost DESC",
        (budget.month_start_utc(),))]


def summary(c: sqlite3.Connection, viewer: dict) -> dict:
    spend = budget.summary(c)
    ppl = people(c)
    return {"people": ppl, "courses": courses(c),
            "spend": {"month": spend["month_spend"], "cap": spend["cap"], "by_course": spend["by_course"][:10],
                      "by_user": spend["by_user"][:10], "by_provider": spend_by_provider(c),
                      "unknown_price_calls": spend["unknown_price_calls"]},
            "feed": {"on": activity.feed_on(c), "items": activity.feed(c, viewer, 20)},
            "totals": {"people": sum(1 for p in ppl if p["active"]), "learning": sum(1 for p in ppl if p["in_progress"]),
                       "finished": sum(p["finished"] for p in ppl)}}
