"""Dependencies: the principal, the role gate, the repository, and the AWS clients.

`require_role("manager")` is the whole RBAC surface. There is one negative test per
manager-only path - no loops that can silently pass on zero iterations.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request

from services.api import problems
from services.api.repo import InMemoryRepo, Repository
from services.api.security import AuthError, Principal, decode_token
from services.common.settings import Settings, get_settings

_repo: Repository = InMemoryRepo()


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
