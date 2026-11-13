"""AI providers behind one interface: text with JSON-schema output, web search where the provider has it, pictures
where it can draw, and token usage for cost.

Gemini is built in (its key lives in settings, as before). OpenAI, Anthropic and any OpenAI-compatible endpoint
(LiteLLM, Ollama, vLLM, LM Studio...) are rows in `providers`. Each role (planning, writing, checks, marking, tutor,
reading lists, illustrations) picks a provider and a model; without a choice it uses Gemini with the model it had.

Requests arrive in Gemini's shape (text parts and inline files) and each adapter translates. Errors are all
`gemini.GeminiError` with the same kinds (rate_limit, quota, auth, server, network, bad_request, bad_output,
blocked), so the job queue treats every provider alike. Keys never leave the server and are never logged.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import sqlite3
from typing import Any

import httpx

from . import db, gemini, pricing
from .gemini import GeminiError, Result

KINDS = {
    "gemini": {"label": "Google Gemini", "search": True, "images": True, "pdf": True, "needs_key": True, "base_url": ""},
    "openai": {"label": "OpenAI", "search": True, "images": True, "pdf": True, "needs_key": True,
               "base_url": "https://api.openai.com/v1"},
    "anthropic": {"label": "Anthropic (Claude)", "search": True, "images": False, "pdf": True, "needs_key": True, "base_url": ""},
    # compatible endpoints search only when an admin says so (LiteLLM's web_search_options, if its models have it)
    "compatible": {"label": "OpenAI-compatible (LiteLLM, Ollama, vLLM...)", "search": False, "images": False, "pdf": False,
                   "needs_key": False, "base_url": ""},
}

# role -> (title, what it does, the old model tier it falls back to on Gemini, needs pictures)
ROLES = {
    "planning": ("Planning and projects", "Questions before a course, the plan, checkpoints and projects. Use the strongest model.", "pro", False),
    "writing": ("Writing lessons", "Writes most sessions and rewrites sections when an author asks.", "flash", False),
    "checks": ("Quick checks", "The second read-through of each session, and marking short answers.", "lite", False),
    "marking": ("Feedback on written work", "Marks written exercises and projects against their rubric.", "flash", False),
    "tutor": ("Tutor", "Answers questions about a course, a session or a question.", "flash", False),
    "research": ("Reading lists", "Finds books, videos and courses (checked before anyone sees them). Works best with web search.", "flash", False),
    "illustrations": ("Illustrations", "Draws AI pictures for courses that have them switched on.", "image", True),
}

GEMINI_ID = "gemini"
TIMEOUT = httpx.Timeout(300.0, connect=20.0)
transport: httpx.BaseTransport | None = None   # tests swap this for an httpx.MockTransport (OpenAI-style calls)
anthropic_call = None                           # tests swap this for a fake (it gets the request kwargs)

# Claude models that take Anthropic's server-side refusal fallback (a declined request is re-run on another Claude model)
CLAUDE_FALLBACK = ("claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")


def role_of(kind: str, tier: str | None) -> str:
    """Which role a job belongs to, from its kind (and, for sessions and marking, the tier its prompt asked for)."""
    if kind in ("questions", "plan"):
        return "planning"
    if kind == "session":
        return "planning" if tier == "pro" else "writing"
    if kind == "revise":
        return "writing"
    if kind == "check":
        return "checks"
    if kind == "mark":
        return "checks" if tier == "lite" else "marking"
    if kind == "chat":
        return "tutor"
    if kind == "reading":
        return "research"
    if kind == "illustration":
        return "illustrations"
    return {"pro": "planning", "lite": "checks", "image": "illustrations"}.get(tier or "", "writing")


# ---------- the provider list ----------

def _gemini_row(c: sqlite3.Connection) -> dict:
    return {"id": GEMINI_ID, "kind": "gemini", "label": "Google Gemini", "base_url": "",
            "api_key": db.get_setting(c, "gemini_api_key") or "",
            "models": db.loads(db.get_setting(c, "gemini_models"), None) or [{"id": m["id"]} for m in pricing.KNOWN_MODELS],
            "tested_at": db.get_setting(c, "gemini_tested_at"), "test_note": db.get_setting(c, "gemini_test_note") or "",
            "builtin": True, "search": True, "search_price": None}


def get(c: sqlite3.Connection, pid: str) -> dict | None:
    if pid == GEMINI_ID:
        return _gemini_row(c)
    r = c.execute("SELECT * FROM providers WHERE id=?", (pid,)).fetchone()
    if r is None:
        return None
    return {"id": r["id"], "kind": r["kind"], "label": r["label"], "base_url": r["base_url"], "api_key": r["api_key"],
            "models": db.loads(r["models_json"], []), "tested_at": r["tested_at"], "test_note": r["test_note"], "builtin": False,
            "search": bool(KINDS[r["kind"]]["search"] or (r["kind"] == "compatible" and r["search"])),
            "search_price": r["search_price"]}


def all_providers(c: sqlite3.Connection) -> list[dict]:
    rows = [r["id"] for r in c.execute("SELECT id FROM providers ORDER BY created_at")]
    return [_gemini_row(c)] + [get(c, pid) for pid in rows]


def price_for(p: dict, model: str) -> tuple[float, float] | None:
    """An admin-entered price for this provider's model, if any ($ per 1M input and output tokens)."""
    for m in p.get("models") or []:
        if m.get("id") == model and m.get("price"):
            return float(m["price"][0]), float(m["price"][1])
    return None


def public(p: dict) -> dict:
    """What the settings page sees: never the key, only its last four characters."""
    k = KINDS[p["kind"]]
    return {"id": p["id"], "kind": p["kind"], "kind_label": k["label"], "label": p["label"], "base_url": p["base_url"],
            "key_hint": f"…{p['api_key'][-4:]}" if p["api_key"] else None, "models": p["models"], "tested_at": p["tested_at"],
            "test_note": p["test_note"], "builtin": p["builtin"], "search_price": p.get("search_price"),
            "can": {"search": bool(p.get("search")), "images": k["images"], "pdf": k["pdf"]}}


def _check_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if url and not re.match(r"^https?://[^\s/]+(/\S*)?$", url):
        raise ValueError("The address must start with http:// or https://.")
    return url


def _check_key(key: str) -> str:
    key = key.strip()
    if len(key) > 400 or any(ch.isspace() for ch in key):
        raise ValueError("That doesn't look like an API key.")
    return key


def _check_search_price(v: float | None) -> float | None:
    if v is None:
        return None
    v = float(v)
    if not 0 <= v <= 1000:
        raise ValueError("The search price is dollars per 1,000 searches, between 0 and 1,000.")
    return v


def add(c: sqlite3.Connection, kind: str, label: str, base_url: str, api_key: str, search: bool = False) -> str:
    if kind not in KINDS or kind == "gemini":
        raise ValueError("Pick OpenAI, Anthropic or an OpenAI-compatible endpoint.")
    base_url = _check_url(base_url) or KINDS[kind]["base_url"]
    if kind == "compatible" and not base_url:
        raise ValueError("An OpenAI-compatible endpoint needs its address, e.g. http://192.168.1.10:11434/v1.")
    api_key = _check_key(api_key)
    if KINDS[kind]["needs_key"] and not api_key:
        raise ValueError("Paste the API key.")
    pid = f"{kind[:4]}-{secrets.token_hex(3)}"
    c.execute("INSERT INTO providers(id, kind, label, base_url, api_key, search, created_at) VALUES (?,?,?,?,?,?,?)",
              (pid, kind, (label.strip() or KINDS[kind]["label"])[:60], base_url, api_key,
               int(bool(search) and kind == "compatible"), db.now()))
    return pid


def update(c: sqlite3.Connection, pid: str, label: str | None = None, base_url: str | None = None, api_key: str | None = None,
           prices: dict | None = None, search: bool | None = None, search_price: float | None | str = "keep") -> None:
    p = get(c, pid)
    if p is None:
        raise ValueError("That provider doesn't exist.")
    if pid == GEMINI_ID:
        if api_key:
            db.set_setting(c, "gemini_api_key", _check_key(api_key))
        if prices is not None:
            db.set_setting(c, "gemini_models", db.dumps(_with_prices(p["models"], prices)))
        return
    fields: dict[str, Any] = {}
    if label is not None and label.strip():
        fields["label"] = label.strip()[:60]
    if base_url is not None:
        fields["base_url"] = _check_url(base_url) or KINDS[p["kind"]]["base_url"]
    if api_key:
        fields["api_key"] = _check_key(api_key)
    if prices is not None:
        fields["models_json"] = db.dumps(_with_prices(p["models"], prices))
    if search is not None and p["kind"] == "compatible":
        fields["search"] = int(bool(search))
    if search_price != "keep" and p["kind"] in ("openai", "compatible"):
        fields["search_price"] = _check_search_price(search_price)   # None: back to the built-in price (or free)
    if fields:
        c.execute(f"UPDATE providers SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), pid))


def _with_prices(models: list[dict], prices: dict) -> list[dict]:
    """prices: model id -> [input $/1M, output $/1M] or None to forget it."""
    out = []
    for m in models:
        m = dict(m)
        if m["id"] in prices:
            v = prices[m["id"]]
            if v is None:
                m.pop("price", None)
            else:
                inp, outp = float(v[0]), float(v[1])
                if not (0 <= inp <= 1000 and 0 <= outp <= 1000):
                    raise ValueError("Prices are dollars per million tokens, between 0 and 1,000.")
                m["price"] = [inp, outp]
        out.append(m)
    return out


def remove(c: sqlite3.Connection, pid: str) -> None:
    if pid == GEMINI_ID:
        raise ValueError("Gemini is built in. Remove its key instead.")
    c.execute("DELETE FROM providers WHERE id=?", (pid,))
    for role in ROLES:   # roles that used it go back to Gemini
        r = route_setting(c, role)
        if r and r.get("provider") == pid:
            db.set_setting(c, f"route_{role}", None)


# ---------- which provider and model each role uses ----------

def route_setting(c: sqlite3.Connection, role: str) -> dict | None:
    return db.loads(db.get_setting(c, f"route_{role}"), None)


def route(c: sqlite3.Connection, role: str) -> tuple[dict, str]:
    """(provider, model) for a role. Unset (or a provider that's gone): Gemini with the model it had before."""
    r = route_setting(c, role)
    if r:
        p = get(c, r.get("provider", ""))
        if p and r.get("model"):
            return p, r["model"]
    tier = ROLES[role][2]
    return _gemini_row(c), db.get_setting(c, f"model_{tier}") or pricing.DEFAULT_MODELS[tier]


def set_route(c: sqlite3.Connection, role: str, pid: str, model: str) -> None:
    if role not in ROLES:
        raise ValueError("Unknown role.")
    p = get(c, pid)
    if p is None:
        raise ValueError("That provider doesn't exist.")
    model = model.strip()
    if not model or len(model) > 120 or not all(ch.isalnum() or ch in "-._:/@" for ch in model):
        raise ValueError("Model ids are letters, digits and - . _ : / @.")
    if ROLES[role][3] and not KINDS[p["kind"]]["images"]:
        raise ValueError(f"{p['label']} can't draw pictures. Pick Gemini or OpenAI for illustrations.")
    db.set_setting(c, f"route_{role}", db.dumps({"provider": pid, "model": model}))


def routes(c: sqlite3.Connection) -> dict:
    out = {}
    for role, (title, hint, tier, images) in ROLES.items():
        p, model = route(c, role)
        out[role] = {"title": title, "hint": hint, "provider": p["id"], "model": model, "needs_images": images,
                     "is_default": route_setting(c, role) is None}
    return out


# ---------- calling a provider ----------

def generate(p: dict, model: str, system: str, parts: list[dict], schema: dict | None = None, search: bool = False,
             search_optional: bool = False) -> Result:
    kind = p["kind"]
    if kind == "gemini":
        return gemini.generate(p["api_key"], model, system, parts, schema=schema, search=search)
    if search and not p.get("search"):
        # no web search here: write without it (reading lists are still checked link by link before they're shown)
        res = generate(p, model, system, parts, schema=schema, search=False)
        res.search_note = (f"{p['label']} isn't set to search the web (Settings), so this was written without live research."
                           if kind == "compatible" else
                           f"{p['label']} can't search the web, so this was written without live research.")
        return res
    if kind == "anthropic":
        return _anthropic(p, model, system, parts, schema, search)
    if kind == "openai" and search:
        return _openai_search(p, model, system, parts, schema)
    return _openai_chat(p, model, system, parts, schema, search)


def generate_image(p: dict, model: str, prompt: str, aspect: str = "16:9") -> Result:
    if p["kind"] == "gemini":
        return gemini.generate_image(p["api_key"], model, prompt, aspect)
    if p["kind"] == "openai":
        return _openai_image(p, model, prompt, aspect)
    raise GeminiError("bad_request", f"{p['label']} can't draw pictures. Pick Gemini or OpenAI for illustrations in Settings.")


def _b64(part: dict) -> tuple[str, str] | None:
    inline = part.get("inlineData")
    return (inline["mimeType"], inline["data"]) if inline else None


def _parse(text: str, schema: dict | None, cut_off: bool, who: str) -> Any:
    if schema is None:
        return text
    try:
        return json.loads(gemini._strip_fences(text))
    except ValueError as e:
        why = "the answer was cut off (too long)" if cut_off else "the answer wasn't valid JSON"
        raise GeminiError("bad_output", f"Couldn't read {who}'s answer: {why}.") from e


# ----- OpenAI and OpenAI-compatible: Chat Completions over plain HTTP -----

def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport)


def _headers(p: dict) -> dict:
    return {"Authorization": f"Bearer {p['api_key']}"} if p["api_key"] else {}


def _http_error(p: dict, resp: httpx.Response) -> GeminiError:
    try:
        err = resp.json().get("error", {})
        err = err if isinstance(err, dict) else {"message": str(err)}
        msg, code = err.get("message") or resp.text[:300], str(err.get("code") or err.get("type") or "")
    except ValueError:
        msg, code = resp.text[:300], ""
    who, s = p["label"], resp.status_code
    if s == 429 and ("insufficient_quota" in code or "quota" in msg.lower() and "exceeded your current quota" in msg.lower()):
        return GeminiError("quota", f"{who} says the account's credit or quota is used up: {msg}", s)
    if s == 429:
        return GeminiError("rate_limit", f"{who} rate limit reached: {msg}", s)
    if s == 402:
        return GeminiError("quota", f"{who} says the credit is used up: {msg}", s)
    if s in (401, 403):
        return GeminiError("auth", f"{who} refused the API key: {msg}", s)
    if s == 404:
        return GeminiError("bad_request", f"{who} doesn't know that model: {msg}", s)
    if s >= 500:
        return GeminiError("server", f"{who} had a problem ({s}): {msg}", s)
    return GeminiError("bad_request", f"{who} rejected the request ({s}): {msg}", s)


def _post(p: dict, path: str, body: dict) -> dict:
    try:
        with _client() as c:
            resp = c.post(p["base_url"].rstrip("/") + path, json=body, headers=_headers(p))
    except httpx.HTTPError as e:
        raise GeminiError("network", f"Couldn't reach {p['label']}: {type(e).__name__}") from e
    if resp.status_code != 200:
        raise _http_error(p, resp)
    try:
        return resp.json()
    except ValueError as e:
        raise GeminiError("bad_output", f"{p['label']} sent something that isn't JSON.") from e


def _chat_content(p: dict, parts: list[dict]) -> list[dict]:
    out: list[dict] = []
    for part in parts:
        if "text" in part:
            out.append({"type": "text", "text": part["text"]})
            continue
        f = _b64(part)
        if not f:
            continue
        mime, data = f
        if mime.startswith("image/") and mime != "image/heic":
            out.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
        elif mime == "application/pdf" and KINDS[p["kind"]]["pdf"]:
            out.append({"type": "file", "file": {"filename": "document.pdf", "file_data": f"data:{mime};base64,{data}"}})
        else:
            out.append({"type": "text", "text": f"(A {mime} file was left out: {p['label']} can't read it here.)"})
    return out


def _openai_chat(p: dict, model: str, system: str, parts: list[dict], schema: dict | None, search: bool = False) -> Result:
    body: dict[str, Any] = {"model": model, "messages": [{"role": "system", "content": system},
                                                         {"role": "user", "content": _chat_content(p, parts)}]}
    if search:
        # LiteLLM's web_search_options (since v1.71), mapped to each provider's own search; plain OpenAI only takes it on
        # its *-search-api models. An endpoint that rejects it writes without search and says so.
        body["web_search_options"] = {"search_context_size": "medium"}
        try:
            return _openai_chat_body(p, model, system, schema, body, search=True)
        except GeminiError as e:
            if e.kind != "bad_request" or e.status != 400:
                raise
            res = _openai_chat(p, model, system, parts, schema, False)
            res.search_note = f"{p['label']} wouldn't search with this model, so this was written without live research."
            return res
    return _openai_chat_body(p, model, system, schema, body)


def _citations(annotations) -> list[dict]:
    """url_citation annotations, flat (Responses) or nested (Chat Completions)."""
    out = []
    for a in annotations or []:
        if isinstance(a, dict) and a.get("type") == "url_citation":
            a = a.get("url_citation") or a
            if str(a.get("url", "")).startswith(("http://", "https://")):
                out.append({"uri": a["url"], "title": a.get("title") or ""})
    return out


def _openai_chat_body(p: dict, model: str, system: str, schema: dict | None, body: dict, search: bool = False) -> Result:
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema, "strict": False}}
    try:
        payload = _post(p, "/chat/completions", body)
    except GeminiError as e:
        if schema is None or e.kind != "bad_request" or e.status != 400:
            raise
        # an endpoint without JSON-schema output: ask for plain JSON and put the schema in the instructions
        body["response_format"] = {"type": "json_object"}
        body["messages"][0]["content"] = (system + "\n\nAnswer with one JSON object that matches this JSON Schema exactly:\n"
                                          + json.dumps(schema, ensure_ascii=False))
        payload = _post(p, "/chat/completions", body)
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    if msg.get("refusal"):
        raise GeminiError("blocked", f"{p['label']} declined: {str(msg['refusal'])[:200]}")
    u = payload.get("usage") or {}
    res = Result(data=None, model=payload.get("model") or model, input_tokens=int(u.get("prompt_tokens") or 0),
                 output_tokens=int(u.get("completion_tokens") or 0))
    searches = 0
    if search:
        searches = int((u.get("prompt_tokens_details") or {}).get("web_search_requests") or 0)
        res.sources += _citations(msg.get("annotations"))
        res.searched = True
        res.search_queries = searches
    res.calls.append({"model": model, "input": res.input_tokens, "output": res.output_tokens, "search": searches})
    text = msg.get("content") or ""
    if isinstance(text, list):   # some servers return content parts
        text = "".join(x.get("text", "") for x in text if isinstance(x, dict))
    if not text and choice.get("finish_reason") == "content_filter":
        raise GeminiError("blocked", f"{p['label']} stopped early (content filter).")
    res.data = _parse(text, schema, choice.get("finish_reason") == "length", p["label"])
    return res


def _responses_content(p: dict, parts: list[dict]) -> list[dict]:
    out: list[dict] = []
    for c in _chat_content(p, parts):
        if c["type"] == "text":
            out.append({"type": "input_text", "text": c["text"]})
        elif c["type"] == "image_url":
            out.append({"type": "input_image", "image_url": c["image_url"]["url"]})
        elif c["type"] == "file":
            out.append({"type": "input_file", **c["file"]})
    return out


def _openai_search(p: dict, model: str, system: str, parts: list[dict], schema: dict | None) -> Result:
    """OpenAI's web search lives in the Responses API (Chat Completions only searches with the *-search-api models).
    JSON output with search in one call first; if the model won't combine them, search in plain text and then shape the
    notes with Chat Completions."""
    body: dict[str, Any] = {"model": model, "instructions": system,
                            "input": [{"role": "user", "content": _responses_content(p, parts)}],
                            "tools": [{"type": "web_search"}]}
    if schema is not None:
        body["text"] = {"format": {"type": "json_schema", "name": "answer", "schema": schema, "strict": False}}
    try:
        return _responses_call(p, model, body, schema)
    except GeminiError as e:
        if schema is None or e.kind not in ("bad_request", "bad_output") or (e.kind == "bad_request" and e.status != 400):
            raise
    body.pop("text")
    body["input"][0]["content"].append({"type": "input_text", "text":
        "\n\nResearch this with web search and answer in plain text, giving the exact URL of every source."})
    found = _responses_call(p, model, body, None)
    srcs = "\n".join(f"- {s['title']}: {s['uri']}" for s in found.sources)
    shaped = _openai_chat(p, model, system, [gemini.text_part(
        "Turn these research notes into the requested JSON. Use only facts and URLs that appear in them.\n\n"
        f"NOTES:\n{found.data}\n\nSEARCH SOURCES:\n{srcs}")], schema)
    found.add(shaped)
    found.data = shaped.data
    return found


def _responses_call(p: dict, model: str, body: dict, schema: dict | None) -> Result:
    payload = _post(p, "/responses", body)
    u = payload.get("usage") or {}
    res = Result(data=None, model=payload.get("model") or model, input_tokens=int(u.get("input_tokens") or 0),
                 output_tokens=int(u.get("output_tokens") or 0))
    text: list[str] = []
    for item in payload.get("output") or []:
        t = item.get("type")
        if t == "web_search_call":
            res.search_queries += 1   # billed per call
            for s in (item.get("action") or {}).get("sources") or []:
                if isinstance(s, dict) and str(s.get("url", "")).startswith(("http://", "https://")):
                    res.sources.append({"uri": s["url"], "title": s.get("title") or ""})
        elif t == "message":
            for c in item.get("content") or []:
                if c.get("type") == "refusal":
                    raise GeminiError("blocked", f"{p['label']} declined: {str(c.get('refusal'))[:200]}")
                if c.get("type") == "output_text":
                    text.append(c.get("text") or "")
                    res.sources += _citations(c.get("annotations"))
    res.searched = True
    res.calls.append({"model": model, "input": res.input_tokens, "output": res.output_tokens, "search": res.search_queries})
    why = (payload.get("incomplete_details") or {}).get("reason") if payload.get("status") == "incomplete" else None
    if why == "content_filter" and not "".join(text):
        raise GeminiError("blocked", f"{p['label']} stopped early (content filter).")
    res.data = _parse("".join(text), schema, why == "max_output_tokens", p["label"])
    return res


def _openai_image(p: dict, model: str, prompt: str, aspect: str) -> Result:
    size = "1536x1024" if aspect in ("16:9", "3:2", "4:3") else "1024x1536" if aspect in ("9:16", "2:3", "3:4") else "1024x1024"
    payload = _post(p, "/images/generations", {"model": model, "prompt": prompt, "size": size, "n": 1})
    item = (payload.get("data") or [{}])[0]
    if not item.get("b64_json"):
        raise GeminiError("bad_output", f"{p['label']} returned no picture.")
    raw = base64.b64decode(item["b64_json"])
    if not raw[:3] == b"\xff\xd8\xff" and not raw[:8] == b"\x89PNG\r\n\x1a\n" and not raw[:4] == b"RIFF":
        raise GeminiError("bad_output", f"{p['label']}'s picture wasn't a PNG, JPEG or WebP.")
    u = payload.get("usage") or {}
    res = Result(data={"mime": "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else "image/webp",
                       "bytes": raw}, model=model, input_tokens=int(u.get("input_tokens") or 0),
                 output_tokens=int(u.get("output_tokens") or 0))
    res.calls.append({"model": model, "input": res.input_tokens, "output": res.output_tokens, "search": 0})
    return res


# ----- Anthropic: the official SDK -----

def _claude_blocks(parts: list[dict]) -> list[dict]:
    out: list[dict] = []
    for part in parts:
        if "text" in part:
            if part["text"].strip():
                out.append({"type": "text", "text": part["text"]})
            continue
        f = _b64(part)
        if not f:
            continue
        mime, data = f
        if mime in ("image/png", "image/jpeg", "image/webp", "image/gif"):
            out.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
        elif mime == "application/pdf":
            out.append({"type": "document", "source": {"type": "base64", "media_type": mime, "data": data}})
        else:
            out.append({"type": "text", "text": f"(A {mime} file was left out: Claude can't read that type.)"})
    return out


def _sdk_call(p: dict, kw: dict):
    """One streamed Messages request (long lessons can take minutes); returns the final message."""
    if anthropic_call is not None:
        return anthropic_call(p, kw)
    import anthropic
    client = anthropic.Anthropic(api_key=p["api_key"], max_retries=1, timeout=600.0,
                                 **({"base_url": p["base_url"]} if p["base_url"] else {}))
    if kw.get("fallbacks"):
        with client.beta.messages.stream(**kw) as stream:
            return stream.get_final_message()
    with client.messages.stream(**kw) as stream:
        return stream.get_final_message()


def _claude_error(e: Exception) -> GeminiError:
    import anthropic
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return GeminiError("auth", f"Anthropic refused the API key: {e.message}", e.status_code)
    if isinstance(e, anthropic.NotFoundError):
        return GeminiError("bad_request", f"Anthropic doesn't know that model: {e.message}", 404)
    if isinstance(e, anthropic.RateLimitError):
        return GeminiError("rate_limit", f"Anthropic rate limit reached: {e.message}", 429)
    if isinstance(e, anthropic.BadRequestError):
        if "credit balance" in str(e.message).lower():
            return GeminiError("quota", f"Anthropic says the credit is used up: {e.message}", 400)
        return GeminiError("bad_request", f"Anthropic rejected the request: {e.message}", 400)
    if isinstance(e, anthropic.APIStatusError):
        if e.status_code >= 500:
            return GeminiError("server", f"Anthropic had a problem ({e.status_code}): {e.message}", e.status_code)
        return GeminiError("bad_request", f"Anthropic rejected the request ({e.status_code}): {e.message}", e.status_code)
    if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return GeminiError("network", f"Couldn't reach Anthropic: {type(e).__name__}")
    return GeminiError("server", f"Anthropic call failed: {type(e).__name__}")


def _get(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _anthropic(p: dict, model: str, system: str, parts: list[dict], schema: dict | None, search: bool) -> Result:
    messages: list[dict] = [{"role": "user", "content": _claude_blocks(parts)}]
    kw: dict[str, Any] = {"model": model, "max_tokens": 64000, "system": system, "messages": messages}
    if schema is not None:
        kw["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    if search:
        kw["tools"] = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    if model in CLAUDE_FALLBACK:
        kw["betas"] = ["server-side-fallback-2026-07-01"]
        kw["fallbacks"] = "default"
    res = Result(data=None, model=model)
    text_parts: list[str] = []
    for _ in range(5):   # web search can pause a long turn; send it back to carry on
        try:
            msg = _sdk_call(p, kw)
        except GeminiError:
            raise
        except Exception as e:  # the SDK's typed errors
            err = _claude_error(e)
            if search and schema is not None and err.kind == "bad_request":
                return _search_then_structure(p, model, system, parts, schema)
            raise err from e
        u = _get(msg, "usage")
        inp = int(_get(u, "input_tokens", 0) or 0) + int(_get(u, "cache_read_input_tokens", 0) or 0) \
            + int(_get(u, "cache_creation_input_tokens", 0) or 0)
        out = int(_get(u, "output_tokens", 0) or 0)
        searches = int(_get(_get(u, "server_tool_use"), "web_search_requests", 0) or 0)
        served_by = _get(msg, "model") or model
        res.input_tokens += inp
        res.output_tokens += out
        res.search_queries += searches
        res.calls.append({"model": served_by, "input": inp, "output": out, "search": searches})
        content = _get(msg, "content") or []
        for block in content:
            t = _get(block, "type")
            if t == "text":
                text_parts.append(_get(block, "text") or "")
            elif t == "web_search_tool_result":
                results = _get(block, "content")
                if isinstance(results, list):   # an error comes back as one object, not a list
                    res.sources += [{"uri": _get(r, "url", ""), "title": _get(r, "title", "")} for r in results]
        stop = _get(msg, "stop_reason")
        if stop == "pause_turn":
            messages.append({"role": "assistant", "content": content})
            text_parts = []
            continue
        if stop == "refusal":
            raise GeminiError("blocked", "Claude declined this request. Try another model for this role in Settings.")
        res.model = served_by
        res.searched = search
        text = "".join(text_parts)
        res.data = _parse(text, schema, stop == "max_tokens", "Claude")
        return res
    raise GeminiError("bad_output", "Claude's search kept pausing without finishing.")


def _search_then_structure(p: dict, model: str, system: str, parts: list[dict], schema: dict) -> Result:
    found = _anthropic(p, model, system, parts + [gemini.text_part(
        "\n\nResearch this with web search and answer in plain text, giving the exact URL of every source.")], None, True)
    srcs = "\n".join(f"- {s['title']}: {s['uri']}" for s in found.sources)
    shaped = _anthropic(p, model, system, [gemini.text_part(
        "Turn these research notes into the requested JSON. Use only facts and URLs that appear in them.\n\n"
        f"NOTES:\n{found.data}\n\nSEARCH SOURCES:\n{srcs}")], schema, False)
    found.add(shaped)
    found.data = shaped.data
    return found


# ---------- testing a key and listing models ----------

TEST_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}, "message": {"type": "string"}},
               "required": ["ok", "message"], "additionalProperties": False}


def list_models(p: dict) -> list[str]:
    """Model ids the key can use, best effort (an endpoint without a list gives an empty one)."""
    kind = p["kind"]
    try:
        if kind == "gemini":
            with httpx.Client(timeout=httpx.Timeout(20.0), transport=gemini.transport) as c:
                r = c.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 200},
                          headers={"x-goog-api-key": p["api_key"]})
            if r.status_code != 200:
                raise _http_error({**p, "label": "Gemini"}, r)
            return sorted(m["name"].split("/", 1)[1] for m in r.json().get("models", [])
                          if "generateContent" in m.get("supportedGenerationMethods", []) and "/" in m.get("name", ""))
        if kind == "anthropic":
            if anthropic_call is not None:
                return ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
            import anthropic
            client = anthropic.Anthropic(api_key=p["api_key"], max_retries=1, timeout=30.0,
                                         **({"base_url": p["base_url"]} if p["base_url"] else {}))
            try:
                return sorted(m.id for m in client.models.list(limit=100))
            except Exception as e:
                raise _claude_error(e) from e
        with _client() as c:
            r = c.get(p["base_url"].rstrip("/") + "/models", headers=_headers(p), timeout=20.0)
        if r.status_code != 200:
            raise _http_error(p, r)
        return sorted(str(m.get("id")) for m in r.json().get("data", []) if m.get("id"))
    except httpx.HTTPError as e:
        raise GeminiError("network", f"Couldn't reach {p['label']}: {type(e).__name__}") from e


def test(c_factory, pid: str, model: str | None = None) -> dict:
    """Ask the provider for its model list and a tiny JSON answer. Saves the list and the outcome on the provider."""
    with c_factory() as c:
        p = get(c, pid)
    if p is None:
        raise ValueError("That provider doesn't exist.")
    note, ok, models, used = "", True, [], None
    try:
        models = list_models(p)
    except GeminiError as e:
        ok, note = False, str(e)
    if ok:
        used = model or _pick_test_model(p, models)
        if not used:
            ok, note = False, "It answered, but listed no models. Type a model id for a role and test again."
        else:
            try:
                res = generate(p, used, "Answer only with the requested JSON.", [gemini.text_part(
                    "Reply with ok=true and a five-word welcome for someone starting to learn.")], schema=TEST_SCHEMA)
                note = f"Works ({used}): {str((res.data or {}).get('message', ''))[:120]}"
            except GeminiError as e:
                ok, note = False, str(e)
    with c_factory() as c:
        known = {m["id"]: m for m in (get(c, pid) or {}).get("models", [])}
        merged = [known.get(m, {"id": m}) for m in models] if models else list(known.values())
        if pid == GEMINI_ID:
            if models:
                db.set_setting(c, "gemini_models", db.dumps(merged))
            db.set_setting(c, "gemini_tested_at", db.now())
            db.set_setting(c, "gemini_test_note", note[:500])
        else:
            c.execute("UPDATE providers SET models_json=?, tested_at=?, test_note=? WHERE id=?",
                      (db.dumps(merged), db.now(), note[:500], pid))
    return {"ok": ok, "message": note, "model": used, "models": [m["id"] for m in merged]}


def _pick_test_model(p: dict, models: list[str]) -> str | None:
    prefer = {"gemini": ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"], "anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5"],
              "openai": ["gpt-5-mini", "gpt-4.1-mini", "gpt-4o-mini"]}.get(p["kind"], [])
    for m in prefer:
        if m in models:
            return m
    text = [m for m in models if not re.search(r"embed|image|tts|whisper|dall|moderation|audio|realtime|transcribe", m)]
    return (text or models or [None])[0]
