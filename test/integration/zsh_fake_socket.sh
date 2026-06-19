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

[prompt]
modules = ["cwd"]
right_modules = ["time"]
EOF

SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" TMUX_PANE="%42" XDG_CONFIG_HOME="$xdg" zsh -fc 'source init/shisa.zsh; print -P "$PROMPT"; shisa_right_prompt_render' >"$out"
grep -F 'fake> ' "$out" >/dev/null
grep -F 'right-zsh' "$out" >/dev/null
zsh -fc 'source init/shisa.zsh; whence shisa_async_self_pipe_setup >/dev/null; whence shisa_async_self_pipe_readable >/dev/null; whence shisa_async_self_pipe_notify >/dev/null'
bell_bytes="$(SHISA_CMD_COMPLETE_BELL=1 SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=1000 zsh -fc 'source init/shisa.zsh; SHISA_LAST_COMMAND="sleep 1"; shisa_cmd_complete_bell 1200' | od -An -tx1 | tr -d ' \n')"
[[ "$bell_bytes" == 07 ]]
