"""Admin CLI.

    uv run python -m dipper_api.admin create-user --name "Rui (CMC)" --role inspector
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
    sub.add_parser("purge-expired")
    pm = sub.add_parser("purge-media", help="delete stored photos older than N days (retention policy)")
    pm.add_argument("--days", type=int, required=True)
    args = ap.parse_args()
    path = Path(os.getenv("DIPPER_DB", str(ROOT / "data" / "dipper.sqlite3")))
    path.parent.mkdir(parents=True, exist_ok=True)
    users = Users(sqlite3.connect(path), threading.RLock())
    if args.cmd == "create-user":
        user, token = users.create(args.name, args.role)
        print(f"Created {user.name} ({user.role}), id {user.id}")
        print(f"Token (shown once, store it securely): {token}")
    elif args.cmd == "purge-media":
        from dipper_api.retention import purge_media
        media = Path(os.getenv("DIPPER_MEDIA", str(ROOT / "data" / "media")))
        removed = purge_media(media, args.days)
        print(f"Removed {removed} photos older than {args.days} days from {media}")
    else:
        print(f"Removed {users.purge_expired()} expired tokens")


if __name__ == "__main__":
    main()
