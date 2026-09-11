"""
Stage 7 - the worker.

Turns "a queue message exists" into "structured reports exist", the way
section 3.5 of the work-pack describes:

    receive (long poll) -> claim -> download from S3 -> parse -> save -> delete message

Stage 8 (handling things going wrong) is folded in here rather than bolted on
after, because the failure modes are part of the same control flow:

  - claim_for_parsing() is what makes processing the same message twice safe:
    a redelivered or duplicate message finds the document already
    'parsing'/'parsed' and is dropped without doing the work again.
  - a VisibilityHeartbeat keeps re-extending the SQS visibility timeout while
    a parse is still running, so SQS doesn't hand the same message to a
    second worker mid-parse.
  - a genuine parse failure is caught ONCE, recorded on the document
    (status='failed', error_text set), and the message is deliberately left
    alone rather than deleted - SQS will redeliver it, and after
    maxReceiveCount attempts the queue's redrive policy moves it to the DLQ.
    We never catch-and-mark-parsed on a broken PDF: a silently swallowed
    exception is the one bug class explicitly called out as unacceptable.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time

from services.common.aws import s3, sqs
from services.common.logging import trace_id_var
from services.common.settings import get_settings
from services.worker import store
from services.worker.hazards import predict_hazards
from services.worker.parser import parse_pdf

logger = logging.getLogger("worker")

# Sowmya owns the real queue's VisibilityTimeout (see her lane: it must sit
# comfortably above Smit's measured p99 parse time). This local constant is
# only a stand-in until her Terraform sets it for real.
VISIBILITY_TIMEOUT_SECONDS = 300


class VisibilityHeartbeat:
    """Re-extends a message's visibility timeout every half-interval while a
    parse is still running, so a slow parse doesn't cause SQS to redeliver
    the message to a second worker before we're done with it."""

    def __init__(
        self, queue_url: str, receipt_handle: str, timeout: int = VISIBILITY_TIMEOUT_SECONDS
    ):
        self._queue_url = queue_url
        self._receipt_handle = receipt_handle
        self._timeout = timeout
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        interval = max(1, self._timeout // 2)
        while not self._stop.wait(interval):
            try:
                sqs().change_message_visibility(
                    QueueUrl=self._queue_url,
                    ReceiptHandle=self._receipt_handle,
                    VisibilityTimeout=self._timeout,
                )
            except Exception:
                logger.exception("heartbeat: failed to extend message visibility")

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)


def handle_message(message: dict, queue_url: str) -> None:
    """Process exactly one SQS message. Never raises - a broken message
    should not take down the whole worker loop."""
    body = json.loads(message["Body"])
    trace_id_var.set(body.get("trace_id", "-"))
    document_id = body["document_id"]

    if not store.claim_for_parsing(document_id):
        logger.info(
            "document already claimed/parsed - dropping duplicate",
            extra={
                "document_id": document_id,
            },
        )
        sqs().delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
        return

    heartbeat = VisibilityHeartbeat(queue_url, message["ReceiptHandle"])
    heartbeat.start()
    started = time.monotonic()
    success = False
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            s3().download_file(body["s3_bucket"], body["s3_key"], tmp.name)
            records = parse_pdf(tmp.name, document_id=document_id)
        for record in records:
            # NASA's own codes are already in record["hazards"] (source='nasa').
            # Add what our own classifier thinks from the narrative alone
            # (source='model') - this is what a real, never-before-coded
            # report would get, since it won't come with NASA's labels.
            record["hazards"].extend(predict_hazards(record["narrative"]))
        inserted = store.save_reports(document_id, records)
        store.mark_parsed(document_id)
        success = True
        duration_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "document parsed",
            extra={
                "document_id": document_id,
                "records_extracted": len(records),
                "records_new": inserted,
                "duration_ms": duration_ms,
            },
        )
    except Exception as exc:
        logger.exception("parse failed", extra={"document_id": document_id})
        store.mark_failed(document_id, f"{type(exc).__name__}: {exc}")
    finally:
        heartbeat.stop()

    if success:
        sqs().delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
    # else: message is left in the queue on purpose. See module docstring.


def run(max_messages: int | None = None, queue_url: str | None = None) -> int:
    """Long-poll the queue and process messages one at a time.

    max_messages: stop after this many (used by tests/demo). None = forever.
    Returns the number of messages processed.
    """
    settings = get_settings()
    queue_url = queue_url or settings.sqs_queue_url
    if not queue_url:
        raise RuntimeError("SQS_QUEUE_URL is not set - nothing to consume from")

    client = sqs()
    processed = 0
    while max_messages is None or processed < max_messages:
        resp = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,  # long polling - see the work-pack trap list
        )
        messages = resp.get("Messages", [])
        if not messages:
            if max_messages is not None:
                # in a bounded test run, an empty poll means there's nothing
                # left to do - don't long-poll forever waiting for more.
                break
            continue
        handle_message(messages[0], queue_url)
        processed += 1
    return processed
