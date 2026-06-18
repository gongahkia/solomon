#!/usr/bin/env bash
set -euo pipefail

if ! command -v zsh >/dev/null 2>&1; then
  printf 'skip zsh integration: zsh not found\n' >&2
  exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip zsh integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-zsh-fake-$$.sock"
out="/tmp/shisa-zsh-fake-$$.out"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$sock" "$out"
}
trap cleanup EXIT

ruby - "$sock" <<'RUBY' &
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
abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
response = '{"v":1,"prompt":"fake> ","redraw_token":null}'
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

SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" zsh -fc 'source init/shisa.zsh; print -P "$PROMPT"' >"$out"
grep -F 'fake> ' "$out" >/dev/null
zsh -fc 'source init/shisa.zsh; whence shisa_async_self_pipe_setup >/dev/null; whence shisa_async_self_pipe_readable >/dev/null; whence shisa_async_self_pipe_notify >/dev/null'
