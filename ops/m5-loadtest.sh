#!/usr/bin/env bash
# M5: generate CPU load so the HPA adds replicas.
#
#   ops/m5-loadtest.sh [seconds] [threads]      # defaults: 240s, 48 threads
#   kubectl -n occdesk get hpa,pods -w          # in a second terminal
#
# The load comes from a short-lived pod INSIDE the cluster. A laptop cannot push enough requests through the
# internet to move CPU past the 50% target; an in-cluster client can. The pod stops by itself when the time is up.
set -euo pipefail

KUBECTL="${KUBECTL:-kubectl}"
DURATION="${1:-240}"
THREADS="${2:-48}"

"$KUBECTL" -n occdesk delete pod loadgen --ignore-not-found --wait=true >/dev/null

"$KUBECTL" -n occdesk run loadgen --image=python:3.12-slim --restart=Never --overrides="$(cat <<EOF
{"spec":{"containers":[{"name":"loadgen","image":"python:3.12-slim",
 "resources":{"requests":{"cpu":"500m","memory":"128Mi"}},
 "command":["python","-c","import threading,time,urllib.request\nend=time.time()+$DURATION\ndef w():\n    while time.time()<end:\n        try: urllib.request.urlopen('http://occdesk-api/healthz',timeout=5).read()\n        except Exception: pass\nfor _ in range($THREADS): threading.Thread(target=w).start()\n"]}]}}
EOF
)"

echo "load running for ${DURATION}s with $THREADS threads. Watch:  kubectl -n occdesk get hpa occdesk-api -w"
