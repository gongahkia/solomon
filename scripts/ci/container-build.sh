#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
artifact_dir="${SHIBAHAMA_CONTAINER_ARTIFACT_DIR:-$ROOT/target/container}"
image="${SHIBAHAMA_CONTAINER_IMAGE:-shibahama:ci}"
metadata="$artifact_dir/build-metadata.json"
sbom="$artifact_dir/sbom.spdx.json"

mkdir -p "$artifact_dir"
docker buildx build \
  --load \
  --provenance=mode=max \
  --metadata-file "$metadata" \
  --tag "$image" \
  "$ROOT"

jq -e '."buildx.build.provenance" != null' "$metadata" >/dev/null

docker run --rm --network none \
  --env SYFT_CHECK_FOR_APP_UPDATE=false \
  -v /var/run/docker.sock:/var/run/docker.sock \
  anchore/syft:v1.40.0@sha256:11a68ff5cd49a1579e1f05b061a96edf0a5add161ea5f38d62fc979704c46918 \
  "$image" -o spdx-json >"$sbom"

test -s "$sbom"
