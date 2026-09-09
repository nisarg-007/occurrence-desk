"""The 202 that defines the project, and the idempotency that is in our success criteria."""

from __future__ import annotations

import hashlib

import pytest

SHA = hashlib.sha256(b"a pretend ASRS report set").hexdigest()


@pytest.fixture(autouse=True)
def _fake_s3(monkeypatch):
    """No AWS in contract tests. The presign call is boto3's job, not ours, and mocking it keeps
    this suite runnable on a laptop with no credentials."""

    class FakeS3:
        def generate_presigned_post(self, Bucket, Key, Fields, Conditions, ExpiresIn):  # noqa: N803
            assert {"Content-Type": "application/pdf"} in Conditions
            assert any(c[0] == "content-length-range" for c in Conditions if isinstance(c, list))
            return {"url": f"https://s3.test/{Bucket}", "fields": {"key": Key, **Fields}}

    monkeypatch.setattr("services.common.aws.s3", lambda: FakeS3())


def _reserve(client, headers, size=1_843_200, sha=SHA):
    return client.post(
        "/api/v1/documents/upload-url",
        json={"filename": "nmac.pdf", "byte_size": size, "sha256": sha},
        headers=headers,
    )


def test_upload_url_returns_a_presigned_post_with_a_content_addressed_key(client, analyst_headers):
    r = _reserve(client, analyst_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["fields"]["key"].endswith(f"{SHA}.pdf")
    assert body["fields"]["key"].startswith("raw/")
    assert body["duplicate"] is False


def test_oversized_upload_is_rejected_before_s3_ever_sees_it(client, analyst_headers):
    r = _reserve(client, analyst_headers, size=400 * 1024 * 1024)
    assert r.status_code == 413


def test_bad_sha_is_a_validation_error(client, analyst_headers):
    r = _reserve(client, analyst_headers, sha="nope")
    assert r.status_code == 422


def test_complete_returns_202(client, analyst_headers):
    doc_id = _reserve(client, analyst_headers).json()["document_id"]
    r = client.post(f"/api/v1/documents/{doc_id}/complete", headers=analyst_headers)
    assert r.status_code == 202
    assert r.json()["enqueued"] is True


def test_same_pdf_twice_is_one_document_row_and_still_202(client, analyst_headers, repo):
    """Duplicate submission is normal, not exceptional."""
    first = _reserve(client, analyst_headers).json()
    second = _reserve(client, analyst_headers).json()
    assert first["document_id"] == second["document_id"]
    assert second["duplicate"] is True

    r1 = client.post(f"/api/v1/documents/{first['document_id']}/complete", headers=analyst_headers)
    r2 = client.post(f"/api/v1/documents/{first['document_id']}/complete", headers=analyst_headers)
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["enqueued"] is True
    assert r2.json()["enqueued"] is False  # one row, one message

    assert len([d for d in repo.documents.values() if d.sha256 == SHA]) == 1


def test_complete_on_an_unknown_document_is_404_problem_json(client, analyst_headers):
    r = client.post("/api/v1/documents/999999/complete", headers=analyst_headers)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_every_response_carries_a_request_id(client, analyst_headers):
    r = client.get("/api/v1/reports", headers=analyst_headers)
    assert r.headers.get("X-Request-Id")


def test_client_supplied_request_id_is_echoed_for_tracing(client, analyst_headers):
    r = client.get(
        "/api/v1/reports", headers={**analyst_headers, "X-Request-Id": "01J8W2Z9QK7M3XN5RB4T6V8YHD"}
    )
    assert r.headers["X-Request-Id"] == "01J8W2Z9QK7M3XN5RB4T6V8YHD"


def test_a_failed_enqueue_rolls_the_status_back_and_returns_503(
    client, analyst_headers, repo, monkeypatch
):
    """A row saying 'queued' with no message behind it is a document stuck forever - the silent
    loss our success criteria forbid. Found by running the API with the queue switched off."""

    class DeadSqs:
        def send_message(self, **_):
            raise ConnectionError("elasticmq is not running")

    from services.common.settings import get_settings

    monkeypatch.setattr("services.common.aws.sqs", lambda: DeadSqs())
    # get_settings is lru_cached, so the dependency and this patch see the same instance.
    monkeypatch.setattr(get_settings(), "sqs_queue_url", "http://127.0.0.1:9/dead")

    doc_id = _reserve(client, analyst_headers).json()["document_id"]
    r = client.post(f"/api/v1/documents/{doc_id}/complete", headers=analyst_headers)

    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/problem+json")
    assert repo.document(doc_id).status == "received", "status must roll back so a retry works"


def test_after_a_failed_enqueue_a_retry_can_still_succeed(client, analyst_headers, repo):
    """The rollback is only worth having if the second attempt actually enqueues."""
    doc_id = _reserve(client, analyst_headers).json()["document_id"]
    repo.mark_queued(doc_id)
    repo.unmark_queued(doc_id)
    r = client.post(f"/api/v1/documents/{doc_id}/complete", headers=analyst_headers)
    assert r.status_code == 202
    assert r.json()["enqueued"] is True
