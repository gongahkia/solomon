#!/usr/bin/env bash
set -euo pipefail

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip render a11y integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-render-a11y-$$.sock"
out="/tmp/shisa-render-a11y-$$.out"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$sock" "$out"
}
trap cleanup EXIT

ruby - "$sock" <<'RUBY' &
require "json"
require "socket"

sock = ARGV.fetch(0)
File.unlink(sock) if File.exist?(sock)
server = UNIXServer.new(sock)
conn = server.accept
header = conn.read(4)
abort("missing frame header") unless header && header.bytesize == 4
length = header.unpack1("N")
payload = conn.read(length)
abort("missing frame payload") unless payload && payload.bytesize == length
abort("missing render op") unless payload.include?('"op":"render"')
abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
arrow = [0x2192].pack("U")
check = [0x2713].pack("U")
response = JSON.generate({v: 1, prompt: "\e[31mprod #{arrow} ok #{check}\e[0m\n", redraw_token: nil})
conn.write([response.bytesize].pack("N"))
conn.write(response)
conn.close
server.close
RUBY
server_pid=$!

for _ in {1..100}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done

[[ -S "$sock" ]] || {
  printf 'fake socket not ready\n' >&2
  exit 1
}

"$root/zig-out/bin/shisa" render --a11y --no-async --shell zsh --cwd /tmp --socket "$sock" >"$out"
grep -F 'prod -> ok ok' "$out" >/dev/null
if grep -F $'\033[31m' "$out" >/dev/null; then
  printf 'render --a11y preserved ANSI styling\n' >&2
  exit 1
fi
