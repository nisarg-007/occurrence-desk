output "vm_external_ip" {
  description = "Public IP of the application VM"
  value       = google_compute_instance.app.network_interface[0].access_config[0].nat_ip
}

output "sql_private_ip" {
  description = "Private IP of the Cloud SQL instance"
  value       = google_sql_database_instance.postgres.private_ip_address
}

output "gcs_bucket" {
  description = "GCS bucket name for PDF uploads"
  value       = google_storage_bucket.docs.name
}

output "dashboard_url" {
  description = "Cloud Monitoring dashboard URL"
  value       = "https://console.cloud.google.com/monitoring/dashboards/builder/${google_monitoring_dashboard.app.id}?project=${var.project_id}"
}

output "app_url" {
  description = "Application HTTPS URL"
  value       = "https://${google_compute_instance.app.network_interface[0].access_config[0].nat_ip}.nip.io"
}
