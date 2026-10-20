#!/usr/bin/env bash
# M5: show the PodDisruptionBudget doing its job.
#
#   ops/m5-pdb-demo.sh
#
# Asks Kubernetes to evict every api pod one after another, exactly what a node drain or upgrade does. With
# minAvailable: 1 the last eviction is refused, so there is always a pod left serving traffic.
# Uses the eviction API directly so only the api pods are touched, not the whole node.
set -euo pipefail

KUBECTL="${KUBECTL:-kubectl}"
LABEL=app.kubernetes.io/name=occdesk-api

"$KUBECTL" -n occdesk get pdb occdesk-api
echo
for pod in $("$KUBECTL" -n occdesk get pods -l "$LABEL" --field-selector=status.phase=Running -o jsonpath='{.items[*].metadata.name}'); do
  printf 'evicting %s ... ' "$pod"
  if out="$(printf '{"apiVersion":"policy/v1","kind":"Eviction","metadata":{"name":"%s","namespace":"occdesk"}}' "$pod" \
      | "$KUBECTL" create --raw "/api/v1/namespaces/occdesk/pods/$pod/eviction" -f - 2>&1)"; then
    echo "allowed"
  else
    echo "REFUSED: ${out#*: }"
  fi
done
echo
"$KUBECTL" -n occdesk get pdb occdesk-api
"$KUBECTL" -n occdesk get pods -l "$LABEL"
