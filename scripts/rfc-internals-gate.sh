#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
missing=0

for rfc in "$repo_root"/rfcs/[0-9][0-9][0-9][0-9]-*.md; do
  [ -f "$rfc" ] || continue
  status="$(awk -F': ' '/^- Status: / { print $2; exit }' "$rfc")"
  case "$status" in
    Accepted|Merged)
      ;;
    *)
      continue
      ;;
  esac

  base="$(basename "$rfc" .md)"
  id="${base%%-*}"
  if ! ls "$repo_root/docs/internals/rfc-$id-"*.md >/dev/null 2>&1; then
    printf 'rfc internals gate: missing docs/internals/rfc-%s-*.md for %s\n' "$id" "$rfc" >&2
    missing=1
  fi
done

if [ "$missing" -ne 0 ]; then
  exit 1
fi

echo "rfc internals gate: ok"
