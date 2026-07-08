#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
command -v python3 >/dev/null 2>&1 || {
  printf 'skip plugin reload stress: python3 not found\n' >&2
  exit 0
}
[[ -x "$root/zig-out/bin/shisa" && -x "$root/zig-out/bin/shisad" ]] || {
  printf 'shisa / shisad not built; run zig build first\n' >&2
  exit 1
}

tmp="/tmp/shisa-reload-stress-$$"
home="$tmp/home"
xdg_config="$tmp/config"
xdg_runtime="$tmp/runtime"
xdg_cache="$tmp/cache"
config_dir="$xdg_config/shisa"
plugins_dir="$config_dir/plugins"
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

rm -rf "$tmp"
mkdir -p "$home" "$xdg_runtime" "$xdg_cache" "$plugins_dir"
cat >"$config_dir/shisa.toml" <<'TOML'
version = 1
theme = "plain"

[prompt]
modules = ["cwd"]
TOML
export HOME="$home"
export XDG_CONFIG_HOME="$xdg_config"
export XDG_RUNTIME_DIR="$xdg_runtime"
export XDG_CACHE_HOME="$xdg_cache"

SHISA_COST_REFRESH_INTERVAL_MS=100 "$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >/dev/null 2>&1 &
daemon_pid=$!
for _ in {1..200}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done
[[ -S "$sock" ]] || {
  printf 'plugin reload stress: daemon socket not ready\n' >&2
  cat "$log" >&2 || true
  exit 1
}

rss_before=$(ps -o rss= -p "$daemon_pid" | tr -d ' ')
python3 - "$sock" "$root/zig-out/bin/shisa" <<'PY'
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time

sock = sys.argv[1]
shisa = sys.argv[2]
deadline = time.monotonic() + 5.0
errors = []
lock = threading.Lock()

def read_exact(client, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = client.recv(remaining)
        if not chunk:
            raise RuntimeError("socket closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)

def reload_once(worker, index):
    payload = json.dumps({"v": 1, "op": "reload", "request_id": f"stress-{worker}-{index}"}, separators=(",", ":")).encode()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(sock)
        client.sendall(struct.pack(">I", len(payload)) + payload)
        size = struct.unpack(">I", read_exact(client, 4))[0]
        response = read_exact(client, size)
        if b'"reloaded":true' not in response:
            raise RuntimeError(response.decode("utf-8", "replace"))

def worker(worker_id):
    index = 0
    while time.monotonic() < deadline:
        name = f"stress-{worker_id}"
        subprocess.run([shisa, "plugin", "trust", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([shisa, "plugin", "disable", "demo-plugin"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([shisa, "plugin", "enable", "demo-plugin"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            reload_once(worker_id, index)
        except Exception as exc:
            with lock:
                errors.append(f"worker {worker_id}: {exc}")
            return
        index += 1

threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
if errors:
    raise SystemExit("\n".join(errors))
PY
rss_after=$(ps -o rss= -p "$daemon_pid" | tr -d ' ')
growth=$((rss_after - rss_before))
max_growth=${SHISA_RELOAD_STRESS_MAX_RSS_KB:-65536}
if (( growth > max_growth )); then
  printf 'plugin reload stress: rss grew %d KiB, max %d KiB\n' "$growth" "$max_growth" >&2
  exit 1
fi

printf 'plugin reload stress: ok rss_growth=%dKiB\n' "$growth"
