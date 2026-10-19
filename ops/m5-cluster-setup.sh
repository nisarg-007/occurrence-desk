#!/usr/bin/env bash
# M5: one-time GCP setup for the GKE deployment. Safe to re-run; every step checks before creating.
#
#   PROJECT=occurrence-desk-2893 ops/m5-cluster-setup.sh
#
# Creates: required APIs, Artifact Registry repo, GKE Autopilot cluster, a Google service account for the
# pods (Workload Identity, no key files) and a reserved global static IP. The queue runs in the cluster
# (k8s/05-queue.yaml), so no firewall rule is needed.
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT="${PROJECT:-occurrence-desk-2893}"
REGION="${REGION:-us-central1}"
CLUSTER="${CLUSTER:-occdesk}"
NETWORK="${NETWORK:-default}"
BUCKET="${BUCKET:-occdesk-docs-occurrence-desk-2893}"
AR_REPO="${AR_REPO:-occurrence-desk}"
GSA_NAME="${GSA_NAME:-occdesk-gke}"
GSA_EMAIL="$GSA_NAME@$PROJECT.iam.gserviceaccount.com"
STATIC_IP_NAME="${STATIC_IP_NAME:-occdesk-ip}"
K8S_NAMESPACE=occdesk
K8S_SA=occdesk

g() { "$GCLOUD" --project "$PROJECT" "$@"; }

echo "== APIs"
g services enable container.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  compute.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com

echo "== Artifact Registry (reuses the M4 repo)"
g artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1 \
  || g artifacts repositories create "$AR_REPO" --repository-format docker --location "$REGION" \
       --description "Occurrence Desk images"

echo "== GKE Autopilot cluster $CLUSTER (takes several minutes)"
g container clusters describe "$CLUSTER" --region "$REGION" >/dev/null 2>&1 \
  || g container clusters create-auto "$CLUSTER" --region "$REGION" --network "$NETWORK"
g container clusters get-credentials "$CLUSTER" --region "$REGION"

echo "== Pod identity: $GSA_EMAIL"
g iam service-accounts describe "$GSA_EMAIL" >/dev/null 2>&1 \
  || g iam service-accounts create "$GSA_NAME" --display-name "Occurrence Desk GKE pods"
g projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$GSA_EMAIL" \
  --role roles/secretmanager.secretAccessor --condition=None >/dev/null
# Uploads are signed and read from the bucket, as on the VM.
g storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$GSA_EMAIL" \
  --role roles/storage.objectAdmin >/dev/null
# generate_signed_post_policy_v4 signs through IAM signBlob, so the account needs Token Creator on itself.
g iam service-accounts add-iam-policy-binding "$GSA_EMAIL" --member "serviceAccount:$GSA_EMAIL" \
  --role roles/iam.serviceAccountTokenCreator >/dev/null
# The Kubernetes service account in k8s/00-namespace-config.yaml may act as the Google one.
g iam service-accounts add-iam-policy-binding "$GSA_EMAIL" \
  --member "serviceAccount:$PROJECT.svc.id.goog[$K8S_NAMESPACE/$K8S_SA]" \
  --role roles/iam.workloadIdentityUser >/dev/null

echo "== Reserved global static IP $STATIC_IP_NAME"
g compute addresses describe "$STATIC_IP_NAME" --global >/dev/null 2>&1 \
  || g compute addresses create "$STATIC_IP_NAME" --global
echo "   address: $(g compute addresses describe "$STATIC_IP_NAME" --global --format='value(address)')"


echo "done. Next: ops/m5-deploy.sh build && ops/m5-deploy.sh apply"
