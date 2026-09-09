"""Unit tests for services/worker/store.py - the temporary stand-in for
Parva's real documents/reports tables (see the module docstring there).

The most important test here (test_failed_document_can_be_reclaimed_for_retry)
is a regression test for a real bug: the work-pack's own claim-query
pseudocode (`WHERE status IN ('queued','parsing')`) silently excludes
'failed', which meant a redelivered message for a document that failed once
got deleted as an "already done" duplicate instead of being retried - found
by actually running the poison-PDF scenario against real SQS, not by
inspection.
"""

from __future__ import annotations

import pytest

from services.worker import store


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "worker_state.json")


def test_claim_then_parse_then_cannot_reclaim():
    store.register_document(1, sha256="a" * 64, s3_bucket="b", s3_key="k.pdf")
    assert store.claim_for_parsing(1) is True

    store.mark_parsed(1)
    # a redelivered/duplicate message for an already-parsed document must
    # NOT be reprocessed - this is the whole idempotency guarantee
    assert store.claim_for_parsing(1) is False


def test_failed_document_can_be_reclaimed_for_retry():
    store.register_document(2, sha256="b" * 64, s3_bucket="b", s3_key="k.pdf")
    assert store.claim_for_parsing(2) is True
    store.mark_failed(2, "boom")

    # redelivery after a genuine failure must get a real second attempt,
    # not be silently dropped as "already done"
    assert store.claim_for_parsing(2) is True
    assert store.document_status(2)["attempts"] == 2


def test_save_reports_is_idempotent_on_acn():
    store.register_document(3, sha256="c" * 64, s3_bucket="b", s3_key="k.pdf")
    records = [{"acn": "555", "narrative": "n"}]

    first = store.save_reports(3, records)
    second = store.save_reports(3, records)  # same document parsed twice

    assert first == 1
    assert second == 0  # nothing new the second time
    assert store.report_count() == 1


def test_claim_on_unknown_document_is_refused():
    assert store.claim_for_parsing(999) is False
