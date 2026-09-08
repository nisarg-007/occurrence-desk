from __future__ import annotations

from fastapi import APIRouter, Depends

from services.api import problems
from services.api.deps import get_repo, settings
from services.api.repo import Repository
from services.api.schemas import LoginRequest, TokenResponse
from services.api.security import issue_token, verify_password
from services.common.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    repo: Repository = Depends(get_repo),
    s: Settings = Depends(settings),
) -> TokenResponse:
    user = repo.user_by_email(body.email.lower())
    # Same error and same shape whether the email is unknown or the password is wrong:
    # a login endpoint that distinguishes them is a user-enumeration oracle.
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise problems.unauthorized("email or password is incorrect")
    return TokenResponse(
        access_token=issue_token(user.id, user.email, user.role),
        expires_in=s.jwt_ttl_minutes * 60,
        role=user.role,  # type: ignore[arg-type]
    )
