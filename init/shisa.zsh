[[ -n ${ZSH_VERSION:-} ]] || return 0
[[ -z ${__SHISA_ZSH_INIT:-} ]] || return 0

typeset -g __SHISA_ZSH_INIT=1
typeset -g SHISA_BIN=${SHISA_BIN:-shisa}
typeset -g SHISA_SOCKET=${SHISA_SOCKET:-}
typeset -g SHISA_LAST_EXIT=0
typeset -g SHISA_LAST_JOBS=0
typeset -g SHISA_LAST_DURATION_MS=0
typeset -g SHISA_PREEXEC_REALTIME=

zmodload zsh/datetime 2>/dev/null || true

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
}

typeset -ga precmd_functions
if (( ${precmd_functions[(I)shisa_precmd]} == 0 )); then
  precmd_functions+=(shisa_precmd)
fi

shisa_preexec() {
  emulate -L zsh
  SHISA_PREEXEC_REALTIME=${EPOCHREALTIME:-}
}

typeset -ga preexec_functions
if (( ${preexec_functions[(I)shisa_preexec]} == 0 )); then
  preexec_functions+=(shisa_preexec)
fi

setopt prompt_subst
PROMPT='$(shisa_prompt_render)'

shisa_prompt_render() {
  emulate -L zsh
  local -a args
  args=(prompt --shell zsh --exit "${SHISA_LAST_EXIT:-0}" --jobs "${SHISA_LAST_JOBS:-0}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}")
  [[ -n ${SHISA_SOCKET:-} ]] && args+=(--socket "${SHISA_SOCKET}")
  "${SHISA_BIN}" "${args[@]}"
}
