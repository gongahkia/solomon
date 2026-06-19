[[ -n ${BASH_VERSION:-} ]] || return 0 2>/dev/null || exit 0
[[ -z ${__SHISA_BASH_INIT:-} ]] || return 0 2>/dev/null || exit 0

__SHISA_BASH_INIT=1
SHISA_BIN=${SHISA_BIN:-shisa}
SHISA_SOCKET=${SHISA_SOCKET:-}

shisa_detect_rtl_locale() {
  local locale=${LC_ALL:-${LC_CTYPE:-${LANG:-}}}
  locale=$(printf '%s' "${locale}" | tr '[:upper:]' '[:lower:]')
  locale=${locale%%.*}
  locale=${locale%%@*}
  locale=${locale%%_*}
  locale=${locale%%-*}
  case ${locale} in
    ar|he|fa|ur|ps|dv|yi) printf '1' ;;
    *) printf '0' ;;
  esac
}

SHISA_RTL=${SHISA_RTL:-$(shisa_detect_rtl_locale)}

shisa_bash_version_at_least_4() {
  local major=${1:-${BASH_VERSINFO[0]:-0}}
  [[ ${major} =~ ^[0-9]+$ ]] || return 1
  ((major >= 4))
}

if ! shisa_bash_version_at_least_4; then
  shisa_bash_legacy_socket_path() {
    if [[ -n ${SHISA_SOCKET:-} ]]; then
      printf '%s' "${SHISA_SOCKET}"
    elif [[ ${OSTYPE:-} == darwin* ]]; then
      printf '%s' "${HOME}/Library/Caches/shisa/shisa.sock"
    elif [[ -n ${XDG_RUNTIME_DIR:-} ]]; then
      printf '%s' "${XDG_RUNTIME_DIR}/shisa.sock"
    else
      printf '%s' "/run/user/${UID}/shisa.sock"
    fi
  }

  shisa_bash_legacy_fallback() {
    local cwd=${PWD}
    if [[ -n ${HOME:-} && ${cwd} == "${HOME}"* ]]; then
      cwd="~${cwd#"${HOME}"}"
    fi
    printf '%s> ' "${cwd}"
  }

  shisa_bash_legacy_prompt() {
    local last_status=$?
    local socket_path
    socket_path=$(shisa_bash_legacy_socket_path)
    local jobs_count
    jobs_count=$(jobs -p 2>/dev/null | wc -l | tr -d ' ')
    local -a rtl_args=()
    [[ ${SHISA_RTL:-0} == 1 ]] && rtl_args+=(--rtl)
    if [[ -S ${socket_path} ]]; then
      if [[ ${SHISA_A11Y:-0} == 1 ]]; then
        "${SHISA_BIN}" prompt --shell bash --cwd "${PWD}" --exit "${last_status}" --jobs "${jobs_count:-0}" --duration-ms 0 --no-async --socket "${socket_path}" --a11y "${rtl_args[@]}" 2>/dev/null && return 0
      else
        "${SHISA_BIN}" prompt --shell bash --cwd "${PWD}" --exit "${last_status}" --jobs "${jobs_count:-0}" --duration-ms 0 --no-async --socket "${socket_path}" "${rtl_args[@]}" 2>/dev/null && return 0
      fi
    fi
    shisa_bash_legacy_fallback
  }

  PS1='$(shisa_bash_legacy_prompt)'
  return 0 2>/dev/null || exit 0
fi

SHISA_LAST_EXIT=0
SHISA_LAST_JOBS=0
SHISA_LAST_DURATION_MS=0
SHISA_LAST_COMMAND=
SHISA_ASYNC_REDRAW=${SHISA_ASYNC_REDRAW:-1}
SHISA_ASYNC_KEYSEQ=${SHISA_ASYNC_KEYSEQ:-'\C-x\C-s'}
SHISA_BASH_RIGHT_PROMPT=${SHISA_BASH_RIGHT_PROMPT:-0}
SHISA_NEXTCMD_KEYSEQ=${SHISA_NEXTCMD_KEYSEQ:-'\C-x\C-n'}
SHISA_NEXTCMD_ACCEPT_KEYSEQ=${SHISA_NEXTCMD_ACCEPT_KEYSEQ:-'\C-i'}
SHISA_NEXTCMD_REJECT_KEYSEQ=${SHISA_NEXTCMD_REJECT_KEYSEQ:-'\e'}
SHISA_NEXTCMD_NEXT_KEYSEQ=${SHISA_NEXTCMD_NEXT_KEYSEQ:-'\e]'}
SHISA_NEXTCMD_SUGGESTION=
SHISA_EXPLAIN_KEYSEQ=${SHISA_EXPLAIN_KEYSEQ:-'\C-x\C-e'}
SHISA_EXPLAIN_LAST_COMMAND=
SHISA_EXPLAIN_LAST_OUTPUT=
SHISA_PROD_GUARD=${SHISA_PROD_GUARD:-0}
SHISA_PROD_GUARD_FORCE=${SHISA_PROD_GUARD_FORCE:-0}
SHISA_AI_RISK_GUARD=${SHISA_AI_RISK_GUARD:-0}
SHISA_A11Y=${SHISA_A11Y:-0}
SHISA_CMD_COMPLETE_BELL=${SHISA_CMD_COMPLETE_BELL:-0}
SHISA_CMD_COMPLETE_BELL_MODE=${SHISA_CMD_COMPLETE_BELL_MODE:-bell}
SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS=${SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS:-10000}
SHISA_CMD_COMPLETE_BELL_MESSAGE=${SHISA_CMD_COMPLETE_BELL_MESSAGE:-shisa: command complete}
SHISA_COMMAND_STARTED=0
SHISA_COMMAND_START_US=
SHISA_IN_PROMPT=0
__SHISA_OLD_PROMPT_COMMAND=${PROMPT_COMMAND:-}

shisa_socket_path() {
  if [[ -n ${SHISA_SOCKET:-} ]]; then
    printf '%s' "${SHISA_SOCKET}"
  elif [[ ${OSTYPE:-} == darwin* ]]; then
    printf '%s' "${HOME}/Library/Caches/shisa/shisa.sock"
  elif [[ -n ${XDG_RUNTIME_DIR:-} ]]; then
    printf '%s' "${XDG_RUNTIME_DIR}/shisa.sock"
  else
    printf '%s' "/run/user/${UID}/shisa.sock"
  fi
}

shisa_prompt_fallback() {
  local cwd=${PWD}
  if [[ -n ${HOME:-} && ${cwd} == "${HOME}"* ]]; then
    cwd="~${cwd#"${HOME}"}"
  fi
  printf '%s> ' "${cwd}"
}

shisa_precmd() {
  local last_status=${1:-$?}
  SHISA_LAST_EXIT=${last_status}
  local count=0
  local job_pid
  while IFS= read -r job_pid; do
    [[ -n ${job_pid} ]] && ((count += 1))
  done < <(jobs -p)
  SHISA_LAST_JOBS=${count}
  local now_us
  if [[ -n ${SHISA_COMMAND_START_US:-} ]] && now_us=$(shisa_epoch_us); then
    if ((now_us >= SHISA_COMMAND_START_US)); then
      SHISA_LAST_DURATION_MS=$(((now_us - SHISA_COMMAND_START_US) / 1000))
    else
      SHISA_LAST_DURATION_MS=0
    fi
  else
    SHISA_LAST_DURATION_MS=0
  fi
  shisa_cmd_complete_bell "${SHISA_LAST_DURATION_MS}"
  SHISA_COMMAND_STARTED=0
  SHISA_COMMAND_START_US=
  return "${last_status}"
}

shisa_epoch_us() {
  local value=${EPOCHREALTIME:-}
  [[ ${value} == *.* ]] || return 1
  local sec=${value%%.*}
  local frac=${value#*.}
  frac=${frac:0:6}
  while ((${#frac} < 6)); do
    frac="${frac}0"
  done
  printf '%s' "$((10#${sec} * 1000000 + 10#${frac}))"
}

shisa_debug_trap() {
  local command=${1:-}
  [[ ${SHISA_IN_PROMPT:-0} == 0 ]] || return 0
  case "${command}" in
    shisa_*|__SHISA_*|PROMPT_COMMAND=*|PS1=*) return 0 ;;
  esac
  [[ ${SHISA_COMMAND_STARTED:-0} == 0 ]] || return 0
  SHISA_LAST_COMMAND=${command}
  shisa_ai_risk_preexec "${command}" || return $?
  shisa_preexec_guard bash "${command}" || return $?
  local now_us
  now_us=$(shisa_epoch_us) || return 0
  SHISA_COMMAND_START_US=${now_us}
  SHISA_COMMAND_STARTED=1
}

shisa_preexec_guard() {
  [[ ${SHISA_PROD_GUARD:-0} == 1 ]] || return 0
  local shell_name=${1:-bash}
  local command=${2:-}
  [[ -n ${command} ]] || return 0
  local socket_path
  socket_path=$(shisa_socket_path)
  local -a args
  args=(cloud preexec --socket "${socket_path}" --shell "${shell_name}")
  [[ ${SHISA_PROD_GUARD_FORCE:-0} == 1 ]] && args+=(--force)
  "${SHISA_BIN}" "${args[@]}" -- "${command}"
}

shisa_ai_risk_preexec() {
  [[ ${SHISA_AI_RISK_GUARD:-0} == 1 ]] || return 0
  local command=${1:-}
  [[ -n ${command} ]] || return 0
  "${SHISA_BIN}" ai risk --preexec -- "${command}"
}

shisa_cmd_complete_bell() {
  [[ ${SHISA_CMD_COMPLETE_BELL:-0} == 1 ]] || return 0
  [[ -n ${SHISA_LAST_COMMAND:-} ]] || return 0
  local duration_ms=${1:-0}
  local threshold_ms=${SHISA_CMD_COMPLETE_BELL_THRESHOLD_MS:-10000}
  [[ ${duration_ms} =~ ^[0-9]+$ && ${threshold_ms} =~ ^[0-9]+$ ]] || return 0
  ((duration_ms >= threshold_ms)) || return 0
  local message=${SHISA_CMD_COMPLETE_BELL_MESSAGE:-shisa: command complete}
  case ${SHISA_CMD_COMPLETE_BELL_MODE:-bell} in
    bell|terminal) printf '\a' ;;
    osc9) printf '\033]9;%s\a' "${message}" ;;
    notify|notify-send) command -v notify-send >/dev/null 2>&1 && notify-send shisa "${message}" >/dev/null 2>&1 || true ;;
    macos|osascript|user-notification) command -v osascript >/dev/null 2>&1 && osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "shisa"' -e 'end run' "${message}" >/dev/null 2>&1 || true ;;
  esac
  return 0
}

shisa_prompt_render() {
  local socket_path
  socket_path=$(shisa_socket_path)
  if [[ ! -S ${socket_path} ]]; then
    shisa_prompt_fallback
    return 0
  fi

  local -a args
  args=(prompt --shell bash --cwd "${PWD}" --exit "${SHISA_LAST_EXIT:-0}" --jobs "${SHISA_LAST_JOBS:-0}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}" --socket "${socket_path}")
  [[ ${SHISA_A11Y:-0} == 1 ]] && args+=(--a11y)
  [[ ${SHISA_RTL:-0} == 1 ]] && args+=(--rtl)
  "${SHISA_BIN}" "${args[@]}" || shisa_prompt_fallback
}

shisa_bash_right_prompt_render() {
  local socket_path
  socket_path=$(shisa_socket_path)
  [[ -S ${socket_path} ]] || return 0

  local -a args
  args=(prompt --right --shell bash --cwd "${PWD}" --exit "${SHISA_LAST_EXIT:-0}" --jobs "${SHISA_LAST_JOBS:-0}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}" --socket "${socket_path}")
  [[ ${SHISA_A11Y:-0} == 1 ]] && args+=(--a11y)
  [[ ${SHISA_RTL:-0} == 1 ]] && args+=(--rtl)
  "${SHISA_BIN}" "${args[@]}" 2>/dev/null || true
}

shisa_bash_right_prompt_draw() {
  [[ ${SHISA_BASH_RIGHT_PROMPT:-0} == 1 ]] || return 0
  local right_prompt
  right_prompt=$(shisa_bash_right_prompt_render) || return 0
  [[ -n ${right_prompt} ]] || return 0
  local cols=${COLUMNS:-80}
  [[ ${cols} =~ ^[0-9]+$ ]] || cols=80
  local width=${#right_prompt}
  ((width < cols)) || return 0
  printf '\r%*s\r' "${cols}" "${right_prompt}"
}

shisa_async_redraw() {
  local line=${READLINE_LINE-}
  local point=${READLINE_POINT-0}
  printf '\r\033[2K'
  READLINE_LINE=${line}
  READLINE_POINT=${point}
  return 0
}

shisa_nextcmd_widget() {
  local suggestion
  suggestion=$("${SHISA_BIN}" ai nextcmd --shell bash --cwd "${PWD}" --last-command "${SHISA_LAST_COMMAND:-}" --last-exit "${SHISA_LAST_EXIT:-0}" --history-path "${HISTFILE:-}" 2>/dev/null) || return 0
  SHISA_NEXTCMD_SUGGESTION=
  [[ -n ${suggestion} ]] || return 0
  SHISA_NEXTCMD_SUGGESTION=${suggestion}
  printf '\n\033[2mshisa next: %s\033[0m\n' "${suggestion}"
}

shisa_nextcmd_accept_widget() {
  [[ -n ${SHISA_NEXTCMD_SUGGESTION:-} ]] || return 0
  local suggestion=${SHISA_NEXTCMD_SUGGESTION}
  SHISA_NEXTCMD_SUGGESTION=
  READLINE_LINE="${READLINE_LINE:0:READLINE_POINT}${suggestion}${READLINE_LINE:READLINE_POINT}"
  READLINE_POINT=$((READLINE_POINT + ${#suggestion}))
}

shisa_nextcmd_reject_widget() {
  SHISA_NEXTCMD_SUGGESTION=
  printf '\r\033[2K'
}

shisa_nextcmd_next_widget() {
  SHISA_NEXTCMD_SUGGESTION=
  shisa_nextcmd_widget
}

shisa_explain_widget() {
  local output
  if [[ ${READLINE_LINE} == "${SHISA_EXPLAIN_LAST_COMMAND}" && -n ${SHISA_EXPLAIN_LAST_OUTPUT} ]]; then
    output=${SHISA_EXPLAIN_LAST_OUTPUT}
  else
    output=$("${SHISA_BIN}" ai explain --command "${READLINE_LINE}" 2>/dev/null) || return 0
    SHISA_EXPLAIN_LAST_COMMAND=${READLINE_LINE}
    SHISA_EXPLAIN_LAST_OUTPUT=${output}
  fi
  [[ -n ${output} ]] || return 0
  printf '\n%s\n' "${output}"
}

shisa_install_async_redraw() {
  [[ ${SHISA_ASYNC_REDRAW:-1} == 1 ]] || return 0
  bind -x "\"${SHISA_ASYNC_KEYSEQ}\": shisa_async_redraw" 2>/dev/null || true
  bind -x "\"${SHISA_NEXTCMD_KEYSEQ}\": shisa_nextcmd_widget" 2>/dev/null || true
  bind -x "\"${SHISA_NEXTCMD_ACCEPT_KEYSEQ}\": shisa_nextcmd_accept_widget" 2>/dev/null || true
  bind -x "\"${SHISA_NEXTCMD_REJECT_KEYSEQ}\": shisa_nextcmd_reject_widget" 2>/dev/null || true
  bind -x "\"${SHISA_NEXTCMD_NEXT_KEYSEQ}\": shisa_nextcmd_next_widget" 2>/dev/null || true
  bind -x "\"${SHISA_EXPLAIN_KEYSEQ}\": shisa_explain_widget" 2>/dev/null || true
}

shisa_prompt_command() {
  local last_status=$?
  SHISA_IN_PROMPT=1
  if [[ -n ${__SHISA_OLD_PROMPT_COMMAND:-} ]]; then
    eval "${__SHISA_OLD_PROMPT_COMMAND}"
  fi
  shisa_precmd "${last_status}"
  shisa_bash_right_prompt_draw
  SHISA_IN_PROMPT=0
  return "${last_status}"
}

PROMPT_COMMAND=shisa_prompt_command
trap 'case " ${FUNCNAME[*]:-} " in *" shisa_"*) ;; *) shisa_debug_trap "$BASH_COMMAND" ;; esac' DEBUG
shisa_install_async_redraw
shopt -s promptvars
PS1='$(shisa_prompt_render)'
