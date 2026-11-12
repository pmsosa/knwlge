"""Checking further-reading suggestions before they're shown, because language models invent citations.

Books: Open Library (by ISBN, else title + author). YouTube: the public oEmbed endpoint. Everything else: fetch the
page. Fetches only go to public internet addresses (never this server or a private network), redirect by
redirect, so a made-up link can't reach anything private.
"""
from __future__ import annotations

import difflib
import html
import ipaddress
import json
import logging
import re
import socket
from urllib.parse import quote, urljoin, urlparse

import httpx

from . import db

log = logging.getLogger("knwlge.verify")

UA = "Knwlge-linkcheck/1.0"
TIMEOUT = httpx.Timeout(12.0, connect=8.0)
MAX_BYTES = 300_000

# Tests swap these.
transport: httpx.BaseTransport | None = None
resolver = socket.getaddrinfo


class Blocked(Exception):
    pass


def _check_host(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise Blocked("not a web link")
    if p.port not in (None, 80, 443):
        raise Blocked("unusual port")
    if p.username or p.password:
        raise Blocked("credentials in link")
    try:
        infos = resolver(p.hostname, p.port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise Blocked("no such site") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise Blocked("private address")


def fetch(url: str, max_redirects: int = 6) -> tuple[int, str, str]:
    """GET a public URL. Returns (status, final url, start of the body as text)."""
    with httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False,
                      headers={"User-Agent": UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.5"}) as c:
        for _ in range(max_redirects + 1):
            _check_host(url)
            with c.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urljoin(url, r.headers["location"])
                    continue
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) >= MAX_BYTES:
                        break
                return r.status_code, url, body.decode(r.encoding or "utf-8", "replace")
    raise Blocked("too many redirects")


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def similar(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def page_title(body: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.I | re.S)
    return html.unescape(m.group(1)).strip()[:200] if m else ""


YOUTUBE = re.compile(r"^https?://(www\.|m\.)?(youtube\.com/(watch\?|shorts/|playlist\?)|youtu\.be/)", re.I)


def check_youtube(url: str) -> tuple[bool, str, dict]:
    status, _, body = fetch(f"https://www.youtube.com/oembed?format=json&url={quote(url, safe='')}")
    if status == 200:
        try:
            info = json.loads(body)
        except ValueError:
            info = {}
        return True, f"YouTube: {info.get('title', '')} ({info.get('author_name', '')})", info
    if status == 401:  # exists, embedding turned off
        return True, "YouTube video (embedding off)", {}
    return False, "YouTube says this video doesn't exist", {}


def check_book(title: str, creator: str, isbn: str) -> tuple[bool, str, str]:
    """Returns (found, note, Open Library URL)."""
    digits = re.sub(r"[^0-9Xx]", "", isbn or "")
    if len(digits) in (10, 13):
        status, final, body = fetch(f"https://openlibrary.org/isbn/{digits}.json")
        if status == 200:
            try:
                info = json.loads(body)
            except ValueError:
                info = {}
            if similar(info.get("title", ""), title):
                key = info.get("key", "")
                return True, f"Open Library: ISBN {digits}", f"https://openlibrary.org{key}" if key else ""
    q = f"https://openlibrary.org/search.json?limit=5&fields=key,title,author_name,first_publish_year&title={quote(title)}"
    if creator:
        q += f"&author={quote(creator.split(',')[0].split(' and ')[0])}"
    status, _, body = fetch(q)
    if status == 200:
        try:
            docs = json.loads(body).get("docs", [])
        except ValueError:
            docs = []
        for d in docs:
            if similar(d.get("title", ""), title):
                return True, f"Open Library: {d.get('title')} ({', '.join(d.get('author_name', [])[:2])})", \
                    f"https://openlibrary.org{d.get('key', '')}"
    return False, "Couldn't find this book on Open Library", ""


def verify_row(r: dict) -> tuple[str, str, str]:
    """Returns (status, note, url) for one reading row."""
    url = r["url"].strip()
    try:
        if r["kind"] == "book":
            ok, note, ol = check_book(r["title"], r["creator"], r["isbn"])
            if ok:
                if url:
                    try:
                        st, final, _ = fetch(url)
                        if st < 400:
                            return "verified", note, final
                    except (Blocked, httpx.HTTPError):
                        pass
                return "verified", note, ol
            if url:  # maybe a free online book Open Library doesn't list
                st, final, body = fetch(url)
                if st < 400 and similar(page_title(body), r["title"]):
                    return "verified", "Found the book online", final
            return "dropped", note, url
        if not url:
            return "dropped", "No link to check", url
        if YOUTUBE.match(url):
            ok, note, _ = check_youtube(url)
            return ("verified" if ok else "dropped"), note, url
        st, final, body = fetch(url)
        if YOUTUBE.match(final):
            ok, note, _ = check_youtube(final)
            return ("verified" if ok else "dropped"), note, final
        if st < 400:
            t = page_title(body)
            return "verified", f"Page found: {t}" if t else "Page found", final
        if st in (401, 403, 429):
            return "verified", f"The site exists but blocks link checks ({st})", final
        return "dropped", f"The link is broken ({st})", url
    except Blocked as e:
        return "dropped", f"Link not checked: {e}", url
    except httpx.HTTPError as e:
        return "dropped", f"Couldn't reach the site ({type(e).__name__})", url


def step() -> bool:
    """Verify one pending reading suggestion. Returns True if it did one (the worker's idle task)."""
    with db.tx() as c:
        row = c.execute("SELECT * FROM reading WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
        if row is None:
            return False
        c.execute("UPDATE reading SET status='checking' WHERE id=?", (row["id"],))
        r = dict(row)
    try:
        status, note, url = verify_row(r)
    except Exception as e:  # never let one odd link stop the worker
        log.exception("verifying reading %s failed", r["id"])
        status, note, url = "dropped", f"Couldn't check: {e}", r["url"]
    with db.tx() as c:
        c.execute("UPDATE reading SET status=?, verify_note=?, url=? WHERE id=?", (status, note[:300], url[:1000], r["id"]))
        if r["kind"] == "source" and status == "verified" and note.startswith("Page found: "):
            # grounding only gives a domain as the title; the page's own title is more useful
            c.execute("UPDATE reading SET creator=title, title=? WHERE id=?", (note.removeprefix("Page found: ")[:300], r["id"]))
        if status == "dropped" and r["top"]:
            # hand the "if you only read one thing" badge to the next verified course-level item
            nxt = c.execute("SELECT id FROM reading WHERE course_id=? AND session_id IS NULL AND status IN ('verified','pending') "
                            "AND id!=? ORDER BY id LIMIT 1", (r["course_id"], r["id"])).fetchone()
            c.execute("UPDATE reading SET top=0 WHERE id=?", (r["id"],))
            if nxt:
                c.execute("UPDATE reading SET top=1 WHERE id=?", (nxt["id"],))
    return True


def reset_stuck() -> None:
    with db.tx() as c:
        c.execute("UPDATE reading SET status='pending' WHERE status='checking'")
