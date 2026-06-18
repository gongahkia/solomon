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
abort("missing pwsh shell") unless payload.include?('"shell":"pwsh"')
abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
response = '{"v":1,"prompt":"fake-pwsh> ","redraw_token":null}'
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

SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; prompt' >"$out"
grep -F 'fake-pwsh> ' "$out" >/dev/null
pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; if (-not (Get-Command Invoke-ShisaRedraw -ErrorAction SilentlyContinue)) { exit 1 }'
pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; if (-not (Get-Command Register-ShisaAsyncFillEvent -ErrorAction SilentlyContinue)) { exit 1 }; if (-not (Get-EventSubscriber -SourceIdentifier Shisa.AsyncFill -ErrorAction SilentlyContinue)) { exit 1 }; $global:SHISA_PWSH_REDRAW_COUNT = 0; function global:Invoke-ShisaRedraw { $global:SHISA_PWSH_REDRAW_COUNT++ }; New-Event -SourceIdentifier Shisa.AsyncFill | Out-Null; Wait-Event -SourceIdentifier Shisa.AsyncFill -Timeout 1 | Out-Null; Start-Sleep -Milliseconds 100; Get-EventSubscriber -SourceIdentifier Shisa.AsyncFill -ErrorAction SilentlyContinue | Unregister-Event; if ($global:SHISA_PWSH_REDRAW_COUNT -lt 1) { exit 1 }'
SHISA_PWSH_ASYNC_EVENT=0 pwsh -NoLogo -NoProfile -Command '. ./init/shisa.ps1; if (Get-EventSubscriber -SourceIdentifier Shisa.AsyncFill -ErrorAction SilentlyContinue) { exit 1 }'
