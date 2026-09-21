# Roadmap

Tracked against the course milestone schedule (M1–M6). Status below reflects actual repo/infra state, not planned state.

## Status at a glance

| Milestone | What it covers | Due | Status |
|---|---|---|---|
| M1 — Working Local App | Full local stack running end-to-end | Sep 13 | ✅ Done |
| M2 — Platform Setup & Lift-and-Shift | Move off laptop onto a real cloud VM, with budget guardrails | Sep 20 | ✅ Done |
| M3 — Containerize & Deploy | Harden the deploy: real container orchestration, CI/CD | Oct 4 | ⬜ Not started |
| M4 — Decouple State | Move state (DB, object storage, queue) off the single VM | Oct 18 | ⬜ Not started |
| M5 — Orchestrate & Expose | Orchestration + public-facing service exposure | Oct 25 | ⬜ Not started |
| Step 11 — Checkpoint (ungraded) | Progress check-in | Nov 1 | ⬜ Not started |
| M6 — Observe & Automate (Final) | Observability, automation, final demo | Nov 8 | ⬜ Not started |

## M1 — Working Local App ✅

- Full local stack via Docker Compose: `api`, `worker`, `db` (Postgres), `minio` (S3-compatible), `elasticmq` (SQS-compatible).
- FastAPI service: auth, presigned-POST upload, async ingest (`202` in <200ms target), reports, `/why` explainability, disposition, assign, queue stats, `healthz`/`readyz`/metrics.
- Deterministic, explainable ranking engine with a documented formula and a `/why` endpoint that shows the math, not just a score.
- Analyst console: worklist, sign-in, detail view, upload — server-rendered, HTMX-driven.
- Stub repo seeded with 19 real NASA ASRS incident records (not synthetic placeholders).
- Test suite: 115 passed / 2 skipped, ruff clean.
- Submit-path benchmark: p95 5.10ms.
- Field-extraction accuracy measured against ground truth: precision/recall/F1 all 1.000 across 2,343 field pairs.

## M2 — Platform Setup & Lift-and-Shift ✅

- Deployed to a real GCP VM (`occurrence-desk-vm`, e2-small, `us-central1-a`) — moved off AWS-as-originally-planned onto GCP for the actual deployment target.
- Fixed the presigned-URL bug that only showed up off localhost: uploads were signed with the internal Docker endpoint instead of a public-facing one; server/browser now use separate `s3()` / `s3_public()` endpoints.
- Fixed a client-side upload failure specific to serving over plain HTTP: `crypto.subtle` (used to hash files before requesting a presigned URL) is only available in secure contexts, so a dependency-free SHA-256 fallback was added — hashing stays 100% client-side either way, preserving the "the API never sees the bytes" design.
- Fixed VM memory exhaustion (`AskTimeoutException` under load) by resizing `e2-micro` → `e2-small`.
- Firewall scoped to named team `/32` IPs only, both for SSH and app ports — `0.0.0.0/0` never used.
- Budget guardrails: $50/mo budget with alert thresholds at 20% / 50% / 100%, plus an automated rule that shuts down billable resources at 30% of the linked $300 credit.
- Automated billing digest (in progress): scheduled cost email via the Gmail API so spend is visible without checking the console.

## M3 — Containerize & Deploy ⬜

Not started. Scope: move from a single Compose stack on one VM to a real container-orchestration deploy (build/push images to a registry, CI/CD pipeline for deploys, health-checked rollouts) rather than SSH + `docker compose up`.

## M4 — Decouple State ⬜

Not started. Scope: move Postgres, object storage (currently MinIO on the same VM), and the queue (currently ElasticMQ on the same VM) to managed or at least externally-hosted services, so the app VM(s) become stateless and disposable.

## M5 — Orchestrate & Expose ⬜

Not started. Scope: orchestrate the now-stateless services (multiple instances, autoscaling — an autoscaling policy already exists on paper in the team's Queue/Autoscaling/Observability lane but hasn't been deployed) and expose the app behind a real public endpoint (load balancer / managed HTTPS) instead of a bare VM IP and port.

## Step 11 — Checkpoint ⬜

Not started. Ungraded progress check-in, due Nov 1.

## M6 — Observe & Automate (Final) ⬜

Not started. Scope: observability (metrics/logs/tracing wired to a dashboard, beyond the current Prometheus metrics endpoint), automation of routine ops, and the final demo. Team's own replay plan (Winter Storm Elliott traffic replay for load/accuracy testing under realistic conditions) targets this window.

## Known open items (not milestone-blocking, but relevant)

- SqlRepo work blocked on a teammate.
- Real p95 latency under a deep queue not yet measured (needs load-test support from two teammates).
- Demo timing not yet rehearsed.
- Hazard-categorization accuracy is lower than field-extraction accuracy (micro-F1 0.78 / macro-F1 0.57) — known, disclosed, not yet improved.
