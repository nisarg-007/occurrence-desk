"""Live infrastructure probe: SQL, object round trip, queue round trip and DLQ policy."""

import json
import os
import uuid

from infra.local.health import client, database


def main():
    database()
    s3 = client("s3")
    sqs = client("sqs")
    bucket = os.environ["S3_BUCKET"]
    key = "infra-smoke/" + uuid.uuid4().hex
    payload = b"Occurrence Desk infrastructure check"
    queue = None
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=payload)
        result = s3.get_object(Bucket=bucket, Key=key)
        if result["Body"].read() != payload:
            raise RuntimeError("Object round trip mismatch")
        result["Body"].close()
        # Never consume a real document job while testing infrastructure.
        queue = sqs.create_queue(QueueName="infra-smoke-" + uuid.uuid4().hex)["QueueUrl"]
        sqs.send_message(QueueUrl=queue, MessageBody=payload.decode())
        messages = sqs.receive_message(QueueUrl=queue, WaitTimeSeconds=5).get("Messages", [])
        if not messages or messages[0]["Body"] != payload.decode():
            raise RuntimeError("Queue round trip mismatch")
        sqs.delete_message(QueueUrl=queue, ReceiptHandle=messages[0]["ReceiptHandle"])
        attributes = sqs.get_queue_attributes(
            QueueUrl=os.environ["SQS_QUEUE_URL"], AttributeNames=["RedrivePolicy"]
        )["Attributes"]
        if int(json.loads(attributes["RedrivePolicy"])["maxReceiveCount"]) != 3:
            raise RuntimeError("Queue redrive policy mismatch")
        print("PASS: database, S3 round trip, isolated SQS round trip, DLQ policy.")
    finally:
        s3.delete_object(Bucket=bucket, Key=key)
        if queue:
            sqs.delete_queue(QueueUrl=queue)


if __name__ == "__main__":
    main()
