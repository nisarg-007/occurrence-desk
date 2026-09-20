"""The ONLY place endpoints are decided.

Empty S3_ENDPOINT_URL / SQS_ENDPOINT_URL means real AWS; set means MinIO / ElasticMQ.
That is the entire difference between local and cloud.
"""

from __future__ import annotations

import boto3

from services.common.settings import get_settings


def s3():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint_url or None,
        region_name=s.aws_region,
    )


def s3_public():
    """S3 client scoped to signing presigned URLs the browser will hit directly.

    Uses S3_PUBLIC_ENDPOINT_URL when set (falls back to s3_endpoint_url, so real
    AWS is unaffected). Every server-side S3 call still goes through s3().
    """
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_public_endpoint_url or s.s3_endpoint_url or None,
        region_name=s.aws_region,
    )


def sqs():
    s = get_settings()
    return boto3.client(
        "sqs",
        endpoint_url=s.sqs_endpoint_url or None,
        region_name=s.aws_region,
    )
