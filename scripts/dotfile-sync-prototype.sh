#!/usr/bin/env bash
set -euo pipefail

repo=""
config="${XDG_CONFIG_HOME:-$HOME/.config}/shisa/shisa.toml"
remote=""
recipient=""
identity=""

usage() {
  cat <<'USAGE'
usage:
  scripts/dotfile-sync-prototype.sh export --repo PATH --recipient AGE_RECIPIENT [--config FILE] [--remote URL]
  scripts/dotfile-sync-prototype.sh import --repo PATH --identity AGE_IDENTITY_FILE [--config FILE]

Prototype only. Requires age and git. Export encrypts shisa.toml into the repo as shisa.toml.age.
Set SHISA_DOTFILE_SYNC_PUSH=1 to push after export.
USAGE
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'dotfile-sync: missing command: %s\n' "$1" >&2
    exit 1
  }
}

next_arg() {
  [ "$#" -ge 2 ] || {
    printf 'dotfile-sync: %s needs a value\n' "$1" >&2
    exit 1
  }
  printf '%s\n' "$2"
}

parse_common() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --repo)
        repo="$(next_arg "$@")"
        shift 2
        ;;
      --config)
        config="$(next_arg "$@")"
        shift 2
        ;;
      --remote)
        remote="$(next_arg "$@")"
        shift 2
        ;;
      --recipient)
        recipient="$(next_arg "$@")"
        shift 2
        ;;
      --identity)
        identity="$(next_arg "$@")"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf 'dotfile-sync: unknown arg: %s\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
  done
}

init_repo() {
  mkdir -p "$repo"
  if [ ! -d "$repo/.git" ]; then
    git -C "$repo" init
  fi
  if [ -n "$remote" ]; then
    if git -C "$repo" remote get-url origin >/dev/null 2>&1; then
      git -C "$repo" remote set-url origin "$remote"
    else
      git -C "$repo" remote add origin "$remote"
    fi
  fi
}

export_config() {
  [ -n "$repo" ] || { printf 'dotfile-sync: --repo is required\n' >&2; exit 1; }
  [ -n "$recipient" ] || { printf 'dotfile-sync: --recipient is required\n' >&2; exit 1; }
  [ -f "$config" ] || { printf 'dotfile-sync: config not found: %s\n' "$config" >&2; exit 1; }
  need age
  need git
  init_repo
  age -r "$recipient" -o "$repo/shisa.toml.age" "$config"
  {
    printf '# Shisa encrypted dotfile sync prototype\n'
    printf 'config = "shisa.toml.age"\n'
    printf 'updated = "%s"\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$repo/SHISA_DOTFILE_SYNC"
  git -C "$repo" add shisa.toml.age SHISA_DOTFILE_SYNC
  git -C "$repo" commit -m "sync shisa config"
  if [ "${SHISA_DOTFILE_SYNC_PUSH:-0}" = "1" ]; then
    git -C "$repo" push -u origin HEAD
  else
    printf 'dotfile-sync: export committed locally; set SHISA_DOTFILE_SYNC_PUSH=1 to push\n'
  fi
}

import_config() {
  [ -n "$repo" ] || { printf 'dotfile-sync: --repo is required\n' >&2; exit 1; }
  [ -n "$identity" ] || { printf 'dotfile-sync: --identity is required\n' >&2; exit 1; }
  [ -f "$repo/shisa.toml.age" ] || { printf 'dotfile-sync: encrypted config not found: %s\n' "$repo/shisa.toml.age" >&2; exit 1; }
  [ -f "$identity" ] || { printf 'dotfile-sync: identity not found: %s\n' "$identity" >&2; exit 1; }
  need age
  mkdir -p "$(dirname "$config")"
  tmp="$(mktemp "${TMPDIR:-/tmp}/shisa-dotfile.XXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  age -d -i "$identity" -o "$tmp" "$repo/shisa.toml.age"
  install -m 0600 "$tmp" "$config"
  printf 'dotfile-sync: imported %s\n' "$config"
}

[ "$#" -ge 1 ] || { usage >&2; exit 1; }
command_name="$1"
shift
parse_common "$@"

case "$command_name" in
  export) export_config ;;
  import) import_config ;;
  -h|--help) usage ;;
  *) printf 'dotfile-sync: unknown command: %s\n' "$command_name" >&2; usage >&2; exit 1 ;;
esac
