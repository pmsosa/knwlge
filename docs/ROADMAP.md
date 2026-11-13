# Roadmap

What's left to build, in rough order. The details and the decisions behind each item are in
[TEAM-PLAN](TEAM-PLAN.md) (the multi-person work) and [PLAN](PLAN.md) (the original single-user build).
Tick items off here as they land.

## Done

- [x] Personal edition: depths, planning, sessions with checks and a second read-through, marking, warm-ups and
      spaced review, verified further reading, the tutor, media in lessons, live research, budget and usage
- [x] Team mode, phase 1: accounts and roles, sign-in with a forced first password change, per-person progress,
      drafts and publishing, the audit log, the upgrade from single-user databases
- [x] Editing: right-click a section to edit it by hand, or have Gemini rewrite it or add to it
- [x] Reading mode: each person can hide questions, practice, written work and warm-ups on any course
- [x] No scores: courses show sessions done, questions answered and what's ready to revisit, never a mastery percentage
- [x] Everyone can change their own display name (`#/account`)
- [x] Installable app (manifest and service worker), phone layout with a menu, Lucide icons
- [x] User guide, technical wiki, browser smoke test and repeatable screenshots (`tools/e2e.sh`)
- [x] **v0.3** Home page: my courses (started, added or pinned) above everything available, with search and shared tags
      (suggested with the plan, edited by authors)
- [x] **v0.3** Other AI providers: OpenAI, Anthropic and any OpenAI-compatible endpoint beside Gemini, a provider and
      model per role, keys tested on entry, model lists filled in, prices per provider (built in for Gemini and Claude,
      entered by an admin for the rest)
- [x] **v0.3** `.knwlge` course packages (optionally with your own progress) and an import that treats them as untrusted
- [x] **v0.3** Print a course (print stylesheet, optional answers) for Save as PDF
- [x] **v0.3** Admin dashboard (team mode): who is taking what, per-session progress, where people get stuck, spend by
      course, person and provider
- [x] **v0.3** Opt-in activity feed (off by default per person, an admin switch for everyone) and achievements (a
      built-in set plus course-themed ones written with the plan, editable by authors)

## Phase 2: shared courses, flags and AI edits

- [ ] **Review before AI edits go live:** show before and after for a section rewrite and accept or discard it
      (today the new version goes live as soon as Gemini answers)
- [ ] **Versions:** keep earlier versions of every edited piece with who, when and why; roll back any of them
- [ ] Mark attempts on a question whose answer changed ("changed since you answered") instead of re-scoring silently
- [ ] **AI edits beyond sections:** a question or exercise, a whole session, the course plan (add, remove or reorder
      sessions), with the same checks as writing and a second read-through
- [ ] **Flag and recheck:** learners flag a part, question, answer key, feedback or reading item; Gemini rechecks it;
      a flags queue for authors, and one click from a confirmed flag to an AI edit
- [ ] Course page shows the author, last update and version
- [ ] Optional: "recommend to" people or the whole group (a nudge, no deadlines)

## Phase 3: other AI providers (follow-ups)

- [ ] Web search for OpenAI (its Responses API) and for OpenAI-compatible endpoints that offer it; today only Gemini
      and Claude search, and the others write reading lists without it (still checked link by link)
- [ ] Price lists fetched for OpenAI models instead of typed in

## Phase 4: welcome

- [ ] A one-time welcome screen, and a one-line reminder under upload and submit buttons about what not to upload

## Phase 5: hands-on labs

- [ ] Its own design document first: per-learner sandboxes on a separate machine, started and checked by Knwlge

## Export and import (follow-ups)

- [ ] A server-made PDF (headless Chromium) if printing from the browser isn't enough

## Known limits

- [ ] **18 MB per request:** the files attached to one Gemini request (your materials and an answer's uploads) are
      sent inline and capped at 18 MB together; bigger PDFs are left out. Google's Files API would lift this.
- [ ] **No writing a course by hand:** every course starts from Gemini. You can edit everything afterwards, but there's
      no blank course builder.
- [ ] **No automated browser tests in CI:** `tools/e2e.sh` runs the smoke test locally; nothing runs it on each push yet.

## Open questions

- Recommend or assign courses to specific people: in or out?
- Per-person soft spend limits?
- Should authors see what their own courses cost?
