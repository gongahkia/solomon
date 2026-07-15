#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="$ROOT/deploy/helm/shibahama"
VALUES=(--set secrets.existingSecret=shibahama-secrets --set image.repository=shibahama --set image.tag=ci)

mkdir -p "$ROOT/target"
helm lint --strict "$CHART" "${VALUES[@]}"
helm template shibahama "$CHART" "${VALUES[@]}" --namespace shibahama >"$ROOT/target/shibahama-helm.yaml"
rg -q 'kind: PersistentVolumeClaim' "$ROOT/target/shibahama-helm.yaml"
rg -q 'readOnlyRootFilesystem: true' "$ROOT/target/shibahama-helm.yaml"
rg -q 'enableServiceLinks: false' "$ROOT/target/shibahama-helm.yaml"
rg -q 'kind: NetworkPolicy' "$ROOT/target/shibahama-helm.yaml"
