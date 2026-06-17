#!/usr/bin/env bash
set -euo pipefail

if ! command -v python3 >/dev/null 2>&1; then
  printf 'skip editor bridge integration: python3 not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmp="${TMPDIR:-/tmp}/shisa-editor-bridge-$$"
sock="$tmp/shisa.sock"
log="$tmp/shisad.log"
out="$tmp/shisad.out"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp"
}
trap cleanup EXIT

mkdir -p "$tmp"
"$root/zig-out/bin/shisad" --foreground --socket "$sock" --log "$log" >"$out" 2>&1 &
server_pid=$!

for _ in {1..200}; do
  [[ -S "$sock" ]] && break
  if ! kill -0 "$server_pid" >/dev/null 2>&1; then
    cat "$out" >&2
    exit 1
  fi
  sleep 0.02
done

[[ -S "$sock" ]] || {
  cat "$out" >&2
  printf 'shisad socket not ready\n' >&2
  exit 1
}

python3 - "$sock" <<'PY'
import collections
import json
import socket
import struct
import sys

sock_path = sys.argv[1]

def send_frame(client, value):
    payload = json.dumps(value, separators=(",", ":")).encode()
    client.sendall(struct.pack(">I", len(payload)) + payload)

def read_event(client):
    data = bytearray()
    while not data.endswith(b"\n"):
        chunk = client.recv(1)
        if not chunk:
            raise AssertionError("socket closed before event")
        data.extend(chunk)
    return json.loads(data.decode())

def expect(condition, message):
    if not condition:
        raise AssertionError(message)

def connect_mock_editor(name, topics, backpressure=16):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(sock_path)
    send_frame(client, {
        "v": 1,
        "op": "subscribe",
        "request_id": name,
        "topics": topics,
        "backpressure_limit": backpressure,
    })
    snapshot = read_event(client)
    refs = dict(collections.Counter(topics))
    expect(snapshot["request_id"] == name, f"{name}: request id mismatch")
    expect(snapshot["kind"] == "snapshot", f"{name}: first event not snapshot")
    expect(snapshot["topic"] == "subscription", f"{name}: snapshot topic mismatch")
    expect(snapshot["data"]["refs"] == refs, f"{name}: refs mismatch")
    expect(snapshot["data"]["topics"] == len(refs), f"{name}: topic count mismatch")
    return client

nvim = connect_mock_editor("mock-nvim", ["vcs.summary", "vcs.summary"])
nvim.sendall(b'{"op":"ping","reason":"mock"}\n')
delta = read_event(nvim)
expect(delta["kind"] == "delta", "mock-nvim: missing delta")
expect(delta["topic"] == "vcs.summary", "mock-nvim: delta topic mismatch")
expect(delta["data"]["sequence"] == 1, "mock-nvim: sequence mismatch")
heartbeat = read_event(nvim)
expect(heartbeat["kind"] == "heartbeat", "mock-nvim: missing heartbeat")
nvim.close()

vscode = connect_mock_editor("mock-vscode", ["cloud_ctx", "risk_tier"], 2)
vscode.sendall(b'{"op":"reload"}\n')
readonly = read_event(vscode)
err = readonly["data"]["error"]
expect(readonly["kind"] == "error", "mock-vscode: missing readonly error")
expect(err["code"] == "E_READONLY", "mock-vscode: wrong readonly code")
expect(err["context"]["op"] == "reload", "mock-vscode: readonly op mismatch")
vscode.close()
PY
