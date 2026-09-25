"""Staff authentication and role-based permissions.

Citizens are anonymous (pseudonymous observer ids). Staff authenticate with personal bearer tokens.
Only a SHA-256 hash of each token is stored. Every human approval is attributed to the authenticated
user, never to a name typed into a form.

Roles (a role also grants the permissions of the roles listed after it in IMPLIES):
  trained        volunteer who may record ammonium strips
  inspector      investigator: records any field check, dispatches, hands off to the utility, closes cases
  public_health  approves public contact advisories
  admin          everything, plus users, reaches and benchmark runs

Create a user:  uv run python -m dipper_api.admin create-user --name "Rui (CMC)" --role inspector
Demo mode (DIPPER_DEMO=1) additionally issues short-lived tokens per role for evaluation.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

ROLES = ("trained", "inspector", "public_health", "admin")
IMPLIES = {"admin": {"admin", "public_health", "inspector", "trained"}, "inspector": {"inspector", "trained"},
           "public_health": {"public_health"}, "trained": {"trained"}}
DEMO_TTL_S = 4 * 3600

SCHEMA = """
create table if not exists users (
  id text primary key, name text not null, role text not null, token_hash text not null unique,
  created_at real not null, expires_at real, demo integer not null default 0
);
"""


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: str
    demo: bool = False

    def can(self, role: str) -> bool:
        return role in IMPLIES.get(self.role, set())


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Users:
    def __init__(self, db: sqlite3.Connection, lock: threading.RLock) -> None:
        self.db, self.lock = db, lock
        with self.lock:
            self.db.executescript(SCHEMA)

    def create(self, name: str, role: str, ttl_s: float | None = None, demo: bool = False) -> tuple[User, str]:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        token = "dpr_" + secrets.token_urlsafe(32)
        uid = "u_" + secrets.token_hex(6)
        now = time.time()
        with self.lock, self.db:
            self.db.execute("insert into users values (?, ?, ?, ?, ?, ?, ?)",
                            (uid, name, role, _hash(token), now, now + ttl_s if ttl_s else None, int(demo)))
        return User(uid, name, role, demo), token

    def resolve(self, token: str) -> User | None:
        with self.lock:
            row = self.db.execute("select id, name, role, expires_at, demo from users where token_hash = ?",
                                  (_hash(token),)).fetchone()
        if not row or (row[3] is not None and row[3] < time.time()):
            return None
        return User(row[0], row[1], row[2], bool(row[4]))

    def purge_expired(self) -> int:
        with self.lock, self.db:
            return self.db.execute("delete from users where expires_at is not null and expires_at < ?",
                                   (time.time(),)).rowcount


def demo_enabled() -> bool:
    return os.getenv("DIPPER_DEMO", "").lower() in ("1", "true", "yes")


def current_user(request: Request) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return request.app.state.users.resolve(header[7:].strip())


def require(role: str):
    """Dependency: an authenticated user holding `role` (or a role that implies it)."""
    def dep(user: User | None = Depends(current_user)) -> User:
        if user is None:
            raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
        if not user.can(role):
            raise HTTPException(403, f"this action needs the {role.replace('_', ' ')} role")
        return user
    return dep


def require_staff(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    return user
