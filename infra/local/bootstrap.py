"""Idempotently create local S3 bucket, upload CORS policy, SQS queue and DLQ."""

import json
import os

from infra.local.health import client


def bootstrap(s3, sqs, bucket):
    buckets = {item["Name"] for item in s3.list_buckets()["Buckets"]}
    if bucket not in buckets:
        s3.create_bucket(Bucket=bucket)
    # MinIO CORS is configured by MINIO_API_CORS_ALLOW_ORIGIN in Compose.
    dlq = sqs.create_queue(QueueName="occdesk-dev-parse-dlq")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    queue = sqs.create_queue(QueueName="occdesk-dev-parse")["QueueUrl"]
    sqs.set_queue_attributes(
        QueueUrl=queue,
        Attributes={
            "VisibilityTimeout": "300",
            "ReceiveMessageWaitTimeSeconds": "20",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": arn, "maxReceiveCount": 3}),
        },
    )
    return queue, dlq


if __name__ == "__main__":
    bootstrap(client("s3"), client("sqs"), os.environ["S3_BUCKET"])
    print("Local bucket, queue and DLQ ready.")
