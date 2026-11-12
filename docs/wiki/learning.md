# Learning

See [index](index.md). Code: [app/learning.py](../../app/learning.py). Everything here is per person (`user_id`).

## Attempts and marking

- **mcq / numeric**: marked on the spot. Numbers within the item's `tolerance` count.
- **short**: a `mark` job (lite) with `MARK_SHORT_SCHEMA` (correct, comment), at `PRIORITY_NOW`.
- **exercise / project**: a `mark` job (flash) with a rubric; Gemini returns per-criterion points and comments, an
  overall comment and what to revisit. The app clamps each line to its maximum and adds them up, so the score never
  comes from the model's own total. Answers can include uploaded files (photos, PDFs), sent inline.
- Answers are fenced as data in marking prompts (`<<<LEARNER_ANSWER ... LEARNER_ANSWER>>>`, with any `<<<`/`>>>`
  inside defused), and capped at 20,000 characters; files at 15 MB.

## What the browser sees

`public_item()` strips answers, explanations, model answers and rubric details until the person has got the question
right or chosen to reveal it (`item_reveals`). Editors load full items from `/api/items/{id}/full`.

## Warm-ups and spaced review

Every answered quick question goes into `review_queue` (`schedule_review`): right → the interval grows ×2.5 (at
least 2 days); wrong → due now, interval back to 1 day, `misses` + 1. `warmup()` picks up to 4 questions from earlier
sessions: due ones (most missed first), then ones from the previous session, then older ones not seen for a while.
Session 1 has none.

## Progress (no scores)

`session_progress()`: quick questions answered (`tried`) and right, written pieces sent. `course_progress()`: sessions
finished, questions answered, written pieces sent, the next session, and how many questions are due in the review
queue (`due_reviews`, shown as "ready to revisit"). There's deliberately no mastery score or percentage anywhere: the
app is for learning for its own sake, so it shows what's been done and what's coming back, not how well. Right and
wrong still drive the review queue, because that's what makes warm-ups useful. **Finish session** stores the wrap-up
summary and the time; **mark as not finished** clears it.

## Reading mode

`course_prefs(user_id, course_id, reading)`, set with `PUT /api/courses/{id}/reading {"on": bool}` (any person who can
view the course; nothing is audited, it's a personal preference). Course and session responses carry
`reading_mode`. The server skips building warm-ups for a session in Reading mode; everything else is the page's job
(`js/readingmode.js`, `views/session.js`): it leaves out check, practice, exercise and project items, the quiz-like
widgets (`QUIZ_WIDGETS`: flashcards, order, match, cloze) and the question counts, and shows the key points with a
**mark as read** button that keeps any earlier summary. Items, attempts and the review queue are untouched, so
turning it off restores everything.

## The tutor

`ask()` stores the question, builds the context with `chat_context()` and enqueues a `chat` job (flash, with the
course's materials; live research if the course has it on). Scope `course` sends the plan and session list; a
session id sends the whole session; an item id adds the question, its answer, rubric and the person's latest attempt
and feedback. The last messages of the conversation go along. One pending question at a time per conversation;
questions up to 4,000 characters. Sources from search are appended to the reply.
