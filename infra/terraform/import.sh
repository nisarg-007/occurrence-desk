#!/usr/bin/env bash
# Import existing GCP resources into Terraform state.
# Run once after `terraform init`, before the first `terraform plan`.
#
#   cd infra/terraform && terraform init && bash import.sh
#
# After import, `terraform plan` should show zero changes (or only non-destructive drift).
set -euo pipefail

PROJECT="occurrence-desk-2893"
ZONE="us-central1-a"
SA="638039823165-compute@developer.gserviceaccount.com"

import() {
  echo "Importing $1 ..."
  terraform import "$1" "$2" 2>/dev/null || echo "  (already imported or not found)"
}

# Network
import 'google_compute_global_address.private_services' "$PROJECT/google-managed-services-default"
import 'google_service_networking_connection.private_vpc' "$PROJECT/default/servicenetworking.googleapis.com"

# Firewall
import 'google_compute_firewall.allow_http'  "$PROJECT/occdesk-allow-http"
import 'google_compute_firewall.allow_https' "$PROJECT/occdesk-allow-https"
import 'google_compute_firewall.allow_ssh'   "$PROJECT/occdesk-allow-ssh"

# VM
import 'google_compute_instance.app' "$PROJECT/$ZONE/occurrence-desk-vm"

# Cloud SQL
import 'google_sql_database_instance.postgres' "$PROJECT/occdesk-pg"
import 'google_sql_database.app'               "$PROJECT/occdesk-pg/occdesk"
import 'google_sql_user.app'                   "$PROJECT/occdesk-pg/occdesk"

# GCS
import 'google_storage_bucket.docs' "$PROJECT/occdesk-docs-occurrence-desk-2893"
import 'google_storage_bucket_iam_member.vm_storage' "b/occdesk-docs-occurrence-desk-2893/roles/storage.objectAdmin/serviceAccount:$SA"

# Secret Manager
for secret in database_url jwt_secret ai_chat_key webhook_url; do
  tf_name=$(echo "$secret" | tr '_' '-')
  import "google_secret_manager_secret.${secret}" "projects/$PROJECT/secrets/occdesk-${tf_name}"
  import "google_secret_manager_secret_iam_member.vm_${secret}" "projects/$PROJECT/secrets/occdesk-${tf_name}/roles/secretmanager.secretAccessor/serviceAccount:$SA"
done

# IAM
import 'google_project_iam_member.vm_log_writer'    "$PROJECT/roles/logging.logWriter/serviceAccount:$SA"
import 'google_project_iam_member.vm_metric_writer'  "$PROJECT/roles/monitoring.metricWriter/serviceAccount:$SA"
import 'google_service_account_iam_member.vm_token_creator' "projects/$PROJECT/serviceAccounts/$SA/roles/iam.serviceAccountTokenCreator/serviceAccount:$SA"

# Monitoring (these are new, no import needed)
echo ""
echo "Done. Monitoring resources (log metric, dashboard, alert) are new and will be created."
echo "Run: terraform plan"
