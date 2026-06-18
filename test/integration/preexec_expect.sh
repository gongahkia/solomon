#!/usr/bin/env bash
set -euo pipefail

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip preexec expect integration: ruby not found\n' >&2
  exit 0
fi

if ! command -v expect >/dev/null 2>&1; then
  printf 'skip preexec expect integration: expect not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-preexec-expect-$$.sock"
export SHISA_BIN="$root/zig-out/bin/shisa"
export SHISA_PREEXEC_SOCKET="$sock"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$sock"
}
trap cleanup EXIT

ruby - "$sock" <<'RUBY' &
require "json"
require "socket"

sock = ARGV.fetch(0)
File.unlink(sock) if File.exist?(sock)
server = UNIXServer.new(sock)
expected = [
  {force: false, allow: false},
  {force: false, allow: false},
  {force: true, allow: true},
]
expected.each do |item|
  conn = server.accept
  header = conn.read(4)
  abort("missing frame header") unless header && header.bytesize == 4
  length = header.unpack1("N")
  payload = conn.read(length)
  abort("missing frame payload") unless payload && payload.bytesize == length
  request = JSON.parse(payload)
  abort("missing preexec kind") unless request["kind"] == "preexec"
  abort("wrong shell") unless request["shell"] == "zsh"
  abort("wrong command") unless request["command"].include?("kubectl delete pod x")
  abort("wrong force") unless request["force"] == item.fetch(:force)
  response = JSON.generate({
    v: 1,
    allow: item.fetch(:allow),
    forced: item.fetch(:force),
    confirm: item.fetch(:allow) ? "" : "prod",
    tier: "prod",
    destructive_pattern: "kubectl delete",
    warning: "",
  })
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

expect <<'EXPECT'
set timeout 5
log_user 0
spawn $env(SHISA_BIN) cloud preexec --socket $env(SHISA_PREEXEC_SOCKET) --shell zsh -- {kubectl delete pod x --context api-prd-use1}
expect {type prod to proceed:}
send "no\r"
expect eof
set status [wait]
if {[lindex $status 3] == 0} {
  puts stderr "preexec deny accepted wrong confirmation"
  exit 1
}
EXPECT

expect <<'EXPECT'
set timeout 5
log_user 0
spawn $env(SHISA_BIN) cloud preexec --socket $env(SHISA_PREEXEC_SOCKET) --shell zsh -- {kubectl delete pod x --context api-prd-use1}
expect {type prod to proceed:}
send "prod\r"
expect eof
set status [wait]
if {[lindex $status 3] != 0} {
  puts stderr "preexec confirm rejected prod confirmation"
  exit 1
}
EXPECT

"$SHISA_BIN" cloud preexec --socket "$SHISA_PREEXEC_SOCKET" --shell zsh --force -- "kubectl delete pod x --context api-prd-use1"
