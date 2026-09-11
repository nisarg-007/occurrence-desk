# Wasim's Milestone 1 local stack

This change supplies infrastructure only. It does not silently merge teammate branches,
replace their stores, or claim the in-memory API is a completed M1 application.

## Prerequisites

- Python 3.12 and Git on the host.
- Docker Desktop running **Linux containers**, with Docker Compose v2 or newer.
- On Windows: install/enable WSL 2 first if Docker requests it; a restart may be required.
- No AWS account, cloud credentials, or paid API is used by these commands.
- Internet is needed initially to download images, Python packages and the sample PDF.

## Windows, macOS and Linux commands

Run in the repository root. `python infra/local/manage.py <action>` works without Make.
The Makefile wraps the same commands (`make infra-up`, `make up`, etc.).

```text
python infra/local/manage.py init
python infra/local/manage.py config
python infra/local/manage.py infra-up
python infra/local/manage.py infra-test
python infra/local/manage.py status
```

`init` creates ignored `.env.local` with random local credentials; repeated runs preserve it.
Never publish that file or the expanded output of `docker compose config`.
`config` validates without displaying credentials.

Infrastructure starts PostgreSQL 16, MinIO and ElasticMQ. A dependency-check container
checks SQL, S3 and SQS APIs before bootstrap creates the bucket, main queue and DLQ.
The ElasticMQ image uses the JVM variant for H2-backed message persistence.
The health gate polls the SQS API rather than assuming a shell or curl exists in its image.
MinIO browser CORS permits only the local application origins.

Host endpoints (bound to loopback only): API 8000, Postgres 5432, S3 9000,
MinIO console 9001, SQS 9324. Ports must be free before starting.

## Full application (after teammate integration)

```text
python infra/local/manage.py up
python infra/local/manage.py sample
python infra/local/manage.py db-load --file data/T_ONTIME_REPORTING_2022_12.csv
python infra/local/manage.py test
```

Obtain the December 2022 Reporting Carrier On-Time CSV from BTS and place it in `data/`.
This command invokes Parva's loader; it does not substitute generated flights.
For PowerShell, set `$env:E2E_PASSWORD` to the local fixture password documented in
the repository README, then run `python infra/local/manage.py e2e`.
E2E runs on the host so it can reach the same signed upload URLs as your browser.
Install `requirements-dev.txt` into a host virtual environment and invoke manage.py with
that environment's Python. E2E refuses a missing sample/password instead of reporting
success with skipped tests.
`sample` downloads NASA's nmac.pdf and records its source URL and hash, without committing it.

The API uses a real dependency health probe (database/S3/SQS plus HTTP liveness),
even though the current application readiness endpoint bypasses SQL in local mode.
The worker entry point calls the existing worker loop; no parser is duplicated here.
Its heartbeat measures the main loop, so a stuck process does not remain falsely healthy.
Longer-than-120-second parses can mark it unhealthy; adjust after Smit measures parse duration.

## Integration blockers found on 2026-09-10

1. Main `027295c` contains neither `db` implementation nor worker. Integrate Parva's
   `d9601dc` and Smit's `fffc576` through the team's review process first.
2. Nisarg must wire `SqlRepo` into `get_repo()`. The API entry point deliberately refuses
   `InMemoryRepo`. Parva must reconcile the repository with the current console (including
   `priority`, dashboard/stat methods); simply importing it is not a verified integration.
3. Smit must implement the worker store against the same PostgreSQL schema. His branch
   currently writes `worker_state.json`. The worker entry point refuses that temporary store.
4. Nisarg must use `S3_PUBLIC_ENDPOINT_URL` for presigned browser URLs and
   `S3_ENDPOINT_URL` for internal S3 operations. `http://minio:9000` resolves in Docker,
   but does not resolve in a teammate's browser. The Compose environment provides both.
   Do not rewrite a signed URL's hostname after signing it.
5. Smit's model file is not committed. Parsing can still produce NASA-coded hazards,
   but do not present that as a trained classifier prediction.

These are application-owner tasks, not hidden changes inside Wasim's infrastructure.
`infra-up` and `infra-test` are independent of them; `up` fails clearly until ready.

## Stop, reset and persistence

- `down` stops containers and **preserves** Postgres, objects and messages in named volumes.
- `destroy --yes` intentionally deletes this Compose project's volumes.
- `db-reset --yes` stops API/worker and resets only PostgreSQL using Parva's migrations.
  Old object and queue records remain: use `destroy --yes` for a complete clean demo reset.
- Use `up` after a DB reset to restart app services.

The work pack used `down -v`; the safer routine stop here retains data and reserves deletion
for explicit `destroy`. Nothing erases an existing database merely by starting the app.

## What to show for your M1 contribution

1. Explain the five services and bootstrap/migration startup order.
2. Show successful image builds and `status` with healthy containers.
3. Run `infra-test` (SQL, object round trip, isolated queue round trip, DLQ configuration).
4. With teammates' integration complete, upload a real PDF and show saved report/disposition.
5. Stop/start and show the saved records still exist. Record image sizes and E2E output.

Dockerfiles use multi-stage builds, non-root UID 10001, versioned base images and cached
dependency layers. The worker installs its currently missing parsing/ML dependencies in
a separate infrastructure-owned requirements file. Live Docker validation and reported image sizes are recorded in VALIDATION.md.
Both runtime images built below the 300 MB target on the tested Linux/amd64 setup.

Cloud Terraform, AWS deployment pipelines, OIDC and cost reporting belong to later milestones.

## References

- https://docs.docker.com/compose/how-tos/startup-order/
- https://github.com/softwaremill/elasticmq#persisting-queues-and-messages-to-sql-database
- https://asrs.arc.nasa.gov/docs/rpsts/nmac.pdf
