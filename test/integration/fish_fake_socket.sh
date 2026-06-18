#!/usr/bin/env bash
set -euo pipefail

if ! command -v fish >/dev/null 2>&1; then
  printf 'skip fish integration: fish not found\n' >&2
  exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip fish integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-fish-fake-$$.sock"
out="/tmp/shisa-fish-fake-$$.out"
xdg="/tmp/shisa-fish-xdg-$$"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$sock" "$out" "$xdg"
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
abort("missing fish shell") unless payload.include?('"shell":"fish"')
abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
response = '{"v":1,"prompt":"fake-fish> ","redraw_token":null}'
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

mkdir -p "$xdg"
SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" XDG_CONFIG_HOME="$xdg" fish -c 'source init/shisa.fish; false; fish_prompt' >"$out"
grep -F 'fake-fish> ' "$out" >/dev/null

mkdir -p "$xdg/shisa"
printf 'cached-fish> ' >"$xdg/shisa/last-prompt"
SHISA_SOCKET="/tmp/shisa-fish-missing-$$.sock" SHISA_BIN="$root/zig-out/bin/shisa" XDG_CONFIG_HOME="$xdg" fish -c 'source init/shisa.fish; fish_prompt' >"$out"
grep -F 'cached-fish> ' "$out" >/dev/null

fish -c 'source init/shisa.fish; functions -q fish_prompt; functions -q shisa_async_redraw; emit shisa_async_redraw'
fish -c 'source init/shisa.fish; functions -q shisa_async_redraw; not functions -q fish_async_prompt'
