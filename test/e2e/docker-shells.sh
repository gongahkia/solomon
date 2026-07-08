#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
matrix="${SHISA_DOCKER_E2E_MATRIX:-$root/test/e2e/docker-matrix.tsv}"
filter="${SHISA_DOCKER_E2E_FILTER:-}"
zig_version="${SHISA_DOCKER_E2E_ZIG_VERSION:-0.15.2}"
require_hardening="${SHISA_DOCKER_E2E_REQUIRE_HARDENING:-0}"
include_hardening="${SHISA_DOCKER_E2E_INCLUDE_HARDENING:-0}"

usage() {
  cat <<'EOF'
usage: test/e2e/docker-shells.sh [--matrix path] [--filter row] [--include-hardening] [--require-hardening]
EOF
}

while (($#)); do
  case "$1" in
    --matrix)
      matrix="$2"
      shift 2
      ;;
    --filter)
      filter="$2"
      shift 2
      ;;
    --require-hardening)
      require_hardening=1
      shift
      ;;
    --include-hardening)
      include_hardening=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 64
      ;;
  esac
done

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
  local scenario="$5"
  local docker_run=(docker run --rm)
  if [[ -n "$platform" ]]; then
    docker_run+=(--platform "$platform")
  fi
  if [[ "$scenario" != "standard" ]]; then
    docker_run+=(--privileged --security-opt label=disable --tmpfs /tmp:exec,mode=1777)
  fi
  local inside_script="test/e2e/inside-standard-shells.sh"
  if [[ "$scenario" != "standard" ]]; then
    inside_script="test/e2e/inside-hardening-shells.sh"
  fi
  "${docker_run[@]}" \
    -e SHISA_E2E_DISTRO="$distro" \
    -e SHISA_E2E_SHELLS="$shells" \
    -e SHISA_E2E_SCENARIO="$scenario" \
    -e SHISA_E2E_REQUIRE_HARDENING="$require_hardening" \
    -v "$root:/src" \
    -w /src \
    "$image" \
    bash "$inside_script"
}

need docker
docker info >/dev/null

while IFS= read -r row; do
  IFS='|' read -r distro image dockerfile shells platform scenario _ <<<"${row//$'\t'/|}"
  [[ -n "${distro:-}" && "${distro:0:1}" != "#" ]] || continue
  scenario="${scenario:-standard}"
  if [[ "$scenario" != "standard" && "$include_hardening" != "1" && "$matrix" == "$root/test/e2e/docker-matrix.tsv" ]]; then
    continue
  fi
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
  printf 'docker-e2e: run %s shells=%s scenario=%s\n' "$distro" "$shells" "$scenario"
  run_in_image "$distro" "$image" "$shells" "${platform:-}" "$scenario"
done <"$matrix"
