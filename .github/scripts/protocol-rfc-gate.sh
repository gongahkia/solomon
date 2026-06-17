#!/usr/bin/env bash
set -eu

head_ref="${2:-HEAD}"
base_ref="${1:-${SHISA_BASE_REF:-}}"

if [ -n "${SHISA_CHANGED_FILES:-}" ]; then
  changed_files="$SHISA_CHANGED_FILES"
else
  if [ -z "$base_ref" ]; then
    base_ref="$(git rev-parse HEAD~1 2>/dev/null || true)"
  fi
  if [ -z "$base_ref" ]; then
    echo "protocol rfc gate: no base ref; skipping"
    exit 0
  fi
  changed_files="$(git diff --name-only "$base_ref"... "$head_ref")"
fi

protocol_changed=0
rfc_changed=0

while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    src/proto/*|src/shisa-client.zig|src/daemon/server.zig|docs/protocol/*)
      protocol_changed=1
      ;;
  esac
  case "$path" in
    rfcs/*.md)
      rfc_changed=1
      ;;
  esac
done <<EOF
$changed_files
EOF

if [ "$protocol_changed" -eq 1 ] && [ "$rfc_changed" -eq 0 ]; then
  echo "protocol rfc gate: protocol changes require an rfcs/*.md update"
  echo "$changed_files" | sed 's/^/changed: /'
  exit 1
fi

echo "protocol rfc gate: ok"
