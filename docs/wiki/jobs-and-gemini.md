# Jobs, Gemini and the budget

See [index](index.md). Code: [app/jobs.py](../../app/jobs.py), [app/gemini.py](../../app/gemini.py),
[app/budget.py](../../app/budget.py), [app/pricing.py](../../app/pricing.py).

## The queue

Anything that calls Gemini is a row in `jobs`: `kind` (which handler), `ref` (what it's about: a session id, an item
id, `session:chunk` for section rewrites), `priority`, `request_json` (role, system prompt, prompt, JSON Schema,
search, whether to attach the course's materials) and the `user_id` who started it.

| Priority | Used for |
|---|---|
| 30 `PRIORITY_NOW` | Someone is waiting: marking, the tutor, section rewrites |
| 20 `PRIORITY_SETUP` | Questions and the plan |
| 10 `PRIORITY_BUILD` | Writing sessions |
| 0 `PRIORITY_LATER` | Reading lists, read-through checks |

The worker claims the highest-priority runnable job, builds the request (inline files from the course folder), calls
Gemini outside any transaction, then in one transaction logs the call's cost, stores the result and runs the kind's
handler inside a savepoint. A handler that raises marks the job failed ("Couldn't use Gemini's answer: ...") and
runs its `on_failed`.

Errors: `rate_limit` waits (1, 5, 15, 30, then 60 minutes); `auth` and `quota` pause everything until the key or
account is fixed and someone presses **resume**; retryable and bad-output errors retry up to 3 times; anything else
fails. Jobs interrupted by a restart are requeued at start.

## Handlers

Registered with `@jobs.handler(kind, on_failed=...)`: `questions`, `plan`, `session`, `check`, `reading`
([course-pipeline](course-pipeline.md)), `mark`, `chat` ([learning](learning.md)), `illustration` ([media](media.md)),
`revise` (section rewrites, [course-pipeline](course-pipeline.md#editing)).

## The Gemini client

A small REST client for `generateContent`:
- Structured output with `responseJsonSchema`. Every schema in [prompts.py](../../app/prompts.py) is strict (all
  properties required, no extras).
- PDFs and images go inline as bytes; Gemini never reads the file system.
- Google Search grounding is a tool on the same call. If a model refuses search together with a schema, the client
  searches first, then structures in a second call. Optional search (live research) that fails, for example on a
  free-tier key, runs without it and the result says so (`search_note`).
- Grounding sources come back as Google redirect links; they're resolved and checked like reading suggestions.
- Images use `responseModalities: IMAGE` with the image model.
- Errors are classified (`rate_limit`, `server`, `auth`, `quota`, `bad_output`...).

## Models

Four roles, each a setting with a default in [pricing.py](../../app/pricing.py):

| Role | Default | Used for |
|---|---|---|
| `pro` | Gemini 4 Argon | Plans, checkpoints, projects |
| `flash` | Gemini 3.8 Flash | Questions, sessions, reading, written feedback, the tutor, section rewrites |
| `lite` | Gemini 3.5 Flash-Lite | Read-through checks, short-answer marking |
| `image` | Nano Banana 2.1 | AI illustrations |

## Cost and the budget

Every call is a row in `llm_calls` with input, output and thinking tokens and search queries. The cost comes from a
price table with effective dates (it includes the increases announced for 1 December 2026 and 1 January 2027);
models without a price are logged with an unknown cost and counted on the Usage page. `budget.over_cap()` compares
this month's spend (in `TZ`) with the cap; when it's reached, queued jobs wait with reason `budget` and resume once the
cap is raised or a new month starts. Search pricing: 5,000 free a month, then $14 per 1,000.
