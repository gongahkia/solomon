#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
tag=""
title=""
from="${SHISA_CHANGELOG_FROM:-}"
target="${SHISA_RELEASE_TARGET:-HEAD}"
notes_file=""
dry_run=0
verify_tag=1

usage() {
  cat <<'EOF'
usage: scripts/create-release-draft.sh --tag TAG [options] [asset...]

Options:
  --title TITLE       Release title. Default: "Shisa TAG".
  --from REV         Changelog start rev. Default: last tag.
  --target REV       Tag/release target. Default: HEAD.
  --notes-file FILE  Use existing notes file instead of generating one.
  --no-verify-tag    Let gh create the tag if it does not exist remotely.
  --dry-run          Print the gh command and generated notes path.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'create-release-draft: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

assets=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --tag)
      [ "$#" -ge 2 ] || { printf 'create-release-draft: --tag needs a value\n' >&2; exit 1; }
      tag="$2"
      shift 2
      ;;
    --title)
      [ "$#" -ge 2 ] || { printf 'create-release-draft: --title needs a value\n' >&2; exit 1; }
      title="$2"
      shift 2
      ;;
    --from)
      [ "$#" -ge 2 ] || { printf 'create-release-draft: --from needs a value\n' >&2; exit 1; }
      from="$2"
      shift 2
      ;;
    --target)
      [ "$#" -ge 2 ] || { printf 'create-release-draft: --target needs a value\n' >&2; exit 1; }
      target="$2"
      shift 2
      ;;
    --notes-file)
      [ "$#" -ge 2 ] || { printf 'create-release-draft: --notes-file needs a value\n' >&2; exit 1; }
      notes_file="$2"
      shift 2
      ;;
    --no-verify-tag)
      verify_tag=0
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        assets+=("$1")
        shift
      done
      ;;
    -*)
      printf 'create-release-draft: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
    *)
      assets+=("$1")
      shift
      ;;
  esac
done

[ -n "$tag" ] || { printf 'create-release-draft: --tag is required\n' >&2; exit 1; }
[ -n "$title" ] || title="Shisa $tag"

need git
need gh
need mktemp
git -C "$repo_root" rev-parse --verify "$target^{commit}" >/dev/null

if [ -n "$notes_file" ]; then
  [ -f "$notes_file" ] || { printf 'create-release-draft: notes file not found: %s\n' "$notes_file" >&2; exit 1; }
else
  notes_file="$(mktemp)"
  changelog_args=(--to "$target" --output "$notes_file")
  [ -z "$from" ] || changelog_args+=(--from "$from")
  "$repo_root/scripts/generate-changelog.sh" "${changelog_args[@]}"
fi

cmd=(gh release create "$tag" --draft --title "$title" --notes-file "$notes_file" --target "$target")
if [ "$verify_tag" -eq 1 ]; then
  cmd+=(--verify-tag)
fi
if [ "${#assets[@]}" -gt 0 ]; then
  cmd+=("${assets[@]}")
fi

if [ "$dry_run" -eq 1 ]; then
  printf 'notes: %s\n' "$notes_file"
  printf 'command:'
  printf ' %q' "${cmd[@]}"
  printf '\n'
  exit 0
fi

"${cmd[@]}"
