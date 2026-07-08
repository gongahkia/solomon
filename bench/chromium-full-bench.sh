#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo=""
out_dir="$root/bench-results"
cold_runs="${SHISA_CHROMIUM_COLD_RUNS:-10}"
warm_runs="${SHISA_CHROMIUM_WARM_RUNS:-50}"
warmup="${SHISA_CHROMIUM_WARMUP:-5}"
tmp=""
warm_pid=""

usage() {
  cat >&2 <<'EOF'
usage: bench/chromium-full-bench.sh --repo /path/to/chromium/src [--out-dir DIR]
EOF
}

while (($#)); do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

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
  if [[ -n "$warm_pid" ]]; then
    kill "$warm_pid" >/dev/null 2>&1 || true
    wait "$warm_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$tmp" ]]; then
    if [[ -f "$tmp/cold.pid" ]]; then
      kill "$(cat "$tmp/cold.pid")" >/dev/null 2>&1 || true
      wait "$(cat "$tmp/cold.pid")" >/dev/null 2>&1 || true
    fi
    rm -rf "$tmp"
  fi
}
trap cleanup EXIT

[[ -n "$repo" ]] || {
  usage
  exit 2
}

need git
need hyperfine
need zig
need du

repo="$(cd "$repo" && pwd)"
git -C "$repo" rev-parse --is-inside-work-tree >/dev/null

mkdir -p "$out_dir"
tmp="$(mktemp -d -t shisa-chromium-full-XXXXXX)"

(cd "$root" && zig build release)

commit="$(git -C "$repo" rev-parse HEAD)"
short_commit="$(git -C "$repo" rev-parse --short=12 HEAD)"
shisa_commit="$(git -C "$root" rev-parse HEAD)"
zig_version="$(zig version)"
du_size="$(du -sh "$repo" | awk '{print $1}')"
tracked_files="$(git -C "$repo" ls-files | wc -l | tr -d ' ')"
host_uname="$(uname -a)"
host_arch="$(uname -m)"
host_ram="$(
  if command -v sysctl >/dev/null 2>&1 && sysctl -n hw.memsize >/dev/null 2>&1; then
    sysctl -n hw.memsize
  elif [[ -r /proc/meminfo ]]; then
    awk '/MemTotal/ {print $2 " KiB"}' /proc/meminfo
  else
    printf 'unknown'
  fi
)"
host_disk="$(df -h "$repo" | tail -n 1 | awk '{print $1 " " $2 " " $4 " free " $6}')"
generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cold_sock="$tmp/cold.sock"
cold_log="$tmp/cold.log"
cold_pid_file="$tmp/cold.pid"
warm_sock="$tmp/warm.sock"
warm_log="$tmp/warm.log"
prompt_cmd="$(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$cold_sock") --shell zsh --cwd $(quote "$repo") --cols 80 --rows 24"
warm_cmd="$(quote "$root/zig-out/bin/shisa") prompt --socket $(quote "$warm_sock") --shell zsh --cwd $(quote "$repo") --cols 80 --rows 24"

cat >"$tmp/cold-prepare.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ -f $(quote "$cold_pid_file") ]]; then
  kill "\$(cat $(quote "$cold_pid_file"))" >/dev/null 2>&1 || true
  wait "\$(cat $(quote "$cold_pid_file"))" >/dev/null 2>&1 || true
  rm -f $(quote "$cold_pid_file")
fi
rm -f $(quote "$cold_sock") $(quote "$cold_log")
$(quote "$root/zig-out/bin/shisad") --foreground --socket $(quote "$cold_sock") --log $(quote "$cold_log") >/dev/null 2>&1 &
echo \$! >$(quote "$cold_pid_file")
for _ in {1..300}; do
  [[ -S $(quote "$cold_sock") ]] && exit 0
  sleep 0.01
done
exit 1
EOF

cat >"$tmp/cold-cleanup.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ -f $(quote "$cold_pid_file") ]]; then
  kill "\$(cat $(quote "$cold_pid_file"))" >/dev/null 2>&1 || true
  wait "\$(cat $(quote "$cold_pid_file"))" >/dev/null 2>&1 || true
  rm -f $(quote "$cold_pid_file")
fi
rm -f $(quote "$cold_sock")
EOF

chmod +x "$tmp/cold-prepare.sh" "$tmp/cold-cleanup.sh"

cold_json="$out_dir/chromium-full-cold.json"
cold_table="$tmp/chromium-full-cold-table.md"
cold_md="$out_dir/chromium-full-cold.md"
warm_json="$out_dir/chromium-full-warm.json"
warm_table="$tmp/chromium-full-warm-table.md"
warm_md="$out_dir/chromium-full-warm.md"

hyperfine \
  --runs "$cold_runs" \
  --warmup 0 \
  --prepare "$tmp/cold-prepare.sh" \
  --cleanup "$tmp/cold-cleanup.sh" \
  --export-json "$cold_json" \
  --export-markdown "$cold_table" \
  --command-name "shisa chromium full cold" \
  "$prompt_cmd"

"$root/zig-out/bin/shisad" --foreground --socket "$warm_sock" --log "$warm_log" >/dev/null 2>&1 &
warm_pid=$!
for _ in {1..300}; do
  [[ -S "$warm_sock" ]] && break
  sleep 0.01
done
[[ -S "$warm_sock" ]] || {
  printf 'warm shisad socket not ready\n' >&2
  exit 1
}
"$root/zig-out/bin/shisa" prompt --socket "$warm_sock" --shell zsh --cwd "$repo" --cols 80 --rows 24 >/dev/null

hyperfine \
  --runs "$warm_runs" \
  --warmup "$warmup" \
  --export-json "$warm_json" \
  --export-markdown "$warm_table" \
  --command-name "shisa chromium full warm" \
  "$warm_cmd"

write_report() {
  local title="$1"
  local json="$2"
  local table="$3"
  local md="$4"

  {
    printf '# %s\n\n' "$title"
    printf 'Generated: `%s`\n\n' "$generated_at"
    printf '## Fixture\n\n'
    printf -- '- Repository: `%s`\n' "$repo"
    printf -- '- Chromium commit: `%s`\n' "$commit"
    printf -- '- Checkout size: `%s`\n' "$du_size"
    printf -- '- Tracked files: `%s`\n\n' "$tracked_files"
    printf '## Host\n\n'
    printf -- '- Arch: `%s`\n' "$host_arch"
    printf -- '- Kernel: `%s`\n' "$host_uname"
    printf -- '- RAM: `%s`\n' "$host_ram"
    printf -- '- Disk: `%s`\n\n' "$host_disk"
    printf '## Build\n\n'
    printf -- '- Zig: `%s`\n' "$zig_version"
    printf -- '- Shisa commit: `%s`\n' "$shisa_commit"
    printf -- '- Chromium short commit: `%s`\n\n' "$short_commit"
    printf '## Hyperfine\n\n'
    cat "$table"
    printf '\n## Raw Hyperfine JSON\n\n```json\n'
    cat "$json"
    printf '\n```\n'
  } >"$md"
}

write_report "Chromium Full Cold" "$cold_json" "$cold_table" "$cold_md"
write_report "Chromium Full Warm" "$warm_json" "$warm_table" "$warm_md"

printf 'wrote %s\n' "$cold_md"
printf 'wrote %s\n' "$warm_md"
