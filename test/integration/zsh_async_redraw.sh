#!/usr/bin/env bash
set -euo pipefail

if ! command -v zsh >/dev/null 2>&1; then
  printf 'skip zsh async redraw integration: zsh not found\n' >&2
  exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip zsh async redraw integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-zsh-async-$$.sock"
redraw_file="/tmp/shisa-zsh-async-redraw-$$"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$sock" "$redraw_file"
}
trap cleanup EXIT

ruby - "$sock" <<'RUBY' &
require "socket"

sock = ARGV.fetch(0)
File.unlink(sock) if File.exist?(sock)
server = UNIXServer.new(sock)
seen_initial = false
loop do
  conn = server.accept
  begin
    header = conn.read(4)
    next unless header && header.bytesize == 4
    length = header.unpack1("N")
    payload = conn.read(length)
    next unless payload && payload.bytesize == length
    if !seen_initial
      abort("expected render request") unless payload.include?('"op":"render"')
      seen_initial = true
      response = '{"v":2,"prompt":"pending> ","right_prompt":null,"redraw_token":"pending"}'
    else
      abort("expected render_continue request") unless payload.include?('"op":"render_continue"')
      response = '{"v":2,"prompt":"ready> ","right_prompt":null,"redraw_token":null}'
    end
    conn.write([response.bytesize].pack("N"))
    conn.write(response)
    break if seen_initial && payload.include?('"op":"render_continue"')
  rescue Errno::EPIPE, Errno::ECONNRESET, IOError
    # Prompt requests enforce a 5 ms deadline; keep accepting a retry if this
    # lightweight fake server loses a scheduling race.
  ensure
    conn.close rescue nil
  end
end
server.close
RUBY
server_pid=$!

for _ in {1..100}; do
  [[ -S "$sock" ]] && break
  sleep 0.01
done

[[ -S "$sock" ]] || {
  printf 'zsh async redraw fake socket not ready\n' >&2
  exit 1
}

SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" SHISA_ASYNC_SELF_PIPE=0 \
  SHISA_ASYNC_CONTINUE_INTERVAL_SECONDS=0.001 SHISA_ASYNC_CONTINUE_ATTEMPTS=20 \
  SHISA_TEST_REDRAW_FILE="$redraw_file" zsh -fc '
    source init/shisa.zsh
    shisa_async_redraw() { print -rn -- redraw >"${SHISA_TEST_REDRAW_FILE}"; }
    prompt=$(shisa_prompt_render)
    [[ ${prompt} == *pending* ]] || exit 1
    for _ in {1..100}; do
      [[ -f ${SHISA_TEST_REDRAW_FILE} ]] && exit 0
      sleep 0.01
    done
    exit 1
  '

[[ $(<"$redraw_file") == redraw ]]
printf 'zsh async redraw: ok\n'
