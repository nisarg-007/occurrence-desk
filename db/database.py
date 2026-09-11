"""Engine and session factory. One place, so the pool size is one decision, not five.

`pool_size=5, max_overflow=2` is deliberately small: `db.t4g.micro` does not have enough
connections to survive Fargate scaling to 8 workers times a naive pool of 10 each (80
connections). This is the ceiling named in work-pack section 2.4 - state it, don't discover
it during the replay.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from services.common.settings import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            max_overflow=2,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """`with session_scope() as session: ...` - commits on success, rolls back on exception."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
