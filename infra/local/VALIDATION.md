# Milestone 1 infrastructure validation â€” 2026-09-10

Owner: Wasim. Base: main `027295c`.

## Passed on this Windows host

- Docker Compose v5.5.1 standalone binary, verified against its published SHA-256:
  `docker-compose --env-file .env.local -f docker-compose.yml --profile app --profile tools config --quiet`
- `python -m pytest -o addopts='' infra/tests tests/unit tests/contract -q`:
  **123 passed** (8 new infrastructure tests plus 115 existing unit/contract tests).
- `python -m ruff check infra` and `python -m ruff format --check infra`.
- Local config initialization is idempotent and retains existing random credentials.
- Docker Hub confirms selected MinIO and ElasticMQ version tags exist for amd64 and arm64.

## Live Docker validation after WSL installation and restart

Docker Desktop 4.90.0, Engine 29.7.2, Linux/amd64 with WSL 2.

- `python infra/local/manage.py infra-up`: passed. PostgreSQL and MinIO healthy;
  SQL/S3/SQS dependency gate and bucket/queue/DLQ bootstrap completed successfully.
- `docker compose --env-file .env.local --profile app --profile tools build api worker tools`:
  all three images built successfully, each with configured runtime user `app` (UID 10001).
- `python infra/local/manage.py infra-test`: passed SQL connectivity, object round trip,
  isolated queue round trip and redrive maxReceiveCount=3 check.
- Persistence: created an isolated SQL row, object and queue message, ran `down` then
  `infra-up`, and verified all three survived container recreation. Test records cleaned.
- Docker image inspect reported API 97,307,792 bytes; worker 199,006,151 bytes;
  tools 152,458,278 bytes. Both runtime images are below the work-pack 300 MB target
  using this Docker size report (not a measured network transfer or startup latency).
- `python infra/local/manage.py test`: all 123 selected tests passed inside the Linux tools container.
  Pytest cache is directed to /tmp so it remains writable for the non-root user.
- `up` fails with the expected missing database/worker integration messages on this branch.

## Still pending — do not claim M1 fully complete

- Database migrations against live PostgreSQL (teammate source not merged).
- Full PDF upload/queue/parse/report/disposition workflow and application-record persistence.

Main has no database or worker implementation; the separate parva/smit branches are
not merged. Their API/worker storage and public upload endpoint need owner-reviewed
wiring. See README.md in this directory for exact handoffs. Container infrastructure is
now verified; it does not substitute for the application integration acceptance test.

## Remaining acceptance run

1. Docker Desktop installed and running (completed).
2. `python infra/local/manage.py infra-up` (passed).
3. `python infra/local/manage.py infra-test` (passed).
4. Integrate application-owner changes listed in README.md.
5. `python infra/local/manage.py up`
6. Download the NASA sample and load Parva's December 2022 BTS source file.
7. Set the local E2E fixture password and run `e2e` from the host virtual environment.
8. Stop/start and confirm saved data persists; record output and image sizes here.

The pull request remains draft pending team integration review and full application E2E.
