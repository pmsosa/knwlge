"""A fake Gemini: answers by looking at which schema was asked for, so the whole pipeline runs offline."""
from __future__ import annotations

import json
import re

import httpx

CALLS: list[dict] = []
SEARCH_FAILS = {"on": False}   # act like a key that can't use Google Search
OVERRIDES: dict[str, object] = {}   # schema key -> response (dict) or an httpx.Response to return as-is


def q(i: int, kind: str = "mcq") -> dict:
    if kind == "numeric":
        return {"id": f"n{i}", "type": "numeric", "prompt": f"What is {i} + {i}?", "options": [], "answer": str(2 * i),
                "explanation": "Add them.", "tolerance": 0, "topic": "adding"}
    if kind == "short":
        return {"id": f"s{i}", "type": "short", "prompt": "Why does the sky look blue?", "options": [],
                "answer": "Blue light scatters more.", "explanation": "Rayleigh scattering.", "tolerance": 0, "topic": "light"}
    return {"id": f"q{i}", "type": "mcq", "prompt": f"Pick the right one ({i})", "options": ["Right", "Wrong", "Also wrong"],
            "answer": "Right", "explanation": "Because it is.", "tolerance": 0, "topic": "basics"}


def m(kind, **kw):
    base = {"kind": kind, "caption": f"A {kind}", "code": "", "query": "", "url": "", "start_seconds": 0, "spec": ""}
    base.update(kw)
    return base


MEDIA = [
    [m("mermaid", code="flowchart LR\n  A[Pluck] --> B[Vibrate] --> C[Sound]"),
     m("image", query="Bayeux Tapestry Halley comet")],
    [m("widget", spec='{"type":"plot","expression":"a*sin(k*x)","x_min":-6,"x_max":6,"y_min":-3,"y_max":3,'
                      '"params":[{"name":"a","min":0,"max":3,"step":0.1,"value":1},{"name":"k","min":0.5,"max":4,"step":0.5,"value":1}]}'),
     m("video", url="https://www.youtube.com/watch?v=abc123XYZ", start_seconds=42)],
    [m("audio", query="King Oliver Dipper Mouth Blues 1923"), m("illustration", query="a cut-away of a castle wall"),
     m("experiment", code="<!doctype html><button id=b>Go</button><script>b.onclick=()=>b.textContent='ok'</script>")],
]


def lesson() -> dict:
    return {
        "goal": "Understand the basics", "hook": "Why it matters.",
        "chunks": [{"title": f"Idea {k}", "markdown": f"Text for idea {k} with $x^2$.", "example_markdown": "Worked example.",
                    "checks": [q(k)], "media": MEDIA[k - 1]} for k in range(1, 4)],
        "practice": [q(10), q(11, "numeric"), q(12, "short")],
        "exercises": [{"title": "Explain it", "prompt": "Explain the idea in a paragraph.",
                       "rubric": [{"criterion": "Accuracy", "points": 3, "description": "Correct"},
                                  {"criterion": "Clarity", "points": 2, "description": "Clear"}],
                       "model_answer": "A model answer."}],
        "wrapup": {"key_points": ["One", "Two", "Three"], "teaser": "Next time: more."},
        "reading": [{"kind": "video", "title": "A good video", "creator": "Some Channel",
                     "url": "https://www.youtube.com/watch?v=abc123", "isbn": "", "year": "2020", "level": "beginner",
                     "minutes": 12, "why": "Clear.", "free": True, "top": False}],
    }


def project() -> dict:
    return {"goal": "Make a thing", "intro_markdown": "Intro.", "tips_markdown": "Tips.",
            "options": [{"title": f"Option {k}", "brief_markdown": "Do this.", "deliverable": "A paragraph.",
                         "rubric": [{"criterion": "Works", "points": 5, "description": "It works"}],
                         "model_answer": "Strong answer."} for k in (1, 2)],
            "reading": []}


def respond(body: dict) -> dict:
    schema = body.get("generationConfig", {}).get("responseJsonSchema") or {}
    props = schema.get("properties", {})
    prompt = "".join(p.get("text", "") for p in body["contents"][0]["parts"])
    key = next(iter(props), "text")
    if key in OVERRIDES:
        return OVERRIDES[key]
    if "questions" in props:
        return {"questions": [{"id": "goal", "text": "What draws you to it?", "kind": "text", "options": []},
                              {"id": "level", "text": "Your level?", "kind": "choice", "options": ["New", "Some"]}]}
    if "sessions" in props:
        n = int(re.search(r"exactly these (\d+) session slots", prompt).group(1))
        return {"title": "Test Course", "summary": "A course for tests.", "prerequisites": [],
                "readiness": {"teaching": "High", "feedback": "Medium-high", "weak_spots": [], "safety_note": ""},
                "sessions": [{"slot": i, "title": f"Session {i}", "topics": ["t"], "objectives": ["o"]} for i in range(1, n + 1)],
                "tags": ["Astronomy", "science", "science"],
                "achievements": [{"title": "First star chart", "description": "Finished the first session.", "rule": "finish_session",
                                  "slot": 1},
                                 {"title": "Out of range", "description": "Points at a slot that isn't there.", "rule": "finish_session",
                                  "slot": 99}]}
    if "chunks" in props:
        return lesson()
    if "options" in props:
        return project()
    if "ok" in props and "issues" in props:
        return {"ok": True, "issues": []}
    if "criteria" in props:
        return {"criteria": [{"index": 0, "awarded": 3, "comment": "Good"}, {"index": 1, "awarded": 9, "comment": "Over"}],
                "overall": "Nice work.", "revisit": ["Clarity"]}
    if "correct" in props:
        return {"correct": "scatter" in prompt.lower(), "comment": "ok"}
    if "items" in props:
        return {"items": [
            {"kind": "book", "title": "Real Book", "creator": "A. Author", "url": "", "isbn": "9780000000001", "year": "2001",
             "level": "beginner", "minutes": 300, "why": "Classic.", "free": False, "top": True},
            {"kind": "book", "title": "Invented Book", "creator": "Nobody", "url": "", "isbn": "", "year": "", "level": "beginner",
             "minutes": 100, "why": "Made up.", "free": True, "top": False},
            {"kind": "article", "title": "An article", "creator": "Site", "url": "https://example.org/article", "isbn": "",
             "year": "", "level": "beginner", "minutes": 10, "why": "Good.", "free": True, "top": False},
            {"kind": "article", "title": "Sneaky", "creator": "", "url": "http://127.0.0.1:9000/api/x", "isbn": "", "year": "",
             "level": "beginner", "minutes": 1, "why": "", "free": True, "top": False},
        ]}
    if "markdown" in props and "example_markdown" in props:
        return {"title": "Rewritten part", "markdown": "Clearer words, with an analogy.", "example_markdown": ""}
    if "reply" in props:
        return {"reply": "Here's how it works."}
    if "message" in props:
        return {"ok": True, "message": "Welcome to learning here today!"}
    return {"text": "?"}


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    CALLS.append({"url": str(request.url), "body": body})
    if "responseModalities" in body.get("generationConfig", {}):
        import base64
        return httpx.Response(200, json={
            "candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(PNG).decode()}}]},
                            "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 1120}})
    if "tools" in body and SEARCH_FAILS["on"]:
        return httpx.Response(403, json={"error": {"code": 403, "message": "Grounding is not available on the free tier."}})
    out = respond(body)
    if isinstance(out, httpx.Response):
        return out
    grounding = {"webSearchQueries": ["q1", "q2"], "groundingChunks": [
        {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "example.org"}},
        {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "example.org"}}]} \
        if "tools" in body else {}
    return httpx.Response(200, json={
        "candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}, "finishReason": "STOP", "groundingMetadata": grounding}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 500, "thoughtsTokenCount": 100},
        "modelVersion": re.search(r"models/([^:]+):", str(request.url)).group(1),
    })


def web(request: httpx.Request) -> httpx.Response:
    """Fake internet for link checks."""
    u = str(request.url)
    if "openlibrary.org/isbn/9780000000001" in u:
        return httpx.Response(200, json={"title": "Real Book", "key": "/books/OL1M"})
    if "openlibrary.org/search.json" in u:
        return httpx.Response(200, json={"docs": []})
    if "youtube.com/oembed" in u:
        return httpx.Response(200, json={"title": "A good video", "author_name": "Some Channel"})
    if u.startswith("https://vertexaisearch.cloud.google.com/grounding-api-redirect/"):
        return httpx.Response(302, headers={"location": "https://example.org/article"})
    if u.startswith("https://commons.wikimedia.org/w/api.php"):
        audio = "filetype%3Aaudio" in u or "filetype:audio" in u
        info = {"url": "https://upload.wikimedia.org/x/orig", "descriptionurl": "https://commons.wikimedia.org/wiki/File:X",
                "mime": "audio/ogg" if audio else "image/jpeg", "thumburl": "https://upload.wikimedia.org/x/thumb.jpg",
                "derivatives": [{"src": "https://upload.wikimedia.org/x/a.mp3", "type": "audio/mpeg"}] if audio else [],
                "extmetadata": {"Artist": {"value": "<a href='x'>Some Artist</a>"}, "LicenseShortName": {"value": "Public domain"}}}
        return httpx.Response(200, json={"query": {"pages": [{"title": "File:X", "index": 1, "videoinfo": [info]}]}})
    if u.startswith("https://upload.wikimedia.org/x/thumb.jpg"):
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"0" * 100, headers={"content-type": "image/jpeg"})
    if u.startswith("https://upload.wikimedia.org/x/a.mp3"):
        return httpx.Response(200, content=b"ID3" + b"0" * 100, headers={"content-type": "audio/mpeg"})
    if u.startswith("https://i.ytimg.com/vi/"):
        return httpx.Response(200, content=b"\xff\xd8\xff" + b"1" * 50, headers={"content-type": "image/jpeg"})
    if u.startswith("https://example.org/article"):
        return httpx.Response(200, text="<html><title>An article</title></html>")
    return httpx.Response(404)


def public_dns(host, port, proto=0):
    import socket
    if host in ("127.0.0.1", "localhost"):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
