# Milestone 6: Observability & Automation Analysis

**Project:** Occurrence Desk -- Aviation Safety Report Triage  
**Team:** Nisarg Patel, Parva Bhatt, Smit Patel, Wasim Shaikh, Sowmya Manchikanti  
**Date:** October 2026

---

## 1. Structured Logging

Every HTTP request produces a JSON log line to stdout containing: timestamp, log level, service name, logger, message, trace_id, request_id, HTTP method, path, status code, and duration in milliseconds. The `trace_id` field threads through the API and worker services so a single document's lifecycle -- upload, queue, parse, store -- can be reconstructed with one CloudWatch Logs Insights query: `filter trace_id = "..."`. Uvicorn's own loggers are redirected through the same JSON formatter so container logs contain exactly one format. The logging module uses Python `contextvars` to propagate request and trace identifiers without passing them through every function signature.

## 2. Metrics & Log-Based Metric

The API exposes a Prometheus `/metrics` endpoint with three application-level instruments: `occdesk_http_request_duration_seconds` (histogram with buckets around the 200ms p95 SLO), `occdesk_documents_submitted_total` (counter), and `occdesk_http_5xx_errors_total` (counter by method and route). In addition, a GCP log-based metric (`occdesk-http-5xx-errors`) counts JSON log entries where `jsonPayload.status >= 500` against the `gce_instance` resource type. This metric feeds the Cloud Monitoring dashboard and alert policy. A controlled `/ops/fault` endpoint produces 500 errors on demand (gated by an environment variable) so the log-based metric, dashboard and alert can be demonstrated live.

## 3. Dashboard

The Cloud Monitoring dashboard contains six panels: HTTP 5xx error count (from the log-based metric), VM CPU utilization, VM memory usage, VM network throughput, Cloud SQL CPU utilization, and Cloud SQL active connections. The layout groups application health (top row), VM resources (middle row), and database resources (bottom row). Each panel uses the GCE instance ID or Cloud SQL database ID as a filter so multi-instance noise is excluded. The dashboard is defined entirely in Terraform (`infra/terraform/monitoring.tf`) and is reproducible from `terraform apply`.

## 4. Alerting

An alert policy fires when the 5xx log-based metric exceeds 5 errors in a 5-minute window. The notification channel is an email address. The alert auto-closes after 30 minutes of silence. During the demo, the `/ops/fault` endpoint is called repeatedly to trigger the threshold, and the received email notification is shown as evidence. The alert policy, notification channel, and documentation are all managed in Terraform.

## 5. Infrastructure as Code (Terraform)

Terraform manages every cloud resource: Compute Engine VM (e2-small, COS image, cloud-platform scope), Cloud SQL PostgreSQL 16 (db-f1-micro, private IP, SSD, daily backup), GCS bucket (uniform access, enforced public prevention), four Secret Manager secrets with per-secret IAM bindings, three firewall rules (HTTP/HTTPS/SSH), VPC peering for private services access, IAM roles (log writer, metric writer, token creator), the log-based metric, monitoring dashboard, and alert policy with notification channel. An import script (`import.sh`) brings existing resources into state. After import, `terraform plan` shows zero changes for all previously created resources; only the new monitoring resources appear as additions.

## 6. CI/CD Pipeline

GitHub Actions runs on every push to `main`. The pipeline has two jobs: `test` (lint with ruff, unit and contract tests with pytest) and `deploy` (authenticated to GCP via a service account key). The deploy job: (1) records the current running image tag for rollback, (2) uploads source and builds Docker images on the VM, (3) tags the current images as `rollback`, (4) starts the new containers with `docker compose up -d`, (5) runs a health check loop (30 attempts, 3 seconds apart) against `/healthz`. If the health check fails, the pipeline automatically restores the `rollback`-tagged images and restarts the previous stack. On success, images are tagged `current` and the source directory is promoted. A deploy summary table is written to the GitHub Actions step summary.

## 7. HTTPS

Caddy runs as a reverse proxy in the Docker Compose stack, terminating TLS on ports 80 and 443. Port 80 redirects to HTTPS. Caddy generates a self-signed internal certificate (suitable for the demo on a raw IP). For a production domain, the Caddyfile is updated to the FQDN and Caddy obtains a Let's Encrypt certificate automatically. Security headers (HSTS, X-Content-Type-Options, X-Frame-Options) are set on every response.

## 8. Architecture Decisions

ElasticMQ remains on the VM rather than migrating to Cloud Pub/Sub. This is a deliberate decision: the queue is a lightweight SQS-compatible container consuming minimal resources, and replacing it would require rewriting the boto3 SQS client calls across the worker and API services for a marginal gain in a project that processes tens of documents per day. The cost stays under the $50/month budget. The VM uses the default Compute Engine service account with `cloud-platform` scope, and individual permissions are granted through fine-grained IAM roles rather than broad project-level roles.
