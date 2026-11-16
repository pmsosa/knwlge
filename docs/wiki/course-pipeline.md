# The course pipeline

See [index](index.md). Code: [app/pipeline.py](../../app/pipeline.py), [app/prompts.py](../../app/prompts.py),
[app/tiers.py](../../app/tiers.py), [app/editing.py](../../app/editing.py).

## Steps

1. **Create** (`pipeline.create`): the course row, its folder, materials, options (extras); author is the person
   creating it, visibility `draft` in team mode and `published` in personal mode. Enqueues `questions`.
2. **Questions** (flash): 4-6 questions with text or choice answers → status `answering`. Skipping goes straight on.
3. **Plan** (pro): title, summary, prerequisites, a readiness report (teaching and feedback bands, weak spots, safety
   note) and one entry per **slot**. Slots come from the depth's skeleton in [tiers.py](../../app/tiers.py), so the
   shape is fixed (a Quarter is always 22 lessons, 2 reviews, a checkpoint and a capstone); the plan fills them in.
   → status `review`. Changes requested re-run the plan with the request.
4. **Approve**: one `session` job per slot, in order, and a `reading` job. → status `building`.
5. **Session** (flash; checkpoints and projects pro): lesson JSON (goal, hook, chunks with Markdown, worked example,
   check questions and media proposals; practice; exercises with rubrics; wrap-up; reading). `validate()` checks what
   code can check: there are lesson chunks, every multiple-choice question has options and its answer is one of them,
   number answers are plain numbers, every exercise and project option has a rubric. Problems → rewrite with them listed (at most 2 rewrites). Then stored: items, media rows, sources.
6. **Check** (lite): a second model reads the session and lists issues with severity. Major ones → rewrite (same
   limit); anything left becomes a warning shown to editors. → session `ready`.
7. **Reading** (flash with search): up to 20 suggestions for the whole course, then checked in the background
   ([reading](reading.md)). The course is `ready` when every session is.

Each prompt starts from `HOUSE`: self-paced, warm, accurate, say when something's uncertain, explain in your own
words, prefer free and openly licensed sources, Markdown with LaTeX, made-up people in examples, JSON only.
`research()` adds the live-research instructions and turns on optional search.

## Editing

| Action | Function | Notes |
|---|---|---|
| Edit a section or a question by hand | `changes.hand_edit` | Title, Markdown, worked example (50,000 characters each at most); multiple-choice answers must match an option, number answers must be numbers. Live and versioned, or a draft with review on |
| Rewrite or add with the AI | `changes.ask_ai` → `revise` job | Prompt `prompts.revise_chunk`: the section, the session outline, the selected passage (if any) and the request; returns the whole section, as a draft to review |
| Rewrite a question, a whole session, the plan | `changes.ask_ai` → `revise_item`, `redo_session`, `replan` jobs | Drafts; a session rewrite archives the old questions with their answers when accepted ([changes-and-flags](changes-and-flags.md)) |
| Take a question out | delete route → `editing.remove_item` | Archived, answers kept |
| Write a failed or unwritten session again | `pipeline.regenerate_session` | A new `session` job (for sessions that aren't ready yet) |
| Rename, extras, publish | routes in [main.py](../../app/main.py) | Extras apply to sessions written later |
| Export | `editing.export_zip` | Markdown per session with the exporting person's own answers and notes |

Every edit is checked server-side with `editable()` (admins, authors, and a course's owner) and `changes.can_publish()`,
kept as a version, and logged in the audit log. Drafts, versions and flags: [changes-and-flags](changes-and-flags.md).
