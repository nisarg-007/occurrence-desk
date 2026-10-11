#!/usr/bin/env bash
# M4: give the VM the cloud-platform access scope so its service account's IAM roles decide
# what it can reach (the old devstorage.read_only scope blocked bucket writes and Secret Manager).
# Stops the VM for a few minutes. Run: GCLOUD=/opt/homebrew/share/google-cloud-sdk/bin/gcloud ops/m4-vm-scope.sh
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT="${PROJECT:-occurrence-desk-2893}"
ZONE="${ZONE:-us-central1-a}"
VM="${VM:-occurrence-desk-vm}"
SA="${SA:-638039823165-compute@developer.gserviceaccount.com}"

g() { "$GCLOUD" --project "$PROJECT" "$@"; }

echo "1/3 Stop the VM"
g compute instances stop "$VM" --zone "$ZONE"
echo "2/3 Set the cloud-platform scope"
g compute instances set-service-account "$VM" --zone "$ZONE" --service-account="$SA" --scopes=cloud-platform
echo "3/3 Start the VM"
g compute instances start "$VM" --zone "$ZONE"
g compute instances describe "$VM" --zone "$ZONE" --format='value(status,serviceAccounts[0].scopes)'
