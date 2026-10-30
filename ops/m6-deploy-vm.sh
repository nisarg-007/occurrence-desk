#!/usr/bin/env bash
# M6: deploy with health check and automatic rollback.
#
#   GCLOUD=/opt/homebrew/share/google-cloud-sdk/bin/gcloud ops/m6-deploy-vm.sh build
#   GCLOUD=... ops/m6-deploy-vm.sh deploy
#   GCLOUD=... ops/m6-deploy-vm.sh rollback
#
# build:    uploads source and builds images (no downtime).
# deploy:   tags rollback images, starts new stack, health-checks, rolls back on failure.
# rollback: manual rollback to previously tagged images.
set -euo pipefail

GCLOUD="${GCLOUD:-gcloud}"
PROJECT="${PROJECT:-occurrence-desk-2893}"
ZONE="${ZONE:-us-central1-a}"
VM="${VM:-occurrence-desk-vm}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST=/opt/occdesk
COMPOSE="ops/vm/docker-compose.m6.yml"

g() { "$GCLOUD" --project "$PROJECT" "$@"; }
remote() { g compute ssh "$VM" --zone "$ZONE" --command "$1"; }

health_check() {
  local max_retries="${1:-30}"
  local wait="${2:-3}"
  for i in $(seq 1 "$max_retries"); do
    if remote "curl -sf http://localhost:8000/healthz" >/dev/null 2>&1; then
      echo "  Healthy after attempt $i"
      return 0
    fi
    echo "  Attempt $i/$max_retries..."
    sleep "$wait"
  done
  return 1
}

case "${1:-}" in
build)
  echo "==> Building images on VM"
  TAR="$(mktemp -t occdesk-src).tgz"
  COPYFILE_DISABLE=1 tar -C "$ROOT" --exclude=.git --exclude=.venv --exclude='.env*' --exclude=data \
    --exclude=tests/e2e/fixtures --exclude=__pycache__ --exclude=.pytest_cache \
    --exclude=.ruff_cache --exclude=.mypy_cache -czf "$TAR" .
  g compute scp "$TAR" "$VM:/tmp/occdesk-src.tgz" --zone "$ZONE"
  rm -f "$TAR"
  remote "sudo rm -rf $DEST/staging && sudo mkdir -p $DEST/staging \
    && sudo tar -xzf /tmp/occdesk-src.tgz -C $DEST/staging \
    && rm -f /tmp/occdesk-src.tgz \
    && cd $DEST/staging \
    && sudo docker compose -f $COMPOSE build"
  echo "==> Build complete"
  ;;

deploy)
  echo "==> Deploying with rollback safety"
  echo "  Tagging current images as rollback..."
  remote "sudo docker tag occdesk-api:m4 occdesk-api:rollback 2>/dev/null || true && \
          sudo docker tag occdesk-worker:m4 occdesk-worker:rollback 2>/dev/null || true"

  echo "  Starting new containers..."
  remote "cd $DEST/staging && sudo docker compose -f $COMPOSE up -d --force-recreate"

  echo "  Running health check..."
  if health_check 30 3; then
    echo "==> Deploy succeeded"
    remote "sudo rm -rf $DEST/prev && sudo mv $DEST/current $DEST/prev 2>/dev/null || true && \
            sudo mv $DEST/staging $DEST/current"
    # Show readiness
    remote "curl -sf http://localhost:8000/readyz | python3 -m json.tool"
  else
    echo "==> Health check failed, rolling back!"
    remote "sudo docker tag occdesk-api:rollback occdesk-api:m4 && \
            sudo docker tag occdesk-worker:rollback occdesk-worker:m4 && \
            cd $DEST/current && sudo docker compose -f $COMPOSE up -d --force-recreate"
    if health_check 15 3; then
      echo "==> Rollback succeeded"
    else
      echo "==> CRITICAL: Rollback also failed. Manual intervention needed."
      remote "cd $DEST/current && sudo docker compose -f $COMPOSE logs --tail 40"
    fi
    exit 1
  fi
  ;;

rollback)
  echo "==> Manual rollback"
  remote "sudo docker tag occdesk-api:rollback occdesk-api:m4 && \
          sudo docker tag occdesk-worker:rollback occdesk-worker:m4 && \
          cd $DEST/current && sudo docker compose -f $COMPOSE up -d --force-recreate"
  health_check 15 3 && echo "==> Rollback healthy" || echo "==> Rollback unhealthy"
  ;;

*)
  echo "usage: $0 build|deploy|rollback" >&2
  exit 2
  ;;
esac
