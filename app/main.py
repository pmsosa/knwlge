"""Knwlge web app: JSON API under /api, the single-page front end at /.

Every API call goes through `me` (who is this?) and then a role or course check on the server; the browser only
hides what a person can't use.
"""
from __future__ import annotations

import fnmatch
import hashlib
import ipaddress
import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (achievements, activity, audit, auth, budget, dashboard, db, editing, gemini, jobs, learning, library, media, package, pipeline,
               pricing, providers, verify)
from .pipeline import Problem
from .tiers import KIND_LABEL, TIERS, public as tiers_public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

HERE = Path(__file__).parent
# slim images lack these, and with nosniff a wrong type is fragile
for _ext, _type in ((".woff2", "font/woff2"), (".woff", "font/woff"), (".ttf", "font/ttf"), (".webmanifest", "application/manifest+json")):
    mimetypes.add_type(_type, _ext)
VENDOR = Path(os.environ.get("KNWLGE_VENDOR", HERE.parent / "vendor"))
worker = jobs.Worker()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    with db.tx() as c:
        jobs.requeue_interrupted(c)
    verify.reset_stuck()
    media.reset_stuck()
    worker.idle_tasks = [media.step, verify.step]
    if os.environ.get("KNWLGE_NO_WORKER") != "1":
        worker.start()
    yield
    worker.stop()


app = FastAPI(title="Knwlge", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; media-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-src 'self' https://www.youtube-nocookie.com; frame-ancestors 'none'; form-action 'self'")
# Experiments run in a frame with an opaque origin (sandbox without same-origin) and this policy: inline code only,
# no network, no forms, nothing else. They can't reach the app, its data or the internet.
EXPERIMENT_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
                  "font-src data:; media-src data: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'; "
                  "frame-ancestors 'self'; sandbox allow-scripts")
FILE_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"


def allowed_hosts() -> list[str]:
    return [h.strip().lower() for h in os.environ.get("KNWLGE_ALLOWED_HOSTS", "").split(",") if h.strip()]


def host_ok(host: str) -> bool:
    """Refuse other site names pointed at this server (DNS rebinding). Always allowed: IP addresses, localhost and
    single-label names; anything else must match KNWLGE_ALLOWED_HOSTS (comma-separated, wildcards like *.example.com)."""
    h = host.strip().lower()
    if h.startswith("["):
        h = h[1:].split("]")[0]
    else:
        h = h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if not h:
        return False
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    return h == "localhost" or "." not in h or any(fnmatch.fnmatchcase(h, p) for p in allowed_hosts())


@app.middleware("http")
async def guard(request: Request, call_next):
    if not host_ok(request.headers.get("host", "")):
        return JSONResponse({"detail": "Unknown host name. Add it to KNWLGE_ALLOWED_HOSTS."}, status_code=421)
    # Writes need a custom header, which browsers won't send cross-site without permission (no CSRF via forms or
    # cookies).
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS") \
            and request.headers.get("x-knwlge") != "1":
        return JSONResponse({"detail": "Missing request header."}, status_code=403)
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)   # media endpoints set their own, stricter ones
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(Problem)
async def problem(_: Request, e: Problem):
    return JSONResponse({"detail": str(e)}, status_code=400)


@app.exception_handler(auth.AuthError)
async def auth_error(_: Request, e: auth.AuthError):
    return JSONResponse({"detail": str(e), "code": e.code}, status_code=e.status)


@app.exception_handler(ValueError)
async def bad_value(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e) or "Bad request."}, status_code=400)


# ---------- who is this ----------

def _user(request: Request, allow_must_change: bool) -> dict:
    with db.tx() as c:
        user = auth.current(c, request.cookies.get(auth.COOKIE), allow_must_change)
    auth.actor.set(user["id"])   # async dependency: the value carries into the endpoint's thread
    return user


async def me(request: Request) -> dict:
    return _user(request, False)


async def me_any(request: Request) -> dict:
    """Signed in, even if a new password must be chosen first (for /api/me and changing the password)."""
    return _user(request, True)


Me = Annotated[dict, Depends(me)]
MeAny = Annotated[dict, Depends(me_any)]


def admin(user: dict) -> None:
    auth.require(user, "admin")


def team_only() -> None:
    if auth.mode() != "team":
        raise Problem("That's only available in team mode.")


def viewable(c, user: dict, course_id: str):
    row = pipeline.course_row(c, course_id)
    auth.check_view(user, row)
    return row


def editable(c, user: dict, course_id: str):
    row = pipeline.course_row(c, course_id)
    auth.check_edit(user, row)
    return row


def _course_of(c, table: str, key: str) -> str:
    row = c.execute(f"SELECT course_id FROM {table} WHERE id=?", (key,)).fetchone()
    if row is None:
        raise Problem("That doesn't exist.")
    return row["course_id"]


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def _set_cookie(resp: Response, request: Request, token: str) -> None:
    resp.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_IDLE_DAYS * 86400, httponly=True, samesite="lax",
                    secure=_secure(request), path="/")


@app.get("/api/me")
def whoami(request: Request) -> dict:
    """Never fails: tells the front end the mode and whether to show the sign-in page."""
    with db.tx() as c:
        info = {"mode": auth.mode(), "needs_signin": auth.needs_signin(c),
                "setup_needed": auth.mode() == "team" and auth.active_admins(c) == 0, "user": None}
        try:
            info["user"] = auth.current(c, request.cookies.get(auth.COOKIE), allow_must_change=True)
        except auth.AuthError:
            pass
        return info


class MeIn(BaseModel):
    display_name: str


@app.put("/api/me")
def rename_me(body: MeIn, user: Me) -> dict:
    """Anyone can change the name others see them by (not their username, which they sign in with)."""
    name = " ".join(body.display_name.split())[:80]
    if not name:
        raise Problem("Your name can't be empty.")
    with db.tx() as c:
        old = c.execute("SELECT display_name FROM users WHERE id=?", (user["id"],)).fetchone()["display_name"]
        if name != old:
            c.execute("UPDATE users SET display_name=? WHERE id=?", (name, user["id"]))
            audit.log(c, "user.renamed_self", "user", str(user["id"]), {"from": old, "to": name})
        return {"user": auth.public_user(c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone())}


class SignIn(BaseModel):
    username: str = ""
    password: str


@app.post("/api/auth/login")
def login(body: SignIn, request: Request) -> JSONResponse:
    try:
        with db.tx() as c:
            username = body.username if auth.mode() == "team" else auth.owner(c)["username"]
            u, token = auth.sign_in(c, username, body.password, request.headers.get("user-agent", ""))
            audit.log(c, "auth.signin", "user", str(u["id"]), user_id=u["id"])
            resp = JSONResponse({"user": auth.public_user(u)})
    except auth.AuthError as e:
        if e.code == "signin":   # its own transaction: the failed one was rolled back
            with db.tx() as c:
                audit.log(c, "auth.signin_failed", "user", "", {"username": (body.username or "")[:64]}, user_id=None)
        raise
    _set_cookie(resp, request, token)
    return resp


@app.post("/api/auth/logout")
def logout(request: Request) -> JSONResponse:
    with db.tx() as c:
        auth.sign_out(c, request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


class PasswordIn(BaseModel):
    current: str = ""
    new: str


@app.post("/api/auth/password")
def change_password(body: PasswordIn, request: Request, user: MeAny) -> dict:
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        if u["password_hash"] and not auth.verify_password(body.current, u["password_hash"]):
            raise Problem("Your current password isn't right.")
        if body.new == body.current:
            raise Problem("Pick a password you haven't used here.")
        auth.check_new_password(body.new, u["username"])
        auth.set_password(c, u["id"], body.new, must_change=False)
        auth.revoke_all(c, u["id"], keep_token=request.cookies.get(auth.COOKIE))
        audit.log(c, "user.password_changed", "user", str(u["id"]))
    return {"ok": True}


class PersonalPassword(BaseModel):
    current: str = ""
    new: str | None = None   # None: remove the password (the app is open again)


@app.post("/api/personal/password")
def personal_password(body: PersonalPassword, request: Request, user: Me) -> JSONResponse:
    """Personal mode: optionally protect the app with a password, or remove it again."""
    if auth.mode() != "personal":
        raise Problem("In team mode every account has its own password.")
    with db.tx() as c:
        o = auth.owner(c)
        if o["password_hash"] and not auth.verify_password(body.current, o["password_hash"]):
            raise Problem("Your current password isn't right.")
        token = None
        if body.new is None:
            c.execute("UPDATE users SET password_hash=NULL, must_change=0 WHERE id=?", (o["id"],))
            auth.revoke_all(c, o["id"])
            audit.log(c, "settings.personal_password_removed")
        else:
            auth.check_new_password(body.new, o["username"])
            auth.set_password(c, o["id"], body.new, must_change=False)
            auth.revoke_all(c, o["id"])
            _, token = auth.sign_in(c, o["username"], body.new, request.headers.get("user-agent", ""))   # stay signed in here
            audit.log(c, "settings.personal_password_set")
    resp = JSONResponse({"ok": True, "protected": body.new is not None})
    if token:
        _set_cookie(resp, request, token)
    else:
        resp.delete_cookie(auth.COOKIE, path="/")
    return resp


# ---------- accounts (team mode, admins) ----------

class NewUser(BaseModel):
    username: str
    display_name: str = ""
    role: str = "learner"
    password: str | None = None   # None: generate one


@app.get("/api/users")
def list_users(user: Me) -> list[dict]:
    admin(user)
    with db.tx() as c:
        return [auth.public_user(u) for u in c.execute("SELECT * FROM users ORDER BY active DESC, display_name COLLATE NOCASE")]


@app.post("/api/users")
def add_user(body: NewUser, user: Me) -> dict:
    admin(user)
    team_only()
    with db.tx() as c:
        uid, pw = auth.create_user(c, body.username, body.display_name, body.role, body.password)
        audit.log(c, "user.created", "user", str(uid), {"username": body.username, "role": body.role})
    return {"id": uid, "password": pw}


class UserIn(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None


@app.put("/api/users/{user_id}")
def update_user(user_id: int, body: UserIn, user: Me) -> dict:
    admin(user)
    team_only()
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if u is None:
            raise Problem("No such user.")
        changes = {}
        if body.display_name is not None and body.display_name.strip() and body.display_name.strip() != u["display_name"]:
            changes["display_name"] = body.display_name.strip()[:80]
        if body.role is not None and body.role != u["role"]:
            if body.role not in auth.ROLES:
                raise Problem("Pick a role: learner, author or admin.")
            changes["role"] = body.role
        if body.active is not None and bool(body.active) != bool(u["active"]):
            if not body.active and u["id"] == user["id"]:
                raise Problem("You can't deactivate yourself.")
            changes["active"] = 1 if body.active else 0
        losing_admin = u["role"] == "admin" and u["active"] and (changes.get("role", "admin") != "admin" or changes.get("active") == 0)
        if losing_admin and auth.active_admins(c) <= 1:
            raise Problem("There must always be at least one active admin.")
        if changes:
            c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in changes)} WHERE id=?", (*changes.values(), user_id))
            if changes.get("active") == 0:
                auth.revoke_all(c, user_id)
            audit.log(c, "user.updated", "user", str(user_id),
                      {"username": u["username"], **{k: {"from": u[k], "to": v} for k, v in changes.items()}})
        return auth.public_user(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


class ResetIn(BaseModel):
    password: str | None = None


@app.post("/api/users/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetIn, user: Me) -> dict:
    admin(user)
    team_only()
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if u is None:
            raise Problem("No such user.")
        pw = body.password or auth.generate_password()
        auth.check_new_password(pw, u["username"])
        auth.set_password(c, user_id, pw, must_change=True)
        auth.revoke_all(c, user_id)
        audit.log(c, "user.password_reset", "user", str(user_id), {"username": u["username"]})
    return {"password": pw}


# ---------- audit log (admins) ----------

def _audit_rows(c, user: str, action: str, target: str, since: str, until: str, limit: int, offset: int) -> list[dict]:
    uid = None
    if user:
        row = c.execute("SELECT id FROM users WHERE username=? OR CAST(id AS TEXT)=?", (user, user)).fetchone()
        uid = row["id"] if row else -1
    return audit.query(c, user=uid, action=action, target=target, since=since, until=until, limit=limit, offset=offset)


@app.get("/api/audit")
def get_audit(user: Me, who: str = "", action: str = "", target: str = "", since: str = "", until: str = "",
              limit: int = 200, offset: int = 0) -> list[dict]:
    admin(user)
    with db.tx() as c:
        return _audit_rows(c, who, action, target, since, until, limit, offset)


@app.get("/api/audit.csv")
def get_audit_csv(user: Me, who: str = "", action: str = "", target: str = "", since: str = "", until: str = "") -> Response:
    admin(user)
    with db.tx() as c:
        rows = _audit_rows(c, who, action, target, since, until, 5000, 0)
        audit.log(c, "audit.exported", details={"rows": len(rows)})
    return Response(audit.to_csv(rows), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="knwlge-audit.csv"'})


class PruneIn(BaseModel):
    before: str


@app.post("/api/audit/prune")
def prune_audit(body: PruneIn, user: Me) -> dict:
    admin(user)
    if db.parse_ts(body.before + ("T00:00:00Z" if len(body.before) == 10 else "")) is None:
        raise Problem("Give a date like 2026-01-31.")
    with db.tx() as c:
        return {"removed": audit.prune(c, body.before)}


# ---------- status, settings, usage ----------

def _key_hint(key: str | None) -> str | None:
    return f"…{key[-4:]}" if key else None


@app.get("/api/status")
def status(user: Me) -> dict:
    with db.tx() as c:
        key = all(p["api_key"] or not providers.KINDS[p["kind"]]["needs_key"]
                  for p, _ in (providers.route(c, r) for r in providers.ROLES))
        waits = [dict(r) for r in c.execute("SELECT wait_reason, count(*) AS n FROM jobs WHERE status='waiting' GROUP BY wait_reason")]
        busy = c.execute("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running')").fetchone()["n"]
        checking = c.execute("SELECT count(*) AS n FROM reading WHERE status IN ('pending','checking')").fetchone()["n"]
        out = {"mode": auth.mode(), "user": user, "key_set": bool(key), "busy": busy, "waiting": waits, "checking_links": checking}
        if auth.at_least(user, "admin"):   # only admins see money
            out.update(month_spend=budget.month_spend(c), cap=budget.cap(c), over_cap=budget.over_cap(c))
        return out


@app.get("/api/tiers")
def get_tiers(user: Me) -> list[dict]:
    return tiers_public()


@app.get("/api/settings")
def get_settings(user: Me) -> dict:
    admin(user)
    with db.tx() as c:
        return {"key_hint": _key_hint(db.get_setting(c, "gemini_api_key")),
                "models": {r: jobs.model_for(c, r) for r in ("pro", "flash", "lite", "image")},
                "providers": [providers.public(p) for p in providers.all_providers(c)],
                "routes": providers.routes(c),
                "kinds": {k: {"label": v["label"], "base_url": v["base_url"], "needs_key": v["needs_key"],
                              "search": v["search"], "images": v["images"], "pdf": v["pdf"]}
                          for k, v in providers.KINDS.items() if k != "gemini"},
                "defaults": pricing.DEFAULT_MODELS, "known_models": pricing.KNOWN_MODELS,
                "budget_monthly_usd": budget.cap(c), "mode": auth.mode(),
                "personal_password": auth.mode() == "personal" and bool(auth.owner(c)["password_hash"])}


class SettingsIn(BaseModel):
    api_key: str | None = None
    clear_key: bool = False
    models: dict[str, str] | None = None
    budget_monthly_usd: float | None = None
    clear_budget: bool = False


@app.put("/api/settings")
def put_settings(body: SettingsIn, user: Me) -> dict:
    admin(user)
    with db.tx() as c:
        if body.clear_key:
            db.set_setting(c, "gemini_api_key", None)
            audit.log(c, "settings.key_removed", "setting", "gemini_api_key")
        elif body.api_key is not None and body.api_key.strip():
            key = body.api_key.strip()
            if len(key) > 200 or any(ch.isspace() for ch in key):
                raise Problem("That doesn't look like an API key.")
            db.set_setting(c, "gemini_api_key", key)
            audit.log(c, "settings.key_changed", "setting", "gemini_api_key", {"ends_with": key[-4:]})
        if body.models:
            changed = {}
            for role, model in body.models.items():
                if role not in ("pro", "flash", "lite", "image"):
                    continue
                model = model.strip()
                if model and not all(ch.isalnum() or ch in "-._" for ch in model):
                    raise Problem("Model ids are letters, digits, dots and dashes.")
                if (db.get_setting(c, f"model_{role}") or "") != model:
                    changed[role] = model or "(default)"
                db.set_setting(c, f"model_{role}", model or None)
            if changed:
                audit.log(c, "settings.models", "setting", "models", changed)
        if body.clear_budget:
            db.set_setting(c, "budget_monthly_usd", None)
            audit.log(c, "settings.budget", "setting", "budget", {"monthly_usd": None})
        elif body.budget_monthly_usd is not None:
            if body.budget_monthly_usd < 0 or body.budget_monthly_usd > 100000:
                raise Problem("Pick a monthly budget between $0 and $100,000, or clear it.")
            db.set_setting(c, "budget_monthly_usd", str(body.budget_monthly_usd) if body.budget_monthly_usd > 0 else None)
            audit.log(c, "settings.budget", "setting", "budget", {"monthly_usd": body.budget_monthly_usd or None})
        jobs.resume_waiting(c)  # a new key, model or budget may unblock paused work
    return get_settings(user)


@app.post("/api/settings/test")
def test_key(user: Me) -> dict:
    """Test the Gemini key (the older button; providers have their own)."""
    admin(user)
    with db.tx() as c:
        model = jobs.model_for(c, "lite")
    try:
        res = gemini.generate(_gemini_key(), model, "Answer only with the requested JSON.",
                              [gemini.text_part("Reply with ok=true and a five-word welcome for someone starting to learn.")],
                              schema=providers.TEST_SCHEMA)
    except gemini.GeminiError as e:
        return {"ok": False, "message": str(e), "model": model}
    with db.tx() as c:
        for call in res.calls:
            budget.log_call(c, job_id=None, course_id=None, kind="test", model=call["model"], input_tokens=call["input"],
                            output_tokens=call["output"], search_queries=call["search"], outcome="ok", user_id=user["id"])
    return {"ok": True, "message": str(res.data.get("message", "")), "model": res.model}


def _gemini_key() -> str:
    with db.tx() as c:
        return db.get_setting(c, "gemini_api_key") or ""


# ---------- AI providers and which one each role uses (admins) ----------

class ProviderIn(BaseModel):
    kind: str
    label: str = ""
    base_url: str = ""
    api_key: str = ""
    search: bool = False


@app.post("/api/providers")
def add_provider(body: ProviderIn, user: Me) -> dict:
    """Add a provider, then test it straight away (which also fills in its model list)."""
    admin(user)
    with db.tx() as c:
        pid = providers.add(c, body.kind, body.label, body.base_url, body.api_key, body.search)
        audit.log(c, "provider.added", "provider", pid, {"kind": body.kind, "label": body.label[:60],
                                                         "base_url": body.base_url[:200]})
    out = providers.test(db.tx, pid)
    return {"id": pid, "test": out}


class ProviderEdit(BaseModel):
    label: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    prices: dict[str, list[float] | None] | None = None
    search: bool | None = None
    search_price: float | None = None
    clear_search_price: bool = False


@app.put("/api/providers/{pid}")
def edit_provider(pid: str, body: ProviderEdit, user: Me) -> dict:
    admin(user)
    with db.tx() as c:
        sp = None if body.clear_search_price else body.search_price if body.search_price is not None else "keep"
        providers.update(c, pid, body.label, body.base_url, body.api_key, body.prices, body.search, sp)
        details: dict[str, Any] = {}
        if body.api_key:
            details["key_ends_with"] = body.api_key.strip()[-4:]
        if body.base_url is not None:
            details["base_url"] = body.base_url[:200]
        if body.prices is not None:
            details["prices"] = body.prices
        if body.search is not None:
            details["search"] = body.search
        if body.search_price is not None or body.clear_search_price:
            details["search_price"] = body.search_price
        audit.log(c, "provider.changed", "provider", pid, details)
        jobs.resume_waiting(c)
        return providers.public(providers.get(c, pid))


@app.delete("/api/providers/{pid}")
def delete_provider(pid: str, user: Me) -> dict:
    admin(user)
    with db.tx() as c:
        providers.remove(c, pid)
        audit.log(c, "provider.removed", "provider", pid)
    return {"ok": True}


class TestIn(BaseModel):
    model: str | None = None


@app.post("/api/providers/{pid}/test")
def test_provider(pid: str, body: TestIn, user: Me) -> dict:
    admin(user)
    out = providers.test(db.tx, pid, (body.model or "").strip() or None)
    with db.tx() as c:
        if out["ok"]:
            jobs.resume_waiting(c)
    return out


class RouteIn(BaseModel):
    provider: str
    model: str


@app.put("/api/routes")
def put_routes(body: dict[str, RouteIn], user: Me) -> dict:
    """Pick a provider and model per role: {"planning": {"provider": "anth-1a2b3c", "model": "claude-opus-5-5"}, ...}"""
    admin(user)
    with db.tx() as c:
        changed = {}
        for role, r in body.items():
            before = providers.route(c, role)
            providers.set_route(c, role, r.provider, r.model)
            if (before[0]["id"], before[1]) != (r.provider, r.model.strip()):
                changed[role] = f"{r.provider}/{r.model.strip()}"
        if changed:
            audit.log(c, "settings.routes", "setting", "routes", changed)
        jobs.resume_waiting(c)
        return providers.routes(c)


@app.get("/api/usage")
def usage(user: Me) -> dict:
    admin(user)
    with db.tx() as c:
        return budget.summary(c)


@app.post("/api/jobs/resume")
def resume(user: Me) -> dict:
    admin(user)
    with db.tx() as c:
        return {"resumed": jobs.resume_waiting(c)}


# ---------- courses ----------

class NewCourse(BaseModel):
    subject: str
    notes: str = ""
    depth: str = "bootcamp"
    options: dict[str, bool] | None = None


@app.post("/api/courses")
def new_course(body: NewCourse, user: Me) -> dict:
    auth.require(user, "author")
    with db.tx() as c:
        cid = pipeline.create(c, body.subject, body.notes, body.depth, body.options)
        audit.log(c, "course.created", "course", cid, {"subject": body.subject[:200], "depth": body.depth})
        return {"id": cid}


@app.get("/api/extras")
def extras(user: Me) -> list[dict]:
    return [{"key": k, "label": o["label"], "hint": o["hint"], "default": media.DEFAULTS[k]} for k, o in media.OPTIONS.items()]


class OptionsIn(BaseModel):
    options: dict[str, bool]


@app.put("/api/courses/{course_id}/options")
def set_options(course_id: str, body: OptionsIn, user: Me) -> dict:
    """Changes apply to sessions written from now on (new courses, rewrites)."""
    with db.tx() as c:
        row = editable(c, user, course_id)
        opts = media.clean_options(body.options)
        c.execute("UPDATE courses SET options_json=?, updated_at=? WHERE id=?", (db.dumps(opts), db.now(), course_id))
        old = media.options_of(row["options_json"])
        audit.log(c, "course.options", "course", course_id, {k: v for k, v in opts.items() if old.get(k) != v})
        return {"options": opts}


class VisibilityIn(BaseModel):
    published: bool


@app.post("/api/courses/{course_id}/visibility")
def set_visibility(course_id: str, body: VisibilityIn, user: Me) -> dict:
    """Publish a course to everyone, or take it back to a draft (people's progress is kept)."""
    team_only()
    with db.tx() as c:
        editable(c, user, course_id)
        vis = "published" if body.published else "draft"
        c.execute("UPDATE courses SET visibility=?, published_at=CASE WHEN ?='published' THEN coalesce(published_at, ?) "
                  "ELSE published_at END, updated_at=? WHERE id=?", (vis, vis, db.now(), db.now(), course_id))
        audit.log(c, "course.published" if body.published else "course.unpublished", "course", course_id)
        return {"visibility": vis}


def _author_name(c, uid: int) -> str:
    row = c.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
    return row["display_name"] if row else ""


@app.get("/api/courses")
def list_courses(user: Me) -> list[dict]:
    with db.tx() as c:
        out = []
        rows = c.execute("SELECT co.*, o.at AS my_open FROM courses co LEFT JOIN course_opens o ON o.course_id=co.id AND o.user_id=? "
                         "ORDER BY coalesce(o.at, co.published_at, co.created_at) DESC", (user["id"],)).fetchall()
        for r in rows:
            if not auth.can_view(user, r):
                continue
            progress = learning.course_progress(c, r["id"], user["id"])
            prefs = library.prefs(c, r["id"], user["id"])
            building = auth.can_edit(user, r) and r["status"] != "ready"
            out.append({"id": r["id"], "title": r["title"], "subject": r["subject"], "summary": r["summary"],
                        "depth": r["depth"], "depth_label": TIERS[r["depth"]]["label"], "status": r["status"],
                        "error": r["error"] if auth.can_edit(user, r) else None,
                        "progress": progress, "tags": library.tags_of(r), "pinned": prefs["pinned"], "shelf": prefs["shelf"],
                        "mine": library.is_mine(prefs, progress, building),
                        "created_at": r["created_at"], "last_opened_at": r["my_open"], "visibility": r["visibility"],
                        "author": _author_name(c, r["author_id"]), "can_edit": auth.can_edit(user, r),
                        "reading_mode": learning.reading_mode(c, r["id"], user["id"])})
        return out


@app.get("/api/courses/{course_id}")
def get_course(course_id: str, user: Me) -> dict:
    with db.tx() as c:
        r = viewable(c, user, course_id)
        mine = auth.can_edit(user, r)
        learning.opened(c, course_id, user["id"])
        sessions = []
        for s in c.execute("SELECT s.*, p.done_at AS my_done, p.started_at AS my_started FROM sessions s LEFT JOIN session_progress p "
                           "ON p.session_id=s.id AND p.user_id=? WHERE s.course_id=? ORDER BY s.seq", (user["id"], course_id)).fetchall():
            sessions.append({"id": s["id"], "seq": s["seq"], "kind": s["kind"], "kind_label": KIND_LABEL[s["kind"]],
                             "title": s["title"], "topics": db.loads(s["topics_json"], []),
                             "objectives": db.loads(s["objectives_json"], []), "minutes": s["minutes"], "state": s["state"],
                             "error": s["error"] if mine else None, "done": bool(s["my_done"]), "started": bool(s["my_started"]),
                             "progress": learning.session_progress(c, s["id"], user["id"]) if s["state"] == "ready" else None})
        reading = [dict(x) for x in c.execute(
            "SELECT r.id, r.session_id, r.kind, r.title, r.creator, r.url, r.year, r.level, r.minutes, r.why, r.free, r.top, "
            "r.status, r.verify_note, s.seq AS session_seq, s.title AS session_title FROM reading r "
            "LEFT JOIN sessions s ON s.id=r.session_id WHERE r.course_id=? ORDER BY r.session_id IS NOT NULL, s.seq, r.id",
            (course_id,))]
        out = {
            "id": r["id"], "subject": r["subject"], "notes": r["notes"] if mine else "", "depth": r["depth"],
            "depth_label": TIERS[r["depth"]]["label"], "title": r["title"], "summary": r["summary"], "status": r["status"],
            "error": r["error"] if mine else None, "questions": db.loads(r["questions_json"], []) if mine else [],
            "answers": db.loads(r["answers_json"], {}) if mine else {},
            "plan": db.loads(r["plan_json"]), "change_request": r["change_request"] if mine else None, "sessions": sessions,
            "reading": [x for x in reading if x["status"] == "verified"],
            "reading_checking": sum(1 for x in reading if x["status"] in ("pending", "checking")),
            "reading_dropped": sum(1 for x in reading if x["status"] == "dropped"),
            "materials": [dict(m) for m in c.execute("SELECT id, name, mime, bytes, added_at FROM materials WHERE course_id=? "
                                                     "ORDER BY added_at", (course_id,))] if mine else [],
            "jobs": jobs.pending(c, course_id) if mine else [],
            "failed_jobs": c.execute("SELECT count(*) AS n FROM jobs WHERE course_id=? AND status='failed'",
                                     (course_id,)).fetchone()["n"] if mine else 0,
            "progress": learning.course_progress(c, course_id, user["id"]),
            "reading_mode": learning.reading_mode(c, course_id, user["id"]),
            "options": media.options_of(r["options_json"]),
            "visibility": r["visibility"], "author": _author_name(c, r["author_id"]), "can_edit": mine,
            "published_at": r["published_at"], "updated_at": r["updated_at"],
            "tags": library.tags_of(r), **library.prefs(c, course_id, user["id"]),
            "achievements": achievements.listing(c, course_id, user["id"]),
            "themed_achievements": achievements.themed(c, course_id) if mine else [],
        }
        if auth.at_least(user, "admin"):
            out["spend"] = c.execute("SELECT coalesce(sum(cost_usd),0) AS s FROM llm_calls WHERE course_id=?",
                                     (course_id,)).fetchone()["s"]
        return out


class Answers(BaseModel):
    answers: dict[str, Any]


@app.post("/api/courses/{course_id}/answers")
def answer(course_id: str, body: Answers, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        pipeline.answer(c, course_id, body.answers)
    return {"ok": True}


@app.post("/api/courses/{course_id}/skip-questions")
def skip(course_id: str, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        pipeline.skip_questions(c, course_id)
    return {"ok": True}


class Text(BaseModel):
    text: str = ""


@app.post("/api/courses/{course_id}/changes")
def changes(course_id: str, body: Text, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        pipeline.request_changes(c, course_id, body.text)
        audit.log(c, "course.plan_changes_requested", "course", course_id, {"request": body.text[:2000]})
    return {"ok": True}


@app.post("/api/courses/{course_id}/approve")
def approve(course_id: str, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        pipeline.approve(c, course_id)
        audit.log(c, "course.plan_approved", "course", course_id)
    return {"ok": True}


@app.post("/api/courses/{course_id}/retry")
def retry(course_id: str, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        return {"retried": pipeline.retry(c, course_id)}


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: str, user: Me) -> dict:
    with db.tx() as c:
        row = editable(c, user, course_id)
        pipeline.delete(c, course_id)
        audit.log(c, "course.deleted", "course", course_id, {"title": row["title"]})
    return {"ok": True}


class Title(BaseModel):
    title: str


@app.put("/api/courses/{course_id}/title")
def rename(course_id: str, body: Title, user: Me) -> dict:
    with db.tx() as c:
        row = editable(c, user, course_id)
        editing.rename_course(c, course_id, body.title)
        audit.log(c, "course.renamed", "course", course_id, {"from": row["title"], "to": body.title.strip()[:200]})
    return {"ok": True}


@app.get("/api/courses/{course_id}/export")
def export(course_id: str, user: Me) -> Response:
    with db.tx() as c:
        editable(c, user, course_id)
        name, data = editing.export_zip(c, course_id, user["id"])
        audit.log(c, "course.exported", "course", course_id, {"format": "markdown"})
    safe = "".join(ch if ch.isalnum() or ch in " -_.()" else "-" for ch in name)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{safe}"'})


class OnOff(BaseModel):
    on: bool


class TagsIn(BaseModel):
    tags: list[str]


@app.put("/api/courses/{course_id}/tags")
def put_tags(course_id: str, body: TagsIn, user: Me) -> dict:
    with db.tx() as c:
        row = editable(c, user, course_id)
        old = library.tags_of(row)
        tags = library.set_tags(c, course_id, body.tags)
        if tags != old:
            audit.log(c, "course.tags", "course", course_id, {"from": old, "to": tags})
        return {"tags": tags}


@app.get("/api/tags")
def get_tags(user: Me) -> list[dict]:
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT * FROM courses").fetchall() if auth.can_view(user, r)]
        return library.all_tags(c, ids)


class ShelfIn(BaseModel):
    pinned: bool | None = None
    shelf: str | None = None      # "mine" | "aside" | "auto"


@app.put("/api/courses/{course_id}/shelf")
def put_shelf(course_id: str, body: ShelfIn, user: Me) -> dict:
    """This person's own place for a course on the home page: pinned, one of mine, or set aside."""
    with db.tx() as c:
        viewable(c, user, course_id)
        if body.shelf is not None:
            library.shelve(c, course_id, user["id"], None if body.shelf == "auto" else body.shelf)
        if body.pinned is not None:
            library.pin(c, course_id, user["id"], body.pinned)
        return library.prefs(c, course_id, user["id"])


class AchievementsIn(BaseModel):
    items: list[dict]


@app.put("/api/courses/{course_id}/achievements")
def put_achievements(course_id: str, body: AchievementsIn, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        slots = [r["seq"] for r in c.execute("SELECT seq FROM sessions WHERE course_id=?", (course_id,))]
        achievements.edit_themed(c, course_id, body.items, slots)
        audit.log(c, "course.achievements", "course", course_id, {"titles": [str(i.get("title", ""))[:60] for i in body.items[:5]]})
        return {"themed_achievements": achievements.themed(c, course_id)}


@app.get("/api/me/achievements")
def my_achievements(user: Me) -> list[dict]:
    with db.tx() as c:
        def visible(cid: str) -> bool:
            r = c.execute("SELECT * FROM courses WHERE id=?", (cid,)).fetchone()
            return bool(r) and auth.can_view(user, r)
        return achievements.profile(c, user["id"], visible)


@app.get("/api/dashboard")
def get_dashboard(user: Me) -> dict:
    admin(user)
    team_only()
    with db.tx() as c:
        activity.prune(c)
        return dashboard.summary(c, user)


# ---------- the activity feed (team mode, opt-in) ----------

@app.get("/api/feed")
def get_feed(user: Me) -> dict:
    with db.tx() as c:
        on = activity.feed_on(c)
        return {"on": on, "sharing": activity.sharing(c, user["id"]), "items": activity.feed(c, user) if on else []}


@app.put("/api/me/sharing")
def put_sharing(body: OnOff, user: Me) -> dict:
    with db.tx() as c:
        activity.set_sharing(c, user["id"], body.on)
        audit.log(c, "user.sharing", "user", str(user["id"]), {"on": body.on})
        return {"sharing": body.on}


@app.put("/api/feed/switch")
def feed_switch(body: OnOff, user: Me) -> dict:
    """Admin: the feed for everyone, on or off (each person still chooses whether they appear)."""
    admin(user)
    team_only()
    with db.tx() as c:
        db.set_setting(c, "feed_off", None if body.on else "1")
        audit.log(c, "settings.feed", "setting", "feed", {"on": body.on})
        return {"on": body.on}


@app.get("/api/courses/{course_id}/package")
def export_package(course_id: str, user: Me, progress: int = 0) -> Response:
    """The whole course as a .knwlge package; with progress=1, the exporter's own progress and notes too."""
    with db.tx() as c:
        editable(c, user, course_id)
        name, data = package.export(c, course_id, user["id"], bool(progress))
        audit.log(c, "course.exported", "course", course_id, {"format": "knwlge", "progress": bool(progress)})
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/import")
async def import_course(user: Me, file: UploadFile = File(...), progress: bool = Form(True)) -> dict:
    auth.require(user, "author")
    data = await file.read(package.MAX_PACKAGE + 1)
    with db.tx() as c:
        cid = package.import_package(c, data, user["id"], progress)
        audit.log(c, "course.imported", "course", cid, {"file": (file.filename or "")[:200], "bytes": len(data),
                                                         "progress": progress})
        return {"id": cid}


@app.get("/api/courses/{course_id}/print")
def print_course(course_id: str, user: Me, answers: int = 0) -> dict:
    """Everything needed to print a course in one go. Answers only for its authors (or when the person has seen them)."""
    with db.tx() as c:
        r = viewable(c, user, course_id)
        mine = auth.can_edit(user, r)
        sessions = []
        for s in c.execute("SELECT * FROM sessions WHERE course_id=? AND state='ready' ORDER BY seq", (course_id,)).fetchall():
            items = []
            for i in c.execute("SELECT * FROM items WHERE session_id=? ORDER BY seq", (s["id"],)).fetchall():
                item = {"id": i["id"], "section": i["section"], "chunk": i["chunk"], "qtype": i["qtype"], "title": i["title"],
                        "prompt": i["prompt"], "options": db.loads(i["options_json"], [])}
                if answers and (mine or learning.revealed(c, i["id"], user["id"]) or learning.latest_attempt(c, i["id"], user["id"])):
                    item.update(answer=i["answer"], explanation=i["explanation"])
                items.append(item)
            sessions.append({"id": s["id"], "seq": s["seq"], "kind": s["kind"], "kind_label": KIND_LABEL[s["kind"]], "title": s["title"],
                             "minutes": s["minutes"], "content": db.loads(s["content_json"], {}), "items": items,
                             "media": [media.public(m) for m in c.execute(
                                 "SELECT * FROM media WHERE session_id=? ORDER BY chunk, seq", (s["id"],))]})
        plan = db.loads(r["plan_json"], {}) or {}
        return {"id": r["id"], "title": r["title"], "summary": r["summary"], "depth_label": TIERS[r["depth"]]["label"],
                "prerequisites": plan.get("prerequisites", []), "author": _author_name(c, r["author_id"]), "sessions": sessions,
                "answers_shown": bool(answers), "can_edit": mine,
                "reading": [dict(x) for x in c.execute("SELECT title, creator, url, kind, why, free FROM reading WHERE course_id=? "
                                                       "AND status='verified' AND kind!='source' ORDER BY id", (course_id,))]}


# ---------- materials (a course's authors and admins) ----------

@app.post("/api/courses/{course_id}/materials")
async def add_materials(course_id: str, user: Me, files: list[UploadFile] = File(...)) -> dict:
    loaded = [(f.filename or "file", await f.read(learning.MAX_FILE + 1)) for f in files[:learning.MAX_MATERIALS]]
    with db.tx() as c:
        editable(c, user, course_id)
        for name, data in loaded:
            learning.add_material(c, course_id, name, data)
        audit.log(c, "material.added", "course", course_id, {"files": [n for n, _ in loaded]})
    return {"added": len(loaded)}


class Note(BaseModel):
    title: str = "Note"
    text: str


@app.post("/api/courses/{course_id}/notes")
def add_note(course_id: str, body: Note, user: Me) -> dict:
    with db.tx() as c:
        editable(c, user, course_id)
        learning.add_note(c, course_id, body.title, body.text)
        audit.log(c, "material.added", "course", course_id, {"note": body.title[:80]})
    return {"ok": True}


@app.get("/api/materials/{material_id}")
def get_material(material_id: str, user: Me) -> FileResponse:
    with db.tx() as c:
        m = c.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        if m is None:
            raise Problem("That material is gone.")
        editable(c, user, m["course_id"])
    base = db.course_dir(m["course_id"]).resolve()
    p = (base / "materials" / m["filename"]).resolve()
    if not p.is_relative_to(base) or not p.is_file():
        raise Problem("That file is missing.")
    return FileResponse(p, filename=m["name"], media_type="application/octet-stream")


@app.delete("/api/materials/{material_id}")
def delete_material(material_id: str, user: Me) -> dict:
    with db.tx() as c:
        m = c.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        if m is None:
            raise Problem("That material is gone.")
        editable(c, user, m["course_id"])
        learning.remove_material(c, material_id)
        audit.log(c, "material.removed", "course", m["course_id"], {"name": m["name"]})
    return {"ok": True}


# ---------- sessions ----------

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, user: Me) -> dict:
    uid = user["id"]
    with db.tx() as c:
        s = c.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if s is None:
            raise Problem("That session doesn't exist.")
        course = viewable(c, user, s["course_id"])
        mine = auth.can_edit(user, course)
        learning.opened(c, s["course_id"], uid)
        p = learning.progress_of(c, session_id, uid)
        reading_on = learning.reading_mode(c, s["course_id"], uid)
        nav = c.execute("SELECT id, seq, title, state FROM sessions WHERE course_id=? AND seq IN (?, ?) ORDER BY seq",
                        (s["course_id"], s["seq"] - 1, s["seq"] + 1)).fetchall()
        items = [learning.public_item(c, r, uid) for r in c.execute("SELECT * FROM items WHERE session_id=? ORDER BY seq",
                                                                    (session_id,)).fetchall()]
        reading = [dict(x) for x in c.execute("SELECT id, kind, title, creator, url, level, minutes, why, free FROM reading "
                                              "WHERE session_id=? AND status='verified' ORDER BY id", (session_id,))]
        ready = s["state"] == "ready"
        content = db.loads(s["content_json"], {}) if ready else None
        return {
            "id": s["id"], "course_id": s["course_id"], "course_title": course["title"], "seq": s["seq"],
            "kind": s["kind"], "kind_label": KIND_LABEL[s["kind"]], "title": s["title"], "minutes": s["minutes"],
            "topics": db.loads(s["topics_json"], []), "objectives": db.loads(s["objectives_json"], []),
            "state": s["state"], "error": s["error"] if mine else None, "warnings": db.loads(s["warnings_json"], []) if mine else [],
            "content": content, "items": items if ready else [], "reading": reading,
            "warmup": learning.warmup(c, session_id, uid) if ready and not reading_on else [],
            "reading_mode": reading_on,
            "progress": learning.session_progress(c, session_id, uid),
            "done": bool(p and p["done_at"]), "summary_note": p["summary_note"] if p else "", "note": p["note"] if p else "",
            "prev": next((dict(n) for n in nav if n["seq"] < s["seq"]), None),
            "next": next((dict(n) for n in nav if n["seq"] > s["seq"]), None),
            "total": c.execute("SELECT count(*) AS n FROM sessions WHERE course_id=?", (s["course_id"],)).fetchone()["n"],
            "jobs": [j for j in jobs.pending(c, s["course_id"]) if j["ref"] == session_id] if mine else [],
            "media": [media.public(m) for m in c.execute("SELECT * FROM media WHERE session_id=? ORDER BY chunk, seq",
                                                           (session_id,))] if ready else [],
            "outline": [{"id": o["id"], "seq": o["seq"], "title": o["title"], "kind": o["kind"], "state": o["state"],
                         "done": bool(o["done_at"])}
                        for o in c.execute("SELECT s.id, s.seq, s.title, s.kind, s.state, p.done_at FROM sessions s "
                                           "LEFT JOIN session_progress p ON p.session_id=s.id AND p.user_id=? "
                                           "WHERE s.course_id=? ORDER BY s.seq", (uid, s["course_id"]))],
            "can_edit": mine,
            "revising": editing.revisions(c, session_id) if mine else [],
        }


class Finish(BaseModel):
    summary: str = ""


@app.post("/api/sessions/{session_id}/finish")
def finish(session_id: str, body: Finish, user: Me) -> dict:
    with db.tx() as c:
        course_id = _course_of(c, "sessions", session_id)
        viewable(c, user, course_id)
        was_done = learning.progress_of(c, session_id, user["id"])
        learning.finish_session(c, session_id, body.summary, user["id"])
        if not (was_done and was_done["done_at"]):
            s = c.execute("SELECT seq, title FROM sessions WHERE id=?", (session_id,)).fetchone()
            activity.record(c, user["id"], "session_done", course_id, {"seq": s["seq"], "title": s["title"]})
            p = learning.course_progress(c, course_id, user["id"])
            if p["sessions"] and p["done"] == p["sessions"]:
                activity.record(c, user["id"], "course_done", course_id, {})
        return {"ok": True, "achievements": achievements.check(c, course_id, user["id"])}


@app.post("/api/sessions/{session_id}/reopen")
def reopen(session_id: str, user: Me) -> dict:
    with db.tx() as c:
        viewable(c, user, _course_of(c, "sessions", session_id))
        learning.reopen_session(c, session_id, user["id"])
    return {"ok": True}


@app.put("/api/sessions/{session_id}/note")
def session_note(session_id: str, body: Text, user: Me) -> dict:
    with db.tx() as c:
        course_id = _course_of(c, "sessions", session_id)
        viewable(c, user, course_id)
        learning.set_note(c, session_id, body.text, user["id"])
        return {"ok": True, "achievements": achievements.check(c, course_id, user["id"])}


@app.put("/api/courses/{course_id}/reading")
def course_reading(course_id: str, body: OnOff, user: Me) -> dict:
    """Reading mode for this person: hide questions, practice, written work and warm-ups. Nothing is deleted."""
    with db.tx() as c:
        viewable(c, user, course_id)
        learning.set_reading_mode(c, course_id, user["id"], body.on)
    return {"reading_mode": body.on}


@app.post("/api/sessions/{session_id}/regenerate")
def regenerate(session_id: str, body: Text, user: Me) -> dict:
    with db.tx() as c:
        cid = _course_of(c, "sessions", session_id)
        editable(c, user, cid)
        pipeline.regenerate_session(c, session_id, body.text)
        audit.log(c, "session.regenerated", "session", session_id, {"course": cid, "wish": body.text[:1000]})
    return {"ok": True}


class ChunkIn(BaseModel):
    title: str
    markdown: str
    example_markdown: str = ""


@app.put("/api/sessions/{session_id}/chunks/{index}")
def edit_chunk(session_id: str, index: int, body: ChunkIn, user: Me) -> dict:
    with db.tx() as c:
        cid = _course_of(c, "sessions", session_id)
        editable(c, user, cid)
        before = (db.loads(c.execute("SELECT content_json FROM sessions WHERE id=?", (session_id,)).fetchone()["content_json"], {})
                  or {}).get("chunks", [])
        editing.edit_chunk(c, session_id, index, body.title, body.markdown, body.example_markdown)
        audit.log(c, "session.chunk_edited", "session", session_id,
                  {"course": cid, "chunk": index, "before": before[index] if 0 <= index < len(before) else None,
                   "after": {"title": body.title, "markdown": body.markdown, "example_markdown": body.example_markdown}})
    return {"ok": True}


class ReviseIn(BaseModel):
    mode: str
    wish: str
    focus: str = ""


@app.post("/api/sessions/{session_id}/chunks/{index}/revise")
def revise_chunk(session_id: str, index: int, body: ReviseIn, user: Me) -> dict:
    """Ask Gemini to rewrite one part of a lesson, or to add something to it. The change lands when the job is done."""
    with db.tx() as c:
        cid = _course_of(c, "sessions", session_id)
        editable(c, user, cid)
        editing.queue_revision(c, session_id, index, body.mode, body.wish, body.focus)
        audit.log(c, "session.chunk_revise_asked", "session", session_id,
                  {"course": cid, "chunk": index, "mode": body.mode, "wish": body.wish[:1000]})
    return {"ok": True}


# ---------- media files ----------

@app.get("/api/media/{media_id}/file")
def media_file(media_id: str, user: Me) -> FileResponse:
    with db.tx() as c:
        m, p = media.file_of(c, media_id)
        if m is not None:
            viewable(c, user, m["course_id"])
    if m is None or m["kind"] == "experiment":
        raise HTTPException(404)
    # an SVG opened on its own still can't run anything
    return FileResponse(p, media_type=m["mime"] or "application/octet-stream",
                        headers={"Content-Security-Policy": FILE_CSP, "Cache-Control": "private, max-age=86400"})


@app.get("/api/media/{media_id}/experiment")
def media_experiment(media_id: str, user: Me) -> Response:
    with db.tx() as c:
        m, p = media.file_of(c, media_id)
        if m is not None:
            viewable(c, user, m["course_id"])
    if m is None or m["kind"] != "experiment":
        raise HTTPException(404)
    return Response(p.read_text(encoding="utf-8"), media_type="text/html",
                    headers={"Content-Security-Policy": EXPERIMENT_CSP, "X-Frame-Options": "SAMEORIGIN",
                             "Cache-Control": "no-store"})


# ---------- items ----------

@app.get("/api/items/{item_id}")
def get_item(item_id: str, user: Me) -> dict:
    with db.tx() as c:
        viewable(c, user, _course_of(c, "items", item_id))
        return learning.public_item(c, learning.item_row(c, item_id), user["id"])


@app.post("/api/items/{item_id}/attempts")
async def post_attempt(item_id: str, user: Me, answer: str = Form(""), context: str = Form("session"),
                       files: list[UploadFile] | None = File(None)) -> dict:
    loaded = [(f.filename or "file", await f.read(learning.MAX_FILE + 1)) for f in (files or [])]
    with db.tx() as c:
        course_id = _course_of(c, "items", item_id)
        viewable(c, user, course_id)
        out = learning.attempt(c, item_id, answer, loaded, context, user["id"])
        out["achievements"] = achievements.check(c, course_id, user["id"])
        return out


@app.post("/api/items/{item_id}/reveal")
def reveal(item_id: str, user: Me) -> dict:
    with db.tx() as c:
        viewable(c, user, _course_of(c, "items", item_id))
        return learning.reveal(c, item_id, user["id"])


class ItemIn(BaseModel):
    prompt: str
    options: list[str] = []
    answer: str = ""
    explanation: str = ""


@app.get("/api/items/{item_id}/full")
def get_item_full(item_id: str, user: Me) -> dict:
    """For editing: the answer and explanation, without counting as 'revealed' for the editor's own progress."""
    with db.tx() as c:
        editable(c, user, _course_of(c, "items", item_id))
        row = learning.item_row(c, item_id)
        return {**learning.public_item(c, row, user["id"]), "answer": row["answer"], "explanation": row["explanation"]}


@app.put("/api/items/{item_id}")
def edit_item(item_id: str, body: ItemIn, user: Me) -> dict:
    with db.tx() as c:
        cid = _course_of(c, "items", item_id)
        editable(c, user, cid)
        old = learning.item_row(c, item_id)
        editing.edit_item(c, item_id, body.prompt, body.options, body.answer, body.explanation)
        audit.log(c, "item.edited", "item", item_id, {
            "course": cid,
            "before": {"prompt": old["prompt"], "options": db.loads(old["options_json"], []), "answer": old["answer"],
                       "explanation": old["explanation"]},
            "after": body.model_dump()})
        return learning.public_item(c, learning.item_row(c, item_id), user["id"])


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str, user: Me) -> dict:
    with db.tx() as c:
        cid = _course_of(c, "items", item_id)
        editable(c, user, cid)
        old = learning.item_row(c, item_id)
        editing.delete_item(c, item_id)
        audit.log(c, "item.deleted", "item", item_id, {"course": cid, "prompt": old["prompt"], "answer": old["answer"]})
    return {"ok": True}


@app.get("/api/uploads/{attempt_id}/{name}")
def get_upload(attempt_id: int, name: str, user: Me) -> FileResponse:
    """Someone's uploaded working: only they (and admins) can open it."""
    with db.tx() as c:
        a = c.execute("SELECT course_id, files_json, user_id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    rel = f"uploads/{attempt_id}/{name}"
    if a is None or rel not in db.loads(a["files_json"], []) or not (a["user_id"] == user["id"] or auth.at_least(user, "admin")):
        raise Problem("That file is gone.")
    base = db.course_dir(a["course_id"]).resolve()
    p = (base / rel).resolve()
    if not p.is_relative_to(base) or not p.is_file():
        raise Problem("That file is missing.")
    return FileResponse(p, filename=name, media_type="application/octet-stream")


# ---------- ask about it ----------

@app.get("/api/chat")
def get_chat(course: str, scope: str, user: Me) -> dict:
    with db.tx() as c:
        viewable(c, user, course)
        pending = learning.chat_pending(c, course, scope, user["id"])
        return {"messages": learning.chat_messages(c, course, scope, user["id"]), "pending": dict(pending) if pending else None}


class ChatIn(BaseModel):
    course: str
    scope: str
    text: str


@app.post("/api/chat")
def post_chat(body: ChatIn, user: Me) -> dict:
    with db.tx() as c:
        viewable(c, user, body.course)
        learning.ask(c, body.course, body.scope, body.text, user["id"])
        return {"ok": True, "achievements": achievements.check(c, body.course, user["id"])}


# ---------- front end ----------

app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
if VENDOR.is_dir():
    app.mount("/vendor", StaticFiles(directory=VENDOR), name="vendor")


ICONS = HERE / "static" / "icons"
ICON_FILES = {"favicon-16.png", "favicon-32.png", "favicon-64.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png",
              "icon-maskable-512.png"}
MANIFEST = {
    "name": "Knwlge", "short_name": "Knwlge", "description": "Self-paced courses on anything, written by AI.",
    "id": "/", "start_url": "/", "scope": "/", "display": "standalone", "background_color": "#efefe4", "theme_color": "#efefe4",
    "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
              {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
              {"src": "/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
}


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(ICONS / "favicon-32.png", media_type="image/png")


@app.get("/manifest.webmanifest")
def manifest() -> JSONResponse:
    return JSONResponse(MANIFEST, media_type="application/manifest+json")


def _build_version() -> str:
    """A short fingerprint of the front end's files, so each build's service worker gets its own cache."""
    h = hashlib.sha256()
    for root in (HERE / "static", VENDOR):
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    st = p.stat()
                    h.update(f"{p.relative_to(root)}:{st.st_size}:{int(st.st_mtime)}".encode())
    return h.hexdigest()[:12]


SW_SOURCE = (HERE / "static" / "sw.js").read_text().replace("__VERSION__", _build_version())


@app.get("/sw.js")
def service_worker() -> Response:
    """Served from the root so it may look after the whole app; never cached by the browser, so updates are seen."""
    return Response(SW_SOURCE, media_type="text/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/{name}.png")
def icon(name: str) -> FileResponse:
    if f"{name}.png" not in ICON_FILES:
        raise HTTPException(404)
    return FileResponse(ICONS / f"{name}.png", media_type="image/png")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})
