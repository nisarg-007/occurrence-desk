"""Auth: bcrypt password hashing and a JWT carrying sub, role, exp.

The negative test comes first: an analyst token must get 403 on every manager-only path.
RBAC that was never tested negatively is RBAC that does not exist.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import bcrypt
from jose import JWTError, jwt

from services.common.settings import get_settings

#: bcrypt directly rather than passlib: passlib 1.7.4 breaks on bcrypt >= 4.1
#: (it reads the removed `bcrypt.__about__`), and this is two functions, not a framework.
BCRYPT_ROUNDS = 12

ROLES = ("analyst", "manager", "admin")
#: admin inherits manager; manager inherits analyst.
_IMPLIES: dict[str, set[str]] = {
    "analyst": {"analyst"},
    "manager": {"analyst", "manager"},
    "admin": {"analyst", "manager", "admin"},
}


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: int
    email: str
    role: str

    def has(self, required: str) -> bool:
        return required in _IMPLIES.get(self.role, set())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        # A malformed stored hash is a failed login, never a 500.
        return False


def issue_token(user_id: int, email: str, role: str, now: dt.datetime | None = None) -> str:
    s = get_settings()
    now = now or dt.datetime.now(dt.UTC)
    claims = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=s.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> Principal:
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError as exc:
        raise AuthError("invalid or expired token") from exc
    role = claims.get("role")
    if role not in ROLES:
        raise AuthError("token carries no usable role")
    return Principal(user_id=int(claims["sub"]), email=claims.get("email", ""), role=role)
