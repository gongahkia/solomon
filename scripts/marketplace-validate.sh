#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
index_path="${1:-"$repo_root/marketplace/index.toml"}"
shisa_bin="${SHISA_BIN:-"$repo_root/zig-out/bin/shisa"}"

if [ ! -x "$shisa_bin" ]; then
  zig build debug >/dev/null
fi

awk '
  /^\[\[plugins\]\]/ {
    if (name != "") print name "|" path "|" version
    name = ""; path = ""; version = ""
    next
  }
  /^[[:space:]]*name[[:space:]]*=/ {
    value = $0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/".*$/, "", value); name = value
  }
  /^[[:space:]]*path[[:space:]]*=/ {
    value = $0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/".*$/, "", value); path = value
  }
  /^[[:space:]]*version[[:space:]]*=/ {
    value = $0; sub(/^[^=]*=[[:space:]]*"/, "", value); sub(/".*$/, "", value); version = value
  }
  END {
    if (name != "") print name "|" path "|" version
  }
' "$index_path" | while IFS='|' read -r name path version; do
  if [ -z "$name" ] || [ -z "$path" ] || [ -z "$version" ]; then
    echo "invalid catalog entry" >&2
    exit 1
  fi
  target="$repo_root/$path"
  "$shisa_bin" plugin verify "$target"
done
