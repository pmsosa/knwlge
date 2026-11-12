# Reading lists and sources

See [index](index.md). Code: [app/verify.py](../../app/verify.py).

Language models invent citations, so every suggestion is checked before anyone sees it (`reading.status`:
`pending` → `verified` / `dropped`).

| Kind | Check |
|---|---|
| Books | Open Library by ISBN, else a title and author search with fuzzy matching; the real title and author are kept |
| YouTube | The public oEmbed endpoint: the video exists; its real title and channel are kept |
| Everything else | Fetch the page (it must load); its real title is kept |

Checks run in the worker's idle time (`verify.step`). Fetches go only to public internet addresses: the host is
resolved and every address checked against private, loopback, link-local and reserved ranges, on every redirect, so a
made-up link can't reach this server or the network around it ([security](security.md#safe-fetching)).

**Live-research sources** (from Google Search grounding) arrive as `vertexaisearch.cloud.google.com` redirect links.
They're resolved to the real page and checked the same way, then listed under the session as "Sources Gemini looked
at" (kind `source`).
