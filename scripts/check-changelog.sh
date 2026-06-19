#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tag=""
release_date="${SHISA_RELEASE_DATE:-$(date +%Y-%m-%d)}"
changelog="$repo_root/CHANGELOG.md"

usage() {
  cat <<'EOF'
usage: scripts/check-changelog.sh --tag TAG [options]

Checks that CHANGELOG.md has a Keep-a-Changelog release section for TAG.

Options:
  --date YYYY-MM-DD  Release date. Default: today or SHISA_RELEASE_DATE.
  --file FILE        Changelog path. Default: CHANGELOG.md.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tag)
      [ "$#" -ge 2 ] || { printf 'check-changelog: --tag needs a value\n' >&2; exit 1; }
      tag="$2"
      shift 2
      ;;
    --date)
      [ "$#" -ge 2 ] || { printf 'check-changelog: --date needs a value\n' >&2; exit 1; }
      release_date="$2"
      shift 2
      ;;
    --file)
      [ "$#" -ge 2 ] || { printf 'check-changelog: --file needs a value\n' >&2; exit 1; }
      changelog="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'check-changelog: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[ -n "$tag" ] || { printf 'check-changelog: --tag is required\n' >&2; exit 1; }
[ -f "$changelog" ] || { printf 'check-changelog: missing %s\n' "$changelog" >&2; exit 1; }

version="${tag#v}"
heading="## [$version] - $release_date"

IFS= read -r first_line < "$changelog" || first_line=""
[ "$first_line" = '# Changelog' ] || {
  printf 'check-changelog: %s must start with # Changelog\n' "$changelog" >&2
  exit 1
}
grep -Fx '## [Unreleased]' "$changelog" >/dev/null || {
  printf 'check-changelog: %s must keep ## [Unreleased]\n' "$changelog" >&2
  exit 1
}
grep -Fx "$heading" "$changelog" >/dev/null || {
  printf 'check-changelog: missing release heading: %s\n' "$heading" >&2
  exit 1
}

if ! awk -v heading="$heading" '
  $0 == heading { found = 1; next }
  found && /^## / { exit }
  found { print }
' "$changelog" | grep -Eq '^### (Added|Changed|Deprecated|Removed|Fixed|Security)$'; then
  printf 'check-changelog: %s needs a Keep-a-Changelog change-type section\n' "$heading" >&2
  exit 1
fi
