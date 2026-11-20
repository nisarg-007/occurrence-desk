# ---------- Secret Manager secrets ----------
# Values are managed outside Terraform (m4-cloudsql-setup.sh creates the database URL,
# jwt_secret is rotated manually). Terraform manages the secret resources and IAM only.

resource "google_secret_manager_secret" "database_url" {
  secret_id = "occdesk-database-url"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "jwt_secret" {
  secret_id = "occdesk-jwt-secret"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "ai_chat_key" {
  secret_id = "occdesk-ai-chat-key"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "webhook_url" {
  secret_id = "occdesk-webhook-url"

  replication {
    auto {}
  }
}

# The VM service account reads all secrets at startup
resource "google_secret_manager_secret_iam_member" "vm_database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_secret_manager_secret_iam_member" "vm_jwt_secret" {
  secret_id = google_secret_manager_secret.jwt_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_secret_manager_secret_iam_member" "vm_ai_chat_key" {
  secret_id = google_secret_manager_secret.ai_chat_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_secret_manager_secret_iam_member" "vm_webhook_url" {
  secret_id = google_secret_manager_secret.webhook_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}
