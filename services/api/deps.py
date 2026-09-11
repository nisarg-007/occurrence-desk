"""Dependencies: the principal, the role gate, the repository, and the AWS clients.

`require_role("manager")` is the whole RBAC surface. There is one negative test per
manager-only path - no loops that can silently pass on zero iterations.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import Depends, Request

from services.api import problems
from services.api.repo import InMemoryRepo, Repository
from services.api.security import AuthError, Principal, decode_token
from services.common.settings import Settings, get_settings

def _default_repo() -> Repository:
    """Parva's `SqlRepo` when a database is configured, the in-memory stub when not.

    `OCCDESK_REPO=memory` forces the stub (tests, an offline console demo);
    `OCCDESK_REPO=sql` forces Postgres and fails loudly if it is unreachable,
    rather than falling back to a stub that would look like a working system.
    With neither set, the presence of `DATABASE_URL` decides - the same rule
    the worker's store uses, so one variable configures both services.
    """
    choice = os.getenv("OCCDESK_REPO") or ("sql" if os.getenv("DATABASE_URL") else "memory")
    if choice not in ("sql", "memory"):
        raise RuntimeError(f"OCCDESK_REPO must be 'sql' or 'memory', got {choice!r}")
    if choice == "memory":
        return InMemoryRepo()

    from db.database import get_sessionmaker
    from db.repo import SqlRepo

    return SqlRepo(get_sessionmaker())


_repo: Repository = _default_repo()


def get_repo() -> Repository:
    return _repo


def set_repo(repo: Repository) -> None:
    """Swap in SqlRepo when Parva's models land, or a fresh stub in tests."""
    global _repo
    _repo = repo


def settings() -> Settings:
    return get_settings()


def principal(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise problems.unauthorized()
    try:
        return decode_token(token)
    except AuthError as exc:
        raise problems.unauthorized(str(exc)) from exc


def require_role(required: str) -> Callable[..., Principal]:
    def dependency(p: Principal = Depends(principal)) -> Principal:
        if not p.has(required):
            raise problems.forbidden(f"this path requires the {required} role")
        return p

    return dependency


analyst = require_role("analyst")
manager = require_role("manager")
