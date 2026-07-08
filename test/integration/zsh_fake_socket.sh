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
xdg="/tmp/shisa-zsh-xdg-$$"

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
2.times do |index|
  conn = server.accept
  header = conn.read(4)
  abort("missing frame header") unless header && header.bytesize == 4
  length = header.unpack1("N")
  payload = conn.read(length)
  abort("missing frame payload") unless payload && payload.bytesize == length
  abort("missing right modules") unless payload.include?('"right_modules":["time"]')
  abort("missing tmux pane") unless payload.include?('"tmux_pane":"%42"')
  if index == 0
    abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
    abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
  end
  response = '{"v":1,"prompt":"fake> ","right_prompt":"right-zsh","redraw_token":null}'
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
transient_prompt = "%~ \u276f"

[prompt]
modules = ["cwd"]
right_modules = ["time"]
EOF
cat >"$xdg/shisa/shell.env" <<'EOF'
SHISA_CMD_COMPLETE_BELL=1
SHISA_CMD_COMPLETE_BELL_MODE=osc9
SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=2500
SHISA_CMD_COMPLETE_BELL_MESSAGE=done
EOF

SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" TMUX_PANE="%42" XDG_CONFIG_HOME="$xdg" zsh -fc 'source init/shisa.zsh; print -P "$PROMPT"; shisa_right_prompt_render' >"$out"
grep -F 'fake> ' "$out" >/dev/null
grep -F 'right-zsh' "$out" >/dev/null
zsh -fc 'source init/shisa.zsh; whence shisa_async_self_pipe_setup >/dev/null; whence shisa_async_self_pipe_readable >/dev/null; whence shisa_async_self_pipe_notify >/dev/null; whence shisa_reactive_self_pipe_notify >/dev/null'
fifo_bytes="$(SHISA_ASYNC_SELF_PIPE=0 zsh -fc 'source init/shisa.zsh; fifo=${TMPDIR:-/tmp}/shisa-zsh-fifo-$$; rm -f -- "$fifo"; mkfifo -m 600 -- "$fifo"; exec {SHISA_ASYNC_FD}<>"$fifo"; shisa_async_self_pipe_notify; read -r -k 1 -u ${SHISA_ASYNC_FD} async_byte; shisa_reactive_self_pipe_notify; read -r -k 1 -u ${SHISA_ASYNC_FD} reactive_byte; exec {SHISA_ASYNC_FD}>&-; SHISA_ASYNC_FD=; rm -f -- "$fifo"; printf "%s%s" "$async_byte" "$reactive_byte"')"
[[ "$fifo_bytes" == AR ]]
dispatch_byte="$(SHISA_ASYNC_SELF_PIPE=0 zsh -fc 'source init/shisa.zsh; fifo=${TMPDIR:-/tmp}/shisa-zsh-dispatch-$$; rm -f -- "$fifo"; mkfifo -m 600 -- "$fifo"; exec {SHISA_ASYNC_FD}<>"$fifo"; shisa_async_redraw() { print -rn -- A; }; shisa_reactive_redraw() { print -rn -- R; }; print -rn -- R >&${SHISA_ASYNC_FD}; shisa_async_self_pipe_readable ${SHISA_ASYNC_FD}; exec {SHISA_ASYNC_FD}>&-; SHISA_ASYNC_FD=; rm -f -- "$fifo"')"
[[ "$dispatch_byte" == R ]]
XDG_CONFIG_HOME="$xdg" zsh -fc 'source init/shisa.zsh; [[ ${SHISA_CMD_COMPLETE_BELL} == 1 ]]; [[ ${SHISA_CMD_COMPLETE_BELL_MODE} == osc9 ]]; [[ ${SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS} == 2500 ]]; [[ ${SHISA_CMD_COMPLETE_BELL_MESSAGE} == done ]]'
bell_bytes="$(SHISA_CMD_COMPLETE_BELL=1 SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=1000 zsh -fc 'source init/shisa.zsh; SHISA_LAST_COMMAND="sleep 1"; shisa_cmd_complete_bell 1200' | od -An -tx1 | tr -d ' \n')"
[[ "$bell_bytes" == 07 ]]
long_output="$(SHISA_LONG_RUNNING=1 SHISA_LONG_RUNNING_THRESHOLD_SECONDS=0 zsh -fc 'source init/shisa.zsh; shisa_long_running_start; sleep 0.1; shisa_long_running_stop')"
grep -F 'shisa: command still running' <<<"$long_output" >/dev/null
transient="$(HOME=/tmp SHISA_BIN="$root/zig-out/bin/shisa" XDG_CONFIG_HOME="$xdg" SHISA_INIT_FILE="$root/init/shisa.zsh" zsh -fc 'cd /tmp; source "$SHISA_INIT_FILE"; shisa_transient_prompt_render')"
[[ "$transient" == "~ ❯" ]]
