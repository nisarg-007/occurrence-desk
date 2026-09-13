"""Presigned browser URLs must not expose Docker-only DNS names."""

import pytest

from services.common import aws
from services.common.settings import Settings


@pytest.mark.parametrize(
    "internal,public,expected",
    [
        ("http://minio:9000", "http://localhost:9000", "http://localhost:9000"),
        ("http://localhost:9000", "", "http://localhost:9000"),
        (None, None, "https://occdesk-dev-docs.s3.amazonaws.com"),
    ],
)
def test_presigning_uses_browser_endpoint_without_changing_internal_io(
    monkeypatch, internal, public, expected
):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
    settings = Settings(
        _env_file=None,
        s3_endpoint_url=internal,
        s3_public_endpoint_url=public,
        aws_region="us-east-1",
    )
    monkeypatch.setattr(aws, "get_settings", lambda: settings)
    signed = aws.s3_presign().generate_presigned_post(Bucket="occdesk-dev-docs", Key="test.pdf")
    assert signed["url"].startswith(expected)
    if internal:
        assert aws.s3().meta.endpoint_url == internal
