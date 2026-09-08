"""Queue statistics without hammering SQS.

GetQueueAttributes is cached in-process for 5 seconds - the console polls this every second
during the demo and SQS should not see that. `drain_eta_seconds` is null with
`estimating: true` until throughput is large enough to mean anything: a wrong number is worse
than no number, and "the system degrades legibly" is one of our success criteria.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

EPSILON = 1e-9
#: Below this many parses per minute the ETA is noise, not information.
MIN_MEANINGFUL_THROUGHPUT_PER_MIN = 1.0


@dataclass
class Snapshot:
    visible: int
    in_flight: int
    oldest_message_age_seconds: int | None
    dlq_depth: int
    fetched_at: float


def drain_eta_seconds(visible: int, throughput_per_min: float) -> int | None:
    if throughput_per_min < MIN_MEANINGFUL_THROUGHPUT_PER_MIN:
        return None
    return int(visible / max(throughput_per_min / 60.0, EPSILON))


class QueueStatsCache:
    def __init__(self, ttl_seconds: int = 5, clock=time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._snapshot: Snapshot | None = None

    def get(self, fetch) -> Snapshot:
        now = self._clock()
        if self._snapshot is None or now - self._snapshot.fetched_at >= self.ttl:
            snap = fetch()
            snap.fetched_at = now
            self._snapshot = snap
        return self._snapshot


def fetch_from_sqs(sqs_client, queue_url: str, dlq_url: str = "") -> Snapshot:
    attrs = sqs_client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
            "ApproximateAgeOfOldestMessage",
        ],
    )["Attributes"]
    dlq_depth = 0
    if dlq_url:
        dlq_depth = int(
            sqs_client.get_queue_attributes(
                QueueUrl=dlq_url, AttributeNames=["ApproximateNumberOfMessages"]
            )["Attributes"].get("ApproximateNumberOfMessages", 0)
        )
    age = attrs.get("ApproximateAgeOfOldestMessage")
    return Snapshot(
        visible=int(attrs.get("ApproximateNumberOfMessages", 0)),
        in_flight=int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        oldest_message_age_seconds=int(age) if age is not None else None,
        dlq_depth=dlq_depth,
        fetched_at=0.0,
    )
