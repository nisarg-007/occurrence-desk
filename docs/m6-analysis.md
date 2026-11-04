# Milestone 6: Observability and Automation Analysis

**Project:** Occurrence Desk. **Team:** Nisarg Patel, Parva Bhatt, Smit Patel, Wasim Shaikh, Sowmya Manchikanti.
**Live URL:** https://34.132.226.2.nip.io (GCP project `occurrence-desk-2893`, branch `main`).

## 1. Logs and the 5xx metric

The API and worker write one JSON object per line to stdout: timestamp, level, service, logger, message, `trace_id`, `request_id`, method, path, `status` and duration in ms. The Docker `gcplogs` driver ships each line to Cloud Logging. A log-based metric, `occdesk-http-5xx-errors`, counts entries from the `api` service whose `status` is 500 to 599. The dashboard and the alert both read this metric. A gated endpoint, `POST /ops/fault`, returns a deliberate 500, so we can raise the count on demand during the demo and watch it rise in Logs Explorer.

## 2. Dashboard and alert

The Cloud Monitoring dashboard "Occurrence Desk" has six panels: 5xx count from the log metric, VM CPU, VM memory, VM network, Cloud SQL CPU and Cloud SQL connections. The alert policy "Occurrence Desk - HTTP 5xx Error Rate" fires when the 5xx metric sums to more than 5 in a 5-minute window. It notifies the "Occurrence Desk Alerts" email channel (nisarg0708@gmail.com) and closes itself after 30 minutes without errors. It fired on 2026-11-01 (12 errors against a threshold of 5) and the email arrived.

## 3. What Terraform manages, and what it does not

Terraform (`infra/terraform/`) manages the VM, Cloud SQL (PostgreSQL 16, private IP), the GCS bucket, four Secret Manager secrets and their IAM bindings, the three firewall rules, private service access, IAM roles for logging and metrics, the log-based metric, the dashboard, the notification channel and the alert policy. Resources that existed first were brought in with `import.sh`. `terraform plan` against the live project reports **No changes**. The dashboard JSON is excluded from diffing because the Monitoring API adds default fields.

Not managed by Terraform, on purpose:

- The GitHub deploy identity: Workload Identity pool `gh-pool`, provider `gh-provider` and service account `gh-deployer`. We created these with gcloud. They need Owner rights, and the Terraform state account only has Editor.
- The budget guard: budget `free-trial-credit-30pct-alert`, its Pub/Sub topic and the Cloud Run service `stop-vm-on-budget`. The guard stopped the VM on every budget message, so we paused it by switching its subscription to pull mode.
- The project itself, enabled APIs, billing, the Terraform state file, and the Caddy local CA certificate.

## 4. Pipeline: deploy, health check, rollback

GitHub Actions workflow "Build, Deploy & Rollback" runs on every push to `main`. The `test` job runs ruff and pytest. The `deploy` job authenticates to GCP with Workload Identity Federation, so no key is stored in GitHub. It then:

1. records the running version and tags the current images as `rollback`;
2. uploads the source over an IAP tunnel and builds the images on the VM with the commit SHA as `APP_VERSION`;
3. recreates the Compose stack (Caddy, API, worker);
4. polls `/healthz` up to 30 times, 3 seconds apart;
5. on failure, retags `rollback` images and recreates the previous stack automatically; on success, promotes the new tag and checks `/readyz` over public HTTPS.

`/healthz` returns the deployed commit SHA, so we verify which version is serving. Run 9 (commit 85b4e56) passed end to end. Run 10 used the `break_health` input to fail the health check on purpose: the pipeline reported Health false and Rolled back true, and the site returned 200 on the previous version.

## 5. HTTPS and security

Caddy terminates TLS on port 443 and redirects port 80. It sets HSTS, nosniff and X-Frame-Options. Secrets live in Secret Manager, Cloud SQL has no public IP, and no state file or key is in the repository. The fault endpoint is gated by `ALLOW_FAULT_INJECTION` and is switched on for the demo and the grading period.
