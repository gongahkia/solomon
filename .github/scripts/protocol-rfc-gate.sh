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
security_changed=0
plugin_api_changed=0
rfc_changed=0

while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    src/proto/*|src/shisa-client.zig|src/daemon/server.zig|docs/protocol/*)
      protocol_changed=1
      ;;
  esac
  case "$path" in
    src/ai/risk.zig|src/daemon/modules/prod_guard.zig|src/plugin/capability.zig|src/plugin/manifest.zig|docs/prod-guard.md|docs/capabilities.md)
      security_changed=1
      ;;
  esac
  case "$path" in
    src/plugin/*|docs/plugin-*|docs/plugins.md|docs/capabilities.md)
      plugin_api_changed=1
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

if [ "${SHISA_REQUIRE_PR_BODY_RFC:-0}" = "1" ]; then
  sensitive_changed=0
  [ "$protocol_changed" -eq 1 ] && sensitive_changed=1
  [ "$security_changed" -eq 1 ] && sensitive_changed=1
  [ "$plugin_api_changed" -eq 1 ] && sensitive_changed=1
  if [ "$sensitive_changed" -eq 1 ]; then
    pr_body="${SHISA_PR_BODY:-}"
    if ! printf '%s\n' "$pr_body" | grep -Eiq '(RFC-[0-9]{4}|rfcs/[0-9]{4}[-a-z0-9]*\.md)'; then
      echo "rfc gate: protocol/security/plugin-api changes require an RFC link in the PR body"
      echo "$changed_files" | sed 's/^/changed: /'
      exit 1
    fi
  fi
fi

echo "protocol rfc gate: ok"
