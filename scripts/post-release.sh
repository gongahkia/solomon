#!/usr/bin/env bash
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

released_tag="${SHISA_RELEASED_TAG:-}"
next_version="${SHISA_NEXT_VERSION:-}"
notice_file="${SHISA_POST_RELEASE_NOTICE:-}"
notify_cmd="${SHISA_NOTIFY_CMD:-}"
dry_run=0
commit_bump=0

usage() {
  cat <<'EOF'
usage: scripts/post-release.sh --released-tag TAG [options]

Bump build.zig.zon to the next dev version and prepare post-release channel copy.

Options:
  --next-version VERSION  Version to write. Default: next patch with -dev suffix.
  --notice-file FILE      Announcement markdown output. Default: dist/post-release-TAG.md.
  --notify-cmd CMD        Executable called with the notice file path.
  --commit                Commit the version bump.
  --dry-run               Print planned edits and write notice to temp storage.
EOF
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'post-release: missing required command: %s\n' "$1" >&2
    exit 1
  }
}

current_version() {
  awk -F '"' '/\.version =/ { print $2; exit }' "$repo_root/build.zig.zon"
}

default_next_version() {
  local released="${1#v}"
  if [[ "$released" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)([-+].*)?$ ]]; then
    printf '%s.%s.%s-dev\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" "$((BASH_REMATCH[3] + 1))"
    return
  fi
  printf 'post-release: cannot infer next version from tag: %s\n' "$1" >&2
  exit 1
}

write_notice() {
  local path="$1"
  mkdir -p "$(dirname "$path")"
  cat > "$path" <<EOF
# Post-release: $released_tag

Release: $released_tag
Next development version: $next_version

## Channel Copy

Shisa $released_tag is out. Release notes and signed artifacts are on GitHub Releases.

## Notify

- GitHub Discussions or release thread
- Project chat
- Social post
- Downstream packaging maintainers
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --released-tag)
      [ "$#" -ge 2 ] || { printf 'post-release: --released-tag needs a value\n' >&2; exit 1; }
      released_tag="$2"
      shift 2
      ;;
    --next-version)
      [ "$#" -ge 2 ] || { printf 'post-release: --next-version needs a value\n' >&2; exit 1; }
      next_version="$2"
      shift 2
      ;;
    --notice-file)
      [ "$#" -ge 2 ] || { printf 'post-release: --notice-file needs a value\n' >&2; exit 1; }
      notice_file="$2"
      shift 2
      ;;
    --notify-cmd)
      [ "$#" -ge 2 ] || { printf 'post-release: --notify-cmd needs a value\n' >&2; exit 1; }
      notify_cmd="$2"
      shift 2
      ;;
    --commit)
      commit_bump=1
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
    *)
      printf 'post-release: unknown arg: %s\n' "$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

need awk
need git
need mktemp
need perl

[ -n "$released_tag" ] || { printf 'post-release: --released-tag is required\n' >&2; exit 1; }
[ -n "$next_version" ] || next_version="$(default_next_version "$released_tag")"
[ -n "$notice_file" ] || notice_file="$repo_root/dist/post-release-$released_tag.md"
if [ "$dry_run" -eq 1 ] && [ -z "${SHISA_POST_RELEASE_NOTICE:-}" ]; then
  notice_file="$(mktemp)"
fi

old_version="$(current_version)"
if [ "$dry_run" -eq 0 ] && [ -n "$(git status --porcelain)" ]; then
  printf 'post-release: worktree must be clean\n' >&2
  exit 1
fi

write_notice "$notice_file"

if [ "$dry_run" -eq 1 ]; then
  printf 'would bump build.zig.zon: %s -> %s\n' "$old_version" "$next_version"
  printf 'notice: %s\n' "$notice_file"
  if [ -n "$notify_cmd" ]; then
    printf 'would run: %s %s\n' "$notify_cmd" "$notice_file"
  fi
  exit 0
fi

NEXT_VERSION="$next_version" perl -0pi -e 's/(\.version\s*=\s*")[^"]+(")/$1$ENV{NEXT_VERSION}$2/' "$repo_root/build.zig.zon"
if [ "$(current_version)" != "$next_version" ]; then
  printf 'post-release: failed to update build.zig.zon\n' >&2
  exit 1
fi

if [ -n "$notify_cmd" ]; then
  "$notify_cmd" "$notice_file"
else
  cat "$notice_file"
fi

if [ "$commit_bump" -eq 1 ]; then
  git add build.zig.zon "$notice_file"
  git commit -m "Bump development version to $next_version"
fi
