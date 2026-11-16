# Changes, review, versions and flags

See [index](index.md). Code: [app/changes.py](../../app/changes.py) and [app/flags.py](../../app/flags.py); the review,
history and flag dialogs and the course page's Changes and Flags tabs are
[app/static/js/review.js](../../app/static/js/review.js).

## Targets

Everything editable in a written course is one of four targets, each with a JSON shape that versions store and drafts
propose:

| Target | Id | Shape |
|---|---|---|
| `chunk` | `<session>@<gen>:<index>` | `title`, `markdown`, `example_markdown` |
| `item` | the item id | `title`, `prompt`, `options`, `answer`, `explanation`, `rubric` (plus `qtype`, `archived`) |
| `session` | the session id | `gen`, `title`, `content` (the display JSON), the live `items` and `media` ids |
| `plan` | the course id | `title`, `summary`, `sessions` (id, seq, kind, title, minutes, topics, objectives, `archived`) |

`changes.current()` reads a target's live state in that shape; `_write()` puts a stored shape live.

## Versions

`versions` holds every state a target has been in: `n` counts per target, `source` is `original`, `hand`, `ai` or
`rollback`, with `why` (the wish or edit note), who and when. The first change to a target records its `original`
first, so the version list always starts from what was first written. Versions are never deleted.
`changes.restore()` writes an old version's data live and records it as a new `rollback` version; with review on and
someone who can't publish, it makes a draft instead.

## Drafts (`changes`)

A row in `changes` is a draft: `kind` `ai` or `hand`, `status` `working` → `pending` → `accepted` / `discarded` (or
`failed`), the target's state when it was asked for (`base_json`), the proposal (`proposed_json`), notes for the
reviewer, who asked, and `auto_publish`.

- **AI changes** (`ask_ai`) are always drafts. They're jobs whose `ref` is `change:<id>`: `revise` (a chunk, rewrite
  or add), `revise_item` (one question, same type, cleaned like a hand edit), `redo_session` (the whole session, the
  same prompt as writing it; problems the app finds trigger one more try, then become notes; then a `redo_check` job,
  the same second read-through a new session gets, while the draft stays `working` with its proposal stored: major
  issues trigger one more try if there's been only one, then become "Second read-through:" notes; if the check can't
  run, the draft goes to review saying so) and `replan` (the plan:
  kept sessions by id, new ones with an empty id, removed ones left out; ids the model made up become new sessions).
  When the job finishes the draft is `pending`; if it was asked for with "publish straight away" by someone who can
  publish, it's accepted at once (`accept(user=None)`).
- **Hand edits** (`hand_edit`) of chunks and questions go live at once, recorded as a version, for anyone who can
  publish; otherwise they're `pending` drafts.
- **Accepting** checks the target still matches `base_json`; if it changed since, it needs `force` (the review screen's
  "accept anyway"). It records the original if needed, writes the proposal, records the new version, bumps the course's
  `version`, `updated_at` and `updated_by`, and closes flags on that target.
- **Discarding**: whoever asked, or anyone who can publish. A `working` draft's job is cancelled.
- Only one AI draft per target is worked on at a time (`busy`).

### Who publishes

`can_publish(user, course)`: anyone who can edit (`auth.can_edit`: admins, authors on any course they can see, and a
course's owner), unless review is on (`settings.review_required`, team mode only): then the course's owner and admins.
Publishing a whole course to everyone is separate (`auth.can_publish_course`): admins, the owner if they're an author,
and any author for a learner's suggested course.

## Rewriting a session without losing anything

A session has a `gen` (generation). Accepting a `redo_session` draft archives the live items and media
(`items.archived`, `media.archived`, with every attempt, reveal and review kept), then stores the new content with ids
of their own (`<session>-g<gen>-i01`, `-g<gen>-m11`) and sets `gen`. Restoring an earlier session version archives the
live ones and un-archives the ones its version lists. Chunk ids include the gen, so a draft or version of a part of
an earlier generation can't land on the new text. Every query a learner's view, progress, warm-ups, achievements, the
dashboard, packages and printing make skips archived rows.

## Plan changes

Accepting a plan draft (`_apply_plan`) renumbers `seq`, updates kept sessions' titles, topics and objectives, inserts
new sessions (`<course>-sNN`, the next free number) and queues them for writing, and archives removed sessions
(`sessions.archived`, `seq` moved past 1000). Themed achievements follow their session to its new number; ones whose
session left go. Kept sessions the model marked `rewrite` get a `redo_session` draft each. Archived sessions show only
to people who have progress in them, under "Earlier sessions". Restoring an old plan brings back archived sessions
it lists and archives ones it doesn't.

## Changed since you answered

When an accepted change (or a rollback) alters a question's prompt, options or answer, the item gets `changed_at` and
`changed_after` (the newest attempt id at that moment). `learning.public_item` sets `changed_since` when the person's
latest attempt is at or before it: their result stays, with a note. Nothing is re-marked automatically.

## Flags

`flags.create` (anyone who can see the course; 30 a day per person; one open flag per person and target) takes a
`chunk`, an `item`, `feedback` (an attempt id: only your own marked written answer) or `reading` (a verified reading
row), and queues a `flag_check` job (role `checks`) with the content and the learner's note, fenced. The answer sets
`verdict` (`right`, `wrong`, `unsure`), `reason` and `suggestion`, and the flag goes `checking` → `open`. Editors work
through `GET /api/courses/{id}/flags` (open ones first, likely-wrong first):

| Action | What happens |
|---|---|
| `fix` | chunk or item: an AI draft from the flag (`flag_id` on the change), flag `fixing`; accepting the draft closes it as `fixed`, discarding reopens it. Feedback: `learning.remark` marks the attempt again. Reading: the row is dropped |
| `fixed` | closed as fixed by hand, with an optional reply |
| `dismiss` | closed as fine, with an optional reply |

The learner sees status and reply at `GET /api/me/flags` (never the suggestion meant for editors).

## Learners' own courses

`settings.learner_courses` (team mode) lets learners create courses (`POST /api/courses`). Their courses are drafts,
visible to them and admins; `POST /api/courses/{id}/suggest` sets `courses.suggested_at`, which makes the course visible
to authors (who can then publish it).

## The learner allowance

`settings.learner_cap_usd` is one monthly amount for every learner (authors and admins have none).
`budget.learner_spend` sums this month's `llm_calls` started by the learner (`user_id`), on any course: the tutor,
marking their written answers, flag checks, their own courses. Once it's reached, `budget.check_learner` refuses new
AI work with a plain message (a tutor question, a written answer, a flag, an AI edit, a new course), and
`budget.hold_capped_learners` (each worker pass) parks anything they'd already queued as `waiting` / `learner_cap`,
releasing it when they're under again (a new month, or the amount raised or cleared). A re-mark an editor asks for
after a flag is started by the editor, so it doesn't count. `GET /api/me/allowance` gives a learner `{cap, used}`.

## Routes

| Route | |
|---|---|
| `PUT /api/sessions/{id}/chunks/{i}`, `PUT /api/items/{id}` | Hand edits (`gen` checks the session wasn't rewritten meanwhile) |
| `POST /api/sessions/{id}/chunks/{i}/revise`, `POST /api/items/{id}/revise`, `POST /api/sessions/{id}/regenerate`, `POST /api/courses/{id}/replan` | AI drafts (`publish_now`) |
| `GET /api/courses/{id}/changes?all=1`, `GET /api/changes/{id}`, `POST /api/changes/{id}/accept`, `POST /api/changes/{id}/discard` | Review |
| `GET /api/history?target=&id=`, `POST /api/versions/{id}/restore` | Versions |
| `POST /api/flags`, `GET /api/courses/{id}/flags`, `GET /api/me/flags`, `POST /api/flags/{id}/fix\|fixed\|dismiss` | Flags |
| `POST /api/courses/{id}/suggest` | A learner's course, suggested for everyone |

Tests: [tests/test_v04.py](../../tests/test_v04.py).
