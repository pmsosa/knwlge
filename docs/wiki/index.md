# Knwlge technical wiki

Living documentation, one topic per page, cross-linked. User guide with screenshots: [wiki/](../../wiki/README.md).
What's left to build: [ROADMAP](../ROADMAP.md). Planning documents: [PLAN](../PLAN.md) (the single-user build),
[TEAM-PLAN](../TEAM-PLAN.md) (team mode, in phases).

| Page | What it covers |
|---|---|
| [architecture](architecture.md) | Parts, modules, how a request flows, how background work runs |
| [data-model](data-model.md) | Tables, ids, course files, schema versions and upgrades |
| [jobs-and-gemini](jobs-and-gemini.md) | The job queue and worker, the Gemini client, models, prices and the budget |
| [course-pipeline](course-pipeline.md) | Questions, plan, sessions, checks, rewrites, the reading list, editing and section rewrites |
| [learning](learning.md) | Attempts, marking, reveals, warm-ups and spaced review, progress (no scores), Reading mode, the tutor |
| [media](media.md) | Diagrams, Commons pictures and audio, YouTube, illustrations, widgets, experiments |
| [reading](reading.md) | Verifying further reading and live-research sources |
| [auth](auth.md) | Modes, accounts, sign-in, sessions, roles, course visibility, the audit log |
| [frontend](frontend.md) | Plain JS modules, the router, views, the tutor bubble, the section menu, Reading mode, the installable app, browser tests |
| [security](security.md) | CSP, host checks, safe fetching, sandboxed experiments, prompt fencing |
| [operations](operations.md) | Running, configuration, testing, the demo, browser tests and screenshots, backups, upgrades |

_There's no interactive API reference (FastAPI's docs routes are switched off); the routes are in
[app/main.py](../../app/main.py), grouped by area._
