# Measurements

Every latency, every accuracy score, every dollar goes here — with a date and the command that
produced it. **The final report is this file, edited.** A number without a command beside it is
a claim, not a measurement.

Format: `| date | what | value | command | who |`

## API (Nisarg)

| Date | What | Value | Command | Who |
|---|---|---|---|---|
| 2026-09-08 | Contract + implementation agree (no drift) | 6/6 conformance tests pass | `pytest tests/contract/test_spec_conformance.py` | Nisarg |
| 2026-09-08 | API test suite, M1 stub repository | 77 passed, 2 skipped (e2e — needs a live stack) | `pytest` | Nisarg |
| 2026-09-08 | `complete` handler cost, **in-process floor** — no network, S3, SQS or database | mean 4.18 ms, p50 4.02, p95 5.10, p99 6.35, max 35.37 (n=400, 25 warmup discarded) | `python tests/bench/bench_submit.py --iterations 400` | Nisarg |
| 2026-09-08 | Lint and format | clean | `ruff check . && ruff format --check .` | Nisarg |
| | `POST /documents/{id}/complete` p95 with 10,000 messages queued | **target < 200 ms** — this is the number for the report; the 5.10 ms above is a floor, not a claim | Sowmya's Locust run, `services/replay/` | pending M2 |
| | Worklist page 1 render at 50,000 reports | **target < 500 ms** | `tests/e2e/test_worklist_latency.py` | pending M2 |
| | Worklist page 100 render at 50,000 reports | **target < 500 ms** | same | pending M2 |
| | `GET /queue/stats` SQS call rate under a 1 Hz console poll | **target ≤ 0.2 calls/s** (5 s cache) | CloudWatch `NumberOfEmptyReceives` | pending M2 |

## Database (Parva)

| Date | What | Value | Command | Who |
|---|---|---|---|---|
| | December 2022 BTS rows loaded vs source CSV | **must match exactly** | `make db-load` then `SELECT count(*) FROM flights` | pending |
| | Linkage top-5 for one report | **target < 100 ms** | `EXPLAIN (ANALYZE, BUFFERS)` | pending |
| | PITR restore wall time | | `aws rds restore-db-instance-to-point-in-time …` | pending |
| | Connection ceiling on the instance class | | `SHOW max_connections` | pending |

## Extraction and categorisation (Smit)

| Date | What | Value | Command | Who |
|---|---|---|---|---|
| | Records extracted from 30 report sets | **target 1,500**, or a written explanation of every shortfall | `python eval/score.py` | pending |
| | Field extraction P / R / F1 vs 50 gold records | | `python eval/score.py` | pending |
| | Categorisation micro-F1 / macro-F1, set-level split | report honestly whatever it comes out at | `python eval/score.py` | pending |
| | Mean and p99 parse time per document | **hand this number to Sowmya** — her visibility timeout and autoscaling target both derive from it | worker structured logs, `duration_ms` | pending |

## Queue, scaling and load (Sowmya)

| Date | What | Value | Command | Who |
|---|---|---|---|---|
| | Autoscaling target = acceptable latency ÷ mean parse time | show the arithmetic | — | pending |
| | Submit p50 / p95 / p99 through the burst, vs baseline | | Locust | pending |
| | HTTP error rate through the burst | **target: zero 5xx** | Locust | pending |
| | Peak backlog / peak task count / drain time | | CloudWatch | pending |
| | Zero loss: documents submitted vs distinct rows, duplicates collapsed | run live in the demo | one SQL query | pending |

## Infrastructure and cost (Wasim)

| Date | What | Value | Command | Who |
|---|---|---|---|---|
| | `terraform apply` from zero, wall time | | `time make deploy-dev` | pending |
| | `make cloud-down` then restore, wall time | rehearse in week 8, not at 1am | `time make cloud-down` | pending |
| | CI wall time | **target < 8 min** | GitHub Actions run summary | pending |
| | Month-to-date cost by service | **every Friday** | Cost Explorer, grouped by service | pending |

## Reading the floor number honestly

The benchmark row above measures **our handler and nothing else**: FastAPI routing, JWT decode,
the row write and the message construction, with the stub repository, in the same process, on a
container that is not the one we deploy to. It does not include a network hop, an S3 presign, an
SQS `SendMessage`, RDS latency, or any contention. It cannot tell you what the service does
under load and it is not the p95 in our definition of done.

It is still worth recording, for one reason: it says how much of the 200 ms budget our own code
spends. About 5 ms of 200 means the budget is dominated by everything *around* the handler, so
if the deployed p95 comes back at 180 ms we should look at SQS, the presign, and the ALB before
we look at this code. That is a useful thing to know before the replay, not after it.

## Notes

- Fargate ARM unit prices used in the cost model: **$0.0000089944 per vCPU-second** and
  **$0.0000009889 per GB-second** (<https://aws.amazon.com/fargate/pricing/>), i.e. $0.03238/vCPU-hr
  and $0.003560/GB-hr. A 0.25 vCPU / 0.5 GB task is **$0.009875/hour ≈ $7.11 per 30-day month**.
- Anything still marked `[verify]` in the work pack is *not* a measurement and does not belong in
  this table until it has been checked against a primary source.
