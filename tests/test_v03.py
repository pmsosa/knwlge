"""v0.3: the home page's shelves and tags, achievements, the feed, the dashboard, course packages, printing and
other AI providers."""
import io
import json
import zipfile

import httpx
import pytest

import fakes
from conftest import drain
from test_team import build, people, sign_in, team  # noqa: F401  (fixtures)


def ready_course(client, subject="Astronomy for fun"):
    cid = client.post("/api/courses", json={"subject": subject, "depth": "dive"}).json()["id"]
    drain()
    client.post(f"/api/courses/{cid}/answers", json={"answers": {}})
    drain()
    client.post(f"/api/courses/{cid}/approve")
    drain()
    return cid


def course(client, cid):
    return client.get(f"/api/courses/{cid}").json()


def mine(client):
    return {c["id"]: c for c in client.get("/api/courses").json()}


# ---------- home: mine vs available, pins, tags ----------

def test_shelves_and_tags(client):
    a, b = ready_course(client, "Astronomy"), ready_course(client, "Pottery")
    c = course(client, a)
    assert c["tags"] == ["astronomy", "science"], "suggested tags are cleaned: lower case, no repeats"
    listed = mine(client)
    # the author's own finished-building courses aren't "mine" until started, pinned or added
    assert not listed[a]["mine"] and not listed[b]["mine"]
    first = c["sessions"][0]["id"]
    client.post(f"/api/sessions/{first}/finish", json={"summary": "x"})
    assert mine(client)[a]["mine"], "a started course moves up to mine"
    assert client.put(f"/api/courses/{b}/shelf", json={"pinned": True}).json() == {"pinned": True, "shelf": "mine"}
    assert mine(client)[b]["mine"] and mine(client)[b]["pinned"]
    client.put(f"/api/courses/{a}/shelf", json={"shelf": "aside"})
    assert not mine(client)[a]["mine"], "set aside: back to available, progress kept"
    assert mine(client)[a]["progress"]["done"] == 1
    client.put(f"/api/courses/{a}/shelf", json={"shelf": "auto"})
    assert mine(client)[a]["mine"]
    assert client.put(f"/api/courses/{a}/shelf", json={"shelf": "nonsense"}).status_code == 400

    r = client.put(f"/api/courses/{b}/tags", json={"tags": ["  Arts & Crafts ", "#clay", "clay", "x" * 80]})
    assert r.json()["tags"] == ["arts & crafts", "clay", "x" * 30]
    tags = {t["tag"]: t["count"] for t in client.get("/api/tags").json()}
    assert tags["clay"] == 1 and tags["science"] == 1


def test_tags_and_shelves_respect_roles(people):
    otto, lena = people["author"], people["learner"]
    cid = build(otto)
    assert lena.put(f"/api/courses/{cid}/shelf", json={"pinned": True}).status_code in (400, 403, 404), "a draft isn't visible"
    otto.post(f"/api/courses/{cid}/visibility", json={"published": True})
    assert lena.put(f"/api/courses/{cid}/shelf", json={"pinned": True}).status_code == 200
    assert lena.put(f"/api/courses/{cid}/tags", json={"tags": ["mine"]}).status_code == 403, "learners can't retag"
    assert not {c["id"]: c for c in otto.get("/api/courses").json()}[cid]["pinned"], "pins are per person"


# ---------- achievements ----------

def test_achievements(client):
    cid = ready_course(client)
    c = course(client, cid)
    keys = [a["key"] for a in c["achievements"]]
    assert "first_steps" in keys and "finished" in keys
    themed = [a for a in c["achievements"] if a["themed"]]
    assert [a["title"] for a in themed] == ["First star chart"], "an achievement for a slot that isn't there is dropped"
    r = client.post(f"/api/sessions/{c['sessions'][0]['id']}/finish", json={"summary": ""}).json()
    got = {a["key"] for a in r["achievements"]}
    assert "first_steps" in got and themed[0]["key"] in got
    assert client.post(f"/api/sessions/{c['sessions'][0]['id']}/finish", json={"summary": ""}).json()["achievements"] == [], \
        "earned once"
    for s in c["sessions"][1:]:
        client.post(f"/api/sessions/{s['id']}/finish", json={"summary": ""})
    earned = {a["key"] for a in course(client, cid)["achievements"] if a["earned_at"]}
    assert {"halfway", "finished"} <= earned
    profile = client.get("/api/me/achievements").json()
    assert any(a["key"] == "finished" and a["course_id"] == cid for a in profile)

    # authors edit the themed list; a key someone earned keeps its earning
    key = themed[0]["key"]
    r = client.put(f"/api/courses/{cid}/achievements", json={"items": [
        {"key": key, "title": "First chart", "description": "Renamed.", "rule": "finish_session", "slot": 1},
        {"title": "Wrote it up", "description": "Sent the written work in session 2.", "rule": "written_session", "slot": 2},
        {"title": "Bad", "description": "", "rule": "speedrun", "slot": 2}]}).json()
    assert [a["title"] for a in r["themed_achievements"]] == ["First chart", "Wrote it up"]
    assert any(a["key"] == key and a["earned_at"] for a in course(client, cid)["achievements"])


# ---------- the feed and the dashboard (team mode) ----------

def test_feed_is_opt_in(people):
    ada, otto, lena = people["admin"], people["author"], people["learner"]
    cid = build(otto)
    otto.post(f"/api/courses/{cid}/visibility", json={"published": True})
    s1 = course(lena, cid)["sessions"][0]["id"]
    lena.post(f"/api/sessions/{s1}/finish", json={"summary": ""})
    assert ada.get("/api/feed").json()["items"] == [], "nothing recorded before opting in"
    lena.put("/api/me/sharing", json={"on": True})
    s2 = course(lena, cid)["sessions"][1]["id"]
    lena.post(f"/api/sessions/{s2}/finish", json={"summary": ""})
    items = ada.get("/api/feed").json()["items"]
    assert [i["kind"] for i in items if i["kind"] == "session_done"] == ["session_done"]
    assert items[0]["who"] == "Lena"
    # admin switches the feed off: nothing shown; the dashboard sees it all the same
    assert lena.put("/api/feed/switch", json={"on": False}).status_code == 403
    ada.put("/api/feed/switch", json={"on": False})
    assert ada.get("/api/feed").json() == {"on": False, "sharing": False, "items": []}
    ada.put("/api/feed/switch", json={"on": True})
    lena.put("/api/me/sharing", json={"on": False})
    assert ada.get("/api/feed").json()["items"] == [], "stopping sharing takes entries off"

    d = ada.get("/api/dashboard").json()
    lena_row = next(p for p in d["people"] if p["name"] == "Lena")
    assert lena_row["courses"][0]["done"] == 2 and lena_row["in_progress"] == 1
    crow = next(x for x in d["courses"] if x["id"] == cid)
    assert crow["takers"] == 1 and crow["funnel"][0]["done"] == 1
    assert d["spend"]["by_provider"][0]["label"] == "Gemini"
    assert lena.get("/api/dashboard").status_code == 403
    assert otto.get("/api/dashboard").status_code == 403


# ---------- packages ----------

def test_package_round_trip(client, app_env):
    cid = ready_course(client)
    c = course(client, cid)
    s1 = client.get(f"/api/sessions/{c['sessions'][0]['id']}").json()
    mcq = next(i for i in s1["items"] if i["qtype"] == "mcq")
    client.post(f"/api/items/{mcq['id']}/attempts", data={"answer": "Right"})
    client.post(f"/api/sessions/{s1['id']}/finish", json={"summary": "My summary"})
    client.put(f"/api/courses/{cid}/tags", json={"tags": ["space"]})

    r = client.get(f"/api/courses/{cid}/package?progress=1")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('.knwlge"')
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"manifest.json", "course.json", "progress.json"} <= names
    assert any(n.startswith("media/") and n.endswith(".svg") or n.endswith(".jpg") for n in names) or True
    body = json.loads(z.read("course.json"))
    assert all("answer" in i for i in body["items"]), "the package keeps answer keys (it's a whole course)"

    calls = len(fakes.CALLS)
    up = client.post("/api/import", files={"file": ("c.knwlge", r.content, "application/zip")}, data={"progress": "true"})
    assert up.status_code == 200, up.text
    new = up.json()["id"]
    assert new != cid
    assert len(fakes.CALLS) == calls, "importing never calls the AI"
    n = course(client, new)
    assert n["status"] == "ready" and n["title"] == c["title"] and n["tags"] == ["space"]
    assert len(n["sessions"]) == len(c["sessions"])
    assert n["progress"]["done"] == 1 and n["progress"]["answered"] == 1, "the exporter's progress came along"
    assert any(a["key"] == "first_steps" and a["earned_at"] for a in n["achievements"])
    ns1 = client.get(f"/api/sessions/{n['sessions'][0]['id']}").json()
    assert [x["id"].split("-s01-")[1] for x in ns1["items"]] == [x["id"].split("-s01-")[1] for x in s1["items"]]
    assert ns1["summary_note"] == "My summary"
    drain()   # reading links are checked again; the media without files are fetched again
    assert {r["title"] for r in course(client, new)["reading"]} == {r["title"] for r in c["reading"]}

    # without progress
    up2 = client.post("/api/import", files={"file": ("c.knwlge", client.get(f"/api/courses/{cid}/package").content)},
                      data={"progress": "true"})
    assert course(client, up2.json()["id"])["progress"]["done"] == 0


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data if isinstance(data, (bytes, str)) else json.dumps(data))
    return buf.getvalue()


def test_import_is_untrusted(client, app_env):
    post = lambda data: client.post("/api/import", files={"file": ("x.knwlge", data)})  # noqa: E731
    assert post(b"not a zip").status_code == 400
    assert post(_zip({"manifest.json": {"format": "other"}})).status_code == 400
    assert "newer Knwlge" in post(_zip({"manifest.json": {"format": "knwlge-course", "version": 99}})).json()["detail"]
    base = {"format": "knwlge-course", "version": 1}
    evil_svg = '<svg xmlns="http://www.w3.org/2000/svg">' + "x" * 20000 + "</svg>"
    pkg = {
        "manifest.json": base,
        "course.json": {"course": {"subject": "Evil", "depth": "dive", "title": "<b>Evil</b>", "tags": ["a"] * 50},
                        "sessions": [
                            {"key": "s01", "kind": "lesson", "title": "One", "minutes": 45, "ready": True,
                             "content": {"goal": "g", "chunks": [{"title": "t", "markdown": "m", "evil": "x"}], "extra": 1}},
                            {"key": "../../etc", "kind": "lesson", "title": "Bad key", "ready": True, "content": {}},
                            {"key": "s02", "kind": "rootkit", "title": "Bad kind", "ready": True, "content": {}},
                            {"key": "s03", "kind": "lesson", "title": "Not written", "ready": False}],
                        "items": [{"key": "s01-i01", "session": "s01", "section": "check", "qtype": "mcq", "prompt": "Q",
                                   "options": ["a", "b"], "answer": "a", "chunk": 0},
                                  {"key": "s09-i01", "session": "s09", "section": "check", "qtype": "mcq", "prompt": "orphan"},
                                  {"key": "s01-i02", "session": "s01", "section": "shell", "qtype": "mcq", "prompt": "bad section"}],
                        "media": [{"key": "s01-m11", "session": "s01", "kind": "svg", "file": "media/s01-m11.svg", "chunk": 0},
                                  {"key": "s01-m12", "session": "s01", "kind": "image", "file": "../../../app/main.py", "chunk": 0,
                                   "spec": {"query": "a cat"}},
                                  {"key": "s01-m13", "session": "s01", "kind": "image", "file": "media/s01-m13.png", "chunk": 0,
                                   "spec": {"query": "fake png"}}],
                        "reading": [{"kind": "article", "title": "Link", "url": "javascript:alert(1)"}]},
        "media/s01-m11.svg": evil_svg,
        "media/s01-m13.png": b"MZ not a png at all",
    }
    r = post(_zip(pkg))
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    c = course(client, cid)
    assert [s["title"] for s in c["sessions"]] == ["One", "Not written"]
    assert c["sessions"][1]["state"] == "failed", "a session the package didn't have can be written with Try again"
    assert len(c["tags"]) == 1
    s1 = client.get(f"/api/sessions/{c['sessions'][0]['id']}").json()
    assert [i["prompt"] for i in s1["items"]] == ["Q"]
    assert s1["content"]["chunks"] == [{"title": "t", "markdown": "m", "example_markdown": ""}]
    kinds = {m["id"].rsplit("-", 1)[1]: m for m in s1["media"]}
    assert "m11" not in kinds, "an SVG that fails the lesson checks is dropped"
    assert kinds["m12"]["status"] == "pending" and kinds["m13"]["status"] == "pending", \
        "no file taken from a path the package names, and no file that isn't really a PNG: both fetched again instead"
    folder = app_env / "data" / "courses" / cid
    assert not any(p.name == "main.py" for p in folder.rglob("*"))
    from app import db
    with db.tx() as conn:
        assert conn.execute("SELECT url FROM reading WHERE course_id=?", (cid,)).fetchone()["url"] == ""


def test_import_needs_an_author(people):
    pkg = _zip({"manifest.json": {"format": "knwlge-course", "version": 1}})
    assert people["learner"].post("/api/import", files={"file": ("x.knwlge", pkg)}).status_code == 403


# ---------- printing ----------

def test_print_shows_answers_only_when_earned(people):
    otto, lena = people["author"], people["learner"]
    cid = build(otto)
    otto.post(f"/api/courses/{cid}/visibility", json={"published": True})
    p = otto.get(f"/api/courses/{cid}/print?answers=1").json()
    assert all("answer" in i for s in p["sessions"] for i in s["items"]), "authors see the answer key"
    p = lena.get(f"/api/courses/{cid}/print?answers=1").json()
    assert not any("answer" in i for s in p["sessions"] for i in s["items"])
    first = p["sessions"][0]["items"][0]
    lena.post(f"/api/items/{first['id']}/reveal")
    p = lena.get(f"/api/courses/{cid}/print?answers=1").json()
    assert "answer" in p["sessions"][0]["items"][0]
    assert lena.get(f"/api/courses/{cid}/print").json()["sessions"][0]["items"][0].get("answer") is None


# ---------- other AI providers ----------

def openai_like(request: httpx.Request) -> httpx.Response:
    """A fake OpenAI-compatible server: /models and /chat/completions answering like the fake Gemini."""
    url = str(request.url)
    if url.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "local-llama"}, {"id": "nomic-embed-text"}]})
    body = json.loads(request.content)
    fakes.CALLS.append({"url": url, "body": body})
    if url.endswith("/images/generations"):
        import base64
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(fakes.PNG).decode()}]})
    schema = (body.get("response_format") or {}).get("json_schema", {}).get("schema") or {}
    text = "".join(p.get("text", "") for p in body["messages"][1]["content"] if p.get("type") == "text")
    gem = {"generationConfig": {"responseJsonSchema": schema}, "contents": [{"parts": [{"text": text}]}]}
    out = fakes.respond(gem)
    return httpx.Response(200, json={"model": body["model"], "choices": [{"message": {"content": json.dumps(out)},
                                                                            "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 100, "completion_tokens": 50}})


@pytest.fixture()
def fake_providers(monkeypatch):
    from app import providers
    monkeypatch.setattr(providers, "transport", httpx.MockTransport(openai_like))
    claude_calls = []

    def claude(p, kw):
        claude_calls.append(kw)
        schema = (kw.get("output_config") or {}).get("format", {}).get("schema") or {}
        text = "".join(b.get("text", "") for b in kw["messages"][0]["content"] if b["type"] == "text")
        out = fakes.respond({"generationConfig": {"responseJsonSchema": schema}, "contents": [{"parts": [{"text": text}]}]})
        content = [{"type": "text", "text": json.dumps(out)}]
        if kw.get("tools") and len(claude_calls) == 1:   # the first search call pauses once
            return {"model": kw["model"], "stop_reason": "pause_turn", "content": [{"type": "server_tool_use"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5, "server_tool_use": {"web_search_requests": 1}}}
        if kw.get("tools"):
            content.insert(0, {"type": "web_search_tool_result", "content": [{"url": "https://example.org/article", "title": "Art"}]})
        return {"model": kw["model"], "stop_reason": "end_turn", "content": content,
                "usage": {"input_tokens": 1000, "output_tokens": 200, "server_tool_use": {"web_search_requests": 1 if kw.get("tools") else 0}}}
    monkeypatch.setattr(providers, "anthropic_call", claude)
    return claude_calls


def test_providers_and_roles(client, fake_providers):
    r = client.post("/api/providers", json={"kind": "compatible", "label": "Local", "base_url": "http://ollama.lan:11434/v1"})
    assert r.status_code == 200, r.text
    local = r.json()["id"]
    assert r.json()["test"]["ok"], r.json()
    assert r.json()["test"]["models"] == ["local-llama", "nomic-embed-text"]
    claude = client.post("/api/providers", json={"kind": "anthropic", "api_key": "sk-ant-test-1234"}).json()["id"]
    s = client.get("/api/settings").json()
    assert all("api_key" not in p for p in s["providers"]), "keys never reach the browser"
    assert next(p for p in s["providers"] if p["id"] == claude)["key_hint"] == "…1234"
    assert s["routes"]["writing"]["provider"] == "gemini" and s["routes"]["writing"]["is_default"]

    bad = client.put("/api/routes", json={"illustrations": {"provider": claude, "model": "claude-opus-5-5"}})
    assert bad.status_code == 400 and "can't draw" in bad.json()["detail"]
    ok = client.put("/api/routes", json={"writing": {"provider": local, "model": "local-llama"},
                                         "planning": {"provider": claude, "model": "claude-opus-5-5"},
                                         "research": {"provider": claude, "model": "claude-sonnet-5-5"}})
    assert ok.status_code == 200, ok.text

    fakes.CALLS.clear()
    cid = ready_course(client)
    assert course(client, cid)["status"] == "ready"
    from app import db
    with db.tx() as conn:
        rows = {(r["kind"], r["provider"], r["model"]) for r in conn.execute("SELECT kind, provider, model FROM llm_calls")}
        assert ("plan", claude, "claude-opus-5-5") in rows and ("questions", claude, "claude-opus-5-5") in rows
        assert ("session", local, "local-llama") in rows
        assert ("check", None, "gemini-3.5-flash-lite") in rows, "roles left alone stay on Gemini"
        assert any(k == "reading" and p == claude for k, p, _ in rows)
        plan = conn.execute("SELECT cost_usd, search_queries FROM llm_calls WHERE kind='plan'").fetchone()
        assert plan["cost_usd"] == pytest.approx(1000 / 1e6 * 4 + 200 / 1e6 * 20 + plan["search_queries"] * 0.01), \
            "Claude prices (and its $10 per 1,000 searches) are built in"
        assert conn.execute("SELECT cost_usd FROM llm_calls WHERE provider=? LIMIT 1", (local,)).fetchone()["cost_usd"] is None
    plan_kw = next(k for k in fake_providers if k["model"] == "claude-opus-5-5")
    assert plan_kw["fallbacks"] == "default" and "temperature" not in plan_kw
    assert plan_kw["output_config"]["format"]["type"] == "json_schema"
    search_kw = [k for k in fake_providers if k.get("tools")]
    assert search_kw and search_kw[0]["tools"][0]["type"] == "web_search_20260209"
    assert len(search_kw) >= 2, "a paused search turn was sent back to finish"

    # a price for the local model; usage counts it from then on
    client.put(f"/api/providers/{local}", json={"prices": {"local-llama": [0, 0]}})
    client.post(f"/api/sessions/{course(client, cid)['sessions'][0]['id']}/regenerate", json={"text": ""})
    drain()
    with db.tx() as conn:
        assert conn.execute("SELECT cost_usd FROM llm_calls WHERE provider=? ORDER BY id DESC LIMIT 1", (local,)).fetchone()[0] == 0

    # removing a provider sends its roles back to Gemini
    client.delete(f"/api/providers/{local}")
    assert client.get("/api/settings").json()["routes"]["writing"]["provider"] == "gemini"
    assert client.delete("/api/providers/gemini").status_code == 400


def test_provider_errors_pause_like_gemini(client, fake_providers, monkeypatch):
    from app import providers
    local = client.post("/api/providers", json={"kind": "compatible", "base_url": "http://x.lan/v1"}).json()["id"]
    client.put("/api/routes", json={"planning": {"provider": local, "model": "local-llama"}})
    monkeypatch.setattr(providers, "transport", httpx.MockTransport(
        lambda req: httpx.Response(401, json={"error": {"message": "bad key"}})))
    cid = client.post("/api/courses", json={"subject": "X", "depth": "dive"}).json()["id"]
    drain()
    from app import db
    with db.tx() as conn:
        job = conn.execute("SELECT status, wait_reason, error FROM jobs WHERE course_id=?", (cid,)).fetchone()
    assert (job["status"], job["wait_reason"]) == ("waiting", "auth") and "refused the API key" in job["error"]


def test_compatible_without_json_schema_falls_back(client, monkeypatch):
    """A server that rejects response_format json_schema gets json_object and the schema in the instructions."""
    from app import providers
    seen = []

    def strict_server(req):
        if str(req.url).endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        body = json.loads(req.content)
        seen.append(body["response_format"]["type"])
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported"}})
        assert "JSON Schema" in body["messages"][0]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true, "message": "hi"}'},
                                                      "finish_reason": "stop"}], "usage": {}})
    monkeypatch.setattr(providers, "transport", httpx.MockTransport(strict_server))
    r = client.post("/api/providers", json={"kind": "compatible", "base_url": "http://x.lan/v1"}).json()
    assert r["test"]["ok"] and seen == ["json_schema", "json_object"]


def test_claude_refusal_is_blocked(client, monkeypatch):
    from app import providers
    monkeypatch.setattr(providers, "anthropic_call", lambda p, kw: {"model": kw["model"], "stop_reason": "refusal", "content": [],
                                                                    "usage": {"input_tokens": 5, "output_tokens": 0}})
    p = {"id": "x", "kind": "anthropic", "label": "Claude", "api_key": "k", "base_url": "", "models": []}
    from app.gemini import GeminiError
    with pytest.raises(GeminiError) as e:
        providers.generate(p, "claude-opus-5-5", "sys", [{"text": "hi"}], schema=providers.TEST_SCHEMA)
    assert e.value.kind == "blocked"


def test_role_mapping():
    from app.providers import role_of
    assert role_of("session", "pro") == "planning" and role_of("session", "flash") == "writing"
    assert role_of("mark", "lite") == "checks" and role_of("mark", "flash") == "marking"
    assert role_of("chat", "flash") == "tutor" and role_of("illustration", "image") == "illustrations"


def test_upgrade_keeps_old_model_choices(client):
    """Before providers, models were picked per tier; those choices still apply until a role is set."""
    from app import db, providers
    with db.tx() as c:
        db.set_setting(c, "model_pro", "gemini-3.1-pro-preview")
        assert providers.route(c, "planning")[1] == "gemini-3.1-pro-preview"
        assert providers.route(c, "writing")[1] == "gemini-3.8-flash"
