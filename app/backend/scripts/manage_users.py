"""
Administer ScrapTrust / BMTL user accounts (run on the server, from app/backend).

    venv\\Scripts\\python.exe scripts\\manage_users.py add alice --role admin       # prompts for the password twice
    venv\\Scripts\\python.exe scripts\\manage_users.py add bob                     # role "user"
    venv\\Scripts\\python.exe scripts\\manage_users.py import users.csv out.csv     # bulk: CSV with columns username,role;
                                                                                # writes generated one-time passwords to out.csv
    venv\\Scripts\\python.exe scripts\\manage_users.py list
    venv\\Scripts\\python.exe scripts\\manage_users.py role bob reviewer
    venv\\Scripts\\python.exe scripts\\manage_users.py disable bob                 # also signs bob out everywhere
    venv\\Scripts\\python.exe scripts\\manage_users.py enable bob
    venv\\Scripts\\python.exe scripts\\manage_users.py reset bob                   # prompts for a new password, revokes sessions
    venv\\Scripts\\python.exe scripts\\manage_users.py signout bob                 # revoke all of bob's sessions

Passwords are read with getpass (never from the command line, so they do not land in shell history)
and stored only as scrypt hashes. Generated passwords in an import output file are secrets: deliver
them securely and delete the file.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.security import ROLES, audit, user_store  # noqa: E402

ALPHABET = string.ascii_letters + string.digits + "-_.!@#%"


def _ask_password(username: str) -> str:
    first = getpass.getpass(f"New password for {username}: ")
    if first != getpass.getpass("Repeat: "):
        sys.exit("Passwords do not match")
    return first


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("username"); a.add_argument("--role", default="user", choices=ROLES)
    i = sub.add_parser("import"); i.add_argument("csv_in"); i.add_argument("csv_out")
    sub.add_parser("list")
    r = sub.add_parser("role"); r.add_argument("username"); r.add_argument("role", choices=ROLES)
    for name in ("disable", "enable", "reset", "signout"):
        sub.add_parser(name).add_argument("username")
    args = ap.parse_args(argv)
    store = user_store()
    try:
        if args.cmd == "add":
            store.add(args.username, _ask_password(args.username), args.role)
            print(f"added {args.username} ({args.role})")
        elif args.cmd == "import":
            out = []
            with open(args.csv_in, newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    pw = generate_password()
                    store.add(row["username"], pw, (row.get("role") or "user").strip())
                    out.append({"username": row["username"].strip().lower(), "one_time_password": pw})
            with open(args.csv_out, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, ["username", "one_time_password"]); w.writeheader(); w.writerows(out)
            print(f"imported {len(out)} users; passwords in {args.csv_out} (secret: deliver securely, then delete)")
        elif args.cmd == "list":
            data = store._read()
            for name, rec in sorted(data.items()):
                print(f"{name:32s} {rec['role']:9s} {'DISABLED' if rec.get('disabled') else 'active'}")
            print(f"{len(data)} users")
            return
        elif args.cmd == "role":
            store.update(args.username, role=args.role); print("role updated; sessions revoked")
        elif args.cmd == "disable":
            store.update(args.username, disabled=True); print("disabled; sessions revoked")
        elif args.cmd == "enable":
            store.update(args.username, disabled=False); print("enabled")
        elif args.cmd == "reset":
            store.update(args.username, password=_ask_password(args.username)); print("password reset; sessions revoked")
        elif args.cmd == "signout":
            store.update(args.username, revoke_sessions=True); print("all sessions revoked")
        audit(f"admin_{args.cmd}", getattr(args, "username", None), "cli", getattr(args, "role", "") or "")
    except ValueError as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
