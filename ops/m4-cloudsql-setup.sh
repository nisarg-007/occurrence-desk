#!/usr/bin/env bash
# M4: managed Postgres on a private IP only, with its connection string in Secret Manager.
#
# Run once from a shell signed in as an account with Editor on the project:
#   GCLOUD=/opt/homebrew/share/google-cloud-sdk/bin/gcloud ops/m4-cloudsql-setup.sh
#
# Cost: one db-f1-micro Cloud SQL instance (about $10-15/month) plus 10 GB SSD, billed to the
# project's billing account. Delete it with: gcloud sql instances delete occdesk-pg
# The database password is generated here and written straight to Secret Manager; it is never
# printed and never written to a file.
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT="${PROJECT:-occurrence-desk-2893}"
REGION="${REGION:-us-central1}"
NETWORK="${NETWORK:-default}"
INSTANCE="${INSTANCE:-occdesk-pg}"
RANGE="google-managed-services-default"

g() { "$GCLOUD" --project "$PROJECT" "$@"; }

echo "1/6 Enable Service Networking (private services access)"
g services enable servicenetworking.googleapis.com

echo "2/6 Reserve a private IP range for Google-managed services"
if ! g compute addresses describe "$RANGE" --global >/dev/null 2>&1; then
  g compute addresses create "$RANGE" --global --purpose=VPC_PEERING --prefix-length=20 \
    --network="$NETWORK" --description="Private services access range for Cloud SQL"
fi

echo "3/6 Peer the VPC with Google services"
g services vpc-peerings connect --service=servicenetworking.googleapis.com \
  --ranges="$RANGE" --network="$NETWORK"

echo "4/6 Create the Cloud SQL instance (Postgres 16, private IP only, no public IP)"
if ! g sql instances describe "$INSTANCE" >/dev/null 2>&1; then
  g sql instances create "$INSTANCE" --database-version=POSTGRES_16 --edition=ENTERPRISE \
    --tier=db-f1-micro --region="$REGION" --availability-type=zonal \
    --storage-type=SSD --storage-size=10GB --backup-start-time=03:00 \
    --network="projects/$PROJECT/global/networks/$NETWORK" --no-assign-ip
fi

echo "5/6 Create the database and application user"
g sql databases create occdesk --instance="$INSTANCE" 2>/dev/null || echo "  database exists"
PASSWORD="$(openssl rand -hex 24)"
if g sql users describe occdesk --instance="$INSTANCE" >/dev/null 2>&1; then
  g sql users set-password occdesk --instance="$INSTANCE" --password="$PASSWORD"
else
  g sql users create occdesk --instance="$INSTANCE" --password="$PASSWORD"
fi

echo "6/6 Store the connection string in Secret Manager as occdesk-database-url"
# With --no-assign-ip the only address on the instance is the PRIVATE one.
PRIVATE_IP="$(g sql instances describe "$INSTANCE" --format='value(ipAddresses[0].ipAddress)')"
URL="postgresql+psycopg://occdesk:${PASSWORD}@${PRIVATE_IP}:5432/occdesk"
if g secrets describe occdesk-database-url >/dev/null 2>&1; then
  printf '%s' "$URL" | g secrets versions add occdesk-database-url --data-file=-
else
  printf '%s' "$URL" | g secrets create occdesk-database-url --replication-policy=automatic \
    --data-file=-
fi

echo "Done. Private IP: $PRIVATE_IP (no public IP assigned)."
g sql instances describe "$INSTANCE" --format='table(name,state,ipAddresses)'
