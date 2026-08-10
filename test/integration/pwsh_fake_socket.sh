#!/usr/bin/env bash
set -euo pipefail

if ! command -v pwsh >/dev/null 2>&1; then
  printf 'skip pwsh integration: pwsh not found\n' >&2
  exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip pwsh integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-pwsh-fake-$$.sock"
out="/tmp/shisa-pwsh-fake-$$.out"
xdg="/tmp/shisa-pwsh-xdg-$$"

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
  abort("missing pwsh shell") unless payload.include?('"shell":"pwsh"')
  abort("missing right modules") unless payload.include?('"right_modules":["time"]')
  abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
  abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
  response = '{"v":2,"prompt":"fake-pwsh> ","right_prompt":"right-pwsh","redraw_token":null}'
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

mkdir -p "$xdg/shisa"
cat >"$xdg/shisa/shisa.toml" <<'EOF'
version = 1
theme = "plain"

[prompt]
modules = ["cwd"]
right_modules = ["time"]
EOF

SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" XDG_CONFIG_HOME="$xdg" pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; prompt; shisa_right_prompt_render' >"$out"
grep -F 'fake-pwsh> ' "$out" >/dev/null
grep -F 'right-pwsh' "$out" >/dev/null
pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; if (-not (Get-Command Invoke-ShisaRedraw -ErrorAction SilentlyContinue)) { exit 1 }'
pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; if (-not (Get-Command Register-ShisaAsyncFillEvent -ErrorAction SilentlyContinue)) { exit 1 }; if (-not (Get-EventSubscriber -SourceIdentifier Shisa.AsyncFill -ErrorAction SilentlyContinue)) { exit 1 }; $global:SHISA_PWSH_REDRAW_COUNT = 0; function global:Invoke-ShisaRedraw { $global:SHISA_PWSH_REDRAW_COUNT++ }; New-Event -SourceIdentifier Shisa.AsyncFill | Out-Null; Wait-Event -SourceIdentifier Shisa.AsyncFill -Timeout 1 | Out-Null; Start-Sleep -Milliseconds 100; Get-EventSubscriber -SourceIdentifier Shisa.AsyncFill -ErrorAction SilentlyContinue | Unregister-Event; if ($global:SHISA_PWSH_REDRAW_COUNT -lt 1) { exit 1 }'
SHISA_PWSH_ASYNC_EVENT=0 pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; if (Get-EventSubscriber -SourceIdentifier Shisa.AsyncFill -ErrorAction SilentlyContinue) { exit 1 }'
