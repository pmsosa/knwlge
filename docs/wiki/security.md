# Security

See [index](index.md). Lessons from reviewing SelfSemester are in [PLAN](../PLAN.md#security-lessons-from-reviewing-selfsemester).

## Requests

- **Writes need a custom header** (`x-knwlge`), which a cross-site form or image can't send, so cookies can't be
  used from another site. The session cookie is also SameSite=Lax.
- **Host check** (DNS rebinding): requests are refused unless the Host is an IP address, `localhost`, a single-label
  name, or matches `KNWLGE_ALLOWED_HOSTS` (comma-separated, wildcards like `*.example.org`).
- **Roles and visibility** are checked on the server for every route ([auth](auth.md)).
- No API docs routes (`/docs`, `/openapi.json` are off).

## Content Security Policy

`default-src 'self'; script-src 'self'` (no inline scripts, no eval), images from self, data and blob URLs, frames
only from self and `youtube-nocookie.com`, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'none'`. Lesson
Markdown goes through DOMPurify; KaTeX output is placed after sanitising, into text only. Mermaid runs in strict mode.
SVGs are shown with `<img>`.

## Experiments

Gemini-written simulations are served from their own route with a separate CSP (inline code only, no network, no
forms) and shown in an `<iframe sandbox="allow-scripts">` without `allow-same-origin`, so the frame has an opaque
origin: it can't read the app, its cookies or its data, or reach the internet. They start only when someone presses
**run experiment**.

## Safe fetching

Link checks and media downloads ([reading](reading.md), [media](media.md)) resolve each host and refuse private,
loopback, link-local, multicast and reserved addresses, again on every redirect, with size and time limits. Course
file paths are checked to stay inside the course's folder.

## Prompts

- Learners' answers are fenced as data in marking prompts, and the score is computed from the rubric with every line
  capped, so "give me full marks" can't work.
- Answer keys reach the browser only after a correct answer or an explicit reveal.
- Section-rewrite requests and selected passages are passed as data inside the prompt.

## The service worker

It caches only the app's own static files and never `/api`, so no course, answer, account or key is stored by the
browser on its behalf. Each build gets its own cache, and old ones are deleted.

## Secrets

The Gemini key is stored in the database, used only by the server, never returned by the API (only a hint of its
last characters) and never logged; audit entries for key changes have no value. Passwords are scrypt hashes; session
tokens are stored as SHA-256 hashes.
