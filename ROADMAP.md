# Roadmap

Tracked against the course milestone schedule (M1–M6). Status below reflects actual repo/infra state, not planned state.

## Status at a glance

| Milestone | What it covers | Due | Status |
|---|---|---|---|
| M1 — Working Local App | Full local stack running end-to-end | Sep 13 | ✅ Done |
| M2 — Platform Setup & Lift-and-Shift | Move off laptop onto a real cloud VM, with budget guardrails | Sep 20 | ✅ Done |
| M3 — Containerize & Deploy | Harden the deploy: real container orchestration, CI/CD | Oct 4 | ✅ Done |
| M4 — Decouple State | Move state (DB, object storage, secrets) off the single VM | Oct 18 | ✅ Done (queue still on the VM) |
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

## M3 — Containerize & Deploy ✅

- Multi-stage Dockerfiles for the API and worker (`infra/docker/api.Dockerfile`, `infra/docker/worker.Dockerfile`), built for `linux/amd64`, with no `.env` baked into either image.
- `requirements.txt` split into `requirements-api.txt` and `requirements-worker.txt`. The API image dropped from 461 MB of installed dependencies to 155 MB. The API image is 407 MB and the worker image is 777 MB.
- `.dockerignore` excludes secrets, `.git`, caches, local data, and test fixtures.
- Images pushed to Artifact Registry (`us-central1`, tag `v1`) and deployed on the VM with `docker pull` + `docker compose`, with no install step on the VM.
- Fixed a worker import that needed `httpx`, found while testing on the VM.

**Not in the repo yet:** the M3 scope also named a CI/CD pipeline and health-checked rollouts. No `.github/` workflow exists in this repo, so treat those as open.

Submission record: `Group4_M3/` (deck, written analysis, demo video, screenshots).

## M4 — Decouple State ✅

- **Database:** Cloud SQL `occdesk-pg` (PostgreSQL 16, `db-f1-micro`, 10 GB SSD) with a **private IP only** (192.168.64.3, public IP disabled) and daily backups. Tables are created by the Alembic migrations in `db/alembic/versions/` (0001 initial schema, 0002 linkage weights). Old vs new row counts match: 265 = 265 across all 14 tables.
- **Uploads:** a private Cloud Storage bucket (`occdesk-docs-occurrence-desk-2893`, public access prevented). The API signs browser uploads as the VM's service account and the worker reads objects with the same identity, with no key files (`services/common/storage.py`, `STORAGE_BACKEND=gcs`; MinIO stays the local default).
- **Secrets:** the database URL and JWT secret live in Secret Manager and are read at startup (`services/common/secrets.py`, `SECRETS_BACKEND=gcp`). The running containers contain no `.env` file and no `DATABASE_URL` or `JWT_SECRET` in their environment. Outside local mode the app refuses to start with the default JWT secret.
- **Deployment:** `ops/vm/docker-compose.m4.yml` runs the API and worker; `ops/m4-deploy-vm.sh` builds the images on the VM and cuts over.
- **IAM:** the VM's service account holds Secret Manager Secret Accessor and Service Account Token Creator (on itself) in addition to the default project-wide Editor role.

**Still on the VM:** the queue. ElasticMQ runs in a container with its data in a volume on the VM's disk, so deleting the VM would lose waiting jobs, and the app is down until a new VM is built. Moving the queue to a managed service means changing the queue client code and is not done.

**Also open:** the AI chat key and the Slack webhook URL are not yet in Secret Manager, so those two optional features are off in the M4 stack (secret names `occdesk-ai-chat-key` and `occdesk-webhook-url` are already read if they exist).

Submission record: `Group4_M4/` (deck, written analysis, demo video, screenshots).

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
