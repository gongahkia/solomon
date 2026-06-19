#!/usr/bin/env bash
set -euo pipefail

if ! command -v nu >/dev/null 2>&1; then
  printf 'skip nu integration: nu not found\n' >&2
  exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip nu integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-nu-fake-$$.sock"
out="/tmp/shisa-nu-fake-$$.out"
xdg="/tmp/shisa-nu-xdg-$$"

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
2.times do
  conn = server.accept
  header = conn.read(4)
  abort("missing frame header") unless header && header.bytesize == 4
  length = header.unpack1("N")
  payload = conn.read(length)
  abort("missing frame payload") unless payload && payload.bytesize == length
  abort("missing nu shell") unless payload.include?('"shell":"nu"')
  abort("missing right modules") unless payload.include?('"right_modules":["time"]')
  abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
  abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
  response = '{"v":1,"prompt":"fake-nu> ","right_prompt":"right-nu","redraw_token":null}'
  conn.write([response.bytesize].pack("N"))
  conn.write(response)
  conn.close
end
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

mkdir -p "$xdg/shisa" "$xdg/nushell"
touch "$xdg/nushell/config.nu" "$xdg/nushell/env.nu"
cat >"$xdg/shisa/shisa.toml" <<'EOF'
version = 1
theme = "plain"

[prompt]
modules = ["cwd"]
right_modules = ["time"]
EOF

SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" XDG_CONFIG_HOME="$xdg" nu --no-config-file -c 'source init/shisa.nu; print (do $env.PROMPT_COMMAND); print (do $env.PROMPT_COMMAND_RIGHT)' >"$out"
grep -F 'fake-nu> ' "$out" >/dev/null
grep -F 'right-nu' "$out" >/dev/null
nu --no-config-file -c 'source init/shisa.nu; if not ("__SHISA_NU_INIT" in $env) { exit 1 }'
nu --no-config-file -c 'source init/shisa.nu; shisa-reprompt; if $env.SHISA_REPROMPT_REQUESTED != "1" { exit 1 }; do --env ($env.config.hooks.pre_prompt | last); if $env.SHISA_REPROMPT_REQUESTED != "0" { exit 1 }'
