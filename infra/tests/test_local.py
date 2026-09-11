import json
from unittest.mock import Mock

import pytest

from infra.local import bootstrap, health, manage


def test_bootstrap_reuses_existing_bucket_and_sets_dlq():
    s3, sqs = Mock(), Mock()
    s3.list_buckets.return_value = {"Buckets": [{"Name": "docs"}]}
    sqs.create_queue.side_effect = [
        {"QueueUrl": "http://elasticmq:9324/dlq"},
        {"QueueUrl": "http://elasticmq:9324/main"},
    ]
    sqs.get_queue_attributes.return_value = {"Attributes": {"QueueArn": "arn:test:dlq"}}
    bootstrap.bootstrap(s3, sqs, "docs")
    s3.create_bucket.assert_not_called()
    attributes = sqs.set_queue_attributes.call_args.kwargs["Attributes"]
    assert json.loads(attributes["RedrivePolicy"]) == {
        "deadLetterTargetArn": "arn:test:dlq",
        "maxReceiveCount": 3,
    }
    assert attributes["ReceiveMessageWaitTimeSeconds"] == "20"


def test_bootstrap_creates_missing_bucket():
    s3, sqs = Mock(), Mock()
    s3.list_buckets.return_value = {"Buckets": []}
    sqs.create_queue.return_value = {"QueueUrl": "http://elasticmq:9324/queue"}
    sqs.get_queue_attributes.return_value = {"Attributes": {"QueueArn": "arn:test:dlq"}}
    bootstrap.bootstrap(s3, sqs, "docs")
    s3.create_bucket.assert_called_once_with(Bucket="docs")


def test_init_does_not_overwrite_local_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "ENV", tmp_path / ".env.local")
    monkeypatch.setattr(manage, "SAMPLE", tmp_path / "tests/e2e/fixtures/nmac.pdf")
    manage.init()
    first = manage.ENV.read_text()
    manage.init()
    assert manage.ENV.read_text() == first
    assert "LOCAL_DB_PASSWORD=" in first


def test_missing_teammate_code_is_an_error(tmp_path):
    errors = manage.source_blockers(tmp_path)
    assert len(errors) == 4
    assert any("Parva" in error for error in errors)
    assert any("Smit" in error for error in errors)


def test_local_tools_refuse_real_aws(monkeypatch):
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.amazonaws.com")
    with pytest.raises(RuntimeError, match="refuses"):
        health.client("s3")


def test_missing_fixture_fails_instead_of_skipping(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "require_sources", lambda: None)
    monkeypatch.setattr(manage, "SAMPLE", tmp_path / "missing.pdf")
    monkeypatch.setattr("sys.argv", ["manage.py", "e2e"])
    with pytest.raises(SystemExit, match="Refusing silently skipped"):
        manage.main()


def test_down_preserves_volumes(monkeypatch):
    compose = Mock()
    monkeypatch.setattr(manage, "compose", compose)
    monkeypatch.setattr("sys.argv", ["manage.py", "down"])
    manage.main()
    assert "--volumes" not in compose.call_args.args


def test_destroy_requires_explicit_confirmation(monkeypatch):
    monkeypatch.setattr("sys.argv", ["manage.py", "destroy"])
    with pytest.raises(SystemExit, match="deletes"):
        manage.main()
