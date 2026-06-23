#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out_dir="${1:-$root/bench-results}"
commits="${SHISA_GIT_1M_COMMITS:-1000000}"
cold_runs="${SHISA_GIT_1M_COLD_RUNS:-10}"
warm_runs="${SHISA_GIT_1M_WARM_RUNS:-50}"
warmup="${SHISA_GIT_1M_WARMUP:-5}"
repo="${SHISA_GIT_1M_REPO:-/tmp/shisa-git-advanced-1m}"
keep_repo="${SHISA_GIT_1M_KEEP_REPO:-0}"
tmp="$(mktemp -d /tmp/shisa-git-advanced-XXXXXX)"
empty_path="$tmp/empty-path"
warm_sock="$tmp/warm.sock"
warm_log="$tmp/warm.log"
cold_sock="$tmp/cold.sock"
cold_log="$tmp/cold.log"

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
  if [[ -n "${warm_pid:-}" ]]; then
    kill "$warm_pid" >/dev/null 2>&1 || true
    wait "$warm_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
  if [[ "$keep_repo" != "1" && "${SHISA_GIT_1M_REPO:-}" == "" ]]; then
    rm -rf "$repo"
  fi
}
trap cleanup EXIT

generate_repo() {
  rm -rf "$repo"
  mkdir -p "$repo"
  git -C "$repo" init -q -b main
  printf 'git-advanced-1m: fast-import %s commits into %s\n' "$commits" "$repo"
  perl -e '
    my $n = shift @ARGV;
    my $base = 1700000000;
    for (my $i = 1; $i <= $n; $i++) {
      print "commit refs/heads/main\n";
      print "mark :$i\n";
      print "committer Shisa Bench <bench\@shisa.local> " . ($base + $i) . " +0000\n";
      my $msg = "commit $i\n";
      print "data " . length($msg) . "\n$msg";
      print "from :" . ($i - 1) . "\n" if $i > 1;
      my $body = "rev $i\n";
      print "M 100644 inline tracked.txt\n";
      print "data " . length($body) . "\n$body";
    }
  ' "$commits" | git -C "$repo" fast-import --quiet
}

prepare_advanced_state() {
  git -C "$repo" checkout -q -f main
  git -C "$repo" reset -q --hard HEAD
  git -C "$repo" clean -q -fd
  git -C "$repo" remote add origin "$repo" 2>/dev/null || git -C "$repo" remote set-url origin "$repo"
  git -C "$repo" update-ref refs/remotes/origin/main HEAD~1
  git -C "$repo" config branch.main.remote origin
  git -C "$repo" config branch.main.merge refs/heads/main
  printf 'staged\n' >"$repo/staged.txt"
  git -C "$repo" add staged.txt
  printf 'rev %s\nunstaged\n' "$commits" >"$repo/tracked.txt"
  printf 'untracked\n' >"$repo/untracked.txt"
}

wait_for_socket() {
  local sock="$1"
  for _ in {1..200}; do
    [[ -S "$sock" ]] && return 0
    sleep 0.01
  done
  return 1
}

need git
need hyperfine
need jq
need perl
need zig
mkdir -p "$out_dir" "$empty_path"

if [[ ! -d "$repo/.git" ]] || [[ "$(git -C "$repo" rev-list --count HEAD 2>/dev/null || printf 0)" != "$commits" ]]; then
  generate_repo
else
  printf 'git-advanced-1m: reusing %s\n' "$repo"
fi
prepare_advanced_state

(cd "$root" && zig build release)

common_cmd="/usr/bin/env PATH=$(quote "$empty_path") $(quote "$root/zig-out/bin/shisa") prompt --socket"
common_tail="--shell zsh --cwd $(quote "$repo") --cols 80 --rows 24 --no-async"

cold_cmd="rm -f $(quote "$cold_sock"); /usr/bin/env PATH=$(quote "$empty_path") $(quote "$root/zig-out/bin/shisad") --foreground --socket $(quote "$cold_sock") --log $(quote "$cold_log") >/dev/null 2>&1 & pid=\$!; trap 'kill \$pid >/dev/null 2>&1 || true; wait \$pid >/dev/null 2>&1 || true; rm -f $(quote "$cold_sock")' EXIT; i=0; while [ \$i -lt 200 ]; do [ -S $(quote "$cold_sock") ] && break; /bin/sleep 0.01; i=\$((i + 1)); done; [ -S $(quote "$cold_sock") ] || exit 1; out=\$(/usr/bin/env PATH=$(quote "$empty_path") $(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$cold_sock") --shell zsh --cwd $(quote "$repo") --cols 80 --rows 24 --no-async); case \"\$out\" in *git:main\\**) ;; *) printf '%s\n' \"\$out\"; exit 1 ;; esac"

hyperfine \
  --runs "$cold_runs" \
  --warmup 0 \
  --command-name "shisa-git-1m-cold-libgit2" \
  --export-json "$out_dir/git-advanced-1m-cold.json" \
  --export-markdown "$out_dir/git-advanced-1m-cold.md" \
  "$cold_cmd"

/usr/bin/env PATH="$empty_path" "$root/zig-out/bin/shisad" --foreground --socket "$warm_sock" --log "$warm_log" >/dev/null 2>&1 &
warm_pid=$!
wait_for_socket "$warm_sock" || {
  printf 'git-advanced-1m: warm daemon socket not ready\n' >&2
  exit 1
}
/usr/bin/env PATH="$empty_path" "$root/zig-out/bin/shisa" prompt --socket "$warm_sock" --shell zsh --cwd "$repo" --cols 80 --rows 24 --no-async >/dev/null

hyperfine \
  --runs "$warm_runs" \
  --warmup "$warmup" \
  --command-name "shisa-git-1m-warm-libgit2" \
  --export-json "$out_dir/git-advanced-1m-warm.json" \
  --export-markdown "$out_dir/git-advanced-1m-warm.md" \
  "$common_cmd $(quote "$warm_sock") $common_tail"

for name in cold warm; do
  json="$out_dir/git-advanced-1m-$name.json"
  mean_ms=$(jq -r '.results[0].mean * 1000' "$json")
  min_ms=$(jq -r '.results[0].min * 1000' "$json")
  max_ms=$(jq -r '.results[0].max * 1000' "$json")
  printf 'git-advanced-1m: %s mean=%.1fms min=%.1fms max=%.1fms commits=%s repo=%s\n' \
    "$name" "$mean_ms" "$min_ms" "$max_ms" "$commits" "$repo"
done
