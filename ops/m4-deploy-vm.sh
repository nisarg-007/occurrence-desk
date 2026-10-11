#!/usr/bin/env bash
# M4: build the new images on the VM, then cut over from the M3 api/worker to the M4 stack.
#
#   GCLOUD=/opt/homebrew/share/google-cloud-sdk/bin/gcloud ops/m4-deploy-vm.sh build
#   GCLOUD=... ops/m4-deploy-vm.sh cutover
#
# build:   uploads the source and builds occdesk-api:m4 / occdesk-worker:m4 (no downtime).
# cutover: stops the M3 api and worker, starts the M4 stack, waits for /healthz.
# The M3 db, minio and elasticmq containers are left alone; elasticmq still carries the queue.
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT="${PROJECT:-occurrence-desk-2893}"
ZONE="${ZONE:-us-central1-a}"
VM="${VM:-occurrence-desk-vm}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/occdesk-m4

g() { "$GCLOUD" --project "$PROJECT" "$@"; }
remote() { g compute ssh "$VM" --zone "$ZONE" --command "$1"; }

case "${1:-}" in
build)
  TAR="$(mktemp -t occdesk-src).tgz"
  COPYFILE_DISABLE=1 tar -C "$ROOT" --exclude=.git --exclude=.venv --exclude='.env*' --exclude=data \
    --exclude=tests/e2e/fixtures --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=.mypy_cache -czf "$TAR" .
  g compute scp "$TAR" "$VM:/tmp/occdesk-src.tgz" --zone "$ZONE"
  rm -f "$TAR"
  remote "sudo rm -rf $DEST && sudo mkdir -p $DEST && sudo tar -xzf /tmp/occdesk-src.tgz -C $DEST \
    && rm -f /tmp/occdesk-src.tgz && cd $DEST && sudo docker compose -f ops/vm/docker-compose.m4.yml build"
  ;;
cutover)
  remote "cd $DEST && sudo docker stop occurrence-desk-api-1 occurrence-desk-worker-1 || true \
    && sudo docker compose -f ops/vm/docker-compose.m4.yml up -d \
    && for i in \$(seq 1 30); do curl -fs http://localhost:8000/healthz && echo && exit 0; sleep 3; done; \
       sudo docker compose -f ops/vm/docker-compose.m4.yml logs --tail 40; exit 1"
  ;;
*)
  echo "usage: $0 build|cutover" >&2
  exit 2
  ;;
esac
