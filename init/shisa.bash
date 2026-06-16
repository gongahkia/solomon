[[ -n ${BASH_VERSION:-} ]] || return 0 2>/dev/null || exit 0
[[ -z ${__SHISA_BASH_INIT:-} ]] || return 0 2>/dev/null || exit 0

__SHISA_BASH_INIT=1
SHISA_BIN=${SHISA_BIN:-shisa}
SHISA_SOCKET=${SHISA_SOCKET:-}
SHISA_LAST_EXIT=0
SHISA_LAST_JOBS=0
SHISA_LAST_DURATION_MS=0

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
  local last_status=$?
  SHISA_LAST_EXIT=${last_status}
  local count=0
  local job_pid
  while IFS= read -r job_pid; do
    [[ -n ${job_pid} ]] && ((count += 1))
  done < <(jobs -p)
  SHISA_LAST_JOBS=${count}
  SHISA_LAST_DURATION_MS=0
  return "${last_status}"
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

shisa_append_prompt_command() {
  case ";${PROMPT_COMMAND:-};" in
    *";shisa_precmd;"*) ;;
    *) PROMPT_COMMAND="shisa_precmd${PROMPT_COMMAND:+;${PROMPT_COMMAND}}" ;;
  esac
}

shisa_append_prompt_command
shopt -s promptvars
PS1='$(shisa_prompt_render)'
