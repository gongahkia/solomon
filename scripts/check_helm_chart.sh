#!/bin/sh
# SPDX-License-Identifier: Apache-2.0

set -eu

if ! command -v helm >/dev/null 2>&1; then
    echo "helm is required to validate the Solomon chart" >&2
    exit 2
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
chart="$root/charts/solomon"
values="$chart/ci/values.yaml"
rendered="$(mktemp)"
service_monitor="$(mktemp)"
legacy="$(mktemp)"
trap 'rm -f "$rendered" "$service_monitor" "$legacy"' EXIT HUP INT TERM

helm lint "$chart" --values "$values"
helm template solomon "$chart" --namespace solomon --kube-version 1.30.0 --values "$values" > "$rendered"
grep -q 'kind: StatefulSet' "$rendered"
grep -q 'kind: Job' "$rendered"
grep -q 'kind: Deployment' "$rendered"
grep -q 'kind: Ingress' "$rendered"
helm template solomon "$chart" --namespace solomon --kube-version 1.30.0 --values "$values" \
  --set observability.prometheus.serviceMonitor.enabled=true > "$service_monitor"
grep -q 'kind: ServiceMonitor' "$service_monitor"
helm template solomon "$chart" --namespace solomon --kube-version 1.30.0 --values "$values" \
  --set auth.mode=legacy-api-key \
  --set auth.legacyApiKeySecret.name=solomon-server-api-key > "$legacy"
grep -q 'name: server-api-key' "$legacy"
grep -q 'SOLOMON_SERVER_API_KEY_FILE' "$legacy"
