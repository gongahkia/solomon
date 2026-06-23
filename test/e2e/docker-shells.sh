#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
matrix="${SHISA_DOCKER_E2E_MATRIX:-$root/test/e2e/docker-matrix.tsv}"
filter="${SHISA_DOCKER_E2E_FILTER:-}"
zig_version="${SHISA_DOCKER_E2E_ZIG_VERSION:-0.15.2}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'docker-e2e: missing required command: %s\n' "$1" >&2
    exit 127
  }
}

run_in_image() {
  local distro="$1"
  local image="$2"
  local shells="$3"
  local platform="$4"
  local docker_run=(docker run --rm)
  if [[ -n "$platform" ]]; then
    docker_run+=(--platform "$platform")
  fi
  "${docker_run[@]}" \
    -e SHISA_E2E_DISTRO="$distro" \
    -e SHISA_E2E_SHELLS="$shells" \
    -v "$root:/src" \
    -w /src \
    "$image" \
    bash test/e2e/inside-docker-shells.sh
}

need docker
docker info >/dev/null

while IFS=$'\t' read -r distro image dockerfile shells platform; do
  [[ -n "${distro:-}" && "${distro:0:1}" != "#" ]] || continue
  if [[ -n "$filter" && "$distro" != "$filter" ]]; then
    continue
  fi
  printf 'docker-e2e: build %s\n' "$distro"
  build_args=(
    --build-arg "ZIG_VERSION=$zig_version"
    -t "$image"
    -f "$root/$dockerfile"
  )
  if [[ -n "${platform:-}" ]]; then
    build_args=(--platform "$platform" "${build_args[@]}")
  fi
  docker build \
    "${build_args[@]}" \
    "$root"
  printf 'docker-e2e: run %s shells=%s\n' "$distro" "$shells"
  run_in_image "$distro" "$image" "$shells" "${platform:-}"
done <"$matrix"
