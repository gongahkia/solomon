[[ -n ${ZSH_VERSION:-} ]] || return 0
[[ -z ${__SHISA_ZSH_INIT:-} ]] || return 0

shisa_zsh_version_at_least_5() {
  emulate -L zsh
  local -a version_parts
  version_parts=(${(s:.:)ZSH_VERSION})
  local major=${version_parts[1]:-0}
  local minor=${version_parts[2]:-0}
  major=${major%%[^0-9]*}
  minor=${minor%%[^0-9]*}
  [[ -n ${major} && -n ${minor} ]] || return 1
  (( major > 5 || (major == 5 && minor >= 0) ))
}

shisa_zsh_version_at_least_5 || return 0

typeset -g __SHISA_ZSH_INIT=1
typeset -g SHISA_BIN=${SHISA_BIN:-shisa}
typeset -g SHISA_SOCKET=${SHISA_SOCKET:-}
export SHISA_HOOK_ACTIVE=1

shisa_config_dir() {
  emulate -L zsh
  if [[ -n ${XDG_CONFIG_HOME:-} ]]; then
    print -rn -- "${XDG_CONFIG_HOME}/shisa"
  else
    print -rn -- "${HOME}/.config/shisa"
  fi
}

shisa_shell_env_unquote() {
  emulate -L zsh
  local value=${1}
  local marker="'\\''"
  local quote="'"
  if (( ${#value} >= 2 )) && [[ ${value[1]} == ${quote} && ${value[-1]} == ${quote} ]]; then
    if (( ${#value} == 2 )); then
      value=
    else
      value=${value[2,-2]}
    fi
    value=${value//$marker/$quote}
  fi
  print -rn -- "${value}"
}

shisa_load_shell_prefs() {
  emulate -L zsh
  local path
  path="$(shisa_config_dir)/shell.env"
  [[ -r ${path} ]] || return 0
  local line key value
  while IFS= read -r line || [[ -n ${line} ]]; do
    [[ -n ${line} && ${line[1]} != '#' && ${line} == *=* ]] || continue
    key=${line%%=*}
    value=$(shisa_shell_env_unquote "${line#*=}")
    case ${key} in
      SHISA_ASYNC_FILL|SHISA_CMD_COMPLETE_BELL|SHISA_CMD_COMPLETE_BELL_MODE|SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS|SHISA_CMD_COMPLETE_BELL_MESSAGE)
        typeset -g "${key}=${value}"
        ;;
    esac
  done <"${path}"
}

shisa_load_shell_prefs

shisa_command_context_target_from_config() {
  emulate -L zsh
  local path="$(shisa_config_dir)/shisa.toml"
  [[ -r ${path} ]] || return 0
  local line in_prompt=0
  while IFS= read -r line || [[ -n ${line} ]]; do
    line=${line%%#*}
    [[ -n ${line//[[:space:]]/} ]] || continue
    if [[ ${line} == '[prompt]' ]]; then
      in_prompt=1
      continue
    fi
    if [[ ${line} == \[* ]]; then
      in_prompt=0
      continue
    fi
    (( in_prompt )) || continue
    if [[ ${line} =~ '^[[:space:]]*command_context[[:space:]]*=[[:space:]]*"(right|message|off)"[[:space:]]*$' ]]; then
      print -rn -- "${match[1]}"
      return 0
    fi
  done <"${path}"
}

typeset -g SHISA_LAST_EXIT=0
typeset -g SHISA_LAST_JOBS=0
typeset -g SHISA_LAST_DURATION_MS=0
typeset -g SHISA_LAST_COMMAND=
typeset -g SHISA_PREEXEC_REALTIME=
typeset -g SHISA_ASYNC_FILL=${SHISA_ASYNC_FILL:-1}
typeset -g SHISA_ASYNC_SIGNAL=${SHISA_ASYNC_SIGNAL:-USR1}
typeset -g SHISA_ASYNC_SELF_PIPE=${SHISA_ASYNC_SELF_PIPE:-${SHISA_ASYNC_FILL}}
typeset -g SHISA_ASYNC_PIPE=
typeset -g SHISA_ASYNC_FD=
typeset -g SHISA_ASYNC_BYTE=${SHISA_ASYNC_BYTE:-A}
typeset -g SHISA_REACTIVE_BYTE=${SHISA_REACTIVE_BYTE:-R}
typeset -g SHISA_COMMAND_CONTEXT_BYTE=${SHISA_COMMAND_CONTEXT_BYTE:-C}
typeset -g SHISA_TRANSIENT_PROMPT=${SHISA_TRANSIENT_PROMPT:-1}
typeset -g SHISA_PROD_GUARD=${SHISA_PROD_GUARD:-0}
typeset -g SHISA_PROD_GUARD_FORCE=${SHISA_PROD_GUARD_FORCE:-0}
typeset -g SHISA_A11Y=${SHISA_A11Y:-0}
typeset -g SHISA_CMD_COMPLETE_BELL=${SHISA_CMD_COMPLETE_BELL:-0}
typeset -g SHISA_CMD_COMPLETE_BELL_MODE=${SHISA_CMD_COMPLETE_BELL_MODE:-bell}
typeset -g SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=${SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS:-10000}
if (( ! ${+SHISA_CMD_COMPLETE_BELL_MESSAGE} )); then
  typeset -g SHISA_CMD_COMPLETE_BELL_MESSAGE="shisa: command complete"
fi
typeset -g SHISA_LONG_RUNNING=${SHISA_LONG_RUNNING:-0}
typeset -g SHISA_LONG_RUNNING_THRESHOLD_SECONDS=${SHISA_LONG_RUNNING_THRESHOLD_SECONDS:-30}
typeset -g SHISA_LONG_RUNNING_MESSAGE=${SHISA_LONG_RUNNING_MESSAGE:-shisa: command still running}
typeset -g SHISA_LONG_RUNNING_PID=

shisa_detect_rtl_locale() {
  emulate -L zsh
  local locale=${LC_ALL:-${LC_CTYPE:-${LANG:-}}}
  locale=${locale:l}
  locale=${locale%%.*}
  locale=${locale%%@*}
  locale=${locale%%_*}
  locale=${locale%%-*}
  case ${locale} in
    ar|he|fa|ur|ps|dv|yi) printf '1' ;;
    *) printf '0' ;;
  esac
}

typeset -g SHISA_RTL=${SHISA_RTL:-$(shisa_detect_rtl_locale)}
# Command-context policy belongs to the daemon. Start in the scheduling mode so
# the first asynchronous request can discover an enabled context without
# parsing shisa.toml in the shell process.
typeset -g SHISA_COMMAND_CONTEXT_TARGET=${SHISA_COMMAND_CONTEXT_TARGET:-right}
typeset -g SHISA_COMMAND_CONTEXT_DEBOUNCE_SECONDS=${SHISA_COMMAND_CONTEXT_DEBOUNCE_SECONDS:-0.08}
typeset -g SHISA_COMMAND_CONTEXT_BUFFER=
typeset -g SHISA_COMMAND_CONTEXT_VALUE=
typeset -g SHISA_COMMAND_CONTEXT_GENERATION=0
typeset -g SHISA_COMMAND_CONTEXT_PID=
typeset -g SHISA_COMMAND_CONTEXT_FILE=

zmodload zsh/datetime 2>/dev/null || true

shisa_hook_once() {
  emulate -L zsh
  local hook_name=${1}
  local hook_fn=${2}
  case ${hook_name} in
    precmd)
      typeset -ga precmd_functions
      (( ${precmd_functions[(I)${hook_fn}]} == 0 )) && precmd_functions+=("${hook_fn}")
      ;;
    preexec)
      typeset -ga preexec_functions
      (( ${preexec_functions[(I)${hook_fn}]} == 0 )) && preexec_functions+=("${hook_fn}")
      ;;
    zshexit)
      typeset -ga zshexit_functions
      (( ${zshexit_functions[(I)${hook_fn}]} == 0 )) && zshexit_functions+=("${hook_fn}")
      ;;
  esac
}

shisa_precmd() {
  local last_status=$?
  emulate -L zsh
  SHISA_LAST_EXIT=${last_status}
  SHISA_LAST_JOBS=${#jobstates}
  if [[ -n ${SHISA_PREEXEC_REALTIME:-} && -n ${EPOCHREALTIME:-} ]]; then
    local elapsed_ms=$(( (EPOCHREALTIME - SHISA_PREEXEC_REALTIME) * 1000 ))
    SHISA_LAST_DURATION_MS=${elapsed_ms%.*}
  else
    SHISA_LAST_DURATION_MS=0
  fi
  shisa_long_running_stop
  shisa_cmd_complete_bell "${SHISA_LAST_DURATION_MS}"
}

shisa_hook_once precmd shisa_precmd

shisa_preexec() {
  emulate -L zsh
  local command=${1:-}
  SHISA_LAST_COMMAND=${command}
  SHISA_PREEXEC_REALTIME=${EPOCHREALTIME:-}
  shisa_preexec_guard zsh "${command}" || return $?
  shisa_long_running_start
}

shisa_hook_once preexec shisa_preexec

shisa_preexec_guard() {
  emulate -L zsh
  [[ ${SHISA_PROD_GUARD:-0} == 1 ]] || return 0
  local shell_name=${1}
  local command=${2:-}
  [[ -n ${command} ]] || return 0
  local socket_path
  socket_path=$(shisa_socket_path)
  local -a args
  args=(cloud preexec --socket "${socket_path}" --shell "${shell_name}")
  [[ ${SHISA_PROD_GUARD_FORCE:-0} == 1 ]] && args+=(--force)
  "${SHISA_BIN}" "${args[@]}" -- "${command}"
}

shisa_cmd_complete_bell() {
  emulate -L zsh
  [[ ${SHISA_CMD_COMPLETE_BELL:-0} == 1 ]] || return 0
  [[ -n ${SHISA_LAST_COMMAND:-} ]] || return 0
  local duration_ms=${1:-0}
  local threshold_ms=${SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS:-10000}
  [[ ${duration_ms} == <-> && ${threshold_ms} == <-> ]] || return 0
  (( duration_ms >= threshold_ms )) || return 0
  local message=${SHISA_CMD_COMPLETE_BELL_MESSAGE:-shisa: command complete}
  case ${SHISA_CMD_COMPLETE_BELL_MODE:-bell} in
    bell|terminal) print -rn -- $'\a' ;;
    osc9) print -rn -- $'\e]9;'"${message}"$'\a' ;;
    notify|notify-send) command -v notify-send >/dev/null 2>&1 && notify-send shisa "${message}" >/dev/null 2>&1 || true ;;
    macos|osascript|user-notification) command -v osascript >/dev/null 2>&1 && osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "shisa"' -e 'end run' "${message}" >/dev/null 2>&1 || true ;;
  esac
  return 0
}

shisa_long_running_start() {
  emulate -L zsh
  shisa_long_running_stop
  [[ ${SHISA_LONG_RUNNING:-0} == 1 ]] || return 0
  local threshold=${SHISA_LONG_RUNNING_THRESHOLD_SECONDS:-30}
  [[ ${threshold} == <-> ]] || return 0
  local message=${SHISA_LONG_RUNNING_MESSAGE:-shisa: command still running}
  ( sleep "${threshold}"; print -r -- $'\n'"${message}" ) &
  SHISA_LONG_RUNNING_PID=$!
  disown "${SHISA_LONG_RUNNING_PID}" 2>/dev/null || true
}

shisa_long_running_stop() {
  emulate -L zsh
  local pid=${SHISA_LONG_RUNNING_PID:-}
  SHISA_LONG_RUNNING_PID=
  [[ -n ${pid} ]] || return 0
  kill "${pid}" >/dev/null 2>&1 || true
}

shisa_hook_once zshexit shisa_long_running_stop

setopt prompt_subst
PROMPT='$(shisa_prompt_render)'
RPROMPT='$(shisa_right_prompt_render)'

shisa_async_redraw() {
  emulate -L zsh
  zle reset-prompt 2>/dev/null || true
}

shisa_reactive_redraw() {
  emulate -L zsh
  zle reset-prompt 2>/dev/null || true
  zle -R 2>/dev/null || true
}

shisa_async_self_pipe_readable() {
  emulate -L zsh
  local fd=${1:-${SHISA_ASYNC_FD:-}}
  [[ -n ${fd} ]] || return 0
  local byte command_context=0 reactive=0 redraw=0
  while read -r -k 1 -t 0 -u ${fd} byte 2>/dev/null; do
    redraw=1
    [[ ${byte} == ${SHISA_REACTIVE_BYTE:-R} ]] && reactive=1
    [[ ${byte} == ${SHISA_COMMAND_CONTEXT_BYTE:-C} ]] && command_context=1
  done
  (( redraw )) || return 0
  if (( command_context )); then
    shisa_command_context_apply
    return 0
  fi
  if (( reactive )); then
    shisa_reactive_redraw
  else
    shisa_async_redraw
  fi
}

shisa_async_self_pipe_notify() {
  emulate -L zsh
  if [[ -n ${SHISA_ASYNC_FD:-} ]]; then
    local byte=${SHISA_ASYNC_BYTE:-A}
    print -rn -- "${byte[1]}" >&${SHISA_ASYNC_FD} 2>/dev/null && return 0
  fi
  shisa_async_redraw
}

shisa_reactive_self_pipe_notify() {
  emulate -L zsh
  if [[ -n ${SHISA_ASYNC_FD:-} ]]; then
    local byte=${SHISA_REACTIVE_BYTE:-R}
    print -rn -- "${byte[1]}" >&${SHISA_ASYNC_FD} 2>/dev/null && return 0
  fi
  shisa_reactive_redraw
}

shisa_command_context_notify() {
  emulate -L zsh
  if [[ -n ${SHISA_ASYNC_FD:-} ]]; then
    local byte=${SHISA_COMMAND_CONTEXT_BYTE:-C}
    print -rn -- "${byte[1]}" >&${SHISA_ASYNC_FD} 2>/dev/null && return 0
  fi
  shisa_command_context_apply
}

shisa_command_context_clear() {
  emulate -L zsh
  SHISA_COMMAND_CONTEXT_VALUE=
  if [[ ${SHISA_COMMAND_CONTEXT_TARGET:-off} == message ]]; then
    zle -M '' 2>/dev/null || true
  fi
}

shisa_command_context_apply() {
  emulate -L zsh
  local path=${SHISA_COMMAND_CONTEXT_FILE:-}
  [[ -r ${path} ]] || return 0
  local -a lines
  lines=("${(@f)$(<"${path}")}")
  (( ${#lines} >= 1 )) || return 0
  local generation=${lines[1]}
  [[ ${generation} == ${SHISA_COMMAND_CONTEXT_GENERATION} ]] || return 0
  local value="${(j:\n:)lines[2,-1]}"
  SHISA_COMMAND_CONTEXT_VALUE=${value}
  if [[ ${SHISA_COMMAND_CONTEXT_TARGET:-off} == message ]]; then
    zle -M "${value}" 2>/dev/null || true
  fi
  shisa_reactive_redraw
}

shisa_command_context_schedule() {
  emulate -L zsh
  [[ ${SHISA_COMMAND_CONTEXT_TARGET:-off} == right || ${SHISA_COMMAND_CONTEXT_TARGET:-off} == message ]] || return 0
  [[ -o interactive ]] || return 0
  local buffer=${BUFFER:-}
  [[ ${buffer} == ${SHISA_COMMAND_CONTEXT_BUFFER} ]] && return 0
  SHISA_COMMAND_CONTEXT_BUFFER=${buffer}
  shisa_command_context_clear
  (( SHISA_COMMAND_CONTEXT_GENERATION += 1 ))
  local generation=${SHISA_COMMAND_CONTEXT_GENERATION}
  if [[ -n ${SHISA_COMMAND_CONTEXT_PID:-} ]]; then
    kill "${SHISA_COMMAND_CONTEXT_PID}" >/dev/null 2>&1 || true
  fi
  local path=${SHISA_COMMAND_CONTEXT_FILE:-}
  [[ -n ${path} ]] || return 0
  local socket_path
  socket_path=$(shisa_socket_path)
  (
    sleep "${SHISA_COMMAND_CONTEXT_DEBOUNCE_SECONDS:-0.08}"
    local output
    output=$("${SHISA_BIN}" prompt --command-context --commandline "${buffer}" --shell zsh --socket "${socket_path}" 2>/dev/null) || output=
    local temp="${path}.${generation}"
    {
      print -r -- "${generation}"
      print -r -- "${output}"
    } >"${temp}"
    mv -f -- "${temp}" "${path}" 2>/dev/null || return 0
    shisa_command_context_notify
  ) &!
  SHISA_COMMAND_CONTEXT_PID=$!
}

shisa_command_context_pre_redraw() {
  emulate -L zsh
  shisa_command_context_schedule
}

shisa_async_self_pipe_cleanup() {
  emulate -L zsh
  if [[ -n ${SHISA_ASYNC_FD:-} ]]; then
    zle -F ${SHISA_ASYNC_FD} 2>/dev/null || true
    exec {SHISA_ASYNC_FD}>&- 2>/dev/null || true
    SHISA_ASYNC_FD=
  fi
  if [[ -n ${SHISA_ASYNC_PIPE:-} ]]; then
    rm -f -- "${SHISA_ASYNC_PIPE}" 2>/dev/null || true
    SHISA_ASYNC_PIPE=
  fi
  if [[ -n ${SHISA_COMMAND_CONTEXT_PID:-} ]]; then
    kill "${SHISA_COMMAND_CONTEXT_PID}" >/dev/null 2>&1 || true
    SHISA_COMMAND_CONTEXT_PID=
  fi
  if [[ -n ${SHISA_COMMAND_CONTEXT_FILE:-} ]]; then
    rm -f -- "${SHISA_COMMAND_CONTEXT_FILE}" "${SHISA_COMMAND_CONTEXT_FILE}".*(N) 2>/dev/null || true
    SHISA_COMMAND_CONTEXT_FILE=
  fi
}

shisa_async_self_pipe_setup() {
  emulate -L zsh
  [[ ${SHISA_ASYNC_SELF_PIPE:-1} == 1 ]] || return 0
  [[ -o interactive ]] || return 0
  [[ -z ${SHISA_ASYNC_FD:-} ]] || return 0
  local dir="${TMPDIR:-/tmp}/shisa-${UID:-0}"
  mkdir -p -- "${dir}" 2>/dev/null || return 0
  SHISA_ASYNC_PIPE="${dir}/zsh-redraw-${$}.fifo"
  SHISA_COMMAND_CONTEXT_FILE="${dir}/zsh-context-${$}"
  [[ -p ${SHISA_ASYNC_PIPE} ]] || mkfifo -m 600 -- "${SHISA_ASYNC_PIPE}" 2>/dev/null || return 0
  exec {SHISA_ASYNC_FD}<>"${SHISA_ASYNC_PIPE}" 2>/dev/null || return 0
  zle -F ${SHISA_ASYNC_FD} shisa_async_self_pipe_readable 2>/dev/null || true
}

if [[ ${SHISA_ASYNC_SIGNAL} == USR1 ]]; then
  TRAPUSR1() {
    shisa_async_self_pipe_notify
    return 0
  }
fi

shisa_hook_once zshexit shisa_async_self_pipe_cleanup
shisa_async_self_pipe_setup
zle -N zle-line-pre-redraw shisa_command_context_pre_redraw 2>/dev/null || true

shisa_accept_line() {
  emulate -L zsh
  local transient
  transient=$(shisa_transient_prompt_render)
  [[ -n ${transient} ]] && print -nr -- $'\r\e[2K'"${transient}"
  zle .accept-line
}

if [[ ${SHISA_TRANSIENT_PROMPT} == 1 ]]; then
  zle -N accept-line shisa_accept_line 2>/dev/null || true
fi

shisa_socket_path() {
  emulate -L zsh
  if [[ -n ${SHISA_SOCKET:-} ]]; then
    print -rn -- "${SHISA_SOCKET}"
  elif [[ ${OSTYPE:-} == darwin* ]]; then
    print -rn -- "${HOME}/Library/Caches/shisa/shisa.sock"
  elif [[ -n ${XDG_RUNTIME_DIR:-} ]]; then
    print -rn -- "${XDG_RUNTIME_DIR}/shisa.sock"
  else
    print -rn -- "/run/user/${UID}/shisa.sock"
  fi
}

shisa_prompt_fallback() {
  emulate -L zsh
  print -Pnr -- '%~> '
}

shisa_prompt_render() {
  emulate -L zsh
  local socket_path
  socket_path=$(shisa_socket_path)
  local -a args
  args=(prompt --auto-spawn --shell zsh --exit "${SHISA_LAST_EXIT:-0}" --jobs "${SHISA_LAST_JOBS:-0}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}" --socket "${socket_path}")
  [[ ${SHISA_ASYNC_FILL:-1} == 0 ]] && args+=(--no-async)
  [[ ${SHISA_A11Y:-0} == 1 ]] && args+=(--a11y)
  [[ ${SHISA_RTL:-0} == 1 ]] && args+=(--rtl)
  "${SHISA_BIN}" "${args[@]}"
}

shisa_transient_prompt_render() {
  emulate -L zsh
  [[ ${SHISA_TRANSIENT_PROMPT:-1} == 1 ]] || return 0
  "${SHISA_BIN}" prompt --transient --shell zsh --cwd "${PWD}" 2>/dev/null || true
}

shisa_right_prompt_render() {
  emulate -L zsh
  local socket_path
  socket_path=$(shisa_socket_path)
  [[ -S ${socket_path} ]] || return 0

  local -a args
  args=(prompt --right --shell zsh --exit "${SHISA_LAST_EXIT:-0}" --jobs "${SHISA_LAST_JOBS:-0}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}" --socket "${socket_path}")
  [[ ${SHISA_ASYNC_FILL:-1} == 0 ]] && args+=(--no-async)
  [[ ${SHISA_RTL:-0} == 1 ]] && args+=(--rtl)
  local static
  static=$("${SHISA_BIN}" "${args[@]}" 2>/dev/null) || static=
  local context=${SHISA_COMMAND_CONTEXT_VALUE:-}
  if [[ -n ${static} && -n ${context} && ${SHISA_COMMAND_CONTEXT_TARGET:-off} == right ]]; then
    print -rn -- "${static} ${context}"
  elif [[ -n ${static} ]]; then
    print -rn -- "${static}"
  elif [[ ${SHISA_COMMAND_CONTEXT_TARGET:-off} == right ]]; then
    print -rn -- "${context}"
  fi
}
