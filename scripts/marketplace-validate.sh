#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
index_path="${1:-"$repo_root/marketplace/index.toml"}"
shisa_bin="${SHISA_BIN:-"$repo_root/zig-out/bin/shisa"}"

if [ ! -x "$shisa_bin" ]; then
  zig build debug >/dev/null
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

awk '
  /^\[\[plugins\]\]/ {
    if (name != "") print name "|" repo "|" version
    name = ""; repo = ""; version = ""
    next
  }
  /^[[:space:]]*name[[:space:]]*=/ {
    value = $0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/".*$/, "", value); name = value
  }
  /^[[:space:]]*repo[[:space:]]*=/ {
    value = $0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/".*$/, "", value); repo = value
  }
  /^[[:space:]]*version[[:space:]]*=/ {
    value = $0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/".*$/, "", value); version = value
  }
  END {
    if (name != "") print name "|" repo "|" version
  }
' "$index_path" | while IFS='|' read -r name repo version; do
  if [ -z "$name" ] || [ -z "$repo" ] || [ -z "$version" ]; then
    echo "invalid marketplace entry" >&2
    exit 1
  fi
  target="$tmp_dir/$name"
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$version" "https://github.com/$repo.git" "$target"
  "$shisa_bin" plugin verify "$target"
done
