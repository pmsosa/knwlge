"""Pictures, diagrams, video, audio, widgets and experiments: proposed by Gemini, checked and fetched by the app."""
import json

import fakes
from conftest import drain
from test_flow import make_course


def built(client, depth="dive", options=None):
    cid = client.post("/api/courses", json={"subject": "Music", "depth": depth, "options": options}).json()["id"]
    drain()
    client.post(f"/api/courses/{cid}/answers", json={"answers": {}})
    drain()
    client.post(f"/api/courses/{cid}/approve")
    drain()
    c = client.get(f"/api/courses/{cid}").json()
    return cid, c, client.get(f"/api/sessions/{c['sessions'][0]['id']}").json()


def test_every_kind_is_checked_and_fetched(client, monkeypatch):
    from app import media
    monkeypatch.setattr(media, "MAX_PER_SESSION", 7)   # the fake proposes one of each kind
    cid, c, s = built(client)
    assert c["options"] == {k: True for k in c["options"]} and len(c["options"]) == 8
    by = {m["kind"]: m for m in s["media"]}
    assert set(by) == {"mermaid", "image", "widget", "video", "audio", "illustration", "experiment"}
    assert all(m["status"] == "ready" for m in s["media"]), s["media"]
    assert by["image"]["credit"].startswith("Some Artist · Public domain") and by["image"]["has_file"]
    assert by["audio"]["source_url"].startswith("https://commons.wikimedia.org/")
    assert by["video"]["spec"] == {"id": "abc123XYZ", "start": 42} and by["video"]["has_file"]   # local thumbnail
    assert by["illustration"]["credit"] == "AI illustration (Gemini)"
    assert by["widget"]["spec"]["type"] == "plot"
    img = client.get(f"/api/media/{by['image']['id']}/file")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and "sandbox" in img.headers["content-security-policy"]
    assert client.get(f"/api/media/{by['audio']['id']}/file").headers["content-type"] == "audio/mpeg"
    exp = client.get(f"/api/media/{by['experiment']['id']}/experiment")
    csp = exp.headers["content-security-policy"]
    assert exp.status_code == 200 and "connect-src 'none'" in csp and "sandbox allow-scripts" in csp
    assert exp.headers["x-frame-options"] == "SAMEORIGIN"
    assert client.get(f"/api/media/{by['experiment']['id']}/file").status_code == 404   # never as a plain file
    assert "youtube-nocookie" in client.get("/").headers["content-security-policy"]
    # illustrations are paid calls, logged like any other
    usage = client.get("/api/usage").json()
    assert any(k["kind"] == "illustration" and k["cost"] > 0.03 for k in usage["by_kind"])
    assert len(s["outline"]) == 7 and s["outline"][0]["id"] == s["id"]


def test_options_off_means_no_media_in_schema(client):
    off = {k: False for k in ("diagrams", "images", "illustrations", "video", "audio", "widgets", "experiments")}
    cid, c, s = built(client, options=off)
    writes = [x for x in fakes.CALLS if "chunks" in x["body"]["generationConfig"].get("responseJsonSchema", {}).get("properties", {})]
    chunk = writes[0]["body"]["generationConfig"]["responseJsonSchema"]["properties"]["chunks"]["items"]
    assert "media" not in chunk["properties"]
    assert "MEDIA:" not in writes[0]["body"]["contents"][0]["parts"][0]["text"]
    assert s["media"] == []                       # the fake proposed media anyway; none of it was kept
    assert not any("responseModalities" in x["body"]["generationConfig"] for x in fakes.CALLS)


def test_partial_options_restrict_kinds(client):
    cid, c, s = built(client, options={"illustrations": False, "experiments": False})
    kinds = {m["kind"] for m in s["media"]}
    assert "illustration" not in kinds and "experiment" not in kinds and "image" in kinds
    writes = [x for x in fakes.CALLS if "chunks" in x["body"]["generationConfig"].get("responseJsonSchema", {}).get("properties", {})]
    enum = writes[0]["body"]["generationConfig"]["responseJsonSchema"]["properties"]["chunks"]["items"]["properties"]["media"]["items"]["properties"]["kind"]["enum"]
    assert "illustration" not in enum and "widget" in enum
    r = client.put(f"/api/courses/{cid}/options", json={"options": {"experiments": True}})
    assert r.json()["options"]["experiments"] is True


def test_bad_media_is_dropped_with_a_note(client):
    bad = fakes.lesson()
    bad["chunks"][0]["media"] = [fakes.m("widget", spec='{"type":"plot","expression":"fetch(1)","params":[]}'),
                                 fakes.m("video", url="https://evil.example/watch?v=abc"),
                                 fakes.m("svg", code="<script>alert(1)</script>")]
    fakes.OVERRIDES["goal"] = bad
    cid, c, s = built(client)
    kinds = [m["kind"] for m in s["media"] if m["chunk"] == 0]
    assert kinds == []
    assert sum("left out media" in w for w in s["warnings"]) == 3


def test_widget_checks():
    from app.media import check_widget
    assert check_widget({"type": "cloze", "text": "Paris is in {{France}}."}) is None
    assert check_widget({"type": "cloze", "text": "no blanks"})
    assert check_widget({"type": "order", "items": ["a", "b", "b"]})
    assert check_widget({"type": "match", "pairs": [{"left": "a", "right": "1"}, {"left": "b", "right": "2"}, {"left": "c", "right": "3"}]}) is None
    assert check_widget({"type": "plot", "expression": "a*x^2", "params": [{"name": "a", "min": 0, "max": 1, "value": 2}]})
    assert check_widget({"type": "plot", "expression": "constructor(x)", "params": []})
    assert check_widget({"type": "plot", "expression": "sin(x)+pi", "params": []}) is None


def test_youtube_ids():
    from app.media import youtube_id
    assert youtube_id("https://youtu.be/dQw4w9WgXcQ?t=3") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "dQw4w9WgXcQ"
    assert youtube_id("https://www.youtube.com.evil.net/watch?v=dQw4w9WgXcQ") is None
    assert youtube_id("javascript:alert(1)") is None


def test_rewrite_replaces_media_files(client, app_env):
    cid, c, s = built(client)
    from app import db
    before = sorted(p.name for p in (db.course_dir(cid) / "media").iterdir() if p.name.startswith(s["id"]))
    assert before
    client.post(f"/api/sessions/{s['id']}/regenerate", json={"text": ""})
    drain()
    after = client.get(f"/api/sessions/{s['id']}").json()
    assert all(m["status"] == "ready" for m in after["media"])


def test_at_most_five_media_per_session(client):
    cid, c, s = built(client)
    assert len(s["media"]) == 5
