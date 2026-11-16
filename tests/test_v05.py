"""Recommending courses, the welcome and the upload reminder, and what an owner's courses cost."""
from test_team import build, people, team  # noqa: F401  (fixtures)
from test_v03 import course, ready_course


def home(c, cid):
    return next(x for x in c.get("/api/courses").json() if x["id"] == cid)


def test_recommending(people):
    learner, author, admin = people["learner"], people["author"], people["admin"]
    cid = build(author)
    lena = next(p for p in author.get(f"/api/courses/{cid}/recommendations").json()["people"] if p["name"] == "Lena")
    # only published courses, only authors and admins
    assert author.post(f"/api/courses/{cid}/recommendations", json={"to": [lena["id"]]}).status_code == 400
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    assert course(author, cid)["can_recommend"] and not course(learner, cid)["can_recommend"]
    assert learner.post(f"/api/courses/{cid}/recommendations", json={"everyone": True}).status_code == 403
    assert learner.get(f"/api/courses/{cid}/recommendations").status_code == 403
    assert author.post(f"/api/courses/{cid}/recommendations", json={"to": []}).status_code == 400
    assert author.post(f"/api/courses/{cid}/recommendations", json={"to": [99999]}).status_code == 400
    assert home(learner, cid)["recommended"] is None
    r = author.post(f"/api/courses/{cid}/recommendations", json={"to": [lena["id"]], "note": "  Great  for beginners "}).json()
    assert r["added"] == 1 and r["recommendations"][0]["to"] == "Lena"
    rec = home(learner, cid)["recommended"]
    assert rec["by"] == "Otto" and rec["note"] == "Great for beginners" and not rec["everyone"]
    assert home(admin, cid)["recommended"] is None, "only to the people it was for"
    # dismissing hides it; a newer one (here, for everyone) shows again
    learner.post(f"/api/courses/{cid}/recommendations/dismiss")
    assert home(learner, cid)["recommended"] is None
    import time
    time.sleep(1.1)
    author.post(f"/api/courses/{cid}/recommendations", json={"everyone": True})
    assert home(learner, cid)["recommended"]["everyone"] and home(admin, cid)["recommended"]["by"] == "Otto"
    assert home(author, cid)["recommended"] is None, "not your own recommendation"
    # recommending everyone again replaces it rather than adding another
    author.post(f"/api/courses/{cid}/recommendations", json={"everyone": True, "note": "again"})
    recs = author.get(f"/api/courses/{cid}/recommendations").json()["recommendations"]
    assert [x["to"] for x in recs] == ["Everyone", "Lena"] and recs[0]["note"] == "again"
    # taking it back: whoever made it, or an admin
    assert learner.delete(f"/api/recommendations/{recs[0]['id']}").status_code == 400
    assert admin.delete(f"/api/recommendations/{recs[0]['id']}").status_code == 200
    assert home(learner, cid)["recommended"] is None, "Lena dismissed the older one to her"
    # a course taken back to draft isn't recommended to anyone
    author.post(f"/api/courses/{cid}/recommendations", json={"to": [lena["id"]]})
    author.post(f"/api/courses/{cid}/visibility", json={"published": False})
    assert cid not in [x["id"] for x in learner.get("/api/courses").json()]


def test_recommending_is_team_only(client):
    cid = ready_course(client)
    assert client.post(f"/api/courses/{cid}/recommendations", json={"everyone": True}).status_code == 400
    assert course(client, cid)["can_recommend"] is False


def test_welcome_and_upload_note(people):
    learner, admin = people["learner"], people["admin"]
    me = learner.get("/api/me").json()
    assert "Welcome to Knwlge" in me["welcome"] and "passwords" in me["upload_note"]
    learner.post("/api/me/welcomed", json={})
    assert "welcome" not in learner.get("/api/me").json()
    assert "Welcome" in learner.post("/api/me/welcomed", json={"seen": False}).json()["welcome"], "asked for it again"
    learner.post("/api/me/welcomed", json={})
    # an admin changes the words
    assert learner.put("/api/settings", json={"upload_note": "x"}).status_code == 403
    s = admin.put("/api/settings", json={"welcome_text": "# Hello team", "upload_note": "No secrets, please."}).json()
    assert s["welcome_text"] == "# Hello team" and s["upload_note"] == "No secrets, please."
    me = learner.get("/api/me").json()
    assert me["upload_note"] == "No secrets, please." and "welcome" not in me, "a new text doesn't show again by itself"
    admin.put("/api/settings", json={"welcome_again": True})
    assert learner.get("/api/me").json()["welcome"] == "# Hello team"
    assert admin.put("/api/settings", json={"upload_note": "x" * 301}).status_code == 400
    s = admin.put("/api/settings", json={"welcome_text": "", "upload_note": ""}).json()
    assert s["welcome_text"] == s["texts_default"]["welcome_text"] and "passwords" in s["upload_note"]


def test_owners_see_what_their_course_costs(people):
    learner, author, admin = people["learner"], people["author"], people["admin"]
    cid = build(author)
    author.post(f"/api/courses/{cid}/visibility", json={"published": True})
    a = course(author, cid)
    assert a["spend"] > 0 and a["spend_month"] == a["spend"]
    assert course(admin, cid)["spend"] == a["spend"]
    assert "spend" not in course(learner, cid)
    other = build(admin, "Glass 101")
    admin.post(f"/api/courses/{other}/visibility", json={"published": True})
    assert "spend" not in course(author, other), "another author's course: no cost shown"
