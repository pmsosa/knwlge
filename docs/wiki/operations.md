# Operations

See [index](index.md).

## Install and run

```sh
cp .env.example .env           # mode, listen address and port, allowed host names, time zone
docker compose up -d --build   # http://<this machine>:9180 by default
```

One container, `knwlge`. It listens on 9180 inside; `KNWLGE_BIND` and `KNWLGE_PORT` choose where it's published.
Firewalls and HTTPS are the deployment's job; behind a reverse proxy, bind `127.0.0.1` and add the proxy's host name
to `KNWLGE_ALLOWED_HOSTS`. uvicorn trusts forwarded headers only from `127.0.0.1`.

## Configuration

| Variable | Description | Default |
|---|---|---|
| `KNWLGE_MODE` | `personal` or `team` | `personal` |
| `KNWLGE_BIND` | Address to publish on | `0.0.0.0` |
| `KNWLGE_PORT` | Port to publish on | `9180` |
| `KNWLGE_ALLOWED_HOSTS` | Extra host names to answer to (comma-separated, wildcards) | empty |
| `TZ` | Time zone for "this month" in the budget | `America/Los_Angeles` |
| `KNWLGE_DATA` | Data folder inside the container | `/data` |
| `KNWLGE_NO_WORKER` | `1` turns the background worker off (tests, demo) | unset |
| `GEMINI_API_URL` | Override the Gemini endpoint (testing) | Google's |

The Gemini key, models and budget are settings in the database, set from the **Settings** page.

## Where things live

| What | Where |
|---|---|
| Database | `data/knwlge.db` (SQLite, WAL) |
| Course files (materials, uploads, media) | `data/courses/<course id>/` |
| Copies made before upgrades | `data/backups/` |
| Settings for the container | `.env` (never committed) |

## Backups and upgrades

Back up `data/` and `.env`. For a consistent copy while it runs, use SQLite's backup API, for example
`docker compose exec app python -c "import sqlite3; sqlite3.connect('/data/knwlge.db').backup(sqlite3.connect('/data/backups/manual.db'))"`,
or stop the container first. Upgrades: pull, `docker compose up -d --build`; the database is
copied to `data/backups/` before any schema change ([data-model](data-model.md#upgrades)).

## Tests

```sh
docker compose run --build --rm app pytest -q
```

The code is baked into the image, so `--build` matters. Gemini and the web are faked ([tests/fakes.py](../../tests/fakes.py));
`tests/conftest.py` pins personal mode so the live `.env` doesn't leak in. Team-mode tests switch it themselves.

## Demo

`python -m app.demo` fills an **empty** data folder with made-up courses (it refuses one that has courses). With
`--team` it also makes three made-up accounts with demo-only passwords (maya, admin; sam, author; kim, learner);
run the app with `KNWLGE_MODE=team` to use them.

```sh
docker run --rm -e KNWLGE_DATA=/demo -v /path/to/scratch:/demo knwlge python -m app.demo --team
docker run --rm -e KNWLGE_DATA=/demo -e KNWLGE_MODE=team -e KNWLGE_NO_WORKER=1 -v /path/to/scratch:/demo -p 9188:9180 knwlge
```

## Browser tests and screenshots

```sh
sh tools/e2e.sh          # the browser smoke test (tests/e2e/smoke.py)
sh tools/e2e.sh shots    # retake the user guide's screenshots into wiki/images (tools/screenshots.py)
```

The script builds the image, writes a team-mode demo into a fresh folder under `.e2e/` (ignored by git), starts it on
a free port, runs the browser job in a Playwright container and removes the demo afterwards. `E2E_IMAGE` picks the
Playwright image (default `mcr.microsoft.com/playwright/python:v1.49.1-noble`), `E2E_RUN` the command that starts it
(default `docker run --rm`) and `E2E_PORT` the port. Screenshots are 1440×1000 (two phone shots on a Pixel 7), shrunk
to 256 colours. Retake them whenever a page they show changes.

## Accounts from the command line

```sh
docker compose exec app python -m app.accounts add-admin <username> "<display name>"
docker compose exec app python -m app.accounts reset-password <username>
docker compose exec app python -m app.accounts list
```
