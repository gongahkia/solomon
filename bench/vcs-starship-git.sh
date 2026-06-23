#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$root/bench-results}"
runs="${SHISA_VCS_BENCH_RUNS:-25}"
warmup="${SHISA_VCS_BENCH_WARMUP:-5}"
sock="/tmp/shisa-vcs-bench-$$.sock"
log="/tmp/shisa-vcs-bench-$$.log"
repo_root="${SHISA_VCS_BENCH_REPOS:-}"
keep_repos="${SHISA_VCS_BENCH_KEEP_REPOS:-0}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 127
  }
}

quote() {
  printf '%q' "$1"
}

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$sock" "$log"
  if [[ "$keep_repos" != "1" && -n "${created_repos:-}" ]]; then
    rm -rf "$created_repos"
  fi
}

commit_file() {
  local repo="$1"
  local file="$2"
  local contents="$3"
  printf '%s\n' "$contents" >"$repo/$file"
  git -C "$repo" add "$file"
  git -C "$repo" -c user.name=Bench -c user.email=bench@example.test commit -q -m "add $file"
}

make_repo_set() {
  if [[ -n "$repo_root" ]]; then
    printf '%s\n' "$repo_root"
    return
  fi

  created_repos="$(mktemp -d /tmp/shisa-vcs-bench.XXXXXX)"

  git -C "$created_repos" init -q -b main clean
  commit_file "$created_repos/clean" "file.txt" "clean"

  git -C "$created_repos" init -q -b main dirty
  commit_file "$created_repos/dirty" "file.txt" "base"
  printf '%s\n' "dirty" >"$created_repos/dirty/dirty.txt"

  git -C "$created_repos" init -q -b main worktree-base
  commit_file "$created_repos/worktree-base" "file.txt" "base"
  git -C "$created_repos/worktree-base" worktree add "$created_repos/worktree-linked" -b feature >/dev/null

  printf '%s\n' "$created_repos"
}

add_case() {
  local label="$1"
  local repo="$2"
  args+=(--command-name "shisa-$label" "$(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$sock") --cwd $(quote "$repo") --shell zsh --cols 80 --rows 24 --no-async")
  args+=(--command-name "starship-$label" "cd $(quote "$repo") && starship prompt --status 0 --jobs 0 --cmd-duration 0")
}

need git
need hyperfine
need starship
need zig
mkdir -p "$out_dir"
trap cleanup EXIT

(cd "$root" && zig build release)
"$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!

for _ in {1..100}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'shisad socket not ready\n' >&2
  exit 1
}

repos="$(make_repo_set)"
args=(--warmup "$warmup" --runs "$runs" --export-json "$out_dir/vcs-starship-git.json" --export-markdown "$out_dir/vcs-starship-git.md")
add_case clean "$repos/clean"
add_case dirty "$repos/dirty"
add_case worktree "$repos/worktree-linked"

hyperfine "${args[@]}"
