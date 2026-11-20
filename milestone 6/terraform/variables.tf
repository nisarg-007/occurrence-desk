variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "occurrence-desk-2893"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone for the VM"
  type        = string
  default     = "us-central1-a"
}

variable "vm_name" {
  description = "Compute Engine instance name"
  type        = string
  default     = "occurrence-desk-vm"
}

variable "sql_instance_name" {
  description = "Cloud SQL instance name"
  type        = string
  default     = "occdesk-pg"
}

variable "gcs_bucket_name" {
  description = "GCS bucket for PDF uploads"
  type        = string
  default     = "occdesk-docs-occurrence-desk-2893"
}

variable "service_account_email" {
  description = "Compute Engine default service account"
  type        = string
  default     = "638039823165-compute@developer.gserviceaccount.com"
}

variable "team_ips" {
  description = "Team member IPs allowed through the firewall"
  type        = list(string)
  default     = []
}

variable "notification_email" {
  description = "Email for alert notifications"
  type        = string
  default     = "nisarg0708@gmail.com"
}
