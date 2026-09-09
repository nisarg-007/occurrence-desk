"""Unit tests for services/worker/worker.py's handle_message() control flow,
with S3/SQS/parse/classify all faked - no real network, no real PDF, no
trained model file required. The real-infrastructure version of these same
scenarios (actual MinIO + ElasticMQ, a real corrupted PDF, a real DLQ
redrive) lives in services/worker/local_stack_test.py; this is the fast,
CI-safe version of the same claims.
"""

from __future__ import annotations

import json

import pytest

from services.worker import store, worker

QUEUE_URL = "http://queue.example/main"


class FakeSQS:
    def __init__(self):
        self.deleted = []

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.deleted.append(ReceiptHandle)

    def change_message_visibility(self, **kw):
        pass


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STATE_PATH", tmp_path / "worker_state.json")


@pytest.fixture(autouse=True)
def fake_infra(monkeypatch):
    fake = FakeSQS()
    monkeypatch.setattr(worker, "sqs", lambda: fake)
    monkeypatch.setattr(worker, "s3", lambda: type("S3", (), {"download_file": staticmethod(lambda *a: None)})())
    monkeypatch.setattr(worker, "predict_hazards", lambda narrative: [])
    return fake


def _message(document_id: int, receipt: str = "r1") -> dict:
    return {
        "Body": json.dumps({
            "document_id": document_id,
            "s3_bucket": "b",
            "s3_key": "k.pdf",
            "trace_id": "test-trace",
        }),
        "ReceiptHandle": receipt,
    }


def test_happy_path_saves_reports_marks_parsed_and_deletes_message(monkeypatch, fake_infra):
    store.register_document(1, sha256="a" * 64, s3_bucket="b", s3_key="k.pdf")
    monkeypatch.setattr(worker, "parse_pdf", lambda path, document_id: [
        {"acn": "111", "narrative": "n", "hazards": []},
    ])

    worker.handle_message(_message(1), QUEUE_URL)

    assert store.document_status(1)["status"] == "parsed"
    assert store.report_count() == 1
    assert fake_infra.deleted == ["r1"]


def test_parse_failure_marks_failed_and_does_not_delete_message(monkeypatch, fake_infra):
    store.register_document(2, sha256="b" * 64, s3_bucket="b", s3_key="k.pdf")

    def boom(path, document_id):
        raise ValueError("corrupt pdf")

    monkeypatch.setattr(worker, "parse_pdf", boom)

    worker.handle_message(_message(2), QUEUE_URL)

    doc = store.document_status(2)
    assert doc["status"] == "failed"
    assert "corrupt pdf" in doc["error_text"]
    assert fake_infra.deleted == []  # message must survive for SQS to redeliver it


def test_duplicate_message_for_already_parsed_document_is_dropped_without_reparsing(monkeypatch, fake_infra):
    store.register_document(3, sha256="c" * 64, s3_bucket="b", s3_key="k.pdf")
    calls = []
    monkeypatch.setattr(worker, "parse_pdf", lambda path, document_id: (
        calls.append(1),
        [{"acn": "333", "narrative": "n", "hazards": []}],
    )[1])

    worker.handle_message(_message(3, receipt="r1"), QUEUE_URL)
    worker.handle_message(_message(3, receipt="r2"), QUEUE_URL)  # redelivered duplicate

    assert len(calls) == 1  # parse only actually ran once
    assert store.report_count() == 1
    assert fake_infra.deleted == ["r1", "r2"]  # both messages cleared, no reprocessing
