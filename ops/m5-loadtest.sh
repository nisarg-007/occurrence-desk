#!/usr/bin/env bash
# M5: generate CPU load against the public URL so the HPA adds replicas, and watch it happen.
#
#   ops/m5-loadtest.sh https://app.example.com [seconds] [parallel]
#
# Hits /healthz, which is CPU-cheap per request but cheap enough to fire in volume; the point is to push
# average CPU over the 50% target. In a second terminal run:  kubectl -n occdesk get hpa,pods -w
set -euo pipefail

URL="${1:?usage: $0 https://host [seconds] [parallel]}"
SECONDS_TOTAL="${2:-180}"
PARALLEL="${3:-40}"
END=$((SECONDS + SECONDS_TOTAL))

echo "load: $PARALLEL workers against $URL/healthz for ${SECONDS_TOTAL}s"
worker() { while ((SECONDS < END)); do curl -s -o /dev/null "$URL/healthz"; done; }
for _ in $(seq 1 "$PARALLEL"); do worker & done
wait
echo "load finished; replicas scale back in after the HPA stabilization window"
