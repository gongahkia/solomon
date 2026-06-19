#!/usr/bin/env bash
set -eu

head_ref="${2:-HEAD}"
base_ref="${1:-${SHISA_BASE_REF:-}}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'i18n catalog gate: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

need git
need msgcat
need msgfmt
need zig

if [ -n "${SHISA_CHANGED_FILES:-}" ]; then
  changed_files="$SHISA_CHANGED_FILES"
else
  if [ -z "$base_ref" ]; then
    base_ref="$(git rev-parse HEAD~1 2>/dev/null || true)"
  fi
  if [ -z "$base_ref" ]; then
    echo "i18n catalog gate: no base ref; checking generated catalogs only"
    changed_files=""
  else
    changed_files="$(git diff --name-only "$base_ref"... "$head_ref")"
  fi
fi

changed_catalogs=0
while IFS= read -r path; do
  [ -n "$path" ] || continue
  case "$path" in
    i18n/*.pot)
      [ -f "$path" ] || continue
      msgcat --use-first "$path" >/dev/null
      changed_catalogs=1
      printf 'i18n catalog changed: %s\n' "$path"
      ;;
    i18n/*/LC_MESSAGES/*.po)
      [ -f "$path" ] || continue
      msgfmt --check --check-header -o /dev/null "$path"
      changed_catalogs=1
      printf 'i18n catalog changed: %s\n' "$path"
      ;;
  esac
done <<EOF
$changed_files
EOF

zig build i18n-extract
if ! git diff --exit-code -- i18n/shisa.pot i18n/en-US/LC_MESSAGES/shisa.po; then
  echo "i18n catalog gate: generated catalogs are stale; run zig build i18n-extract" >&2
  exit 1
fi

if [ "$changed_catalogs" -eq 1 ]; then
  echo "::warning title=i18n catalog review::Locale catalogs changed; request translation review before merge."
else
  echo "i18n catalog gate: ok"
fi
