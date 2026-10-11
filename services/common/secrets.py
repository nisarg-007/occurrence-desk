"""Secret Manager loading. Production secrets live there, never in code, the image or a .env.

SECRETS_BACKEND=gcp reads each secret below from GCP_PROJECT as the VM service account, which
needs roles/secretmanager.secretAccessor. Anything else (the default) leaves Settings to read
plain environment variables, as local development does.
"""

from __future__ import annotations

from collections.abc import Callable

# Settings field -> (Secret Manager secret id, required)
SECRETS = {
    "database_url": ("occdesk-database-url", True),
    "jwt_secret": ("occdesk-jwt-secret", True),
    "ai_chat_key": ("occdesk-ai-chat-key", False),
    "webhook_url": ("occdesk-webhook-url", False),
}


def _default_fetch(project: str) -> Callable[[str], str]:
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()

    def fetch(secret_id: str) -> str:
        name = f"projects/{project}/secrets/{secret_id}/versions/latest"
        return client.access_secret_version(name=name).payload.data.decode("utf-8").strip()

    return fetch


def load_secrets(project: str, fetch: Callable[[str], str] | None = None) -> dict[str, str]:
    """Return {settings field: value}. A missing required secret is a startup error."""
    if not project:
        raise RuntimeError("SECRETS_BACKEND=gcp requires GCP_PROJECT")
    fetch = fetch or _default_fetch(project)
    values: dict[str, str] = {}
    for field, (secret_id, required) in SECRETS.items():
        try:
            values[field] = fetch(secret_id)
        except Exception as exc:
            if required:
                raise RuntimeError(f"required secret {secret_id!r} could not be read") from exc
    return values
