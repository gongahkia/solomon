#!/usr/bin/env bash
set -euo pipefail

if ! command -v bash >/dev/null 2>&1; then
  printf 'skip bash integration: bash not found\n' >&2
  exit 0
fi

if ! command -v ruby >/dev/null 2>&1; then
  printf 'skip bash integration: ruby not found\n' >&2
  exit 0
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
sock="/tmp/shisa-bash-fake-$$.sock"
out="/tmp/shisa-bash-fake-$$.out"
xdg="/tmp/shisa-bash-xdg-$$"

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
abort("missing a11y color caps") unless payload.include?('"color_caps":"none"')
abort("missing a11y glyph caps") unless payload.include?('"glyph_caps":"ascii"')
abort("missing tmux pane") unless payload.include?('"tmux_pane":"%42"')
response = '{"v":1,"prompt":"fake-bash> ","redraw_token":null}'
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

if ((BASH_VERSINFO[0] >= 4)); then
  SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" TMUX_PANE="%42" bash --noprofile --norc -c 'source init/shisa.bash; shisa_precmd; shisa_prompt_render; [[ "$PROMPT_COMMAND" == shisa_prompt_command ]]' >"$out"
else
  SHISA_A11Y=1 SHISA_SOCKET="$sock" SHISA_BIN="$root/zig-out/bin/shisa" TMUX_PANE="%42" bash --noprofile --norc -c 'source init/shisa.bash; shisa_bash_legacy_prompt' >"$out"
fi
grep -F 'fake-bash> ' "$out" >/dev/null

mkdir -p "$xdg/shisa"
cat >"$xdg/shisa/shisa.toml" <<'EOF'
version = 1
transient_prompt = "%~ \u276f"

[prompt]
modules = ["cwd"]
EOF
cat >"$xdg/shisa/shell.env" <<'EOF'
SHISA_CMD_COMPLETE_BELL=1
SHISA_CMD_COMPLETE_BELL_MODE=osc9
SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=2500
SHISA_CMD_COMPLETE_BELL_MESSAGE=done
EOF

bash --noprofile --norc -c 'source init/shisa.bash; shisa_bash_version_at_least_4 4; ! shisa_bash_version_at_least_4 3'
if ((BASH_VERSINFO[0] >= 4)); then
  XDG_CONFIG_HOME="$xdg" bash --noprofile --norc -c 'source init/shisa.bash; [[ ${SHISA_CMD_COMPLETE_BELL} == 1 ]]; [[ ${SHISA_CMD_COMPLETE_BELL_MODE} == osc9 ]]; [[ ${SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS} == 2500 ]]; [[ ${SHISA_CMD_COMPLETE_BELL_MESSAGE} == done ]]'
  bash --noprofile --norc -c 'source init/shisa.bash; EPOCHREALTIME=100.000000; shisa_debug_trap "sleep 1"; EPOCHREALTIME=101.234000; shisa_precmd 7; [[ ${SHISA_LAST_EXIT} == 7 ]]; [[ ${SHISA_LAST_DURATION_MS} == 1234 ]]'
  bash --noprofile --norc -c 'source init/shisa.bash; [[ ${SHISA_ASYNC_KEYSEQ} == "\\C-x\\C-s" ]]; declare -F shisa_async_redraw >/dev/null'
  bash --noprofile --norc -c 'source init/shisa.bash; READLINE_LINE=abc; READLINE_POINT=2; bytes=$(shisa_async_redraw | od -An -tx1 | tr -d " \n"); [[ ${bytes} == 0d1b5b324b ]]; [[ ${READLINE_LINE} == abc ]]; [[ ${READLINE_POINT} == 2 ]]'
  bell_bytes="$(SHISA_CMD_COMPLETE_BELL=1 SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=1000 bash --noprofile --norc -c 'source init/shisa.bash; SHISA_LAST_COMMAND="sleep 1"; shisa_cmd_complete_bell 1200' | od -An -tx1 | tr -d ' \n')"
  [[ "$bell_bytes" == 07 ]]
  bash --noprofile --norc -c 'source init/shisa.bash; SHISA_BASH_RIGHT_PROMPT=1; COLUMNS=12; shisa_bash_right_prompt_render() { printf rb; }; bytes=$(shisa_bash_right_prompt_draw | od -An -tx1 | tr -d " \n"); [[ ${bytes} == 2020202020202020202072620d ]]'
  long_output="$(SHISA_LONG_RUNNING=1 SHISA_LONG_RUNNING_THRESHOLD_SECONDS=0 bash --noprofile --norc -c 'source init/shisa.bash; shisa_long_running_start; sleep 0.1; shisa_long_running_stop')"
  grep -F 'shisa: command still running' <<<"$long_output" >/dev/null
  transient="$(HOME=/tmp SHISA_BIN="$root/zig-out/bin/shisa" XDG_CONFIG_HOME="$xdg" SHISA_INIT_FILE="$root/init/shisa.bash" bash --noprofile --norc -c 'cd /tmp; source "$SHISA_INIT_FILE"; shisa_transient_prompt_render')"
  [[ "$transient" == "~ ❯" ]]
fi
