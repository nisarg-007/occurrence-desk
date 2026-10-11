"""Settings for every service. The same twelve variables everywhere.

The only place that decides local-vs-AWS is whether S3_ENDPOINT_URL / SQS_ENDPOINT_URL are
set. If you find yourself writing `if LOCAL:` anywhere else, stop and raise it in the channel.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


_LOCAL_JWT_SECRET = "change-me-locally-only"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    app_env: str = "local"
    app_version: str = "dev"  # set to the git SHA at build time; never "latest"

    database_url: str = "postgresql+psycopg://occdesk:occdesk@localhost:5432/occdesk"

    storage_backend: str = "s3"  # "s3" (MinIO / AWS S3) or "gcs" (Google Cloud Storage via the VM service account)
    secrets_backend: str = "env"  # "env" or "gcp" (Secret Manager, see services/common/secrets.py)
    gcp_project: str = ""  # project that holds the secrets when secrets_backend is "gcp"

    s3_endpoint_url: str | None = None  # empty on AWS
    s3_public_endpoint_url: str | None = None  # browser-facing host for presigned URLs; falls back to s3_endpoint_url
    s3_bucket: str = "occdesk-dev-docs"

    sqs_endpoint_url: str | None = None  # empty on AWS
    sqs_queue_url: str = ""
    sqs_dlq_url: str = ""

    aws_region: str = "us-east-1"

    jwt_secret: str = _LOCAL_JWT_SECRET
    jwt_ttl_minutes: int = 60
    jwt_algorithm: str = "HS256"

    max_upload_bytes: int = 26_214_400  # 25 MB
    presign_expires_seconds: int = 900

    worker_concurrency: int = 1
    log_level: str = "INFO"

    queue_stats_cache_seconds: int = 5

    ai_chat_key: str = ""  # xAI / Grok API key — set via GROK_API_KEY env var (never commit a real key)

    webhook_url: str = ""  # Slack incoming-webhook URL for critical-priority alerts (never commit a real one)

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.secrets_backend == "gcp":
        from services.common.secrets import load_secrets

        # Init kwargs outrank environment variables, so Secret Manager values always win.
        settings = Settings(**load_secrets(settings.gcp_project))
    if not settings.is_local and settings.jwt_secret == _LOCAL_JWT_SECRET:
        raise RuntimeError("JWT_SECRET is still the local default outside APP_ENV=local")
    return settings
