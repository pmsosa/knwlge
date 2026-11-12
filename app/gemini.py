"""A small client for Gemini's generateContent REST endpoint.

Structured output uses `responseJsonSchema` (standard JSON Schema). PDFs and images go in the request as inline
bytes, so the model never reads anything from disk. Google Search grounding is a tool on the same call; if a model
refuses search + schema together, the call falls back to search first, then a separate structuring call.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

API_URL = os.environ.get(
    "GEMINI_API_URL", "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
TIMEOUT = httpx.Timeout(300.0, connect=20.0)

# Tests swap this for an httpx.MockTransport.
transport: httpx.BaseTransport | None = None


class GeminiError(Exception):
    """kind: rate_limit and server are worth retrying later; the rest are not."""

    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.kind in ("rate_limit", "server", "network")


@dataclass
class Result:
    data: Any
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    search_queries: int = 0
    sources: list[dict] = field(default_factory=list)  # [{"uri", "title"}] from grounding
    searched: bool = False                              # did this result use Google Search
    search_note: str = ""                               # why search was skipped, when it was asked for and unavailable
    calls: list[dict] = field(default_factory=list)    # one entry per HTTP call, for cost logging

    def add(self, other: "Result") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.thinking_tokens += other.thinking_tokens
        self.search_queries += other.search_queries
        self.sources += other.sources
        self.calls += other.calls


def text_part(text: str) -> dict:
    return {"text": text}


def file_part(data: bytes, mime: str) -> dict:
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport)


def _error_from(resp: httpx.Response) -> GeminiError:
    try:
        err = resp.json().get("error", {})
        msg = err.get("message") or resp.text[:300]
    except ValueError:
        msg = resp.text[:300]
    s = resp.status_code
    if s == 429:
        return GeminiError("rate_limit", f"Gemini rate or spend limit reached: {msg}", s)
    if s == 402:
        return GeminiError("quota", f"Gemini says the prepaid credit is used up: {msg}", s)
    if s in (401, 403):
        return GeminiError("auth", f"Gemini refused the API key: {msg}", s)
    if s == 404:
        return GeminiError("bad_request", f"Gemini doesn't know that model: {msg}", s)
    if s >= 500:
        return GeminiError("server", f"Gemini had a problem ({s}): {msg}", s)
    return GeminiError("bad_request", f"Gemini rejected the request ({s}): {msg}", s)


def _strip_fences(t: str) -> str:
    t = t.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    return m.group(1) if m else t


def _call(api_key: str, model: str, body: dict) -> tuple[dict, Result]:
    try:
        with _client() as c:
            resp = c.post(API_URL.format(model=model), json=body, headers={"x-goog-api-key": api_key})
    except httpx.HTTPError as e:
        raise GeminiError("network", f"Couldn't reach Gemini: {e}") from e
    if resp.status_code != 200:
        raise _error_from(resp)
    payload = resp.json()
    u = payload.get("usageMetadata", {}) or {}
    cand = (payload.get("candidates") or [{}])[0]
    gm = cand.get("groundingMetadata") or {}
    res = Result(
        data=None,
        model=payload.get("modelVersion") or model,
        input_tokens=int(u.get("promptTokenCount", 0) or 0),
        output_tokens=int(u.get("candidatesTokenCount", 0) or 0),
        thinking_tokens=int(u.get("thoughtsTokenCount", 0) or 0),
        search_queries=len(gm.get("webSearchQueries") or []),
        sources=[{"uri": ch["web"].get("uri", ""), "title": ch["web"].get("title", "")}
                 for ch in gm.get("groundingChunks") or [] if ch.get("web")],
    )
    res.calls.append({"model": model, "input": res.input_tokens, "output": res.output_tokens + res.thinking_tokens,
                      "search": res.search_queries})
    if not payload.get("candidates"):
        block = (payload.get("promptFeedback") or {}).get("blockReason")
        raise GeminiError("blocked", f"Gemini returned nothing{f' (blocked: {block})' if block else ''}.")
    return cand, res


def _text_of(cand: dict) -> str:
    parts = (cand.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def generate(
    api_key: str,
    model: str,
    system: str,
    parts: list[dict],
    schema: dict | None = None,
    search: bool = False,
) -> Result:
    """One request. With a schema, returns parsed JSON in `.data`; without, the text."""
    if not api_key:
        raise GeminiError("auth", "No Gemini API key yet. Add one in Settings.")
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {},
    }
    if schema is not None:
        body["generationConfig"] = {"responseMimeType": "application/json", "responseJsonSchema": schema}
    if search:
        body["tools"] = [{"googleSearch": {}}]
    try:
        cand, res = _call(api_key, model, body)
    except GeminiError as e:
        if search and schema is not None and e.kind == "bad_request" and e.status == 400:
            return _search_then_structure(api_key, model, system, parts, schema)
        raise
    finish = cand.get("finishReason", "STOP")
    text = _text_of(cand)
    if finish not in ("STOP", "MAX_TOKENS") and not text:
        raise GeminiError("blocked", f"Gemini stopped early ({finish}).")
    res.searched = search
    if schema is None:
        res.data = text
        return res
    try:
        res.data = json.loads(_strip_fences(text))
    except ValueError as e:
        why = "the answer was cut off (too long)" if finish == "MAX_TOKENS" else "the answer wasn't valid JSON"
        raise GeminiError("bad_output", f"Couldn't read Gemini's answer: {why}.") from e
    return res


def _search_then_structure(api_key: str, model: str, system: str, parts: list[dict], schema: dict) -> Result:
    """For models that won't combine search and a schema: search in plain text, then structure it."""
    found = generate(api_key, model, system, parts + [text_part(
        "\n\nResearch this with Google Search and answer in plain text, giving the exact URL of every source.")],
        schema=None, search=True)
    srcs = "\n".join(f"- {s['title']}: {s['uri']}" for s in found.sources)
    shaped = generate(api_key, model, system, [text_part(
        "Turn these research notes into the requested JSON. Use only facts and URLs that appear in them.\n\n"
        f"NOTES:\n{found.data}\n\nSEARCH SOURCES:\n{srcs}")], schema=schema, search=False)
    found.add(shaped)
    found.data = shaped.data
    return found


def generate_image(api_key: str, model: str, prompt: str, aspect: str = "16:9") -> Result:
    """One illustration (Nano Banana). `.data` is {"mime", "bytes"}; nothing is kept in the job's stored result."""
    if not api_key:
        raise GeminiError("auth", "No Gemini API key yet. Add one in Settings.")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}
    cand, res = _call(api_key, model, body)
    for p in (cand.get("content") or {}).get("parts") or []:
        inline = p.get("inlineData") or p.get("inline_data")
        if inline and inline.get("data"):
            raw_bytes = base64.b64decode(inline["data"])
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            if not raw_bytes[:3] == b"\xff\xd8\xff" and not raw_bytes[:8] == b"\x89PNG\r\n\x1a\n" and not raw_bytes[:4] == b"RIFF":
                raise GeminiError("bad_output", "Gemini's picture wasn't a PNG, JPEG or WebP.")
            res.data = {"mime": mime, "bytes": raw_bytes}
            return res
    raise GeminiError("bad_output", f"Gemini returned no picture ({cand.get('finishReason', 'no reason given')}).")
