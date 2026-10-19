#!/usr/bin/env bash
# M5: build images with Cloud Build and apply the Kubernetes manifests.
#
#   APP_HOSTNAME=app.example.com ops/m5-deploy.sh build
#   APP_HOSTNAME=app.example.com ops/m5-deploy.sh apply
#   ops/m5-deploy.sh render     # print the final YAML without touching the cluster
#
# build: Cloud Build builds linux/amd64 images (a Mac would otherwise push arm64) and pushes them tagged
#        with the git SHA, never "latest".
# apply: fills the ${VARS} in k8s/*.yaml and applies them, then waits for the rollouts.
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
KUBECTL="${KUBECTL:-kubectl}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export PROJECT_ID="${PROJECT:-occurrence-desk-2893}"
export REGION="${REGION:-us-central1}"
export BUCKET="${BUCKET:-occdesk-docs-occurrence-desk-2893}"
export GSA_EMAIL="${GSA_EMAIL:-occdesk-gke@$PROJECT_ID.iam.gserviceaccount.com}"
export STATIC_IP_NAME="${STATIC_IP_NAME:-occdesk-ip}"
export IMAGE_TAG="${IMAGE_TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}"
export APP_HOSTNAME="${APP_HOSTNAME:?set APP_HOSTNAME to the public DNS name}"
export REGISTRY="$REGION-docker.pkg.dev/$PROJECT_ID/${AR_REPO:-occurrence-desk}"
VARS='${PROJECT_ID} ${REGION} ${BUCKET} ${GSA_EMAIL} ${STATIC_IP_NAME} ${IMAGE_TAG} ${APP_HOSTNAME} ${REGISTRY}'

render() {
  for f in "$ROOT"/k8s/*.yaml; do
    envsubst "$VARS" <"$f"
    echo "---"
  done
}

case "${1:-}" in
build)
  for svc in api worker; do
    cfg="$(mktemp -t cloudbuild).yaml"
    cat >"$cfg" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "--platform", "linux/amd64", "-f", "infra/docker/$svc.Dockerfile", "--target", "runtime", "-t", "$REGISTRY/$svc:$IMAGE_TAG", "."]
images: ["$REGISTRY/$svc:$IMAGE_TAG"]
EOF
    "$GCLOUD" --project "$PROJECT_ID" builds submit "$ROOT" --config "$cfg" --ignore-file "$ROOT/.dockerignore"
    rm -f "$cfg"
  done
  ;;
apply)
  render | "$KUBECTL" apply -f -
  "$KUBECTL" -n occdesk rollout status deploy/occdesk-api --timeout=300s
  "$KUBECTL" -n occdesk rollout status deploy/occdesk-worker --timeout=300s
  "$KUBECTL" -n occdesk get pods,hpa,pdb,ingress,managedcertificate
  ;;
render)
  render
  ;;
*)
  echo "usage: $0 build|apply|render" >&2
  exit 2
  ;;
esac
