"""
Stage 7 + Stage 8 proof: run the real worker against real (local) S3 + SQS.

This uses the temporary MinIO + ElasticMQ containers started for this
session (NOT Wasim's docker-compose.yml, which hasn't landed yet - this is
just how Smit's lane proves the worker works before that exists). Talks to
the exact same services.common.aws.s3()/sqs() clients, and the exact same
queue-message shape in contracts/queue-message.schema.json, that the real
stack will use.

Three scenarios, run in order:
  1. Happy path - upload a real PDF, enqueue it, let the worker parse it.
  2. Duplicate message - send the identical message again. The worker must
     not reprocess it (idempotency).
  3. Poison PDF - enqueue a deliberately corrupted file. The worker must
     mark it failed and MUST NOT delete the message or crash the loop -
     we prove the message survives in-flight, on its way to the DLQ instead
     of vanishing silently.

Run from the repo root:
    python services/worker/local_stack_test.py
"""

import contextlib
import datetime as dt
import hashlib
import json
import os
import uuid

# Point at the temporary local stack BEFORE anything imports settings.
os.environ["S3_ENDPOINT_URL"] = "http://127.0.0.1:19000"
os.environ["SQS_ENDPOINT_URL"] = "http://127.0.0.1:9324"
os.environ["AWS_ACCESS_KEY_ID"] = "minioadmin"
os.environ["AWS_SECRET_ACCESS_KEY"] = "minioadmin"
os.environ["AWS_REGION"] = "us-east-1"

from services.common.aws import s3, sqs  # noqa: E402
from services.worker import store, worker  # noqa: E402

BUCKET = "occdesk-test-docs"


def bootstrap():
    """Create the bucket + main queue + DLQ if they don't already exist."""
    s3_client = s3()
    # already exists is fine: this script is meant to be re-runnable
    with contextlib.suppress(Exception):
        s3_client.create_bucket(Bucket=BUCKET)

    sqs_client = sqs()
    dlq = sqs_client.create_queue(QueueName="occdesk-test-parse-dlq")
    dlq_arn = sqs_client.get_queue_attributes(
        QueueUrl=dlq["QueueUrl"], AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]

    # NOTE: VisibilityTimeout=5 and maxReceiveCount=2 here are TEST-ONLY
    # values so this script can observe a full redrive-to-DLQ cycle in a
    # few seconds. The real queue (Sowmya's lane) uses 300s, sized against
    # the measured p99 parse time - see the work-pack, section 5.3.
    main = sqs_client.create_queue(
        QueueName="occdesk-test-parse",
        Attributes={
            "VisibilityTimeout": "5",
            "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 2}),
        },
    )
    return main["QueueUrl"], dlq["QueueUrl"]


def upload_and_enqueue(queue_url: str, local_path: str, document_id: int) -> str:
    with open(local_path, "rb") as handle:
        data = handle.read()
    sha256 = hashlib.sha256(data).hexdigest()
    today = dt.date.today()
    s3_key = f"raw/{today:%Y/%m/%d}/{sha256}.pdf"

    s3().upload_file(local_path, BUCKET, s3_key)
    store.register_document(document_id, sha256, BUCKET, s3_key)

    message = {
        "schema_version": 1,
        "kind": "document.parse",
        "document_id": document_id,
        "s3_bucket": BUCKET,
        "s3_key": s3_key,
        "sha256": sha256,
        "submitted_at": dt.datetime.now(dt.UTC).isoformat(),
        "trace_id": uuid.uuid4().hex,
    }
    sqs().send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
    return json.dumps(message)


def main():
    store.reset()
    queue_url, dlq_url = bootstrap()
    print(f"Queue ready: {queue_url}")
    print(f"DLQ ready:   {dlq_url}\n")

    # --- Scenario 1: happy path -------------------------------------------
    print("=== Scenario 1: happy path (real PDF through real S3 + SQS) ===")
    msg = upload_and_enqueue(queue_url, "services/worker/sample_pdfs/nmac.pdf", document_id=1)
    print(f"Sent message: {msg}")
    processed = worker.run(max_messages=1, queue_url=queue_url)
    print(f"Worker processed {processed} message(s)")
    doc = store.document_status(1)
    print(f"Document 1 status: {doc}")
    print(f"Total reports saved: {store.report_count()} (expected 50)\n")

    # --- Scenario 2: duplicate message -------------------------------------
    print("=== Scenario 2: duplicate message (idempotency) ===")
    before = store.report_count()
    sqs().send_message(QueueUrl=queue_url, MessageBody=msg)  # same message again
    processed = worker.run(max_messages=1, queue_url=queue_url)
    after = store.report_count()
    print(f"Worker processed {processed} message(s)")
    print(f"Report count before={before} after={after} (must be equal)\n")

    # --- Scenario 3: poison PDF ---------------------------------------------
    print("=== Scenario 3: poison PDF (corrupted file, must fail loudly) ===")
    poison_path = "services/worker/output/poison.pdf"
    os.makedirs("services/worker/output", exist_ok=True)
    with open(poison_path, "wb") as f:
        f.write(b"%PDF-1.7\nthis is not a real pdf, just garbage bytes\n")

    upload_and_enqueue(queue_url, poison_path, document_id=2)
    processed = worker.run(max_messages=1, queue_url=queue_url)
    doc2 = store.document_status(2)
    print(f"Worker processed {processed} message(s) without crashing")
    print(f"Document 2 status: {doc2}")

    attrs = sqs().get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    print(f"Queue right after failure: {attrs}")
    print("(message should still be counted - NOT deleted - because the parse failed)\n")

    print("Waiting 6s for the visibility timeout to expire, then letting the worker try again...")
    import time

    time.sleep(6)
    processed = worker.run(max_messages=1, queue_url=queue_url)
    print(f"Second delivery attempt: worker processed {processed} message(s)")

    print("Waiting 6s more, then a third receive to trigger the redrive to the DLQ...")
    time.sleep(6)
    # after maxReceiveCount=2 is exceeded, SQS/ElasticMQ moves it to the DLQ
    # on the next receive rather than handing it to us again
    resp = sqs().receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=1)
    print(
        "Main queue receive after redrive: "
        f"{'a message' if resp.get('Messages') else 'EMPTY - moved on'}"
    )
    dlq_resp = sqs().receive_message(QueueUrl=dlq_url, MaxNumberOfMessages=1, WaitTimeSeconds=1)
    print(f"DLQ receive: {'FOUND the poison message' if dlq_resp.get('Messages') else 'not found'}")


if __name__ == "__main__":
    main()
