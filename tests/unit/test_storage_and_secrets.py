import pytest

from services.common import secrets, storage
from services.common.settings import Settings


def test_s3_backend_presigns_through_boto3_with_pdf_and_size_policy(monkeypatch):
    seen = {}

    class FakeS3:
        def generate_presigned_post(self, **kwargs):
            seen.update(kwargs)
            return {"url": "https://s3.test", "fields": {}}

    monkeypatch.setattr("services.common.aws.s3_public", lambda: FakeS3())
    storage.presign_upload("b", "raw/k.pdf", 100, 60)
    assert seen["Bucket"] == "b" and seen["Key"] == "raw/k.pdf" and seen["ExpiresIn"] == 60
    assert ["content-length-range", 1, 100] in seen["Conditions"]


def test_gcs_backend_signs_a_post_policy_as_the_service_account(monkeypatch):
    seen = {}

    class Creds:
        service_account_email = "vm@project.iam.gserviceaccount.com"
        token = "token"

        def refresh(self, request):
            pass

    class FakeClient:
        def __init__(self, credentials=None):
            pass

        def generate_signed_post_policy_v4(self, bucket, key, **kwargs):
            seen.update(bucket=bucket, key=key, **kwargs)
            return {"url": "https://storage.googleapis.com/b/", "fields": {}}

    monkeypatch.setattr(
        "services.common.storage.get_settings", lambda: Settings(storage_backend="gcs")
    )
    monkeypatch.setattr("google.auth.default", lambda scopes: (Creds(), "project"))
    monkeypatch.setattr("google.cloud.storage.Client", FakeClient)
    storage.presign_upload("b", "raw/k.pdf", 100, 60)
    assert seen["service_account_email"] == "vm@project.iam.gserviceaccount.com"
    assert seen["access_token"] == "token"
    assert ["content-length-range", 1, 100] in seen["conditions"]


def test_load_secrets_returns_values_and_tolerates_missing_optional_ones():
    def fetch(secret_id):
        if secret_id in ("occdesk-ai-chat-key", "occdesk-webhook-url"):
            raise KeyError(secret_id)
        return f"value-of-{secret_id}"

    loaded = secrets.load_secrets("project", fetch)
    assert loaded == {
        "database_url": "value-of-occdesk-database-url",
        "jwt_secret": "value-of-occdesk-jwt-secret",
    }


def test_load_secrets_fails_when_a_required_secret_is_missing():
    def fetch(secret_id):
        raise KeyError(secret_id)

    with pytest.raises(RuntimeError, match="occdesk-database-url"):
        secrets.load_secrets("project", fetch)


def test_get_settings_refuses_the_local_jwt_secret_outside_local(monkeypatch):
    from services.common import settings as settings_module

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("JWT_SECRET", "change-me-locally-only")
    settings_module.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            settings_module.get_settings()
    finally:
        settings_module.get_settings.cache_clear()
