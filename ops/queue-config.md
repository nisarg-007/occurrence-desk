# Local Queue Configuration — Justification

Owner: Sowmya — Queue, Autoscaling, Observability & Load

Local queue: ElasticMQ (SQS-compatible), created via `ops/setup-local-queue.sh`.

## Queues
- `occdesk-dev-parse` — main parse queue
- `occdesk-dev-parse-dlq` — dead-letter queue for messages that fail repeatedly

## Config decisions

**Visibility timeout: default (30s), not yet tuned to Smit's measured parse time.**
Per the work pack, this should be set to comfortably exceed the worker's real p99
parse time once `services/worker/` exists — too short causes duplicate processing
(SQS redelivers a message a worker is still handling), too long delays retry of a
genuinely failed message. Revisit once Smit has real parse timing.

**Standard queue, not FIFO.**
FIFO caps throughput per message group, which would throttle exactly the kind of
burst this project's async-processing claim is meant to demonstrate. Ordering
independence is acceptable because idempotency lives in the database layer
(unique constraints on `documents.sha256` and `reports.acn`), not in queue order.

**Dead-letter queue included from day one.**
A poison message (e.g. a corrupted PDF) should not block the queue indefinitely.
Once `services/worker/` exists, redrive policy (maxReceiveCount) should be set to
3 attempts before a message moves to the DLQ, matching the work pack's spec.

## Verified locally (2026-09-11)
- Queue created and reachable: confirmed via `curl ... Action=CreateQueue`
- Message send/receive round-trip: confirmed via manual SendMessage + dashboard
  "Waiting to parse" counter going 0 → 1 → 0 after purge
- Load test: 5 concurrent users via `services/replay/locustfile.py`, 0% failures,
  `/documents/upload-url` median 17ms / p95 30ms / max 72ms
