# Knwlge: expansion plan (team mode)

Turning Knwlge from a single-person learning app into a course-building and teaching platform for groups such as clubs,
classes or study groups: some people build courses, publish them to the group, and everyone learns at their own pace.
"Team mode" is the app's name for this multi-person setup.

Decided 2026-11-10. Builds on [PLAN.md](PLAN.md); everything there still applies unless changed here.

## Decisions

| Topic | Decision |
|---|---|
| Hosting | Anywhere Docker runs. Listen address and port are settings (`0.0.0.0:9180` by default); network access, firewalls and HTTPS are the deployer's job |
| Identity | Built-in accounts: username and password. Admins create accounts and set a first password; the user must change it at first sign-in. No assumptions about the network in front of the app |
| Roles | admin, author, learner |
| Migration | today's single-user data becomes the first admin's |
| Budget | one budget for the whole install; only admins see spend |
| Auditing | yes: who did what, when, at what cost |
| Freshness | Live research (already built), can be made mandatory by an admin |
| Providers | Gemini, OpenAI, Anthropic, LiteLLM / any OpenAI-compatible endpoint; keys tested and model lists filled in automatically |
| Data sensitivity | a reminder under upload and submit buttons, and a one-time welcome screen |
| Social | optional, opt-in activity feed and per-course achievements; admin-only dashboard |

## Phases

1. Users, roles, per-user progress, migration, audit log  **(done)**
2. Shared courses: drafts, publishing, versions; flag-and-recheck; targeted AI edits
3. Multiple AI providers
4. Admin dashboard, activity feed, achievements, welcome screen
5. Hands-on labs (its own design document)

Each phase ships on its own and keeps the app usable.

---

## Phase 1: users, roles and audit

### Identity
- Built-in accounts, nothing network-specific. An admin creates an account (username, display name, role) and sets a
  first password, or lets the app generate one to hand over. At first sign-in the user must choose a new password.
- Passwords are hashed with scrypt (salted). Sign-in sets an HttpOnly, SameSite cookie for a server-side session
  (Secure when the request arrived over HTTPS); sessions expire after 30 idle days and are revoked on password change,
  password reset or deactivation. Repeated failed sign-ins are slowed down per account.
- The first admin is created from the command line (`python -m app.accounts add-admin <name>`, which prints a
  one-time password). In a personal install upgraded to team mode, that admin takes over the existing owner's data.
- Admins can rename, change roles, reset passwords and deactivate accounts (never the last active admin).
- The app listens on a configurable address and port; whether that is `127.0.0.1` behind a proxy, `0.0.0.0` behind a
  firewall, plain HTTP or HTTPS is up to the deployment.

### Roles
| Role | Can |
|---|---|
| learner | take published courses, flag problems, use the tutor, see their own progress |
| author | everything a learner can, plus create, edit and publish courses, run targeted AI edits, review flags on their courses |
| admin | everything, plus manage users and roles, settings, providers and keys, budget and spend, the dashboard, audit log |

Checks happen on the server for every endpoint, not just in the UI.

### What becomes per-user
- attempts, review queue (warm-ups), progress
- session done / summary notes / personal notes
- tutor chats
- course "last opened", continue banner
- theme choice (already per device)

### What stays shared
- courses, sessions, items, media, reading lists, sources
- materials attached to a course (visible to its authors)

### Migration
- One-off migration on upgrade: create the first admin from the configured login, assign every existing course,
  attempt, note and chat to them, mark existing courses as published by them.
- Backed up first (a copy of the database), schema version bump, tested on a copy of a real database.

### Audit log
- Table: who, when, action, target (course/session/item/user/setting), details (JSON), cost if an AI call.
- Logged: course created/published/unpublished/deleted, manual edits, AI edits (instruction, before/after), flag
  verdicts and resolutions, role changes, provider/key changes (never the key itself), budget changes.
- Admin view with filters (person, course, action, date) and CSV export.
- Kept indefinitely (small); prunable by admins.

## Phase 2: shared courses, flags and AI edits

### Drafts and publishing
- A new course is a draft visible only to its author (and admins) until published.
- Publish makes it visible to everyone; unpublish hides it again (learners' progress is kept).
- Optional: "recommend to" people or the whole group (a nudge on their home page, no deadlines).
- Course page shows author, last updated, version.

### Versioning
- Every edited piece (lesson part, question, exercise, session, plan) keeps previous versions with who/when/why.
- Roll back any piece to an earlier version.
- If a question's answer changes, existing attempts are marked "question changed since you answered" rather than
  re-scored silently.

### Flag and recheck ("this is wrong")
- Learners can flag a lesson part, question, answer key, feedback they got, or a reading item, with a comment.
- A background job re-checks it: the flagged piece, the surrounding lesson, the learner's comment, live research if
  on. Verdict: **confirmed problem** (with what's wrong and a proposed fix), **unclear**, or **looks right** (with the
  explanation).
- The learner sees the verdict on the piece they flagged.
- Authors and admins get a flags queue: open / confirmed / dismissed / fixed, per course, with the verdict and the
  proposed fix. One click turns a confirmed flag into a targeted AI edit pre-filled with the fix.
- Every verdict and resolution goes in the audit log.

### Targeted AI edits (authors and admins)
- Select a piece: a lesson part (text, worked example, its media), a question or exercise, a whole session, or the
  course plan (to add, remove or reorder sessions).
- Type an instruction: "fix the explanation of photosynthesis, it mixes up the light and dark reactions", "add an
  example using a sourdough starter", "add a session on the Harlem Renaissance after session 6".
- The AI rewrites only that piece, using the rest of the course as context and live research if on, with the same
  checks as generation (schema, media checks, second-model read-through).
- Review screen: before/after diff, accept or discard. Nothing changes for learners until accepted.
- Ripple handling: new or changed questions join the warm-up pool; an added session updates outline, numbering and
  the reading list; changed answers flag existing attempts.
- Logged with instruction, before/after and cost; previous version kept.

## Phase 3: multiple AI providers

- Provider layer with one interface: text with JSON-schema output, web search (where supported), image generation
  (where supported), token usage for cost.
- Providers: Gemini, OpenAI, Anthropic, and LiteLLM or any OpenAI-compatible endpoint (which also covers local or
  self-hosted models).
- Admin pastes a key; the app tests it immediately and lists the models it can use, with prices where known.
- Each role picks provider + model: planning, writing, checks, marking, tutor, illustrations, research.
- Each role declares what it needs (structured output, search, images); the settings page only offers models that
  can do it, and falls back where a capability is missing (e.g. search via a separate step, or off with a note).
- Per-provider price tables; unknown prices logged as unknown, as today.
- Keys are instance-wide (admin only), stored server-side, never sent to browsers, never logged.
- Useful when one provider is over-cautious with a subject (medicine, chemistry, history of warfare...): switch that
  role to another.

## Phase 4: dashboard, social, achievements, welcome

### Admin dashboard
- Who is taking what: per person, courses in progress, sessions done, last active (no scores: see PLAN).
- Per course: enrolled, completion funnel by session, where people get stuck (sessions with many missed or
  revealed answers), open flags.
- Spend: this month, per course, per person, per provider, against the budget.

### Shared budget (admin only)
- One monthly cap for everyone (as today, but install-wide); work pauses when reached, admins notified in-app.
- Spend and usage pages visible to admins only; learners never see costs.
- Optional soft per-person limit later if needed.

### Activity feed (opt-in)
- "Alex finished session 4 of Astronomy for Beginners", "Sam completed Watercolour Basics", "Kim shared a note on X".
- Each person chooses whether their activity appears (default off). Admin can turn the feed off entirely.

### Achievements
- Generated per course with the plan (and editable by authors): e.g. "Finished every warm-up", "Completed the
  capstone", "Flagged a real error", course-themed ones ("First star chart").
- Reward exploring and finishing, never speed. Shown on the person's profile; in the feed only if they opted in.

### Welcome screen and data reminder
- First visit: a short "lay of the land": what Knwlge is, self-paced, how courses are made, that uploads and answers
  go to the configured AI provider, what not to upload (other people's personal details, private documents, passwords).
- A one-line reminder under every upload and submit button.

## Phase 5: hands-on labs

Separate design document before building. Constraints and outline:
- Labs run on a separate machine (space and isolation). The Knwlge server starts, stops and checks labs; the lab
  machine only serves the lab itself to the learner, and never needs to connect back to the Knwlge server.
- Per-learner lab containers (a coding sandbox, a data notebook, a small web server to configure), time-limited,
  reset on demand.
- Automatic checks: tests passing, a file produced, an expected output.
- Lab definitions authored like courses (and possibly AI-drafted, author-reviewed).
- Containers first; no virtual machines unless there's a clear need.

## Data model changes (summary)

- `users` (username, display name, role, password hash, must-change flag, active, joined, last seen, prefs)
- `login_sessions` (token hash, user, created, last used)
- `courses`: + author_id, status (draft/published), published_at, version
- per-user tables or user_id columns: attempts, review_queue, session progress (done, summary, note), chat_messages,
  course last-opened
- `versions` (piece type, piece id, content, who, when, reason)
- `flags` (who, piece, comment, status, verdict, proposed fix, resolved by/when)
- `edit_requests` (who, piece, instruction, before, after, status, cost)
- `audit_log`
- `providers` (type, base URL, encrypted key reference, models, tested_at) and role → provider/model settings
- `achievements` (per course) and `user_achievements`
- `activity` (feed events)

## Security notes

- Identity from the app's own accounts (scrypt-hashed passwords, server-side sessions, forced first change,
  slowed-down failed sign-ins). Writes still need the custom request header, so cookies can't be used cross-site.
- Role checks on every endpoint; course and draft visibility enforced server-side.
- Keys admin-only, never in responses or logs; audit records key changes without values.
- Learner flags and edit instructions are data, not instructions to the model (fenced like answers today).
- Existing protections stay: CSP, sandboxed experiments, safe link fetching, upload limits.

## Deployment modes

- `KNWLGE_MODE=personal` (default) or `team`, set at install time. One codebase, one data model.
- Personal: one built-in owner with all permissions. Open by default (no sign-in); the owner can optionally set a
  password in Settings, after which the app asks for it (and can turn it off again). Team-only features hidden
  (users/roles, publishing, flags queue, dashboard, feed, audit page). Still available: double-check
  ("flag") for yourself, targeted AI edits, versions, achievements, providers, budget, export/import.
- Team: sign-in with accounts, roles, everything in this plan.
- Personal → team: the owner becomes the first admin; courses become published; progress stays theirs.
- Team → personal: refused if more than one active user.
- `/api/status` reports the mode; the UI shows or hides features from it; the server enforces it.

## Export and import (both modes)

- **Course package (`.knwlge` zip):** manifest with format version; plan, sessions, items (answers, rubrics),
  media files and credits, reading list and sources, achievements, options. No personal progress by default
  (personal mode may include "my progress").
- **Import:** treated as untrusted. Schema validation, size limits, zip-slip protection, media re-checks
  (SVG, experiments, widgets), new ids. Arrives as a draft (team) owned by the importer.
- **PDF:** printable course page (print stylesheet, browser Save as PDF) first; server-side PDF via headless
  Chromium later if needed. Optional answer-key appendix. Interactive media shown as a note and link.
- **Markdown zip:** as today.
- Team mode: authors/admins export courses they can edit; learners print published courses and export their
  own notes. Exports and imports are audited.

## Open questions for later (These aren't that important right now so we can leave that towards the end)

- Recommend/assign courses to specific people: in or out?
- Per-person soft spend limits?
- Should authors see their own course's spend?
- Lab hosting details and resource limits.

---

## Review notes (2026-11-10)

### Identity (resolved)
Decided 2026-11-10: no identity from a proxy header. (A design that trusted a header set by a VPN or reverse proxy
was considered, but behind some container setups, such as rootless Docker, every client appears to come from the
Docker gateway, so a forwarded identity header couldn't be told apart from a forged one.) Built-in username/password
accounts instead, as described under Phase 1.

### Smaller notes
- "Encrypted key reference": the encryption key would live on the same box as the data, so this mostly protects
  backups and casual reads. Worth doing, but keys are only as safe as the box.
- Learner flags and edit instructions are fenced as data in prompts, like answers today.
- Labs: learners' browsers reach the lab machine directly; the Knwlge server talks to its lab controller; nothing on
  the lab machine ever needs to call the Knwlge server (results are pulled).
