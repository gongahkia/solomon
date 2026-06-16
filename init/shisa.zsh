[[ -n ${ZSH_VERSION:-} ]] || return 0
[[ -z ${__SHISA_ZSH_INIT:-} ]] || return 0

typeset -g __SHISA_ZSH_INIT=1
typeset -g SHISA_BIN=${SHISA_BIN:-shisa}
typeset -g SHISA_SOCKET=${SHISA_SOCKET:-}
typeset -g SHISA_LAST_EXIT=0
typeset -g SHISA_LAST_DURATION_MS=0
typeset -g SHISA_PREEXEC_REALTIME=

shisa_prompt_render() {
  emulate -L zsh
  local -a args
  args=(prompt --shell zsh --exit "${SHISA_LAST_EXIT:-0}" --jobs "${#jobstates}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}")
  [[ -n ${SHISA_SOCKET:-} ]] && args+=(--socket "${SHISA_SOCKET}")
  "${SHISA_BIN}" "${args[@]}"
}
