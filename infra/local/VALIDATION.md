# Milestone 1 infrastructure validation — 2026-09-10

Owner: Wasim. Base: main `027295c`.

## Passed on this Windows host

- Docker Compose v5.5.1 standalone binary, verified against its published SHA-256:
  `docker-compose --env-file .env.local -f docker-compose.yml --profile app --profile tools config --quiet`
- `python -m pytest -o addopts='' infra/tests tests/unit tests/contract -q`:
  **123 passed** (8 new infrastructure tests plus 115 existing unit/contract tests).
- `python -m ruff check infra` and `python -m ruff format --check infra`.
- Local config initialization is idempotent and retains existing random credentials.
- Docker Hub confirms selected MinIO and ElasticMQ version tags exist for amd64 and arm64.

## Not executed — do not claim M1 fully complete

- Docker image builds, image-size measurement, container health and live infrastructure smoke.
- Database migrations against live PostgreSQL.
- Full PDF upload/queue/parse/report/disposition workflow and persistence test.

This host has neither Docker Desktop nor WSL installed. Docker Desktop installation was
attempted; Windows elevation was canceled (installer log: `The operation was canceled
by the user`). No restart or second installation attempt was forced.

Even on a Docker-enabled host, application integration remains required. Main has no
database or worker implementation; the separate parva/smit branches are not merged.
Their API/worker storage and public upload endpoint need owner-reviewed wiring.
See README.md in this directory for exact handoffs. The included startup guards fail
clearly rather than passing an in-memory or JSON-backed mock as a complete integration.

## Remaining acceptance run

1. Install/start Docker Desktop (Linux containers).
2. `python infra/local/manage.py infra-up`
3. `python infra/local/manage.py infra-test`
4. Integrate application-owner changes listed in README.md.
5. `python infra/local/manage.py up`
6. Download the NASA sample and load Parva's December 2022 BTS source file.
7. Set the local E2E fixture password and run `e2e` from the host virtual environment.
8. Stop/start and confirm saved data persists; record output and image sizes here.

The pull request must remain draft until container checks and integration are reviewed.
