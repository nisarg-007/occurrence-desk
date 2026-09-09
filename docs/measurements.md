# Measurements

Every latency, every accuracy score, every dollar goes here — with a date and the command that
produced it. **The final report is this file, edited.** A number without a command beside it is
a claim, not a measurement.

Format: `| date | what | value | command | who |`

## API (Nisarg)

| Date | What | Value | Command | Who |
|---|---|---|---|---|
| 2026-09-08 | Contract + implementation agree (no drift) | 6/6 conformance tests pass | `pytest tests/contract/test_spec_conformance.py` | Nisarg |
| 2026-09-09 | API test suite, M1 stub repository | 85 passed, 2 skipped (e2e — needs a live stack) | `pytest` | Nisarg |
| 2026-09-09 | API test suite, after the console dashboard (charts + latency reader + fragment) | 114 passed, 2 skipped | `pytest` | Nisarg |
| 2026-09-09 | Dashboard rendered in Chromium, light + dark | 0 console errors, 0 failed requests, 4 charts, auto-signed-in with no login screen (`APP_ENV=local`) | `playwright` screenshot pass | Nisarg |
| 2026-09-09 | Console redesign: contrast of every text/surface pair | worst pair **5.0:1** (light `--ink-3`), target 4.5:1 | `python3 /tmp/contrast.py`, values recorded in `web/static/css/console.css` | Nisarg |
| 2026-09-09 | Console redesign: rendered in Chromium, light + dark, 4 pages | 0 console errors, 0 failed requests | `playwright` screenshot pass | Nisarg |
| 2026-09-09 | Row link hit target | 63 × 28 px (desktop minimum 28 × 28) | `elementFromPoint` probe | Nisarg |
| 2026-09-09 | Clean-clone boot: runtime deps only, every page 200 | `/ /healthz /console /console/login /console/upload /console/reports/1 /docs /metrics` all 200 | `pip install -r requirements.txt && uvicorn services.api.main:app` | Nisarg |
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
| 2026-09-09 | Records extracted from 30 report sets | **1,500 / 1,500** — all 30 sets, 0 schema failures, 0 crashes | `python services/worker/classifier.py` (prints total while loading) | Smit |
| 2026-09-09 | Field extraction P / R / F1 vs gold records | **P 1.000 R 1.000 F1 1.000** (n=32 records, 1,546 field pairs) — **32 of the 50 the work-pack specifies; not yet complete**, see note below | `python eval/score.py` | Smit |
| 2026-09-09 | Categorisation micro-F1 / macro-F1, set-level split (6 sets held out entirely) | **micro-F1 0.783, macro-F1 0.574** (n=300 held-out records) — per-label table + error analysis in `eval/report.md` | `python services/worker/classifier.py` | Smit |
| 2026-09-09 | Mean and p99 parse time per document (one PDF, ~50 records) | mean **3752 ms**, p50 3534, p95 5248, **p99 6010 ms**, max 6010 (n=30 documents; ≈75 ms/record) — **hand-off to Sowmya**: her SQS `visibility_timeout` must sit comfortably above 6.0 s, and her autoscaling target is `acceptable_latency_s / 3.75` | `python tests/bench/bench_parse.py` | Smit |

**Open item, flagged not hidden:** the extraction accuracy score above is real, but the sample is 32 hand-verified records (one per report set for 24 of the 30 sets, plus extra coverage on structural edge cases), not the full 50 the work-pack calls for ("budget a full day"). Two real bugs were found and fixed via this process before it hit 1.000 (see `services/worker/parser.py` history: bare `Person` and bare `Aircraft` sections were briefly merging into the wrong neighbouring section). `ga_train.pdf` and `helo.pdf` share one identical ACN (2056353) in NASA's own data — only counted once, under `ga_train.pdf`. Expanding to a full, ideally team-reviewed, 50-record set is still open.

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

## What the design numbers mean

Contrast was computed, not judged: every colour pair in the console stylesheet was run
through the WCAG relative-luminance formula before it was written down, and the ratio is in
a comment beside it. The old palette had three colours that failed in light mode (amber at
1.6:1, green at 2.1:1, red at 2.8:1) because only the dark palette was ever looked at.

The rendered check matters as much as the computed one. Three defects in this pass were only
visible in a screenshot: a fabricated Subresource Integrity hash that silently blocked htmx
(the worklist said "loading" forever), a sticky table header that swallowed row clicks, and
ranking bars squeezed to 91 px in a side column. None of them would have failed a unit test.

Two more turned up the same way building the dashboard's bar charts: a value label (`94`) sat
half-behind its own bar whenever that row was the chart's max, because the 12px gap reserved
for the label was narrower than the label itself once it hit two digits; and a long hazard
category name (`Deviation - Track / Heading`) ran straight into the bar next to it, because the
label column's width was sized for the four short priority-band names and never re-checked
against real category names. Both are geometry a unit test on the SVG string would pass without
noticing — `test_charts.py` checks that a `<rect>` exists at all, not whether it overlaps a
`<text>` next to it. Fixed by widening the label column, truncating with an ellipsis past 20
characters (full name kept in `aria-label` and a `<title>` tooltip), and widening the value gap
to clear a three-digit number.

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
