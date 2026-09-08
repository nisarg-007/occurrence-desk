# Occurrence Desk

**Aviation safety report triage, built as a cloud system.**
Real federal data, a real queue, a real spike — and a ranked queue instead of a folder of PDFs.

[![status](https://img.shields.io/badge/milestone-M1%20in%20progress-blue)](#milestones)
[![python](https://img.shields.io/badge/python-3.12-blue)](#the-stack)
[![licence](https://img.shields.io/badge/licence-MIT-green)](LICENSE)

---

## The problem

Airlines run voluntary safety reporting programs. Pilots and mechanics write up what
went wrong in free prose. A safety analyst reads each one, works out what it describes,
finds the flight it belongs to, and decides what escalates.

The bottleneck is **intake, not judgement**. The reports are documents, the operational
data lives in another system, and nobody joins them until a human does it by hand.

**Occurrence Desk sits in front of the analyst.** It accepts a report, parses it, links
it to a real flight, categorises the hazard, scores it, and hands over a ranked queue.
Under a surge it lengthens a queue instead of returning errors, adds workers, and says
how long the backlog will take to drain.

## What it is not

We do not claim this system measures how often anything happens in aviation. NASA states
plainly that ASRS reports are submitted voluntarily, are subject to self-reporting biases,
are not verified or validated by NASA, and **cannot be used to infer the prevalence of a
problem in the National Airspace System**. We triage a document backlog. That is the claim.

---

## Ground truth — three real datasets, nothing invented

| Source | Role | Link |
|---|---|---|
| **NASA ASRS Report Sets** — 30 topics × 50 de-identified records = **1,500 narrative reports** (PDF) | the documents we parse and classify | <https://asrs.arc.nasa.gov/search/reportsets.html> |
| **BTS Reporting Carrier On-Time Performance** — monthly CSV, 111 fields, 1987→present | the relational spine we link reports to | <https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ&QO_fu146_anzr=b0-gvzr> |
| **NTSB accident database** | optional later milestone | <https://www.ntsb.gov/safety/data/Pages/Data_Stats.aspx> |
| ASRS data caveats — the honesty clause quoted above | read this before writing a claim | <https://asrs.arc.nasa.gov/search/dbol/aboutdata.html> |

**Why this corpus.** Each ASRS record is a block of NASA-coded fields
(`Assessments.Primary Problem`, `Events.Anomaly.*`, `Aircraft.Flight Phase`) followed by
the reporter's own narrative. NASA analysts read the narrative and assigned those codes.
So the narrative is our input and **somebody else's labels are our ground truth** — which
is the only kind of accuracy number worth putting on a slide.

---

## How it works

```
                 presigned POST                    SQS (standard, DLQ after 3)
   analyst  ──────────────────────►  S3  ──┐   ┌──────────────────────────────┐
      │                                    │   │                              ▼
      │  POST /documents/{id}/complete     └──►│  202 Accepted, <200ms p95   worker (Fargate)
      │  ─────────────────────────────────────►│  writes a row, sends 1 msg   pdfplumber
      │                                        └──────────────────────────────┤ TF-IDF + LinearSVC
      │                                                                       ▼
      │   GET /reports?…  keyset paged, ranked            PostgreSQL 16 (RDS)  ◄── BTS flights
      ◄───────────────────────────────────────────────────────────────────────┘
                                          worker count scales on backlog ÷ tasks
```

**The rule that defines the project:** `POST /documents/{id}/complete` returns **202 in
under 200 ms at p95, always**. It writes a row, sends one SQS message, and returns. It
never opens a PDF. The moment parsing creeps onto the request path, the project has lost
its thesis.

**Idempotency lives in two unique constraints**, not in clever code:
`documents.sha256` (the same PDF submitted twice is one row) and `reports.acn` (the same
ASRS record extracted twice is one row). S3 keys are content-addressed
(`raw/<yyyy>/<mm>/<dd>/<sha256>.pdf`), so a duplicate upload overwrites itself into an
identical object. This survives a worker crashing mid-parse.

---

## The stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 everywhere | one language across API, worker and load harness |
| API | FastAPI + Pydantic v2 | the OpenAPI spec everyone codes against, for free |
| ORM / migrations | SQLAlchemy 2.0 + Alembic | reviewed, reversible migrations |
| Database | PostgreSQL 16 → Amazon RDS | real foreign keys, `jsonb`, full-text search |
| Objects | S3 (MinIO locally) | presigned uploads keep large PDFs off the request path |
| Queue | Amazon SQS (ElasticMQ locally) | durable, at-least-once, dead-letter queue |
| Workers | ECS Fargate, ARM64, autoscaled on queue depth | no servers to patch, ~20% cheaper than x86 |
| Parsing | `pdfplumber` | pure CPU — **no paid API anywhere in the pipeline** |
| Categorisation | scikit-learn TF-IDF + LinearSVC | trains in seconds, honest about its error rate |
| Front end | Jinja2 + HTMX, server-rendered | stays responsive while work is still processing |
| Infra | Terraform | the environment is a reviewable diff |
| CI/CD | GitHub Actions + OIDC | no long-lived AWS keys in repo secrets |
| Load | Locust | the harness reuses our own client code |

---

## Running it locally

Nobody needs an AWS account to write code. MinIO speaks the S3 API and ElasticMQ speaks
the SQS API, so **application code is identical locally and on AWS** — the only difference
is whether `S3_ENDPOINT_URL` / `SQS_ENDPOINT_URL` are set.

```bash
cp .env.example .env
make up          # postgres 16 + minio + elasticmq + api + worker
make db-reset    # drop, create, alembic upgrade head
make db-load     # load December 2022 BTS
make test        # pytest
make e2e         # full path against the running stack
```

Until the compose stack lands (Wasim, week 1), the API alone runs against an in-memory
stub repository — enough to develop and test every route:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
APP_ENV=local uvicorn services.api.main:app --reload
# http://127.0.0.1:8000/docs   http://127.0.0.1:8000/console
```

Seeded stub logins (local only, never in prod): `analyst@occdesk.example` / `manager@occdesk.example`,
password `occdesk-local`.

---

## The API

Version prefix `/api/v1`. Every response carries `X-Request-Id`. Errors are RFC 7807
`application/problem+json`. Full spec: [`contracts/openapi.yaml`](contracts/openapi.yaml).

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/auth/login` | — | JWT, 60 min TTL |
| POST | `/documents/upload-url` | analyst | `{filename, byte_size, sha256}` → presigned **POST** + `document_id` |
| POST | `/documents/{id}/complete` | analyst | **202**, enqueues, never parses inline |
| GET | `/documents/{id}` | analyst | `{status, attempts, error_text, reports[]}` |
| GET | `/reports` | analyst | keyset paged; filters `category`, `state`, `priority_min`, `flight_date`, `q` |
| GET | `/reports/{id}` | analyst | coded fields, narrative, hazards, linked flight |
| GET | `/reports/{id}/why` | analyst | the four ranking terms and their products |
| POST | `/reports/{id}/disposition` | analyst | own assignments only |
| PATCH | `/reports/{id}/assign` | **manager** | 403 for analyst — and there is a test for that |
| GET | `/queue/stats` | manager | `{visible, in_flight, workers, throughput_per_min, drain_eta_seconds}` |
| GET | `/healthz` `/readyz` `/metrics` | — | liveness (checks nothing), readiness (DB + SQS), Prometheus |

**Presigned POST, not PUT.** POST can enforce `content-length-range` and `Content-Type`
in the policy, so a 400 MB file is rejected by S3 before it costs us a request.

### The ranked queue

An analyst does not want a list of reports; they want the *right* report first. The score
is deterministic and every term is explainable in one sentence:

```
priority = 100 × ( 0.45·severity + 0.25·link_confidence + 0.20·recency + 0.10·manager_flag )
                                                          recency = exp(−age_days / 365)
```

`severity_weight` is a column on `hazard_categories`, so the weights are **data we can
defend and change**, not magic numbers in code. `GET /reports/{id}/why` returns the four
terms and their products — because "why is this one at the top?" is the first question any
examiner asks about a ranking.

Paging is **keyset**, ordered on `(priority DESC, report_date DESC, id DESC)`. `OFFSET
50000` reads fifty thousand rows and throws them away; under the replay that is exactly
when the console would go dark.

---

## Repository layout

One repo, one owner per directory. Need a change in someone else's directory? Open a PR
and tag them — do not edit around them. See [CODEOWNERS](CODEOWNERS).

```
contracts/     Nisarg   openapi.yaml, queue + extraction schemas, CHANGELOG
db/            Parva    SQLAlchemy models, alembic migrations, BTS loader
services/
  common/      shared   aws.py, settings.py, logging.py
  api/         Nisarg   FastAPI + Jinja2/HTMX console, ranking, pagination
  worker/      Smit     SQS consumer, pdfplumber parser, classifier
  replay/      Sowmya   Locust harness + BTS event replay
web/           Nisarg   templates and static assets
infra/         Wasim    terraform modules + envs, Dockerfiles
ops/           Sowmya   CloudWatch dashboard as code, alarms, runbooks
eval/          Smit     50 hand-labelled gold records, score.py
tests/         unit · contract · e2e
docs/          measurements.md — every number, dated, with the command that produced it
```

## The team

| Lane | Owner |
|---|---|
| Application, API & Integration *(lead)* | **Nisarg** |
| Data Model & Managed Database | Parva |
| Storage, Ingestion & Extraction | Smit |
| Infrastructure, Containers & CI/CD | Wasim |
| Queue, Autoscaling, Observability & Load | Sowmya |

Two week-1 artefacts block everyone: the **local compose stack** (Wasim) and
**`contracts/openapi.yaml`** (Nisarg). Both are checked in early on purpose.

---

## Milestones

| | Weeks | The bar |
|---|---|---|
| **M1** | 1–3 | Local stack end to end. One PDF uploaded, queued, parsed, visible in the worklist. Zero AWS spend. |
| **M2** | 4–7 | Everything on AWS: RDS, S3, SQS, Fargate behind an ALB, deployed by GitHub Actions. Autoscaling and dashboard live. |
| **M3** | 8–11 | Accuracy scored on held-out data. Real hub-closure day replayed at scale, with graphs. Cost report. |
| **Demo** | 12 | One unbroken run, rehearsed three times. |

**Integration day, every Friday, 90 minutes, all five.** A lane is not done for the week
until `make e2e` passes on the dev environment — not when it passes on your laptop.

## Definition of done (measurable, not adjectival)

- `POST /documents/{id}/complete` p95 **< 200 ms** while the queue holds 10,000 messages.
- Worklist page 1 and page 100 both render **< 500 ms** at 50,000 reports.
- An analyst token gets **403** on every manager-only path — one test per path.
- Same PDF twice → one `documents` row, one report set. Proven by a test.
- Extraction P/R/F1 against 50 hand-labelled records; categorisation micro- **and** macro-F1
  on a **set-level** held-out split, with a per-label table and an error analysis.
- Submit latency flat at p95 through the replayed spike, **zero 5xx**, zero lost documents.

Every number lands in [`docs/measurements.md`](docs/measurements.md) with a date and the
command that produced it. The final report is that file, edited.

## Rules of engagement

1. **The contract changes by PR, never by message.** New field → PR on `contracts/`, tag
   Nisarg, add a dated line to `contracts/CHANGELOG.md`.
2. **`main` is always deployable.** Branch `feat/<lane>/<thing>`, one approving review, CI green.
3. **No migration merges without Parva's review; no Terraform without Wasim's.**
4. **No secrets in the repo, ever** — not even a local one. CI runs a secret scanner.
5. **Write the number down when you measure it.**
6. **Blocked for more than two hours? Say so.** Five lanes exist so that being blocked is unusual.

## Cost discipline

Budget is the AWS free account plan: **$100 credits at sign-up plus up to $100 earned,
expiring at six months or credit exhaustion, whichever comes first**
(<https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/>).
An always-on ALB and a NAT Gateway will eat that before the demo, so `make cloud-down`
destroys the expensive half (ALB, ECS, NAT; RDS snapshotted) and `make deploy-dev` brings
it back with data intact. Fargate ARM at 0.25 vCPU / 0.5 GB is **$0.009875/hour ≈ $7.11 a
month** per task (<https://aws.amazon.com/fargate/pricing/>). Budget alerts at 50 / 80 /
100% of $100, to all five of us.

## Licence

MIT — see [LICENSE](LICENSE). ASRS and BTS source data remain the property of their
respective agencies and are not redistributed in this repository.
