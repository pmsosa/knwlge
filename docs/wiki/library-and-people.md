# The library and people

See [index](index.md). Code: [app/library.py](../../app/library.py), [app/achievements.py](../../app/achievements.py),
[app/activity.py](../../app/activity.py), [app/dashboard.py](../../app/dashboard.py), [app/recommend.py](../../app/recommend.py),
[app/texts.py](../../app/texts.py).

## Tags and shelves

- **Tags** are shared, on `courses.tags_json`: lower case, at most 8, 30 characters each. The plan's schema asks for
  2-3; they're kept only if the course has none yet, so an author's tags always win. Authors and admins change them
  (`PUT /api/courses/{id}/tags`); `GET /api/tags` counts the ones on courses this person can open.
- **Shelves** are per person, on `course_prefs`: `pinned`, and `shelf` (NULL automatic, `mine`, `aside`). A course is
  *mine* when it's pinned or on `mine`, or when the shelf is automatic and the person has started it (a session
  started or finished, or a question answered). An author's course that isn't `ready` yet is theirs too. `aside`
  keeps progress and unpins. `PUT /api/courses/{id}/shelf` takes `{pinned}` and/or `{shelf: "mine"|"aside"|"auto"}`.
- `GET /api/courses` returns `tags`, `pinned`, `shelf` and `mine` per course; the home page splits on `mine`, pinned
  first, then by last opened.

## Recommendations

Team mode, authors and admins, published courses only. `POST /api/courses/{id}/recommendations` takes
`{everyone, to: [user ids], note}`: one row per person, or one with `to_user` NULL for everyone; a new one for the same
person (or everyone) on the same course replaces the old. `GET` on the same path gives the people to pick from and the
current list; `DELETE /api/recommendations/{id}` takes one back (whoever made it, or an admin). `recommend.for_user`
gives each course's newest recommendation to this person or everyone, not made by them, and newer than their
`rec_dismissed` row (`POST /api/courses/{id}/recommendations/dismiss`, "not now"); `GET /api/courses` returns it as
`recommended` on published courses, and the home page shows those that aren't *mine* yet under "Recommended for you".

## The welcome and the upload reminder

`texts.py` holds the built-in welcome (Markdown) and reminder; the `welcome_text` and `upload_note` settings replace
them (empty, or the built-in words, clears the setting). `GET /api/me` returns `upload_note` always, and `welcome` until
the person has closed it (`users.prefs_json.welcomed_at`, set by `POST /api/me/welcomed`; `{seen: false}` clears it and
returns the text). The front end shows it after the first page draws, and `uploadNote()` (util.js) puts the reminder
under file inputs, written answers and the tutor. `PUT /api/settings` with `welcome_again` clears everyone's
`welcomed_at`.

## What a course costs

`GET /api/courses/{id}` returns `spend` (all time) and `spend_month` to admins and the course's owner, from
`llm_calls.course_id`. The Course tab shows them.

## Achievements

A built-in set (`achievements.BUILTIN`) applies to every course: first session, half the sessions, all of them,
every quick question tried, every written exercise sent, ten warm-up answers, five tutor questions, notes in three
sessions. Course-themed ones come from the plan (`achievements` in its schema: title, description, a rule and a slot)
into the `achievements` table, replaced each time the plan is redrafted; authors edit them
(`PUT /api/courses/{id}/achievements`), and keys people have earned are kept. Rules are `finish_session`,
`practice_session` (every non-written question in that session tried) and `written_session` (its written work sent).

The app decides who earned what, never the model: `achievements.check` runs after finishing a session, answering,
asking the tutor and saving notes, records new ones in `user_achievements` and returns them (the browser shows a
toast). Nothing is ever taken away.

## The activity feed

Team mode only. `activity.record` writes a row only when the feed is on (`feed_off` isn't set), the person shares
(`users.prefs_json.share_activity`) and the course is published. Turning sharing off deletes that person's rows;
reading the feed also re-checks sharing and visibility. Rows older than 90 days are pruned when the dashboard loads.

## The dashboard

`GET /api/dashboard` (admins, team mode): per person, the courses they've started with sessions done, finished
courses, achievements and last seen; per course, takers, finishers, a per-session count of finishers (the funnel),
sessions where at least 40% of 3+ marked quick answers were missed or revealed, and spend; spend by provider and
person this month; and the feed. Progress only, never scores ([learning](learning.md)).
