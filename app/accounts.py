"""Account commands for whoever runs the server (no web sign-in needed).

    docker compose exec app python -m app.accounts add-admin <username> [display name]
    docker compose exec app python -m app.accounts reset-password <username>
    docker compose exec app python -m app.accounts list

Each prints a one-time password; the person must choose a new one at first sign-in. The first `add-admin` on an
install that was used in personal mode takes over the owner account, so all existing courses and progress become
that admin's.
"""
from __future__ import annotations

import sys

from . import audit, auth, db
from .pipeline import Problem


def add_admin(username: str, display: str = "") -> tuple[str, str]:
    with db.tx() as c:
        o = auth.owner(c)
        pw = auth.generate_password()
        if o["username"] == "owner" and not o["password_hash"]:
            name = auth._clean_username(username)
            if c.execute("SELECT 1 FROM users WHERE username=? AND id!=?", (name, o["id"])).fetchone():
                raise Problem("That username is taken.")
            c.execute("UPDATE users SET username=?, display_name=?, role='admin', active=1 WHERE id=?",
                      (name, (display or name)[:80], o["id"]))
            auth.set_password(c, o["id"], pw, must_change=True)
            audit.log(c, "user.claimed_owner", "user", str(o["id"]), {"username": name, "via": "command line"}, user_id=o["id"])
            return name, pw
        uid, pw = auth.create_user(c, username, display or username, "admin", pw)
        audit.log(c, "user.created", "user", str(uid), {"username": username, "role": "admin", "via": "command line"}, user_id=uid)
        return username, pw


def reset_password(username: str) -> str:
    with db.tx() as c:
        u = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if u is None:
            raise Problem("No such user.")
        pw = auth.generate_password()
        auth.set_password(c, u["id"], pw, must_change=True)
        c.execute("UPDATE users SET active=1 WHERE id=?", (u["id"],))
        auth.revoke_all(c, u["id"])
        audit.log(c, "user.password_reset", "user", str(u["id"]), {"username": u["username"], "via": "command line"},
                  user_id=u["id"])
        return pw


def main(argv: list[str]) -> int:
    db.init()
    try:
        if len(argv) >= 2 and argv[0] == "add-admin":
            name, pw = add_admin(argv[1], " ".join(argv[2:]))
            print(f"Admin '{name}' is ready. One-time password (they'll choose a new one at first sign-in):\n\n    {pw}\n")
        elif len(argv) == 2 and argv[0] == "reset-password":
            pw = reset_password(argv[1])
            print(f"New one-time password for '{argv[1]}' (they'll choose a new one at sign-in):\n\n    {pw}\n")
        elif argv[:1] == ["list"]:
            with db.tx() as c:
                for u in c.execute("SELECT * FROM users ORDER BY id"):
                    state = "active" if u["active"] else "deactivated"
                    pw = "password set" if u["password_hash"] else "no password"
                    print(f"{u['id']:>4}  {u['username']:<24} {u['role']:<8} {state:<12} {pw}")
        else:
            print(__doc__)
            return 2
    except Problem as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
