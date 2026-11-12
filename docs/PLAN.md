# Knwlge: plan

Knwlge (pronounced "knowledge") is a self-hosted web app that turns any subject into a self-paced course: you
name a subject, Gemini plans it at the depth you pick, writes every session, marks your written work, and suggests
books, videos and articles for going further. It's for learning fun things in your own time: no deadlines, no
notifications, no grades to chase.

Plan agreed 2026-11-09. Inspired by [SelfSemester](https://github.com/munitkala/selfsemester) (MIT), a Windows/Tauri
app that drives Claude Code. Its course pipeline, prompts and classroom layout are the starting point; the code is
rewritten, not copied.

## Decisions

| Topic | Decision |
|---|---|
| Name | Knwlge |
| Where | Self-hosted, one container, port **9180** by default; the network around it and HTTPS are up to whoever runs it |
| Stack | Python 3.12, FastAPI, SQLite, one Docker container (compose). Plain HTML/CSS/JS front end, no build step |
| AI | Google Gemini with your API key, REST over `httpx`. No SDK needed |
| Users | Single user. No accounts, profiles or login (accounts came later: see [TEAM-PLAN](TEAM-PLAN.md)) |
| Pace | Self-paced. No deadlines, late penalties, release schedule, reminders or notifications |
| Marks | Feedback, not grades. No score of any kind (a mastery percentage was tried and dropped on 2026-11-11: it felt like a grade). Unlimited retries. Answers viewable whenever you want. No transcript |
| Budget | No cap by default. Optional monthly cap (USD) in Settings; usage page with cost per course |
| Course builder (write a course without AI) | Not in v1. Instead: edit a generated course (fix a lesson, swap a question, add a note) |
| Further reading | Every course and session gets verified suggestions: books, YouTube videos, articles, courses |

## Course depth

Sessions are all-in study time: the "homework" (retrieval, practice, a written exercise) is inside each session.
Quarter covers a university quarter course's syllabus; it doesn't claim the full workload (a real quarter course is
about 30 h in class plus about 60 h outside). An optional exercise bank can add more practice.

| Tier | Sessions | Each | Total | Suggested pace (ignorable) | Covers |
|---|---|---|---|---|---|
| Cursory Dive | 6 + 1 wrap-up | 45 min | ~5 h | ~2 a week, ~3 weeks | The big map: core vocabulary, 4-6 central ideas, why it matters, where to go next |
| Boot Camp | 12 + 2 project | 50 min | ~12 h | ~2 a week, ~7 weeks | Working skill: the core syllabus with practice, one small project |
| Quarter | 22 + 3 project | 60 min | ~25 h | ~2 a week, ~12 weeks | A full intro course: sub-topics, harder problems, a midpoint checkpoint, a capstone |

How the tiers differ besides length:

- **Breadth vs depth.** Dive: one session per big idea, conceptual, no prerequisites. Boot Camp: core topics at
  "can use it" depth. Quarter: adds sub-topics, the deeper why (proofs, edge cases), one or two advanced topics.
- **Practice.** Dive about 4 check questions + 1 written exercise per session; Boot Camp about 8 + 1; Quarter about
  10-12 + 1-2, plus the optional exercise bank.
- **Difficulty arc.** More worked examples early, faded faster in longer tiers (expertise reversal).
- **Projects.** Dive: none, ends with a reflective wrap-up and a 10-question "what stuck" quiz. Boot Camp: one small
  project. Quarter: a "put it together" checkpoint at the middle and a capstone.
- **Prerequisites.** Quarter lists them up front and offers a one-session primer, or suggests taking the Dive first.
  The Dive is a valid on-ramp to the Quarter.

## A session (60 min; 45/50-minute tiers shrink steps 3 and 4)

1. **Warm-up, 5 min.** 3-4 questions from memory on earlier sessions (the last one plus older ones). Questions you
   missed come back sooner.
2. **Goal, 2 min.** The one question this session answers.
3. **Learn, about 25 min.** 3-4 short chunks (about 6 min of reading each): one idea, a worked example, 1-2 check
   questions with instant feedback.
4. **Practice, 15 min.** Problems that go from partly worked to independent. From session 3 on, about a third mixes
   in earlier topics. Some ask "explain why".
5. **Written exercise, 8 min.** A short answer Gemini marks against a rubric, with feedback rather than a grade.
6. **Wrap-up, 5 min.** You write a 2-3 sentence summary from memory, then see the key points and a teaser for next
   time.

Every 5-6 sessions, a **review session** (mostly retrieval, little new material). Projects: pick one of 2-3 options
suited to the subject (a program, an essay, an annotated listening list, a problem set); Gemini gives rubric feedback
and you can revise.

Evidence: Dunlosky et al. 2013 (retrieval practice and spacing are "high utility"); Adesope et al. 2017 (practice
tests beat restudying); Cepeda et al. 2008 (spacing); Guo et al. 2014 (short chunks); Sweller, Renkl (worked
examples); Kalyuga (expertise reversal); Jordan 2014 and Coursera (shorter courses get finished more). Chunk sizes for
text and the further-reading counts are judgment, not evidence.

## Further reading

- Per course: Dive about 5, Boot Camp about 8, Quarter about 12. Per session: 0-2 optional items.
- Each item: type (book, video, article, course, podcast), title, creator, link, level, rough time, why it's worth
  it, free or paid. One marked "if you only read one thing".
- **Verified before it's shown**, because AI invents citations: books against Open Library (title/author/ISBN),
  YouTube videos through YouTube's oEmbed lookup (exists, real title, channel), other links by fetching them (status
  and page title). Grounded-search links are Google redirects and are resolved to the real URL. Anything unverified
  is dropped.
- Prefer free, openly licensed material; mark paid things as such. No paywall workarounds.

## How a course is made

Each step is a row in a job queue (survives restarts, rate limits and the budget cap), run one at a time by a
background worker inside the app.

1. **Subject.** You name it, add optional notes, pick a depth, and optionally attach materials (PDFs, images, notes).
2. **Questions** (Flash). 4-8 questions: goal, current level, what you already know, what you want to make or do with
   it. No hours/deadline questions.
3. **Plan** (Pro). Title, summary, prerequisites, session list (with review, checkpoint and project sessions where
   the tier has them), and a readiness note: how well Gemini can teach and give feedback on this subject, weak spots,
   and a safety note for risky subjects (health, law, money, electrical work...). You approve, or ask for changes.
4. **Further reading** (Flash with Google Search grounding), then verification.
5. **Sessions** (Flash; projects and checkpoints by Pro). Lesson chunks, check questions, practice, written exercise,
   rubric, answer key, warm-up questions drawn from earlier sessions, 0-2 reading items.
6. **Check** (Flash-Lite). Is each question solvable from the lesson, is every answer key right (re-derive numbers),
   does each multiple-choice answer match an option, do rubric points add up. Major problems: the session is rewritten
   once. Idea for later: solve every answer key twice independently and compare.
7. **Ready.** Everything open from the start, with a "next up" suggestion. Progress tracked per session.

Generation runs in the background; you can start session 1 as soon as it's written (no need to wait for the rest).

## Doing the work

- Multiple choice and number questions: marked instantly by the app.
- Written answers and uploads (photos, PDFs): marked by Gemini against the rubric, with comments and what to revisit.
  Points are computed by the app against the rubric's real totals, each line capped at its maximum; your answer is
  fenced off in the prompt as data to be marked.
- Retry as often as you like; "show me the answer" whenever you want.
- **Ask about it:** a chat on any session or exercise ("why is this wrong?", "explain chunk 2 differently").
- Progress per session: questions answered, written work sent. Wrong answers feed future warm-ups.
- Finished courses can be exported as a Markdown folder (lessons, your work, feedback, reading list).

## Gemini

Model ids and prices as of 2026-11-09 (USD per 1M tokens, input/output). All three are settings.

| Role | Model | Price | Notes |
|---|---|---|---|
| Pro: plans, projects | `gemini-4-argon` | 2.00 / 10.00 | Doubles to 4.00 / 20.00 on 2026-12-01. No free tier |
| Flash: questions, sessions, marking, chat | `gemini-3.8-flash` | 0.75 / 3.75 | Doubles to 1.50 / 7.50 on 2027-01-01. `gemini-3.6-flash` is the stable fallback |
| Lite: checks | `gemini-3.5-flash-lite` | 0.30 / 2.50 | Stable |

- Structured output: `responseMimeType: application/json` + `responseJsonSchema` (standard JSON Schema; `enum`,
  `required`, `additionalProperties`, nesting all supported; length limits not enforced, so validate in code).
- Google Search grounding can be combined with JSON schema on Gemini 3+ (marked Preview). Billed per search query:
  5,000 free a month, then $14 per 1,000.
- PDFs and images go in the request directly (inline bytes, or the Files API for big ones; up to 50 MB / 1,000 pages).
  So the model never reads files from disk.
- Cost per call from `usageMetadata`: input = `promptTokenCount`, output = `candidatesTokenCount` +
  `thoughtsTokenCount`. A price table with effective dates lives in the app, so the December/January changes are
  handled.
- Errors: 429 `RESOURCE_EXHAUSTED` = wait and retry with backoff; 402 = prepaid credit gone, stop and say so; 500/503
  retry; 400 = our bug, fail the job with the message.
- The key is pasted into Settings, stored in the database, never sent to the browser.
- Google now leads with its newer Interactions API; `generateContent` is labeled legacy but supported. Start with
  `generateContent`, keep the client small so switching later is easy.

## Budget

- Every call is logged: model, tokens, search queries, cost.
- Optional monthly cap (calendar month, USD). When the next job would go over, the queue pauses and the app says so;
  raise the cap or wait for the next month.
- Usage page: this month, per course, per step.

## Data

SQLite at `data/knwlge.db` plus `data/courses/<id>/` (materials, uploads). Back up the `data/` folder.

Tables: `settings`, `courses`, `materials`, `sessions`, `items` (check questions, practice, exercises, projects),
`attempts`, `feedback`, `reading`, `chat_messages`, `jobs`, `llm_calls`, `review_queue` (missed questions due back).

## Security (lessons from reviewing SelfSemester)

- The model gets content in the request, never file-system access.
- IDs from the browser are looked up in the database; file paths are built only from stored ids, resolved and checked
  to stay inside `data/courses/<id>/`.
- Uploads: type allow-list (PDF, images, text) and a size limit.
- Markdown rendered with DOMPurify after maths is rendered (not before), plus a strict Content-Security-Policy.
  External links open in a new tab with `rel=noopener`.
- Answer keys are only sent to the browser when you ask to see them.
- No telemetry; the only outbound calls are Gemini and the link checks.

## Screens

Plain HTML/CSS/JS, dark theme, in the spirit of SelfSemester's classroom.

- **Home:** courses in progress with "continue where you left off", and a new-course button.
- **New course:** subject, notes, depth picker (with session counts and hours), materials; then the questions; then
  the plan to approve.
- **Course:** overview (summary, prerequisites, progress), sessions list, further reading, materials, ask-about-it.
- **Session:** warm-up, chunks with check questions, practice, written exercise with feedback, wrap-up; previous/next.
- **Usage:** spend this month, per course, budget setting.
- **Settings:** Gemini key, models, budget, export.

Favicon from the start (placeholder inline SVG, then the `app-icons` skill); README with banner (`media-gen`) and
screenshots from a demo with made-up courses, following the glyph-sast README.

## Build order

1. **Foundation:** Docker/compose, FastAPI, database, Gemini client with cost logging, job queue and worker, budget,
   settings page. Tests with a fake Gemini.
2. **Making a course:** questions, plan, approve, sessions, checks.
3. **Taking a course:** session page, instant marking, written-exercise marking, retries, show answer.
4. **Further reading** with verification.
5. **Warm-ups and review queue**, progress, ask-about-it chat.
6. **Polish:** materials, edit a generated course, export, usage page, favicon/icons, README, optional HTTPS/PWA.

## Storage

The app itself is small (code, a SQLite file, uploads), so everything lives in one `data/` folder on fast local
storage. Big, replaceable extras (for example a cache of downloaded open textbooks), if they ever appear, could go on
a separate volume; the app would then check it's there and say so plainly rather than quietly fill the main disk.

## Update 2026-11-09: media, look and layout

- **Extras, chosen when creating a course** (all on by default, changeable later on the Course tab): diagrams
  (Mermaid, SVG), real pictures and audio from Wikimedia Commons, AI illustrations (Nano Banana 2.1, ~3¢ each, at most
  two a session), YouTube videos (click to load, no-cookie player), interactive exercises (flashcards, ordering,
  matching, fill-the-gaps, timelines, plots with sliders) and experiments (Gemini-written simulations in a sandboxed,
  network-less frame). At most five media items per session; the app checks and fetches everything itself.
- **Look:** RawBlock's structure on papyrus with a green accent; compact; dark theme as green-black with papyrus text.
- **Layout:** app-style. The bar stays put, only content scrolls; course and session pages have a fixed sidebar.
