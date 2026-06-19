#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work_dir="${SHISA_REPRO_WORK_DIR:-$(mktemp -d "${TMPDIR:-/tmp}/shisa-repro.XXXXXX")}"
target="${SHISA_REPRO_TARGET:-}"
epoch="${SOURCE_DATE_EPOCH:-$(git -C "$repo_root" log -1 --format=%ct)}"

cleanup() {
  if [ -z "${SHISA_REPRO_WORK_DIR:-}" ]; then
    rm -rf "$work_dir"
  fi
}
trap cleanup EXIT

hash_outputs() {
  local prefix="$1"
  local output="$2"
  : > "$output"
  for bin in shisa shisad shisa-supervisor; do
    [ -f "$prefix/bin/$bin" ] || {
      printf 'reproducibility-check: missing %s\n' "$prefix/bin/$bin" >&2
      exit 1
    }
    local digest
    digest="$(shasum -a 256 "$prefix/bin/$bin" | awk '{print $1}')"
    printf '%s  %s\n' "$digest" "$bin" >> "$output"
  done
}

build_once() {
  local name="$1"
  local prefix="$work_dir/out"
  local cache="$work_dir/cache"
  local global_cache="$work_dir/global-cache"
  local args=(
    build release
    --cache-dir "$cache"
    --global-cache-dir "$global_cache"
    --seed 0
    --build-id=none
    --prefix "$prefix"
    --summary all
  )
  if [ -n "$target" ]; then
    args+=("-Dtarget=$target" "-Dcpu=baseline")
  fi
  rm -rf "$prefix" "$cache" "$global_cache"
  (
    cd "$repo_root"
    SOURCE_DATE_EPOCH="$epoch" LC_ALL=C TZ=UTC zig "${args[@]}"
  )
  hash_outputs "$prefix" "$work_dir/$name.sha256"
}

build_once first
build_once second

if ! diff -u "$work_dir/first.sha256" "$work_dir/second.sha256"; then
  printf 'reproducibility-check: repeated release builds produced different hashes\n' >&2
  exit 1
fi

cat "$work_dir/first.sha256"
