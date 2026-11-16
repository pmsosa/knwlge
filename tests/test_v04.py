"""v0.4: drafts and review, versions and rollback, AI edits to questions, sessions and the plan, flags, learners' courses."""
import pytest

from conftest import drain
from test_team import build, people, team  # noqa: F401  (fixtures)
from test_v03 import course, ready_course


def session(client, sid):
    return client.get(f"/api/sessions/{sid}").json()


def first_session(client, cid):
    return course(client, cid)["sessions"][0]["id"]


# ---------- versions ----------

def test_versions_and_rollback(client):
    cid = ready_course(client)
    sid = first_session(client, cid)
    original = session(client, sid)["content"]["chunks"][0]
    v0 = course(client, cid)["version"]
    for words in ("First edit", "Second edit"):
        r = client.put(f"/api/sessions/{sid}/chunks/0", json={"title": "Mine", "markdown": words, "why": "tidy"})
        assert r.json()["applied"] is True
    assert course(client, cid)["version"] == v0 + 2
    tid = f"{sid}@0:0"
    h = client.get("/api/history", params={"target": "chunk", "id": tid}).json()["versions"]
    assert [v["source"] for v in h] == ["hand", "hand", "original"] and h[0]["latest"] and h[0]["why"] == "tidy"
    assert h[-1]["data"]["markdown"] == original["markdown"]
    assert client.post(f"/api/versions/{h[-1]['id']}/restore").json()["applied"]
    assert session(client, sid)["content"]["chunks"][0]["markdown"] == original["markdown"]
    h = client.get("/api/history", params={"target": "chunk", "id": tid}).json()["versions"]
    assert h[0]["source"] == "rollback" and "version 1" in h[0]["why"] and len(h) == 4
    # a whole-course list of what changed
    hist = client.get(f"/api/courses/{cid}/changes", params={"all": 1}).json()["history"]
    assert len(hist) == 3 and hist[0]["where"] == "Session 1, part 1"


def test_answer_key_change_labels_earlier_answers(client):
    cid = ready_course(client)
    sid = first_session(client, cid)
    mcq = next(i for i in session(client, sid)["items"] if i["qtype"] == "mcq")
    client.post(f"/api/items/{mcq['id']}/attempts", data={"answer": mcq["options"][0]})
    assert session(client, sid)["items"][0]["changed_since"] is False
    # only the explanation: no label
    full = client.get(f"/api/items/{mcq['id']}/full").json()
    client.put(f"/api/items/{mcq['id']}", json={**{k: full[k] for k in ("prompt", "options", "answer")}, "explanation": "Better."})
    item = next(i for i in session(client, sid)["items"] if i["id"] == mcq["id"])
    assert item["changed_since"] is False
    # the AI rewrites the question: a draft, then live, and the earlier answer is labelled (not re-marked)
    change = client.post(f"/api/items/{mcq['id']}/revise", json={"wish": "make it clearer"}).json()["change"]
    drain()
    d = client.get(f"/api/changes/{change}").json()
    assert d["status"] == "pending" and d["after"]["answer"] == "Yes" and d["before"]["answer"] == full["answer"]
    assert client.post(f"/api/changes/{change}/accept", json={}).status_code == 200
    item = next(i for i in session(client, sid)["items"] if i["id"] == mcq["id"])
    assert item["prompt"] == "Rewritten question?" and item["changed_since"] is True
    assert item["last"]["answer"] == mcq["options"][0], "the earlier answer and its result stay"
    client.post(f"/api/items/{mcq['id']}/attempts", data={"answer": "Yes"})
    assert next(i for i in session(client, sid)["items"] if i["id"] == mcq["id"])["changed_since"] is False


def test_stale_drafts_need_a_second_look(client):
    cid = ready_course(client)
    sid = first_session(client, cid)
    change = client.post(f"/api/sessions/{sid}/chunks/0/revise", json={"wish": "simpler"}).json()["change"]
    drain()
    client.put(f"/api/sessions/{sid}/chunks/0", json={"title": "Mine", "markdown": "Changed meanwhile"})
    assert client.get(f"/api/changes/{change}").json()["stale"] is True
    r = client.post(f"/api/changes/{change}/accept", json={})
    assert r.status_code == 400 and "changed since" in r.json()["detail"]
    assert client.post(f"/api/changes/{change}/accept", json={"force": True}).status_code == 200
    # discarding
    change = client.post(f"/api/sessions/{sid}/chunks/1/revise", json={"wish": "shorter"}).json()["change"]
    drain()
    assert client.post(f"/api/changes/{change}/discard").status_code == 200
    assert client.post(f"/api/changes/{change}/accept", json={}).status_code == 400


# ---------- whole sessions ----------

def test_session_rewrite_keeps_answers_and_rolls_back(client):
    cid = ready_course(client)
    sid = first_session(client, cid)
    s = session(client, sid)
    old_ids = [i["id"] for i in s["items"]]
    mcq = next(i for i in s["items"] if i["qtype"] == "mcq")
    client.post(f"/api/items/{mcq['id']}/attempts", data={"answer": mcq["options"][0]})
    change = client.post(f"/api/sessions/{sid}/regenerate", json={"text": "more examples"}).json()["change"]
    assert [i["id"] for i in session(client, sid)["items"]] == old_ids, "the live session stays while the draft is written"
    drain()
    d = client.get(f"/api/changes/{change}").json()
    assert d["target"] == "session" and d["after"] and d["after_questions"] > 0
    client.post(f"/api/changes/{change}/accept", json={})
    s2 = session(client, sid)
    assert s2["gen"] == 1 and not set(i["id"] for i in s2["items"]) & set(old_ids)
    assert s2["progress"]["tried"] == 0, "progress counts the live questions"
    from app import db
    with db.tx() as c:
        assert c.execute("SELECT count(*) FROM attempts WHERE item_id=?", (mcq["id"],)).fetchone()[0] == 1, "answers are kept"
    # an edit to the new version, then back to the first version: the old questions and the answer return
    client.put(f"/api/sessions/{sid}/chunks/0", json={"title": "x", "markdown": "y", "gen": 1})
    assert client.put(f"/api/sessions/{sid}/chunks/0", json={"title": "x", "markdown": "y", "gen": 0}).status_code == 400
    h = client.get("/api/history", params={"target": "session", "id": sid}).json()["versions"]
    assert [v["source"] for v in h] == ["ai", "original"]
    client.post(f"/api/versions/{h[-1]['id']}/restore")
    s3 = session(client, sid)
    assert [i["id"] for i in s3["items"]] == old_ids and s3["gen"] == 0
    assert next(i for i in s3["items"] if i["id"] == mcq["id"])["last"]["answer"] == mcq["options"][0]


# ---------- the plan ----------

def test_plan_change(client):
    cid = ready_course(client)
    before = course(client, cid)["sessions"]
    last = before[-1]
    # someone started the session that's about to be removed
    client.post(f"/api/sessions/{last['id']}/finish", json={"summary": ""})
    change = client.post(f"/api/courses/{cid}/replan", json={"wish": "add one, drop the last"}).json()["change"]
    drain()
    d = client.get(f"/api/changes/{change}").json()
    assert any(x.get("new") for x in d["after"]) and any(x.get("removed") for x in d["after"])
    assert any("Earlier sessions" in n for n in d["notes"])
    client.post(f"/api/changes/{change}/accept", json={})
    c = course(client, cid)
    titles = [s["title"] for s in c["sessions"]]
    assert titles[1] == "A new session" and len(titles) == len(before) and last["id"] not in [s["id"] for s in c["sessions"]]
    assert c["earlier"] == [{"id": last["id"], "title": last["title"], "kind_label": last["kind_label"], "done": True}]
    assert c["status"] == "building"
    drain()
    c = course(client, cid)
    assert c["status"] == "ready" and all(s["state"] == "ready" for s in c["sessions"])
    # the session whose topics changed got a draft rewrite to review
    open_ = client.get(f"/api/courses/{cid}/changes").json()["changes"]
    assert [x["target"] for x in open_] == ["session"] and open_[0]["status"] == "pending"
    # and the plan can go back
    h = client.get("/api/history", params={"target": "plan", "id": cid}).json()["versions"]
    client.post(f"/api/versions/{h[-1]['id']}/restore")
    assert [s["id"] for s in course(client, cid)["sessions"]] == [s["id"] for s in before]


# ---------- review (team mode) ----------

def test_review_switch(people):
    admin, author = people["admin"], people["author"]
    cid = build(admin, "Admins' course")
    admin.post(f"/api/courses/{cid}/visibility", json={"published": True})
    sid = admin.get(f"/api/courses/{cid}").json()["sessions"][0]["id"]
    # authors edit any course; with review off it's live at once
    r = author.put(f"/api/sessions/{sid}/chunks/0", json={"title": "By Otto", "markdown": "Otto's words"})
    assert r.status_code == 200 and r.json()["applied"]
    assert author.get(f"/api/courses/{cid}").json()["updated_by"] == "Otto"
    assert author.delete(f"/api/courses/{cid}").status_code == 403, "only the owner or an admin deletes"
    assert author.post(f"/api/courses/{cid}/visibility", json={"published": False}).status_code == 403
    # review on: an author's change to someone else's course waits for the owner or an admin
    admin.put("/api/settings", json={"review_required": True})
    r = author.put(f"/api/sessions/{sid}/chunks/0", json={"title": "By Otto", "markdown": "Needs review"})
    assert r.json() == {"applied": False, "change": r.json()["change"]}
    assert session(admin, sid)["content"]["chunks"][0]["markdown"] == "Otto's words"
    assert author.post(f"/api/changes/{r.json()['change']}/accept", json={}).status_code == 400
    c = author.get(f"/api/courses/{cid}").json()
    assert c["can_publish"] is False and c["review_on"] and c["open_changes"] == 1
    ai = author.post(f"/api/sessions/{sid}/chunks/1/revise", json={"wish": "simpler", "publish_now": True}).json()["change"]
    drain()
    assert admin.get(f"/api/changes/{ai}").json()["status"] == "pending", "publish straight away needs the right to publish"
    assert admin.post(f"/api/changes/{r.json()['change']}/accept", json={}).status_code == 200
    assert session(admin, sid)["content"]["chunks"][0]["markdown"] == "Needs review"
    assert author.post(f"/api/changes/{ai}/discard").status_code == 200, "whoever asked can discard"
    # the owner's own edits stay live
    own = build(author, "Otto's own")
    osid = author.get(f"/api/courses/{own}").json()["sessions"][0]["id"]
    assert author.put(f"/api/sessions/{osid}/chunks/0", json={"title": "t", "markdown": "m"}).json()["applied"]
    # learners can't see drafts or changes
    assert people["learner"].get(f"/api/courses/{cid}/changes").status_code == 403


# ---------- learners' own courses ----------

def test_learner_courses(people):
    admin, author, learner = people["admin"], people["author"], people["learner"]
    assert learner.post("/api/courses", json={"subject": "Knots", "depth": "dive"}).status_code == 403
    assert learner.get("/api/me").json()["user"]["can_create"] is False
    admin.put("/api/settings", json={"learner_courses": True})
    assert learner.get("/api/me").json()["user"]["can_create"] is True
    cid = build(learner, "Knots")
    mine = learner.get(f"/api/courses/{cid}").json()
    assert mine["visibility"] == "draft" and mine["can_edit"] and mine["own"] and not mine["can_publish_course"]
    assert author.get(f"/api/courses/{cid}").status_code == 400, "private: authors don't see it"
    assert learner.post(f"/api/courses/{cid}/visibility", json={"published": True}).status_code == 403
    sid = mine["sessions"][0]["id"]
    assert learner.put(f"/api/sessions/{sid}/chunks/0", json={"title": "t", "markdown": "mine"}).json()["applied"]
    # suggested for everyone: authors see it and publish it; then authors can edit it too
    learner.post(f"/api/courses/{cid}/suggest", json={"on": True})
    listed = {c["id"]: c for c in author.get("/api/courses").json()}
    assert listed[cid]["suggested"] is True
    assert author.post(f"/api/courses/{cid}/visibility", json={"published": True}).status_code == 200
    assert author.put(f"/api/sessions/{sid}/chunks/0", json={"title": "t", "markdown": "edited"}).json()["applied"]
    # learners still can't touch anyone else's course
    other = build(admin, "Admins' course")
    admin.post(f"/api/courses/{other}/visibility", json={"published": True})
    osid = learner.get(f"/api/courses/{other}").json()["sessions"][0]["id"]
    assert learner.put(f"/api/sessions/{osid}/chunks/0", json={"title": "t", "markdown": "x"}).status_code == 403
    # one monthly AI allowance, the same for every learner, covering everything their own actions use
    assert learner.get("/api/me/allowance").json() == {"cap": None}
    learner.post(f"/api/sessions/{sid}/chunks/1/revise", json={"wish": "simpler"})   # queued before the allowance is set
    admin.put("/api/settings", json={"learner_cap_usd": 0.0001})
    assert admin.get("/api/settings").json()["learner_cap_usd"] == 0.0001
    a = learner.get("/api/me/allowance").json()
    assert a["cap"] == 0.0001 and a["used"] > 0, "making Knots counted"
    assert author.get("/api/me/allowance").json() == {"cap": None}, "authors and admins have no allowance"
    drain()
    from app import db
    with db.tx() as c:
        assert c.execute("SELECT wait_reason FROM jobs WHERE kind='revise' ORDER BY id DESC").fetchone()[0] == "learner_cap"
    used = "this month's AI allowance"
    r = learner.post("/api/courses", json={"subject": "More knots", "depth": "dive"})
    assert r.status_code == 400 and used in r.json()["detail"]
    # it isn't only their own courses: the tutor and written answers on anyone's course count too
    r = learner.post("/api/chat", json={"course": other, "scope": "course", "text": "Why?"})
    assert r.status_code == 400 and used in r.json()["detail"]
    s_other = session(learner, osid)
    written = next(i for i in s_other["items"] if i["qtype"] in ("short", "long"))
    assert learner.post(f"/api/items/{written['id']}/attempts", data={"answer": "words"}).status_code == 400
    mcq = next(i for i in s_other["items"] if i["qtype"] == "mcq")
    assert learner.post(f"/api/items/{mcq['id']}/attempts", data={"answer": mcq["options"][0]}).status_code == 200, \
        "quick questions don't use the AI"
    assert author.post("/api/chat", json={"course": other, "scope": "course", "text": "Why?"}).status_code == 200
    admin.put("/api/settings", json={"clear_learner_cap": True})
    drain()
    with db.tx() as c:
        assert c.execute("SELECT status FROM jobs WHERE kind='revise' ORDER BY id DESC").fetchone()[0] == "done"
    assert learner.post("/api/chat", json={"course": other, "scope": "course", "text": "Why?"}).status_code == 200


# ---------- flags ----------

def test_flags(people):
    admin, author, learner = people["admin"], people["author"], people["learner"]
    cid = build(author, "Flags 101")
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    sid = learner.get(f"/api/courses/{cid}").json()["sessions"][0]["id"]
    s = session(learner, sid)
    mcq = next(i for i in s["items"] if i["qtype"] == "mcq")
    fid = learner.post("/api/flags", json={"target": "item", "target_id": mcq["id"], "note": "The key is wrong"}).json()["id"]
    assert learner.post("/api/flags", json={"target": "item", "target_id": mcq["id"]}).status_code == 400, "once is enough"
    assert learner.get("/api/me/flags").json()["flags"][0]["status"] == "checking"
    drain()
    queue = author.get(f"/api/courses/{cid}/flags").json()["flags"]
    assert queue[0]["id"] == fid and queue[0]["verdict"] == "wrong" and queue[0]["by"] == "Lena"
    assert author.get(f"/api/courses/{cid}").json()["open_flags"] == 1
    assert learner.post(f"/api/flags/{fid}/fix", json={}).status_code == 403
    change = author.post(f"/api/flags/{fid}/fix", json={}).json()["change"]
    drain()
    d = author.get(f"/api/changes/{change}").json()
    assert d["flag_id"] == fid and "flagged" in d["wish"]
    author.post(f"/api/changes/{change}/accept", json={})
    mine = learner.get("/api/me/flags").json()["flags"][0]
    assert mine["status"] == "fixed" and "suggestion" in mine and mine["suggestion"] == ""
    # a part of the lesson, judged fine, dismissed with a reply
    f2 = learner.post("/api/flags", json={"target": "chunk", "target_id": f"{sid}@0:0", "note": "looks fine maybe?"}).json()["id"]
    drain()
    assert author.get(f"/api/courses/{cid}/flags").json()["flags"][0]["verdict"] == "right"
    author.post(f"/api/flags/{f2}/dismiss", json={"reply": "It's right: see the example."})
    assert learner.get("/api/me/flags").json()["flags"][0]["reply"] == "It's right: see the example."
    # feedback on a written answer is marked again
    written = next(i for i in s["items"] if i["qtype"] in ("short", "long"))
    learner.post(f"/api/items/{written['id']}/attempts", data={"answer": "Because of scattering of light"})
    drain()
    att = session(learner, sid)
    att_id = next(i for i in att["items"] if i["id"] == written["id"])["last"]["id"]
    f3 = learner.post("/api/flags", json={"target": "feedback", "target_id": str(att_id), "note": "unfair"}).json()["id"]
    assert admin.post("/api/flags", json={"target": "feedback", "target_id": str(att_id)}).status_code == 400, "only your own"
    drain()
    assert author.post(f"/api/flags/{f3}/fix", json={}).json() == {"remarked": True}
    drain()
    # a reading item is taken out
    reading = learner.get(f"/api/courses/{cid}").json()["reading"]
    if reading:
        f4 = learner.post("/api/flags", json={"target": "reading", "target_id": str(reading[0]["id"])}).json()["id"]
        drain()
        author.post(f"/api/flags/{f4}/fix", json={})
        assert reading[0]["id"] not in [r["id"] for r in learner.get(f"/api/courses/{cid}").json()["reading"]]
    assert author.get(f"/api/courses/{cid}/flags").json()["flags"] == []
    assert len(author.get(f"/api/courses/{cid}/flags", params={"all": 1}).json()["flags"]) >= 3


def test_session_rewrite_gets_second_read_through(client):
    import fakes
    cid = ready_course(client)
    sid = first_session(client, cid)
    fakes.CALLS.clear()
    fakes.OVERRIDES["ok"] = {"ok": False, "issues": [{"where": "practice q1", "problem": "The answer is wrong", "severity": "major"}]}
    change = client.post(f"/api/sessions/{sid}/regenerate", json={"text": "more examples"}).json()["change"]
    drain()
    redo = [x for x in fakes.CALLS if "chunks" in x["body"]["generationConfig"].get("responseJsonSchema", {}).get("properties", {})]
    assert len(redo) == 2 and "practice q1: The answer is wrong" in "".join(
        p.get("text", "") for p in redo[-1]["body"]["contents"][0]["parts"]), "one more try with what the reader found"
    d = client.get(f"/api/changes/{change}").json()
    assert d["status"] == "pending" and d["after"]
    assert "Second read-through: practice q1: The answer is wrong" in d["notes"], "still wrong after the retry: it says so"
    # a reader that's happy lets the draft through with no notes
    client.post(f"/api/changes/{change}/discard", json={})
    fakes.OVERRIDES.pop("ok")
    change = client.post(f"/api/sessions/{sid}/regenerate", json={"text": "fewer examples"}).json()["change"]
    drain()
    d = client.get(f"/api/changes/{change}").json()
    assert d["status"] == "pending" and not any("read-through" in n for n in d["notes"])
