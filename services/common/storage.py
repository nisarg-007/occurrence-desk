"""Object storage for uploads: the second place a storage decision is made, after aws.py.

STORAGE_BACKEND=s3 (default) keeps the MinIO / AWS S3 path through services.common.aws.
STORAGE_BACKEND=gcs uses a Google Cloud Storage bucket with Application Default Credentials,
which on a Compute Engine VM means the VM's service account. No key file, no HMAC key.
"""

from __future__ import annotations

from services.common import aws
from services.common.settings import get_settings

PDF = "application/pdf"


def presign_upload(bucket: str, key: str, max_bytes: int, expires: int) -> dict:
    """A browser-usable POST target that enforces PDF content type and a size range."""
    if get_settings().storage_backend == "gcs":
        return _gcs_presign_upload(bucket, key, max_bytes, expires)
    return aws.s3_public().generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields={"Content-Type": PDF},
        Conditions=[{"Content-Type": PDF}, ["content-length-range", 1, max_bytes]],
        ExpiresIn=expires,
    )


def download(bucket: str, key: str, path: str) -> None:
    if get_settings().storage_backend == "gcs":
        _gcs_client().bucket(bucket).blob(key).download_to_filename(path)
        return
    aws.s3().download_file(bucket, key, path)


def _gcs_client():
    from google.cloud import storage

    return storage.Client()


def _gcs_presign_upload(bucket: str, key: str, max_bytes: int, expires: int) -> dict:
    import google.auth
    from google.auth.transport.requests import Request
    from google.cloud import storage

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())
    # Compute Engine credentials hold no private key, so the policy is signed through the IAM
    # signBlob API as the VM service account (it needs Token Creator on itself).
    return storage.Client(credentials=credentials).generate_signed_post_policy_v4(
        bucket,
        key,
        expiration=expires,
        fields={"Content-Type": PDF},
        conditions=[{"Content-Type": PDF}, ["content-length-range", 1, max_bytes]],
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )
