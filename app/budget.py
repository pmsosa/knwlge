"""Spend tracking and the optional monthly cap (no cap unless one is set)."""
from __future__ import annotations

import datetime as dt
import sqlite3

from . import db, pricing


def month_start_utc(now: dt.datetime | None = None) -> str:
    """Start of the current calendar month in local time (the container's TZ), as a UTC timestamp string."""
    local = (now or dt.datetime.now().astimezone()).astimezone()
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def month_spend(c: sqlite3.Connection, now: dt.datetime | None = None) -> float:
    row = c.execute("SELECT coalesce(sum(cost_usd), 0) AS s FROM llm_calls WHERE at >= ?", (month_start_utc(now),)).fetchone()
    return float(row["s"])


def month_searches(c: sqlite3.Connection, now: dt.datetime | None = None) -> int:
    row = c.execute("SELECT coalesce(sum(search_queries), 0) AS s FROM llm_calls WHERE at >= ?",
                    (month_start_utc(now),)).fetchone()
    return int(row["s"])


def cap(c: sqlite3.Connection) -> float | None:
    v = db.get_setting(c, "budget_monthly_usd")
    try:
        f = float(v) if v not in (None, "") else None
    except ValueError:
        return None
    return f if f and f > 0 else None


def over_cap(c: sqlite3.Connection) -> bool:
    limit = cap(c)
    return limit is not None and month_spend(c) >= limit


def log_call(c: sqlite3.Connection, *, job_id: int | None, course_id: str | None, kind: str, model: str,
             input_tokens: int, output_tokens: int, search_queries: int, outcome: str, thinking_tokens: int = 0,
             user_id: int | None = None) -> float | None:
    today = dt.date.today()
    cost = pricing.token_cost(model, input_tokens, output_tokens, today)
    if cost is not None and search_queries:
        cost += pricing.search_cost(search_queries, month_searches(c))
    c.execute(
        "INSERT INTO llm_calls(job_id, course_id, kind, model, input_tokens, output_tokens, thinking_tokens, search_queries, "
        "cost_usd, outcome, at, user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, course_id, kind, model, input_tokens, output_tokens, thinking_tokens, search_queries, cost, outcome, db.now(),
         user_id),
    )
    return cost


def summary(c: sqlite3.Connection) -> dict:
    start = month_start_utc()
    by_course = [dict(r) for r in c.execute(
        "SELECT l.course_id, coalesce(co.title, l.course_id) AS title, sum(l.cost_usd) AS cost, count(*) AS calls, "
        "sum(l.input_tokens) AS input_tokens, sum(l.output_tokens) AS output_tokens "
        "FROM llm_calls l LEFT JOIN courses co ON co.id = l.course_id WHERE l.at >= ? GROUP BY l.course_id ORDER BY cost DESC",
        (start,))]
    by_kind = [dict(r) for r in c.execute(
        "SELECT kind, sum(cost_usd) AS cost, count(*) AS calls FROM llm_calls WHERE at >= ? GROUP BY kind ORDER BY cost DESC",
        (start,))]
    by_user = [dict(r) for r in c.execute(
        "SELECT l.user_id, coalesce(u.display_name, 'unattributed') AS name, sum(l.cost_usd) AS cost, count(*) AS calls "
        "FROM llm_calls l LEFT JOIN users u ON u.id = l.user_id WHERE l.at >= ? GROUP BY l.user_id ORDER BY cost DESC",
        (start,))]
    unknown = c.execute("SELECT count(*) AS n FROM llm_calls WHERE at >= ? AND cost_usd IS NULL", (start,)).fetchone()["n"]
    all_time = c.execute("SELECT coalesce(sum(cost_usd),0) AS s FROM llm_calls").fetchone()["s"]
    return {
        "month_start": start,
        "month_spend": month_spend(c),
        "all_time": float(all_time),
        "cap": cap(c),
        "over_cap": over_cap(c),
        "searches": month_searches(c),
        "unknown_price_calls": unknown,
        "by_course": by_course,
        "by_kind": by_kind,
        "by_user": by_user,
    }
