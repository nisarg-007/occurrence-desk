"""Local-development fixture logins only. Mirrors `services/api/repo.py::InMemoryRepo._seed`
so `SqlRepo` and `InMemoryRepo` present the same three accounts.

Guarded on `APP_ENV != 'prod'` in the script itself, not just in a comment — the work pack
is explicit that a comment is not a guard. Running this against a production database exits
loudly instead of silently creating known-password accounts.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.database import session_scope
from db.models import User
from services.api.security import hash_password
from services.common.settings import get_settings

logger = logging.getLogger(__name__)

#: (email, role) — password is the same local-only value the API's stub repo and the
#: contract tests already assume: "occdesk-local".
_FIXTURE_USERS: tuple[tuple[str, str], ...] = (
    ("analyst@occdesk.example", "analyst"),
    ("manager@occdesk.example", "manager"),
    ("admin@occdesk.example", "admin"),
)
_FIXTURE_PASSWORD = "occdesk-local"


def seed(session: Session) -> int:
    existing = {email.lower() for email in session.execute(select(User.email)).scalars()}
    created = 0
    hashed = hash_password(_FIXTURE_PASSWORD)
    for email, role in _FIXTURE_USERS:
        if email.lower() in existing:
            continue
        session.add(User(email=email, password_hash=hashed, role=role, is_active=True))
        created += 1
    return created


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = get_settings()
    if settings.app_env == "prod":
        print(
            "refusing to seed known-password fixture users into a prod database "
            "(APP_ENV=prod). This guard lives in the script, not a comment.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    with session_scope() as session:
        created = seed(session)
    logger.info("users: %d fixture row(s) created", created)


if __name__ == "__main__":
    main()
