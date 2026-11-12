"""Live research: Gemini searches while planning, writing and answering; sources are kept and resolved."""
import fakes
from conftest import drain
from test_media import built


def calls_with(key):
    return [x for x in fakes.CALLS if key in x["body"]["generationConfig"].get("responseJsonSchema", {}).get("properties", {})]


def test_on_by_default_searches_and_keeps_sources(client):
    cid, c, s = built(client)
    assert c["options"]["research"] is True
    writes, plans = calls_with("chunks"), calls_with("readiness")
    assert writes and all(x["body"].get("tools") == [{"googleSearch": {}}] for x in writes)
    assert all(x["body"].get("tools") for x in plans)
    assert "LIVE RESEARCH" in writes[0]["body"]["contents"][0]["parts"][0]["text"]
    sources = [r for r in s["reading"] if r["kind"] == "source"]
    assert len(sources) == 1                                   # the duplicate chunk was dropped
    assert sources[0]["url"] == "https://example.org/article"  # the Google redirect was resolved
    assert sources[0]["title"] == "An article" and sources[0]["creator"] == "example.org"
    assert not any("Live research" in w for w in s["warnings"])
    # searches are logged for the budget
    assert client.get("/api/usage").json()["searches"] > 0


def test_off_means_no_search_except_the_reading_list(client):
    cid, c, s = built(client, options={"research": False})
    assert not any(x["body"].get("tools") for x in calls_with("chunks") + calls_with("readiness"))
    assert all(x["body"].get("tools") for x in calls_with("items"))   # the reading list always searches
    assert not [r for r in s["reading"] if r["kind"] == "source"]


def test_without_search_access_lessons_are_still_written(client):
    fakes.SEARCH_FAILS["on"] = True
    cid, c, s = built(client)
    assert c["status"] == "ready" and s["state"] == "ready"
    assert any("Live research wasn't available" in w for w in s["warnings"])
    assert not [r for r in s["reading"] if r["kind"] == "source"]
    assert c["status"] != "failed"


def test_tutor_lists_sources(client):
    cid, c, s = built(client)
    client.post("/api/chat", json={"course": cid, "scope": s["id"], "text": "What's new in this field?"})
    drain()
    reply = client.get("/api/chat", params={"course": cid, "scope": s["id"]}).json()["messages"][-1]["text"]
    assert "Sources looked at: example.org" in reply
