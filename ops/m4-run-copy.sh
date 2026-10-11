#!/usr/bin/env bash
# M4: one command that copies the VM database into Cloud SQL and prints old vs new row counts.
#
# Run from your laptop (your IP is on the firewall allow-list):
#   GCLOUD=/opt/homebrew/share/google-cloud-sdk/bin/gcloud ops/m4-run-copy.sh
#
# It sets a fresh Cloud SQL password, stores the new connection string in Secret Manager, sends
# it to the VM over SSH stdin (never printed, never written to disk; kept only in /dev/shm and
# deleted at the end), runs ops/m4-copy-data.sh on the VM, then cleans up.
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT="${PROJECT:-occurrence-desk-2893}"
ZONE="${ZONE:-us-central1-a}"
VM="${VM:-occurrence-desk-vm}"
INSTANCE="${INSTANCE:-occdesk-pg}"
HERE="$(cd "$(dirname "$0")" && pwd)"

g() { "$GCLOUD" --project "$PROJECT" "$@"; }

IP="$(g sql instances describe "$INSTANCE" --format='value(ipAddresses[0].ipAddress)')"
PW="$(openssl rand -hex 24)"

echo "1/4 New database password and Secret Manager version"
g sql users set-password occdesk --instance="$INSTANCE" --password="$PW" >/dev/null
printf '%s' "postgresql+psycopg://occdesk:${PW}@${IP}:5432/occdesk" |
  g secrets versions add occdesk-database-url --data-file=- >/dev/null

echo "2/4 Stage the copy script and connection string on the VM"
g compute scp "$HERE/m4-copy-data.sh" "$VM:/tmp/m4-copy-data.sh" --zone "$ZONE" >/dev/null
printf '%s\n' "postgresql://occdesk:${PW}@${IP}:5432/occdesk" |
  g compute ssh "$VM" --zone "$ZONE" --command 'umask 077; cat > /dev/shm/m4url' 2>/dev/null

echo "3/4 Copy the data and compare exact row counts (old | new)"
g compute ssh "$VM" --zone "$ZONE" --command \
  'CLOUDSQL_URL="$(cat /dev/shm/m4url)" bash /tmp/m4-copy-data.sh' 2>/dev/null

echo "4/4 Clean up the VM"
g compute ssh "$VM" --zone "$ZONE" --command 'rm -f /dev/shm/m4url /tmp/m4-copy-data.sh' 2>/dev/null
echo "Done."
