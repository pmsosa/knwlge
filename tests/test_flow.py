"""The whole journey with a fake Gemini: create, questions, plan, approve, build, study, feedback, reading."""
import httpx

import fakes
from conftest import drain


def make_course(client, depth="dive"):
    cid = client.post("/api/courses", json={"subject": "Astronomy for fun", "notes": "", "depth": depth}).json()["id"]
    drain()
    c = client.get(f"/api/courses/{cid}").json()
    assert c["status"] == "answering", c
    assert client.post(f"/api/courses/{cid}/answers", json={"answers": {"goal": "stargazing", "level": "New"}}).status_code == 200
    drain()
    c = client.get(f"/api/courses/{cid}").json()
    assert c["status"] == "review", c
    return cid, c


def test_full_dive(client):
    cid, c = make_course(client)
    assert len(c["plan"]["sessions"]) == 7
    assert [s["kind"] for s in c["plan"]["sessions"]][-1] == "wrapup"
    assert client.post(f"/api/courses/{cid}/approve").status_code == 200
    drain()
    c = client.get(f"/api/courses/{cid}").json()
    assert c["status"] == "ready", c
    assert all(s["state"] == "ready" for s in c["sessions"])
    # reading: real book and the article and the video survive; the invented book and the private address don't
    titles = {r["title"] for r in c["reading"]}
    assert {"Real Book", "An article", "A good video"} <= titles
    assert "Invented Book" not in titles and "Sneaky" not in titles
    assert sum(1 for r in c["reading"] if r["top"] and r["session_id"] is None) == 1

    s1 = client.get(f"/api/sessions/{c['sessions'][0]['id']}").json()
    assert s1["warmup"] == []
    assert len(s1["content"]["chunks"]) == 3
    assert all(i["answer"] is None for i in s1["items"]), "answers must not reach the browser before they're earned"

    mcq = next(i for i in s1["items"] if i["qtype"] == "mcq")
    wrong = client.post(f"/api/items/{mcq['id']}/attempts", data={"answer": "Wrong"}).json()
    assert wrong["last"]["score"] == 0 and wrong["answer"] is None
    right = client.post(f"/api/items/{mcq['id']}/attempts", data={"answer": " right "}).json()
    assert right["last"]["score"] == 1 and right["answer"] == "Right"

    num = next(i for i in s1["items"] if i["qtype"] == "numeric")
    assert client.post(f"/api/items/{num['id']}/attempts", data={"answer": "22"}).json()["last"]["score"] == 1

    short = next(i for i in s1["items"] if i["qtype"] == "short")
    r = client.post(f"/api/items/{short['id']}/attempts", data={"answer": "Light scatters off air"}).json()
    assert r["last"]["status"] == "queued"
    drain()
    assert client.get(f"/api/items/{short['id']}").json()["last"]["score"] == 1

    ex = next(i for i in s1["items"] if i["qtype"] == "long")
    client.post(f"/api/items/{ex['id']}/attempts", data={"answer": "My paragraph."},
                files=[("files", ("working.png", b"\x89PNG fake", "image/png"))])
    drain()
    got = client.get(f"/api/items/{ex['id']}").json()["last"]
    fb = got["feedback"]
    # the model claimed 9 points on a 2-point criterion: capped, so 3 + 2 out of 5
    assert [l["awarded"] for l in fb["lines"]] == [3, 2]
    assert got["score"] == 1.0 and fb["level"] == "Strong"
    mark_call = fakes.CALLS[-1]["body"]
    assert any("inlineData" in p for p in mark_call["contents"][0]["parts"]), "the upload goes to Gemini inline"
    assert "<<<LEARNER_ANSWER" in mark_call["contents"][0]["parts"][0]["text"]

    # finishing session 1; the missed mcq comes back in session 2's warm-up
    client.post(f"/api/sessions/{s1['id']}/finish", json={"summary": "Stars are far."})
    s2 = client.get(f"/api/sessions/{c['sessions'][1]['id']}").json()
    assert 1 <= len(s2["warmup"]) <= 4
    prog = client.get(f"/api/courses/{cid}").json()["progress"]
    assert prog["done"] == 1 and prog["next"] == s2["id"]

    # export
    z = client.get(f"/api/courses/{cid}/export")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"

    usage = client.get("/api/usage").json()
    assert usage["month_spend"] > 0 and usage["by_course"][0]["course_id"] == cid


def test_bootcamp_has_project_and_checkpoint(client):
    cid, c = make_course(client, "bootcamp")
    kinds = [s["kind"] for s in c["plan"]["sessions"]]
    assert len(kinds) == 14 and kinds[6] == "checkpoint" and kinds[-1] == "project"
    client.post(f"/api/courses/{cid}/approve")
    drain()
    c = client.get(f"/api/courses/{cid}").json()
    proj = client.get(f"/api/sessions/{c['sessions'][-1]['id']}").json()
    assert [i["section"] for i in proj["items"]] == ["project", "project"]
    # the checkpoint is written by the pro model
    pro_calls = [x for x in fakes.CALLS if "gemini-4-argon" in x["url"]]
    assert len(pro_calls) >= 3  # plan, checkpoint, project


def test_quarter_shape():
    from app.tiers import skeleton
    s = skeleton("quarter")
    assert sum(1 for x in s if x["kind"] == "lesson") == 22
    assert len(s) == 26 and s[-1]["kind"] == "project" and s[-1]["minutes"] == 120


def test_bad_session_is_rewritten_once(client):
    cid, c = make_course(client)
    bad = fakes.lesson()
    bad["chunks"][0]["checks"][0]["answer"] = "Not an option"
    fakes.OVERRIDES["goal"] = bad
    client.post(f"/api/courses/{cid}/approve")
    drain()
    c = client.get(f"/api/courses/{cid}").json()
    s = client.get(f"/api/sessions/{c['sessions'][0]['id']}").json()
    assert s["state"] == "ready"
    assert any("isn't one of the options" in w for w in s["warnings"])
    writes = [x for x in fakes.CALLS if "chunks" in x["body"]["generationConfig"].get("responseJsonSchema", {}).get("properties", {})]
    assert len(writes) == 7 * 2  # every session drafted twice, then kept with a warning


def test_changes_and_skip(client):
    cid = client.post("/api/courses", json={"subject": "Jazz history", "depth": "dive"}).json()["id"]
    client.post(f"/api/courses/{cid}/skip-questions")
    drain()
    assert client.get(f"/api/courses/{cid}").json()["status"] == "review"
    client.post(f"/api/courses/{cid}/changes", json={"text": "More bebop please"})
    drain()
    plan_prompt = [x for x in fakes.CALLS if "exactly these" in x["body"]["contents"][0]["parts"][0]["text"]][-1]
    assert "More bebop please" in plan_prompt["body"]["contents"][0]["parts"][0]["text"]
    assert client.get(f"/api/courses/{cid}").json()["status"] == "review"


def test_rate_limit_waits_then_succeeds(client):
    fakes.OVERRIDES["questions"] = httpx.Response(429, json={"error": {"code": 429, "message": "slow down"}})
    cid = client.post("/api/courses", json={"subject": "Knots", "depth": "dive"}).json()["id"]
    drain()
    st = client.get("/api/status").json()
    assert st["waiting"][0]["wait_reason"] == "rate_limit"
    fakes.OVERRIDES.clear()
    client.post("/api/jobs/resume")
    drain()
    assert client.get(f"/api/courses/{cid}").json()["status"] == "answering"


def test_budget_cap_pauses_and_resumes(client):
    client.put("/api/settings", json={"budget_monthly_usd": 0.0001})
    cid = client.post("/api/courses", json={"subject": "Birds", "depth": "dive"}).json()["id"]
    drain()   # the first call runs (spend starts at 0) and goes over the tiny cap
    client.post(f"/api/courses/{cid}/answers", json={"answers": {}})
    drain()
    st = client.get("/api/status").json()
    assert st["over_cap"] and any(w["wait_reason"] == "budget" for w in st["waiting"])
    assert client.get(f"/api/courses/{cid}").json()["status"] == "planning"
    client.put("/api/settings", json={"clear_budget": True})
    drain()
    assert client.get(f"/api/courses/{cid}").json()["status"] == "review"


def test_chat(client):
    cid, c = make_course(client)
    client.post(f"/api/courses/{cid}/approve")
    drain()
    sid = client.get(f"/api/courses/{cid}").json()["sessions"][0]["id"]
    assert client.post("/api/chat", json={"course": cid, "scope": sid, "text": "Explain chunk 2?"}).status_code == 200
    assert client.post("/api/chat", json={"course": cid, "scope": sid, "text": "again"}).status_code == 400
    drain()
    msgs = client.get("/api/chat", params={"course": cid, "scope": sid}).json()["messages"]
    assert [m["role"] for m in msgs] == ["learner", "tutor"]


def test_edit_and_regenerate(client):
    cid, c = make_course(client)
    client.post(f"/api/courses/{cid}/approve")
    drain()
    sid = client.get(f"/api/courses/{cid}").json()["sessions"][0]["id"]
    s = client.get(f"/api/sessions/{sid}").json()
    assert client.put(f"/api/sessions/{sid}/chunks/0", json={"title": "Mine", "markdown": "My words"}).status_code == 200
    mcq = next(i for i in s["items"] if i["qtype"] == "mcq")
    assert client.put(f"/api/items/{mcq['id']}", json={"prompt": "New?", "options": ["A", "B"], "answer": "C"}).status_code == 400
    assert client.put(f"/api/items/{mcq['id']}", json={"prompt": "New?", "options": ["A", "B"], "answer": "B"}).status_code == 200
    assert client.get(f"/api/sessions/{sid}").json()["content"]["chunks"][0]["markdown"] == "My words"
    # one part rewritten by Gemini; the rest of the session stays as it was
    before = client.get(f"/api/sessions/{sid}").json()["content"]["chunks"]
    r = client.post(f"/api/sessions/{sid}/chunks/1/revise", json={"mode": "rewrite", "wish": "", "focus": ""})
    assert r.status_code == 400
    r = client.post(f"/api/sessions/{sid}/chunks/1/revise", json={"mode": "rewrite", "wish": "use an analogy", "focus": "some words"})
    assert r.status_code == 200
    assert client.get(f"/api/sessions/{sid}").json()["revising"] == [1]
    assert client.post(f"/api/sessions/{sid}/chunks/1/revise", json={"mode": "add", "wish": "x"}).status_code == 400
    assert client.post(f"/api/sessions/{sid}/chunks/9/revise", json={"mode": "add", "wish": "x"}).status_code == 400
    drain()
    after = client.get(f"/api/sessions/{sid}").json()
    assert after["revising"] == []
    assert after["content"]["chunks"][1]["markdown"] == "Clearer words, with an analogy."
    assert after["content"]["chunks"][0] == before[0]
    assert client.post(f"/api/sessions/{sid}/chunks/0/revise", json={"mode": "add", "wish": "a table"}).status_code == 200
    drain()
    assert client.get(f"/api/sessions/{sid}").json()["content"]["chunks"][0]["title"] == "Rewritten part"
    client.post(f"/api/sessions/{sid}/regenerate", json={"text": "more pictures"})
    assert client.get(f"/api/sessions/{sid}").json()["state"] == "writing"
    drain()
    assert client.get(f"/api/sessions/{sid}").json()["state"] == "ready"


def test_materials_go_to_gemini(client):
    cid = client.post("/api/courses", json={"subject": "Chess", "depth": "dive"}).json()["id"]
    r = client.post(f"/api/courses/{cid}/materials", files=[("files", ("openings.pdf", b"%PDF-1.4 fake", "application/pdf"))])
    assert r.status_code == 200
    assert client.post(f"/api/courses/{cid}/materials", files=[("files", ("evil.exe", b"MZ", "application/octet-stream"))]).status_code == 400
    client.post(f"/api/courses/{cid}/notes", json={"title": "My level", "text": "I know the rules."})
    drain()
    body = fakes.CALLS[-1]["body"]
    parts = body["contents"][0]["parts"]
    assert any(p.get("inlineData", {}).get("mimeType") == "application/pdf" for p in parts)
    assert any("I know the rules." in p.get("text", "") for p in parts)
    mats = client.get(f"/api/courses/{cid}").json()["materials"]
    assert len(mats) == 2
    assert client.get(f"/api/materials/{mats[0]['id']}").status_code == 200
    client.delete(f"/api/materials/{mats[0]['id']}")
    assert len(client.get(f"/api/courses/{cid}").json()["materials"]) == 1


def test_delete_course(client, app_env):
    cid = client.post("/api/courses", json={"subject": "Delete me", "depth": "dive"}).json()["id"]
    from app import db
    assert db.course_dir(cid).is_dir()
    assert client.delete(f"/api/courses/{cid}").status_code == 200
    assert not db.course_dir(cid).exists()
    assert client.get(f"/api/courses/{cid}").status_code == 400
