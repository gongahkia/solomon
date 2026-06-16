[[ -n ${BASH_VERSION:-} ]] || return 0 2>/dev/null || exit 0
[[ -z ${__SHISA_BASH_INIT:-} ]] || return 0 2>/dev/null || exit 0

__SHISA_BASH_INIT=1
SHISA_BIN=${SHISA_BIN:-shisa}
SHISA_SOCKET=${SHISA_SOCKET:-}
SHISA_LAST_EXIT=0
SHISA_LAST_JOBS=0
SHISA_LAST_DURATION_MS=0
SHISA_ASYNC_REDRAW=${SHISA_ASYNC_REDRAW:-1}
SHISA_ASYNC_KEYSEQ=${SHISA_ASYNC_KEYSEQ:-'\C-x\C-s'}
SHISA_PROD_GUARD=${SHISA_PROD_GUARD:-0}
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
  "${SHISA_BIN}" cloud preexec --shell "${shell_name}" -- "${command}"
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
  "${SHISA_BIN}" "${args[@]}" || shisa_prompt_fallback
}

shisa_async_redraw() {
  return 0
}

shisa_install_async_redraw() {
  [[ ${SHISA_ASYNC_REDRAW:-1} == 1 ]] || return 0
  bind -x "\"${SHISA_ASYNC_KEYSEQ}\": shisa_async_redraw" 2>/dev/null || true
}

shisa_prompt_command() {
  local last_status=$?
  SHISA_IN_PROMPT=1
  if [[ -n ${__SHISA_OLD_PROMPT_COMMAND:-} ]]; then
    eval "${__SHISA_OLD_PROMPT_COMMAND}"
  fi
  shisa_precmd "${last_status}"
  SHISA_IN_PROMPT=0
  return "${last_status}"
}

PROMPT_COMMAND=shisa_prompt_command
trap 'case " ${FUNCNAME[*]:-} " in *" shisa_"*) ;; *) shisa_debug_trap "$BASH_COMMAND" ;; esac' DEBUG
shisa_install_async_redraw
shopt -s promptvars
PS1='$(shisa_prompt_render)'
