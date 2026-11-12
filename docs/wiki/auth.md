# Modes, accounts and the audit log

See [index](index.md). Code: [app/auth.py](../../app/auth.py), [app/accounts.py](../../app/accounts.py),
[app/audit.py](../../app/audit.py), routes in [app/main.py](../../app/main.py).

## Modes

`KNWLGE_MODE` (`personal` by default, or `team`), read on every request. `/api/me` reports the mode, whether
sign-in is needed and the current user; it never fails.

- **Personal:** one owner (user id 1, role admin). Open unless the owner sets a password (`/api/personal/password`);
  then it signs in like team mode, with the owner's username filled in.
- **Team:** everyone signs in. If there's no active admin, the app says so and the first admin is made from the
  command line (`python -m app.accounts add-admin`), which claims the unnamed, passwordless owner if it's still there.

## Accounts and sign-in

- Passwords: scrypt (n=2^14), at least 10 characters, not the username, at most 256. New and reset accounts have
  `must_change`; every route except sign-in, sign-out, `/api/me` and the password change answers 403
  `change_password` until it's done.
- Sign-in creates a random token in the HttpOnly `knwlge_session` cookie (SameSite=Lax, `Secure` over HTTPS). Only
  its SHA-256 is stored (`login_sessions`); it expires after 30 idle days. Sign-out deletes it; password changes,
  resets and deactivation revoke the others.
- Throttle (in memory, per process): 5 free failed tries per username, then waits from 30 seconds doubling to 15 minutes (429 `throttled`).

## Your own name

`PUT /api/me {"display_name"}`: anyone signed in can change the name others see (spaces collapsed, 1-80 characters);
the username is unchanged. Audited as `user.renamed_self` with the old and new name. The page is `#/account`, linked
from the name in the top bar, with a link to the password change.

## Roles and courses

`learner` < `author` < `admin`. `require(user, role)` on routes; `can_view(user, course)`: admins, the author, or a
published course; `can_edit`: admins or the author. A course someone can't see answers "That course doesn't exist."
Costs, settings, people and the audit log are admin-only. In personal mode the owner can do everything.

## Audit log

`audit.log(c, action, target_type, target_id, details, user_id, cost)` writes in the same transaction as the change
(failed sign-ins in their own, so they survive the failed request). `auth.actor` (a context variable set by the auth
dependency) supplies the person when `user_id` isn't given; jobs carry their `user_id` instead. Edits keep `before` and
`after`; key changes never include the key. `GET /api/audit` filters by person, action prefix, target and dates;
`/api/audit.csv` exports (cells starting with `= + - @` are prefixed so spreadsheets don't run them);
`POST /api/audit/prune` removes entries before a date.
