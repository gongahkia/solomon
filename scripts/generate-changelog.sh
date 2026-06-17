#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
from="${SHISA_CHANGELOG_FROM:-}"
to="${SHISA_CHANGELOG_TO:-HEAD}"
output=""

usage() {
  cat <<'EOF'
usage: scripts/generate-changelog.sh [--from REV] [--to REV] [--output FILE]

Generate a release changelog from commits and RFC files changed since the last tag.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'generate-changelog: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --from)
      [ "$#" -ge 2 ] || { printf 'generate-changelog: --from needs a value\n' >&2; exit 1; }
      from="$2"
      shift 2
      ;;
    --to)
      [ "$#" -ge 2 ] || { printf 'generate-changelog: --to needs a value\n' >&2; exit 1; }
      to="$2"
      shift 2
      ;;
    --output)
      [ "$#" -ge 2 ] || { printf 'generate-changelog: --output needs a value\n' >&2; exit 1; }
      output="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'generate-changelog: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

need git
need awk
git -C "$repo_root" rev-parse --verify "$to^{commit}" >/dev/null

if [ -z "$from" ]; then
  from="$(git -C "$repo_root" describe --tags --abbrev=0 "$to" 2>/dev/null || true)"
fi

if [ -n "$from" ]; then
  git -C "$repo_root" rev-parse --verify "$from^{commit}" >/dev/null
  range="$from..$to"
  range_label="$from..$to"
else
  range="$to"
  range_label="repository-start..$to"
fi

version="${SHISA_VERSION:-$(awk -F '"' '/\.version =/ { print $2; exit }' "$repo_root/build.zig.zon")}"
release_date="${SHISA_RELEASE_DATE:-$(date +%Y-%m-%d)}"

rfc_paths() {
  if [ -n "$from" ]; then
    git -C "$repo_root" diff --name-only --diff-filter=ACMRT "$from" "$to" -- rfcs |
      awk '/^rfcs\/.*\.md$/ { print }'
  else
    git -C "$repo_root" ls-tree -r --name-only "$to" -- rfcs |
      awk '/^rfcs\/.*\.md$/ { print }'
  fi
}

emit() {
  printf '# Shisa %s - %s\n\n' "$version" "$release_date"
  printf '_Range: %s%s%s_\n\n' '`' "$range_label" '`'

  printf '## Commits\n\n'
  if git -C "$repo_root" log --format=%H "$range" | grep -q .; then
    git -C "$repo_root" log --reverse --no-merges --format='- %s (%h)' "$range"
  else
    printf '%s\n' '- No commits.'
  fi
  printf '\n## RFCs\n\n'

  wrote_rfc=0
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    content="$(git -C "$repo_root" show "$to:$path" 2>/dev/null || true)"
    [ -n "$content" ] || continue
    title="$(printf '%s\n' "$content" | awk '/^# / { sub(/^# /, ""); print; exit }')"
    status="$(printf '%s\n' "$content" | awk '/^- Status: / { sub(/^- Status: /, ""); print; exit }')"
    [ -n "$title" ] || title="$path"
    if [ -n "$status" ]; then
      printf -- '- %s [%s] (%s%s%s)\n' "$title" "$status" '`' "$path" '`'
    else
      printf -- '- %s (%s%s%s)\n' "$title" '`' "$path" '`'
    fi
    wrote_rfc=1
  done < <(rfc_paths | sort -u)

  if [ "$wrote_rfc" -eq 0 ]; then
    printf '%s\n' '- No RFC changes.'
  fi
}

if [ -n "$output" ]; then
  emit > "$output"
else
  emit
fi
