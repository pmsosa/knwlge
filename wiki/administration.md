# Administration

[Guide home](README.md) · Previous: [Editing a course](editing-courses.md)

For admins. In personal mode you're the admin; **people** and **audit** only exist in team mode.

## Settings

<img src="images/settings.png" alt="Settings: appearance, the Gemini key, the monthly budget, models and paused work" width="100%">

| Section | What it does |
|---|---|
| Appearance | Auto, light or dark, for this browser |
| Gemini API key | **save key**, **test it** (a tiny call that checks it works), **remove key**. The key never leaves the server and isn't shown again |
| Monthly budget | A cap in dollars, or **no limit** (the default). When the month's spend reaches it, new work pauses until next month or until you raise it |
| Models | Which Gemini model does what: planning and checkpoints, writing and feedback, quick checks, illustrations. Change them if Google renames or retires one |
| Password (personal mode) | Off by default: the app just opens. Set one and Knwlge asks for it; **turn off password** opens it again |
| Paused work | Work pauses when Gemini rate-limits, refuses the key, or the budget is reached. **resume paused work now** tries again (saving settings does too) |

## Usage and the budget

<img src="images/usage.png" alt="Usage: this month's spend, all time, by course and by kind of work" width="100%">

Every Gemini call is logged with the tokens it used and its cost, from a price table that includes Google's
announced December 2026 and January 2027 increases. **usage** shows this month and all time, by course, by person
(team mode) and by kind of work, and how many Google searches were used (5,000 a month are free). Your Google bill is
the final word. Learners never see costs.

Rough costs: planning is a few cents; a Boot Camp is about 30-35 calls to build, mostly writing sessions; feedback,
tutor answers and section rewrites are a cent or two each; an AI illustration is about 3¢.

## People (team mode)

<img src="images/people.png" alt="People: accounts with their roles and last seen, and the Add someone form" width="100%">

| Role | Can |
|---|---|
| Learner | Take published courses, ask the tutor |
| Author | Also make courses, edit and publish their own |
| Admin | Also manage people, settings, spend and the audit log, and edit any course |

- **Add someone**: username, display name, role, and a first password (leave it empty and Knwlge makes one). It's
  shown once; give it to them privately. They must choose their own at first sign-in.
- **Role**: change it in the list. You can't change your own role, and the last active admin can't be demoted.
- **reset password**: makes a new one-time password and signs them out everywhere.
- **deactivate**: signs them out and stops them signing in. Their progress is kept; **reactivate** brings them back.

## The audit log

<img src="images/audit.png" alt="The audit log: who did what and when, with filters and a CSV export" width="100%">

Who did what, and when: sign-ins (and failed ones), accounts made and changed, courses made, published, renamed,
exported and deleted, sections and questions edited (with before and after), section rewrites asked for and done,
key, model and budget changes. Never passwords or the key. Filter by person, action, course or item and dates;
**export CSV**; **prune** removes entries older than a date.

## From the command line

Run these from the folder Knwlge is installed in (or point `-f` at its `compose.yaml`):

```sh
docker compose exec app python -m app.accounts add-admin <username> "<display name>"   # first admin; prints a one-time password
docker compose exec app python -m app.accounts reset-password <username>              # if an admin is locked out
docker compose exec app python -m app.accounts list
```

`add-admin` on a fresh team install (or one switched over from personal mode) takes over the personal-mode owner,
so every course and setting made so far becomes the new admin's.

## Switching modes

Set `KNWLGE_MODE=team` (or `personal`) in `.env` and run `docker compose up -d`. Going to team mode: create the first
admin as above. Going back: the accounts stay in the database, and the app opens without signing in again.

## Backups

Everything lives in `data/`: the SQLite database, course files (materials, pictures, recordings) and uploads. Back
up that folder together with `.env`. Before every database upgrade Knwlge saves a copy in `data/backups/` by itself.
**Download as Markdown (zip)** on a course's **Course** tab exports one course for reading elsewhere.
