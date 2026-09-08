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


def sqs():
    s = get_settings()
    return boto3.client(
        "sqs",
        endpoint_url=s.sqs_endpoint_url or None,
        region_name=s.aws_region,
    )
