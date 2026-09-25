"""Admin CLI.

    uv run python -m dipper_api.admin create-user --name "A. Inspector" --role inspector [--days 90]
    uv run python -m dipper_api.admin list-users
    uv run python -m dipper_api.admin revoke-user --id u_0123456789ab
    uv run python -m dipper_api.admin purge-expired

The token is printed once. Only its hash is stored.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import threading
from pathlib import Path

from .auth import ROLES, Users

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser(prog="dipper-admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", required=True, choices=ROLES)
    cu.add_argument("--days", type=float, default=90, help="token lifetime in days (default 90; 0 = no expiry)")
    sub.add_parser("list-users")
    rv = sub.add_parser("revoke-user", help="invalidate a person's token immediately")
    rv.add_argument("--id", required=True)
    sub.add_parser("purge-expired")
    pm = sub.add_parser("purge-media", help="delete stored photos older than N days (retention policy)")
    pm.add_argument("--days", type=int, required=True)
    args = ap.parse_args()
    path = Path(os.getenv("DIPPER_DB", str(ROOT / "data" / "dipper.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    users = Users(sqlite3.connect(path), threading.RLock())
    if args.cmd == "create-user":
        user, token = users.create(args.name, args.role, ttl_s=args.days * 86400 if args.days else None)
        print(f"Created {user.name} ({user.role}), id {user.id}")
        print(f"Token (shown once, store it securely): {token}")
    elif args.cmd == "list-users":
        import datetime as dt
        for u in users.list():
            exp = dt.datetime.fromtimestamp(u["expires_at"]).date().isoformat() if u["expires_at"] else "never"
            print(f"{u['id']}  {u['role']:<14} expires {exp:<10} {'demo ' if u['demo'] else ''}{u['name']}")
    elif args.cmd == "revoke-user":
        print("Revoked" if users.revoke(args.id) else f"No user with id {args.id}")
    elif args.cmd == "purge-media":
        from dipper_api.retention import purge_media
        media = Path(os.getenv("DIPPER_MEDIA", str(ROOT / "data" / "media")))
        removed = purge_media(media, args.days)
        print(f"Removed {removed} photos older than {args.days} days from {media}")
    else:
        print(f"Removed {users.purge_expired()} expired tokens")


if __name__ == "__main__":
    main()
