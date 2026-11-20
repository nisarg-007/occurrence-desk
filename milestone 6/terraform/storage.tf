# ---------- GCS bucket for PDF uploads ----------

resource "google_storage_bucket" "docs" {
  name     = var.gcs_bucket_name
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = false
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 365
    }
  }
}

# The VM service account needs Storage Object Admin on this bucket
resource "google_storage_bucket_iam_member" "vm_storage" {
  bucket = google_storage_bucket.docs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.service_account_email}"
}
