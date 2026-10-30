# ---------- IAM: VM service account roles ----------
# The VM SA needs these roles for the application to function:
#   - Secret Manager Secret Accessor (per-secret, in secrets.tf)
#   - Storage Object Admin (per-bucket, in storage.tf)
#   - Service Account Token Creator on itself (for GCS signed URLs)
#   - Logs Writer (for Cloud Logging)
#   - Monitoring Metric Writer (for Cloud Monitoring)

resource "google_project_iam_member" "vm_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${var.service_account_email}"
}

resource "google_project_iam_member" "vm_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${var.service_account_email}"
}

resource "google_service_account_iam_member" "vm_token_creator" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${var.service_account_email}"
}
