"""
Temporary stand-in for Parva's `documents` / `reports` tables.

Parva's real Postgres schema (see contracts + the work-pack §0.6) isn't built
yet. This gives the worker something real to read/write against in the
meantime, using the SAME status machine and the SAME "claim" idempotency
trick the real schema will use:

    UPDATE documents SET status='parsing', attempts=attempts+1
    WHERE id=%s AND status IN ('queued','parsing')
    RETURNING id

When the real database lands, this file goes away and the worker's calls to
`claim_for_parsing`, `mark_parsed`, `mark_failed`, `save_reports` become one
SQL statement each - the worker's control flow (worker.py) does not change.

Backed by a JSON file so state survives across separate `python` runs, which
is what lets us test "duplicate message -> one set of reports" as two
separate process runs, the way it would really happen.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

STATE_PATH = Path("services/worker/output/worker_state.json")
_lock = threading.Lock()


def _load() -> dict:
    if not STATE_PATH.exists():
        return {"documents": {}, "reports": {}}
    return json.loads(STATE_PATH.read_text())


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def reset() -> None:
    """Wipe local state. Only ever used by test/demo scripts."""
    with _lock:
        _save({"documents": {}, "reports": {}})


def register_document(document_id: int, sha256: str, s3_bucket: str, s3_key: str) -> None:
    """Equivalent of the INSERT that POST /documents/complete would already have
    done for real. Our test harness calls this to simulate that having happened,
    since we're standing in for the API + DB here too."""
    with _lock:
        state = _load()
        state["documents"][str(document_id)] = {
            "id": document_id,
            "sha256": sha256,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
            "status": "queued",
            "attempts": 0,
            "error_text": None,
        }
        _save(state)


def claim_for_parsing(document_id: int) -> bool:
    """True only for the call that actually gets to parse this document.

    'queued' / 'parsing' / 'failed' are all reclaimable - a previous attempt
    that crashed mid-parse or genuinely failed should still be retried by a
    redelivered message. Only 'parsed' is treated as already done and
    refused: that is the real duplicate case (someone else's redelivered
    message, or a duplicate `complete` call, for a document we already
    finished successfully).

    (An earlier version of this matched the work-pack's WHERE clause
    literally - `status IN ('queued','parsing')` - which silently excluded
    'failed' too. That meant a message that failed once was deleted as an
    "already done" duplicate on redelivery, instead of being retried up to
    maxReceiveCount and landing on the DLQ as intended. Found by actually
    running the poison-PDF test end to end, not by inspection.)
    """
    with _lock:
        state = _load()
        doc = state["documents"].get(str(document_id))
        if doc is None or doc["status"] == "parsed":
            return False
        doc["status"] = "parsing"
        doc["attempts"] += 1
        _save(state)
        return True


def mark_parsed(document_id: int) -> None:
    with _lock:
        state = _load()
        doc = state["documents"].get(str(document_id))
        if doc is not None:
            doc["status"] = "parsed"
            doc["error_text"] = None
            _save(state)


def mark_failed(document_id: int, error_text: str) -> None:
    with _lock:
        state = _load()
        doc = state["documents"].get(str(document_id))
        if doc is not None:
            doc["status"] = "failed"
            doc["error_text"] = error_text
            _save(state)


def document_status(document_id: int) -> dict | None:
    state = _load()
    return state["documents"].get(str(document_id))


def save_reports(document_id: int, extracted_records: list[dict]) -> int:
    """Equivalent of `INSERT ... ON CONFLICT (acn) DO NOTHING`.

    Returns how many were actually NEW - the same document parsed twice
    contributes 0 the second time, which is exactly the idempotency
    guarantee this is standing in for.
    """
    with _lock:
        state = _load()
        inserted = 0
        for rec in extracted_records:
            acn = rec["acn"]
            if acn in state["reports"]:
                continue
            state["reports"][acn] = rec
            inserted += 1
        _save(state)
        return inserted


def report_count() -> int:
    return len(_load()["reports"])
