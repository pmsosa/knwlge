"""The audit log: who did what, when, to what (and what it cost, for AI work). Admins can view, export and prune it.
Keys and passwords are never written here: only that they changed."""
from __future__ import annotations

import csv
import io
import json
import sqlite3

from . import auth, db


def log(c: sqlite3.Connection, action: str, target_type: str = "", target_id: str = "", details: dict | None = None,
        user_id: int | None = None, cost: float | None = None) -> None:
    uid = user_id if user_id is not None else auth.actor.get()
    c.execute("INSERT INTO audit_log(at, user_id, action, target_type, target_id, details_json, cost_usd) VALUES (?,?,?,?,?,?,?)",
              (db.now(), uid, action, target_type, str(target_id or ""), json.dumps(details or {}, ensure_ascii=False)[:20000], cost))


def query(c: sqlite3.Connection, *, user: int | None = None, action: str = "", target: str = "", since: str = "",
          until: str = "", limit: int = 200, offset: int = 0) -> list[dict]:
    sql = ("SELECT a.*, u.username, u.display_name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE 1=1")
    args: list = []
    if user is not None:
        sql += " AND a.user_id=?"
        args.append(user)
    if action:
        sql += " AND a.action LIKE ?"
        args.append(action.replace("%", "") + "%")
    if target:
        sql += " AND (a.target_id=? OR a.details_json LIKE ?)"
        args += [target, f'%"{target.replace("%", "")}"%']
    if since:
        sql += " AND a.at >= ?"
        args.append(since)
    if until:
        sql += " AND a.at < ?"
        args.append(until)
    sql += " ORDER BY a.id DESC LIMIT ? OFFSET ?"
    args += [max(1, min(limit, 5000)), max(0, offset)]
    return [{**dict(r), "details": db.loads(r["details_json"], {})} for r in c.execute(sql, args)]


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["at", "user", "action", "target_type", "target_id", "cost_usd", "details"])
    for r in rows:
        # keep spreadsheets from treating cell text as formulas
        cells = [r["at"], r.get("username") or "", r["action"], r["target_type"], r["target_id"],
                 "" if r["cost_usd"] is None else f"{r['cost_usd']:.4f}", json.dumps(r["details"], ensure_ascii=False)]
        w.writerow([("'" + x) if isinstance(x, str) and x[:1] in ("=", "+", "-", "@") else x for x in cells])
    return buf.getvalue()


def prune(c: sqlite3.Connection, before: str) -> int:
    n = c.execute("DELETE FROM audit_log WHERE at < ?", (before,)).rowcount
    log(c, "audit.pruned", details={"before": before, "removed": n})
    return n
