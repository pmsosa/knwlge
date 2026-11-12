# Data model

See [index](index.md). Schema and upgrades: [app/db.py](../../app/db.py). `SCHEMA_VERSION = 3`.

| Table | Holds |
|---|---|
| `settings` | Key-value settings: the Gemini key, models, budget cap, schema version |
| `courses` | Subject, notes, depth, status (`questions` → `answering` → `planning` → `review` → `building` → `ready`), plan JSON, answers, options (extras), `author_id`, `visibility` (`draft`/`published`), `published_at` |
| `sessions` | One per plan slot: kind, minutes, title, topics, objectives, `state` (`pending`/`writing`/`checking`/`ready`/`failed`), `content_json` (goal, hook, chunks with Markdown and worked examples, wrap-up), warnings |
| `items` | Questions, exercises and project options: section (`check`, `practice`, `exercise`, `project`), chunk, type, options, answer, explanation, tolerance, rubric |
| `attempts` | A person's answers: per item and `user_id`, status, score, feedback, files |
| `item_reveals` | Which answers a person chose to see |
| `review_queue` | Spaced review, keyed on (`user_id`, `item_id`): due date, interval, misses |
| `session_progress` | Per person and session: finished, wrap-up summary, notes |
| `course_prefs` | Per person and course: Reading mode on or off |
| `course_opens` | When each person last opened each course (for "continue") |
| `materials` | Uploaded files and typed notes per course |
| `reading` | Reading suggestions and live-research sources, with their check status |
| `media` | Lesson media per session and chunk, with fetch status, credit and file |
| `chat_messages` | Tutor conversations, per course, scope (`course`, a session id or an item id) and person |
| `jobs` | The queue: kind, ref, priority, status, attempts, request and result JSON, error, wait reason, `user_id` |
| `llm_calls` | Every Gemini call: model, tokens, searches, cost, outcome, course, kind, person |
| `users`, `login_sessions` | Accounts and sign-ins ([auth](auth.md)) |
| `audit_log` | Who did what, when, with details as JSON ([auth](auth.md#audit-log)) |

## Ids and files

Course ids are a slug of the subject plus a random suffix (`the-physics-of-music-536f13`); session ids add `-s01`.
Each course has a folder under `data/courses/<id>/` for materials, uploads and media files; deleting a course removes
it. Paths inside are checked to stay in that folder.

## Upgrades

`db.init()` runs at start. When the stored schema version is older, it first copies the database with SQLite's
backup API to `data/backups/knwlge-v<old>-before-upgrade-<stamp>.db`, then upgrades in one transaction. The v2 → v3
upgrade (team edition) creates the owner account (id 1), adds `user_id` columns, moves per-person columns out of
`sessions` into `session_progress` and `course_opens`, and rebuilds `review_queue` with its new key. Each upgrade is
idempotent, and a v0.1.0 database is kept as a test fixture ([tests/fixtures/schema_v2.sql](../../tests/fixtures/schema_v2.sql)).
