#!/usr/bin/env bash
# Manual, evidence-producing prompt performance suite. It intentionally does
# not run in hosted CI: wall-clock prompt latency is useful only with the host,
# repository, command, and raw samples that produced it.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo="$root"
out_dir="$root/bench-results/perf-$(date -u +%Y%m%dT%H%M%SZ)"
enforce=0
runs="${SHISA_PERF_RUNS:-100}"
warmup="${SHISA_PERF_WARMUP:-20}"
client_budget_ms="${SHISA_PERF_CLIENT_P99_BUDGET_MS:-10}"
daemon_budget_us="${SHISA_PERF_DAEMON_P99_BUDGET_US:-2000}"
cold_budget_ms="${SHISA_PERF_COLD_P99_BUDGET_MS:-150}"
recovery_budget_ms="${SHISA_PERF_RECOVERY_P99_BUDGET_MS:-50}"

usage() {
  cat >&2 <<'EOF'
usage: scripts/perf-suite.sh [--repo PATH] [--out-dir DIR] [--enforce]

Use --repo with a checked-out, real large repository (for example a pinned
nixpkgs or Chromium checkout). Without it, the Shisa repository is measured
only to validate the harness; its result is not a big-repo baseline.

--enforce compares local results with SHISA_PERF_*_BUDGET_* values. It never
runs in hosted CI.
EOF
}

while (($#)); do
  case "$1" in
    --repo)
      repo="${2:?--repo needs a path}"
      shift 2
      ;;
    --out-dir)
      out_dir="${2:?--out-dir needs a path}"
      shift 2
      ;;
    --enforce)
      enforce=1
      shift
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
    printf 'perf-suite: missing required command: %s\n' "$1" >&2
    exit 127
  }
}

need git
need hyperfine
need jq
need python3
need zig

repo="$(cd "$repo" && pwd)"
git -C "$repo" rev-parse --is-inside-work-tree >/dev/null
mkdir -p "$out_dir"

(cd "$root" && zig build release)
shisa="$root/zig-out/bin/shisa"
shisad="$root/zig-out/bin/shisad"
tmp="$(mktemp -d -t shisa-perf-suite-XXXXXX)"
sock="$tmp/shisa.sock"
log="$tmp/shisad.log"

cleanup() {
  if [[ -n "${daemon_pid:-}" ]]; then
    kill "$daemon_pid" >/dev/null 2>&1 || true
    wait "$daemon_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

"$shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'perf-suite: daemon socket not ready\n' >&2
  exit 1
}

prompt=("$shisa" prompt --socket "$sock" --shell zsh --cwd "$repo" --cols 80 --rows 24 --no-async)
prompt_command="$shisa prompt --socket $sock --shell zsh --cwd $repo --cols 80 --rows 24 --no-async"
"${prompt[@]}" >/dev/null
"$shisad" --metrics --socket "$sock" >"$out_dir/metrics-warm.json"

# 1. Client process + socket round trip. This is the user-visible command.
hyperfine --shell=none --warmup "$warmup" --runs "$runs" \
  --export-json "$out_dir/client-roundtrip.json" \
  "$prompt_command" >/dev/null

# 2. Daemon render. The sample value is server-side elapsed_us from framed
# requests, so it excludes client process startup while retaining request parse,
# cache lookup, render, and response serialization.
python3 - "$sock" "$repo" "$runs" "$warmup" >"$out_dir/daemon-render.json" <<'PY'
import json
import math
import socket
import struct
import sys

sock_path, cwd, runs, warmup = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])

def receive_exact(conn, count):
    chunks = []
    while count:
        chunk = conn.recv(count)
        if not chunk:
            raise RuntimeError("daemon closed the connection")
        chunks.append(chunk)
        count -= len(chunk)
    return b"".join(chunks)

def render(index):
    payload = json.dumps({
        "v": 1, "op": "render", "cwd": cwd, "exit": 0, "jobs": 0,
        "duration_ms": 0, "shell": "zsh", "cols": 80, "rows": 24,
        "tty": None, "color_caps": "truecolor", "glyph_caps": "unicode",
        "user_id": None, "session": None, "request_id": f"perf-{index}",
        "no_async": True,
    }).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(sock_path)
        conn.sendall(struct.pack(">I", len(payload)) + payload)
        size = struct.unpack(">I", receive_exact(conn, 4))[0]
        response = json.loads(receive_exact(conn, size))
    if "error" in response:
        raise RuntimeError(response["error"])
    return response["elapsed_us"]

for index in range(warmup):
    render(index)
samples = sorted(render(index + warmup) for index in range(runs))
p99_index = max(0, math.ceil(len(samples) * 0.99) - 1)
print(json.dumps({"runs": runs, "warmup": warmup, "unit": "us", "samples": samples,
                  "mean_us": sum(samples) / len(samples), "p99_us": samples[p99_index],
                  "max_us": samples[-1]}, indent=2))
PY

# 3. Cold render in the selected large-repository fixture. A fresh daemon is
# started per hyperfine sample, avoiding an accidental warm cache.
hyperfine --warmup 0 --runs "$runs" \
  --export-json "$out_dir/cold-large-repo.json" \
  "bash $root/scripts/perf-cold-render.sh $repo" >/dev/null

# 4. Cache invalidation and recovery. Reload changes the daemon's cache key,
# then this measures the next client render. This is deliberately distinct from
# the cold-daemon case and leaves the selected repository untouched.
python3 - "$sock" <<'PY'
import json
import socket
import struct
import sys

payload = json.dumps({"v": 1, "op": "reload", "request_id": "perf-reload"}).encode()
def receive_exact(conn, count):
    chunks = []
    while count:
        chunk = conn.recv(count)
        if not chunk:
            raise RuntimeError("daemon closed the connection")
        chunks.append(chunk)
        count -= len(chunk)
    return b"".join(chunks)
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
    conn.connect(sys.argv[1])
    conn.sendall(struct.pack(">I", len(payload)) + payload)
    size = struct.unpack(">I", receive_exact(conn, 4))[0]
    response = json.loads(receive_exact(conn, size))
if response.get("reloaded") is not True:
    raise SystemExit(f"perf-suite: reload failed: {response}")
PY
hyperfine --shell=none --warmup "$warmup" --runs "$runs" \
  --export-json "$out_dir/cache-recovery.json" \
  "$prompt_command" >/dev/null

"$shisad" --metrics --socket "$sock" >"$out_dir/metrics-after.json"
SHISA_DEBUG=1 "${prompt[@]}" >/dev/null 2>"$out_dir/trace-after-recovery.log" || true

python3 - "$out_dir" "$repo" "$runs" "$warmup" >"$out_dir/summary.json" <<'PY'
import json
import os
import platform
import subprocess
import sys

out_dir, repo, runs, warmup = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])

def read_json(name):
    with open(os.path.join(out_dir, name), encoding="utf-8") as stream:
        return json.load(stream)

def p99_ms(name):
    samples = sorted(read_json(name)["results"][0]["times"])
    return samples[max(0, (len(samples) * 99 + 99) // 100 - 1)] * 1000

def output(command):
    return subprocess.check_output(command, text=True).strip()

def optional_output(command):
    try:
        return output(command)
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"

summary = {
    "format": "shisa-performance-suite-v1",
    "runs": runs,
    "warmup": warmup,
    "fixture": {
        "path": repo,
        "git_commit": output(["git", "-C", repo, "rev-parse", "HEAD"]),
        "tracked_files": int(output(["git", "-C", repo, "ls-files"]).count("\n") + 1),
        "disk_kib": int(output(["du", "-sk", repo]).split()[0]),
    },
    "host": {
        "system": platform.platform(),
        "machine": platform.machine(),
        "uname": optional_output(["uname", "-a"]),
        "cpu": optional_output(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "python": platform.python_version(),
        "zig": output(["zig", "version"]),
    },
    "cases": {
        "client_process_socket_round_trip": {"p99_ms": p99_ms("client-roundtrip.json")},
        "daemon_render": read_json("daemon-render.json"),
        "cold_large_repo": {"p99_ms": p99_ms("cold-large-repo.json")},
        "cache_invalidation_recovery": {"p99_ms": p99_ms("cache-recovery.json")},
    },
    "artifacts": ["client-roundtrip.json", "daemon-render.json", "cold-large-repo.json",
                  "cache-recovery.json", "metrics-warm.json", "metrics-after.json",
                  "trace-after-recovery.log"],
}
print(json.dumps(summary, indent=2))
PY

client_p99="$(jq -r '.cases.client_process_socket_round_trip.p99_ms' "$out_dir/summary.json")"
daemon_p99="$(jq -r '.cases.daemon_render.p99_us' "$out_dir/summary.json")"
cold_p99="$(jq -r '.cases.cold_large_repo.p99_ms' "$out_dir/summary.json")"
recovery_p99="$(jq -r '.cases.cache_invalidation_recovery.p99_ms' "$out_dir/summary.json")"
printf 'perf-suite: client_p99=%.2fms daemon_p99=%.0fus cold_p99=%.2fms recovery_p99=%.2fms\n' \
  "$client_p99" "$daemon_p99" "$cold_p99" "$recovery_p99"
printf 'perf-suite: artifacts=%s\n' "$out_dir"

if [[ "$enforce" == 1 ]]; then
  over=0
  check() {
    local value="$1" budget="$2" label="$3" unit="$4"
    if awk -v value="$value" -v budget="$budget" 'BEGIN { exit !(value > budget) }'; then
      printf 'perf-suite: %s %.2f%s exceeds %.2f%s\n' "$label" "$value" "$unit" "$budget" "$unit" >&2
      over=1
    fi
  }
  check "$client_p99" "$client_budget_ms" client_p99 ms
  check "$daemon_p99" "$daemon_budget_us" daemon_p99 us
  check "$cold_p99" "$cold_budget_ms" cold_p99 ms
  check "$recovery_p99" "$recovery_budget_ms" recovery_p99 ms
  [[ "$over" == 0 ]] || exit 1
fi
