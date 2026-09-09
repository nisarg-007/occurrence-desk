# Contract changelog

Every change to anything in `contracts/` gets a dated line here with who signed off.
Anything agreed verbally and not written down will be forgotten by Friday.

The format is `YYYY-MM-DD - what changed - why - signed off by`.

## Unreleased

- **2026-09-09** - `POST /documents/{document_id}/complete` gains a documented **503**
  (`Queue Unavailable`). Found by running the API with the queue switched off: the row was
  already flipped to `queued`, the `SendMessage` failed, and the caller got a bare 500 - leaving
  a document marked queued for a message that never existed. It now rolls the row back to
  `received` and returns problem+json, so a retry can enqueue it. Consumers should treat 503
  here as retryable; Sowmya's harness should count it as a failure, not a submission. - Nisarg

- **2026-09-08** - No change to `openapi.yaml`. Recording two things other lanes now depend on:
  **(1)** `/metrics` publishes `occdesk_http_request_duration_seconds` (histogram; labels
  `method`, `route`, `status`; bucket edges include `0.2`) and
  `occdesk_documents_submitted_total{enqueued}`. Sowmya's dashboard and alarms read those names,
  so renaming one is a contract change and comes here first.
  **(2)** The console's HTMX fragments under `/console/fragments/` require the same bearer token
  as the API they render, and are deliberately absent from the OpenAPI document - they are not
  a public interface and nobody should code against them. - Nisarg

## 1.0.0 - 2026-09-08

- **2026-09-08** - Initial `openapi.yaml` (v1.0.0), `queue-message.schema.json` (schema_version 1),
  `extraction-record.schema.json`. Hand-written before any route exists, so the other four lanes
  can build against a stub from week 1. - Nisarg

### Decisions baked into v1.0.0, with the reasoning

| Decision | Why |
|---|---|
| `POST /documents/{id}/complete` returns **202**, never 200 | the parse must never be on the request path; a 200 invites someone to "just parse it inline for now" |
| Presigned **POST**, not PUT | POST can enforce `content-length-range` and `Content-Type`; PUT cannot, so a 400 MB upload would reach us |
| **Keyset** pagination, no `offset` parameter | `OFFSET 50000` reads and discards 50,000 rows - exactly the failure mode the replay will find |
| `sha256` is a required field on `upload-url` | it is the idempotency key and the S3 object key; making it optional would make duplicates undetectable |
| NASA dotted paths kept **verbatim** in `coded` and `fields` | snake-casing them makes our extraction uncheckable against the printed PDF |
| `report_hazards.source` is `nasa` or `model`, both in one table | scoring becomes a single SQL query instead of a join across two tables |
| `queue/stats.drain_eta_seconds` is nullable with an `estimating` flag | a wrong ETA is worse than no ETA; "the system degrades legibly" is a success criterion |
| `/healthz` checks nothing; `/readyz` checks DB and SQS | if liveness and readiness are the same endpoint, one slow query makes ECS kill healthy tasks in a loop |

### Open items

- [ ] `[verify]` dev hostname in `servers:` once Wasim's ACM certificate is issued.
- [ ] Hazard `code` vocabulary is a placeholder until Smit's `eval/labels.json` enumerates the
      `Anomaly.*` values that actually appear in the corpus. The list is data, not a hand-written guess.
- [ ] `FlightLink.method` values to be fixed once Parva's linkage query lands.
