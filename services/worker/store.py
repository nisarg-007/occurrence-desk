"""
The worker's storage seam: one of two backends, chosen by configuration.

    sql   services/worker/sql_store.py    Parva's Postgres tables (the real one)
    json  services/worker/json_store.py   a file on disk (offline tests, no DB)

Which one runs is decided by `OCCDESK_WORKER_STORE`. With nothing set, the
rule is: if `DATABASE_URL` is in the environment, use Postgres. That makes the
container stack (which sets it) and a fresh clone with no database (which does
not) both do the right thing without an `if LOCAL:` anywhere in the worker.

`worker.py` calls these names and nothing else, so swapping the backend is a
configuration change, not a code change.
"""

from __future__ import annotations

import os
from types import ModuleType

_VALID = ("sql", "json")


def backend_name() -> str:
    """'sql' or 'json'. Raises on a typo rather than silently defaulting -
    a worker quietly writing to a JSON file in the cloud is the failure this
    guards against."""
    explicit = os.getenv("OCCDESK_WORKER_STORE")
    if explicit:
        if explicit not in _VALID:
            raise RuntimeError(f"OCCDESK_WORKER_STORE must be one of {_VALID}, got {explicit!r}")
        return explicit
    return "sql" if os.getenv("DATABASE_URL") else "json"


def backend() -> ModuleType:
    if backend_name() == "sql":
        from services.worker import sql_store

        return sql_store
    from services.worker import json_store

    return json_store


def reset() -> None:
    backend().reset()


def register_document(document_id: int, sha256: str, s3_bucket: str, s3_key: str) -> None:
    backend().register_document(
        document_id, sha256=sha256, s3_bucket=s3_bucket, s3_key=s3_key
    )


def claim_for_parsing(document_id: int) -> bool:
    return backend().claim_for_parsing(document_id)


def mark_parsed(document_id: int) -> None:
    backend().mark_parsed(document_id)


def mark_failed(document_id: int, error_text: str) -> None:
    backend().mark_failed(document_id, error_text)


def document_status(document_id: int) -> dict | None:
    return backend().document_status(document_id)


def save_reports(document_id: int, extracted_records: list[dict]) -> int:
    return backend().save_reports(document_id, extracted_records)


def report_count() -> int:
    return backend().report_count()
