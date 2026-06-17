#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
tag="${SHISA_RELEASE_TAG:-}"
from="${SHISA_CHANGELOG_FROM:-}"
target="${SHISA_RELEASE_TARGET:-HEAD}"
notes_file="${SHISA_RELEASE_NOTES_FILE:-}"
dry_run=0
skip_checks=0
verify_tag=0
assets=()

usage() {
  cat <<'EOF'
usage: scripts/monthly-release.sh [--tag TAG] [options] [asset...]

Runs the local monthly release gate, writes release notes, and creates a GitHub draft release.

Options:
  --tag TAG          Release tag. Default: v<build.zig.zon version>.
  --from REV         Changelog start rev. Default: last tag.
  --target REV       Release target. Default: HEAD.
  --notes-file FILE  Release notes output. Default: dist/release-notes-TAG.md.
  --dry-run          Generate notes in temp storage and print the release command.
  --skip-checks      Skip local Zig checks.
  --verify-tag       Require the tag to already exist remotely.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'monthly-release: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

run_step() {
  printf '==> %s\n' "$*"
  "$@"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tag)
      [ "$#" -ge 2 ] || { printf 'monthly-release: --tag needs a value\n' >&2; exit 1; }
      tag="$2"
      shift 2
      ;;
    --from)
      [ "$#" -ge 2 ] || { printf 'monthly-release: --from needs a value\n' >&2; exit 1; }
      from="$2"
      shift 2
      ;;
    --target)
      [ "$#" -ge 2 ] || { printf 'monthly-release: --target needs a value\n' >&2; exit 1; }
      target="$2"
      shift 2
      ;;
    --notes-file)
      [ "$#" -ge 2 ] || { printf 'monthly-release: --notes-file needs a value\n' >&2; exit 1; }
      notes_file="$2"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-checks)
      skip_checks=1
      shift
      ;;
    --verify-tag)
      verify_tag=1
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
      printf 'monthly-release: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
    *)
      assets+=("$1")
      shift
      ;;
  esac
done

need git
need awk
need zig
need gh
need mktemp
git -C "$repo_root" rev-parse --verify "$target^{commit}" >/dev/null

version="$(awk -F '"' '/\.version =/ { print $2; exit }' "$repo_root/build.zig.zon")"
[ -n "$tag" ] || tag="v$version"

if [ -z "$notes_file" ]; then
  if [ "$dry_run" -eq 1 ]; then
    notes_file="$(mktemp)"
  else
    notes_file="$repo_root/dist/release-notes-$tag.md"
  fi
fi

changelog_args=(--to "$target" --output "$notes_file")
[ -z "$from" ] || changelog_args+=(--from "$from")

if [ "$dry_run" -eq 0 ]; then
  if [ -n "$(git -C "$repo_root" status --porcelain)" ]; then
    printf 'monthly-release: worktree must be clean\n' >&2
    exit 1
  fi
  mkdir -p "$(dirname "$notes_file")"
  if [ "$skip_checks" -eq 0 ]; then
    run_step zig fmt --check "$repo_root/build.zig" "$repo_root/src" "$repo_root/tools"
    run_step zig build schema
    run_step git -C "$repo_root" diff --exit-code docs/protocol/v1.schema.json
    run_step zig build test
    run_step zig build release
  fi
else
  mkdir -p "$(dirname "$notes_file")"
fi

run_step "$repo_root/scripts/generate-changelog.sh" "${changelog_args[@]}"

draft_args=(--tag "$tag" --title "Shisa $tag" --target "$target" --notes-file "$notes_file")
if [ "$verify_tag" -eq 0 ]; then
  draft_args+=(--no-verify-tag)
fi
if [ "$dry_run" -eq 1 ]; then
  draft_args+=(--dry-run)
fi
if [ "${#assets[@]}" -gt 0 ]; then
  draft_args+=("${assets[@]}")
fi

run_step "$repo_root/scripts/create-release-draft.sh" "${draft_args[@]}"
