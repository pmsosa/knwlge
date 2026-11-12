"""Team mode: accounts, sign-in, roles, drafts, per-person progress, audit; personal-mode password; the upgrade."""
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fakes
from conftest import drain


@pytest.fixture()
def team(app_env, monkeypatch):
    monkeypatch.setenv("KNWLGE_MODE", "team")
    from app import auth
    auth.reset_throttle()
    from app.main import app
    with TestClient(app):          # run startup once
        pass
    yield app


def client(app):
    return TestClient(app, headers={"x-knwlge": "1"})


def sign_in(app, username, password, new_password=None):
    c = client(app)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    if new_password:
        r = c.post("/api/auth/password", json={"current": password, "new": new_password})
        assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def people(team):
    """An admin (who took over the owner account), an author and a learner, all past their first sign-in."""
    from app import accounts
    name, pw = accounts.add_admin("ada", "Ada Admin")
    admin = sign_in(team, "ada", pw, "ada-new-password-1")
    out = {"admin": admin}
    for role, uname in (("author", "otto"), ("learner", "lena")):
        r = admin.post("/api/users", json={"username": uname, "display_name": uname.title(), "role": role})
        assert r.status_code == 200, r.text
        out[role] = sign_in(team, uname, r.json()["password"], f"{uname}-new-password-1")
    return out


def build(c, subject="Pottery 101"):
    cid = c.post("/api/courses", json={"subject": subject, "depth": "dive"}).json()["id"]
    drain()
    c.post(f"/api/courses/{cid}/answers", json={"answers": {}})
    drain()
    c.post(f"/api/courses/{cid}/approve")
    drain()
    return cid


def test_setup_and_first_sign_in(team):
    anon = client(team)
    me = anon.get("/api/me").json()
    assert me["mode"] == "team" and me["needs_signin"] and me["setup_needed"] and me["user"] is None
    assert anon.get("/api/courses").status_code == 401
    from app import accounts
    name, pw = accounts.add_admin("ada")
    c = client(team)
    assert c.post("/api/auth/login", json={"username": "ada", "password": "wrong-password"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "ada", "password": pw}).status_code == 200
    r = c.get("/api/courses")
    assert r.status_code == 403 and r.json()["code"] == "change_password"
    assert c.post("/api/auth/password", json={"current": pw, "new": "short"}).status_code == 400
    assert c.post("/api/auth/password", json={"current": pw, "new": "a-much-better-password"}).status_code == 200
    assert c.get("/api/courses").status_code == 200
    assert c.get("/api/me").json()["user"]["role"] == "admin"
    assert client(team).get("/api/me").json()["setup_needed"] is False


def test_roles_are_enforced_on_the_server(people):
    learner, author, admin = people["learner"], people["author"], people["admin"]
    assert learner.post("/api/courses", json={"subject": "x", "depth": "dive"}).status_code == 403
    for path in ("/api/settings", "/api/usage", "/api/users", "/api/audit"):
        assert learner.get(path).status_code == 403, path
        assert author.get(path).status_code == 403, path
        assert admin.get(path).status_code == 200, path
    assert learner.put("/api/settings", json={"budget_monthly_usd": 1}).status_code == 403
    assert "month_spend" not in learner.get("/api/status").json()
    assert "month_spend" in admin.get("/api/status").json()


def test_drafts_publishing_and_editing_rights(people):
    learner, author, admin = people["learner"], people["author"], people["admin"]
    cid = build(author)
    assert author.get(f"/api/courses/{cid}").json()["visibility"] == "draft"
    assert cid not in [c["id"] for c in learner.get("/api/courses").json()]
    assert learner.get(f"/api/courses/{cid}").status_code == 400          # a draft looks like it doesn't exist
    assert learner.post(f"/api/courses/{cid}/visibility", json={"published": True}).status_code == 400
    assert author.post(f"/api/courses/{cid}/visibility", json={"published": True}).json()["visibility"] == "published"
    c = learner.get(f"/api/courses/{cid}").json()
    assert c["can_edit"] is False and c["materials"] == [] and "spend" not in c and c["author"] == "Otto"
    sid = c["sessions"][0]["id"]
    s = learner.get(f"/api/sessions/{sid}").json()
    item = s["items"][0]["id"]
    # learners can't change a course
    assert learner.post(f"/api/sessions/{sid}/regenerate", json={"text": ""}).status_code == 403
    assert learner.post(f"/api/sessions/{sid}/chunks/0/revise", json={"mode": "add", "wish": "x"}).status_code == 403
    assert learner.put(f"/api/items/{item}", json={"prompt": "x", "options": ["a", "b"], "answer": "a"}).status_code == 403
    assert learner.get(f"/api/items/{item}/full").status_code == 403
    assert learner.delete(f"/api/courses/{cid}").status_code == 403
    assert learner.get(f"/api/courses/{cid}/export").status_code == 403
    # another author can't either, an admin can
    assert admin.put(f"/api/courses/{cid}/title", json={"title": "Pottery for Everyone"}).status_code == 200
    assert author.get(f"/api/items/{item}/full").json()["answer"]


def test_progress_is_per_person(people):
    learner, author = people["learner"], people["author"]
    cid = build(author)
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    sid = author.get(f"/api/courses/{cid}").json()["sessions"][0]["id"]
    mcq = next(i for i in learner.get(f"/api/sessions/{sid}").json()["items"] if i["qtype"] == "mcq")
    assert learner.post(f"/api/items/{mcq['id']}/attempts", data={"answer": "Wrong"}).json()["last"]["score"] == 0
    learner.post(f"/api/items/{mcq['id']}/reveal")
    learner.post(f"/api/sessions/{sid}/finish", json={"summary": "learnt things"})
    learner.put(f"/api/sessions/{sid}/note", json={"text": "my private note"})
    mine = learner.get(f"/api/sessions/{sid}").json()
    theirs = author.get(f"/api/sessions/{sid}").json()
    assert mine["done"] and mine["note"] == "my private note"
    assert not theirs["done"] and theirs["note"] == "" and theirs["summary_note"] == ""
    a_item = next(i for i in theirs["items"] if i["id"] == mcq["id"])
    l_item = next(i for i in mine["items"] if i["id"] == mcq["id"])
    assert l_item["revealed"] and l_item["answer"] and not a_item["revealed"] and a_item["answer"] is None and a_item["last"] is None
    assert learner.get(f"/api/courses/{cid}").json()["progress"]["done"] == 1
    assert author.get(f"/api/courses/{cid}").json()["progress"]["done"] == 0
    # tutor chats are private too
    learner.post("/api/chat", json={"course": cid, "scope": sid, "text": "Why?"})
    drain()
    assert len(learner.get("/api/chat", params={"course": cid, "scope": sid}).json()["messages"]) == 2
    assert author.get("/api/chat", params={"course": cid, "scope": sid}).json()["messages"] == []
    # the AI calls the learner caused are counted against them
    usage = people["admin"].get("/api/usage").json()
    assert any(u["name"] == "Lena" and u["cost"] > 0 for u in usage["by_user"])


def test_uploads_are_private(people):
    learner, author, admin = people["learner"], people["author"], people["admin"]
    cid = build(author)
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    sid = author.get(f"/api/courses/{cid}").json()["sessions"][0]["id"]
    ex = next(i for i in learner.get(f"/api/sessions/{sid}").json()["items"] if i["qtype"] == "long")
    r = learner.post(f"/api/items/{ex['id']}/attempts", data={"answer": "mine"}, files=[("files", ("w.png", b"\x89PNG x", "image/png"))])
    att = r.json()["last"]["id"]
    url = f"/api/uploads/{att}/w.png"
    assert learner.get(url).status_code == 200
    assert admin.get(url).status_code == 200
    assert author.get(url).status_code == 400


def test_account_management(people, team):
    admin, learner = people["admin"], people["learner"]
    users = {u["username"]: u for u in admin.get("/api/users").json()}
    lena = users["lena"]["id"]
    ada = users["ada"]["id"]
    assert admin.put(f"/api/users/{ada}", json={"role": "learner"}).status_code == 400      # last admin stays
    assert admin.put(f"/api/users/{ada}", json={"active": False}).status_code == 400        # can't deactivate yourself
    assert admin.put(f"/api/users/{lena}", json={"role": "author", "display_name": "Lena L."}).json()["role"] == "author"
    assert admin.put(f"/api/users/{lena}", json={"active": False}).status_code == 200
    assert learner.get("/api/courses").status_code == 401                                   # signed out everywhere
    admin.put(f"/api/users/{lena}", json={"active": True})
    pw = admin.post(f"/api/users/{lena}/reset-password", json={}).json()["password"]
    c = sign_in(team, "lena", pw)
    assert c.get("/api/courses").json()["code"] == "change_password"
    assert admin.post("/api/users", json={"username": "lena", "role": "learner"}).status_code == 400   # taken
    assert admin.post("/api/users", json={"username": "x y", "role": "learner"}).status_code == 400    # bad name


def test_sign_in_is_throttled(people, team):
    c = client(team)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "lena", "password": "nope-nope-nope"}).status_code == 401
    assert c.post("/api/auth/login", json={"username": "lena", "password": "lena-new-password-1"}).status_code == 429
    # unknown accounts give the same answer as wrong passwords
    assert c.post("/api/auth/login", json={"username": "nobody", "password": "whatever-1234"}).json()["detail"] == \
        "That username and password don't match."


def test_audit_log(people):
    admin, author = people["admin"], people["author"]
    cid = build(author)
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    admin.put("/api/settings", json={"api_key": "AIzaSECRETSECRETSECRET1234"})
    client_bad = TestClient(admin.app, headers={"x-knwlge": "1"})
    client_bad.post("/api/auth/login", json={"username": "otto", "password": "wrong-password-x"})
    rows = admin.get("/api/audit").json()
    actions = [r["action"] for r in rows]
    for a in ("user.created", "course.created", "course.plan_approved", "course.published", "settings.key_changed",
              "auth.signin_failed", "user.password_changed", "user.claimed_owner"):
        assert a in actions, a
    created = next(r for r in rows if r["action"] == "course.created")
    assert created["username"] == "otto" and created["target_id"] == cid
    assert "SECRETSECRET" not in str(rows)
    assert len(admin.get("/api/audit", params={"who": "otto"}).json()) >= 3
    assert all(r["action"].startswith("course.") for r in admin.get("/api/audit", params={"action": "course."}).json())
    csv = admin.get("/api/audit.csv")
    assert csv.status_code == 200 and csv.text.startswith("at,user,action")
    assert admin.post("/api/audit/prune", json={"before": "2000-01-01"}).json()["removed"] == 0


def test_personal_password(app_env):
    from app import auth
    auth.reset_throttle()
    from app.main import app
    with TestClient(app, headers={"x-knwlge": "1"}) as c:
        assert c.get("/api/me").json() | {} and not c.get("/api/me").json()["needs_signin"]
        assert c.get("/api/courses").status_code == 200                         # open by default
        assert c.post("/api/personal/password", json={"new": "a-personal-password"}).json()["protected"]
        assert c.get("/api/courses").status_code == 200                         # still signed in here
        other = TestClient(app, headers={"x-knwlge": "1"})
        assert other.get("/api/courses").status_code == 401
        assert other.post("/api/auth/login", json={"password": "a-personal-password"}).status_code == 200
        assert other.get("/api/courses").status_code == 200
        assert c.post("/api/personal/password", json={"current": "wrong", "new": None}).status_code == 400
        assert c.post("/api/personal/password", json={"current": "a-personal-password", "new": None}).json()["protected"] is False
        assert TestClient(app).get("/api/courses").status_code == 200           # open again
        assert c.post("/api/users", json={"username": "x", "role": "learner"}).status_code == 400   # team only


def test_upgrade_from_v0_1_0(app_env):
    """A database made by the personal edition (schema 2) becomes the owner's, after a backup."""
    from app import db
    path = db.db_path()
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript((Path(__file__).parent / "fixtures" / "schema_v2.sql").read_text())
    conn.executescript("""
        INSERT INTO courses(id, subject, depth, title, status, created_at, updated_at, last_opened_at)
            VALUES ('c1', 'Old', 'dive', 'Old course', 'ready', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', '2026-11-08T00:00:00Z');
        INSERT INTO sessions(id, course_id, seq, kind, title, minutes, state, done_at, summary_note, note, started_at)
            VALUES ('c1-s01', 'c1', 1, 'lesson', 'One', 45, 'ready', '2026-11-02T00:00:00Z', 'summary', 'note', '2026-11-02T00:00:00Z');
        INSERT INTO items(id, course_id, session_id, seq, section, qtype, prompt, answer, revealed)
            VALUES ('c1-s01-i01', 'c1', 'c1-s01', 1, 'check', 'mcq', 'Q?', 'A', 1);
        INSERT INTO attempts(item_id, course_id, created_at, answer, status, score) VALUES ('c1-s01-i01', 'c1', '2026-11-02T00:00:00Z', 'B', 'marked', 0);
        INSERT INTO review_queue(item_id, course_id, due_at) VALUES ('c1-s01-i01', 'c1', '2026-11-03T00:00:00Z');
        INSERT INTO chat_messages(course_id, scope, role, text, created_at) VALUES ('c1', 'course', 'learner', 'hi', '2026-11-02T00:00:00Z');
        PRAGMA user_version = 2;
    """)
    conn.close()
    db.init()
    db.init()   # twice: the upgrade is idempotent
    with db.tx() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 3
        owner = c.execute("SELECT * FROM users WHERE id=1").fetchone()
        assert owner["username"] == "owner" and owner["role"] == "admin" and owner["password_hash"] is None
        p = c.execute("SELECT * FROM session_progress").fetchone()
        assert (p["user_id"], p["done_at"], p["summary_note"], p["note"]) == (1, "2026-11-02T00:00:00Z", "summary", "note")
        assert c.execute("SELECT user_id FROM item_reveals").fetchone()[0] == 1
        assert c.execute("SELECT user_id, misses FROM review_queue").fetchone()[0] == 1
        assert c.execute("SELECT user_id FROM attempts").fetchone()[0] == 1
        assert c.execute("SELECT user_id FROM chat_messages").fetchone()[0] == 1
        co = c.execute("SELECT * FROM courses").fetchone()
        assert (co["author_id"], co["visibility"], co["published_at"]) == (1, "published", "2026-11-01T00:00:00Z")
        assert c.execute("SELECT at FROM course_opens").fetchone()[0] == "2026-11-08T00:00:00Z"
    backups = list((db.data_dir() / "backups").glob("knwlge-v2-before-upgrade-*.db"))
    assert len(backups) == 1
    old = sqlite3.connect(backups[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 2 and old.execute("SELECT count(*) FROM courses").fetchone()[0] == 1
    # the owner sees it all through the API, as before
    from app.main import app
    with TestClient(app, headers={"x-knwlge": "1"}) as tc:
        s = tc.get("/api/sessions/c1-s01").json()
        assert s["done"] and s["note"] == "note" and s["items"][0]["revealed"]
    # and the first team admin takes it over
    from app import accounts
    name, pw = accounts.add_admin("ada")
    with db.tx() as c:
        assert c.execute("SELECT username FROM users WHERE id=1").fetchone()[0] == "ada"


def test_reading_mode_is_per_person(people):
    """Reading mode hides practice for one person only; the questions still exist for everyone else."""
    author, learner = people["author"], people["learner"]
    cid = build(author)
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    sid = author.get(f"/api/courses/{cid}").json()["sessions"][1]["id"]
    assert learner.get(f"/api/courses/{cid}").json()["reading_mode"] is False
    assert learner.put(f"/api/courses/{cid}/reading", json={"on": True}).json() == {"reading_mode": True}
    mine = learner.get(f"/api/sessions/{sid}").json()
    theirs = author.get(f"/api/sessions/{sid}").json()
    assert mine["reading_mode"] is True and mine["warmup"] == []
    assert mine["items"] and len(mine["items"]) == len(theirs["items"])   # nothing deleted, only hidden by the page
    assert theirs["reading_mode"] is False
    assert next(c for c in learner.get("/api/courses").json() if c["id"] == cid)["reading_mode"] is True
    assert learner.put(f"/api/courses/{cid}/reading", json={"on": False}).json() == {"reading_mode": False}


def test_people_rename_themselves(people):
    """Anyone can change the name others see; the username they sign in with stays; it's audited."""
    learner, admin = people["learner"], people["admin"]
    assert learner.put("/api/me", json={"display_name": "   "}).status_code == 400
    r = learner.put("/api/me", json={"display_name": "  Lena   Lindgren "})
    assert r.status_code == 200 and r.json()["user"]["display_name"] == "Lena Lindgren"
    assert r.json()["user"]["username"] == "lena"
    assert learner.get("/api/me").json()["user"]["display_name"] == "Lena Lindgren"
    rows = admin.get("/api/audit", params={"action": "user.renamed_self"}).json()
    assert rows and rows[0]["details"] == {"from": "Lena", "to": "Lena Lindgren"}


def test_no_scores_only_progress(people):
    """Courses report what's been done and what's coming back, never a mastery score."""
    author = people["author"]
    cid = build(author)
    p = author.get(f"/api/courses/{cid}").json()["progress"]
    assert "mastery" not in p and {"answered", "written_done", "due_reviews"} <= set(p)
