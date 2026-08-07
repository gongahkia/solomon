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
    echo "user docs gate: no base ref; skipping"
    exit 0
  fi
  changed_files="$(git diff --name-only "$base_ref...$head_ref")"
fi

user_facing_changed=0
docs_changed=0

while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    src/main.zig|src/config.zig|src/daemon/modules/*|src/theme/*|themes/*.toml|init/*|src/ai/*|src/plugin/*|examples/plugins/*)
      user_facing_changed=1
      ;;
  esac
  case "$path" in
    docs/*|README.md|CHANGELOG.md|themes/README.md|examples/*/README.md|examples/*/*/README.md)
      docs_changed=1
      ;;
  esac
done <<EOF
$changed_files
EOF

if [ "$user_facing_changed" -eq 0 ]; then
  echo "user docs gate: ok"
  exit 0
fi

if [ "$docs_changed" -eq 1 ]; then
  echo "user docs gate: ok"
  exit 0
fi

if printf '%s\n' "${SHISA_PR_BODY:-}" | grep -Eiq 'docs?[-_[:space:]]+(not[-_[:space:]]+needed|not[-_[:space:]]+applicable|n/a)'; then
  echo "user docs gate: docs not needed per PR body"
  exit 0
fi

echo "user docs gate: user-facing changes require docs, README, or CHANGELOG updates"
echo "$changed_files" | sed 's/^/changed: /'
exit 1
