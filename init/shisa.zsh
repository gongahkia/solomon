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
typeset -g SHISA_LAST_EXIT=0
typeset -g SHISA_LAST_JOBS=0
typeset -g SHISA_LAST_DURATION_MS=0
typeset -g SHISA_LAST_COMMAND=
typeset -g SHISA_PREEXEC_REALTIME=
typeset -g SHISA_ASYNC_SIGNAL=${SHISA_ASYNC_SIGNAL:-USR1}
typeset -g SHISA_ASYNC_SELF_PIPE=${SHISA_ASYNC_SELF_PIPE:-1}
typeset -g SHISA_ASYNC_PIPE=
typeset -g SHISA_ASYNC_FD=
typeset -g SHISA_TRANSIENT_PROMPT=${SHISA_TRANSIENT_PROMPT:-1}
typeset -g SHISA_PROD_GUARD=${SHISA_PROD_GUARD:-0}
typeset -g SHISA_PROD_GUARD_FORCE=${SHISA_PROD_GUARD_FORCE:-0}
typeset -g SHISA_AI_RISK_GUARD=${SHISA_AI_RISK_GUARD:-0}
typeset -g SHISA_A11Y=${SHISA_A11Y:-0}

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
typeset -g SHISA_NEXTCMD_KEYSEQ=${SHISA_NEXTCMD_KEYSEQ:-'^X^N'}
typeset -g SHISA_NEXTCMD_ACCEPT_KEYSEQ=${SHISA_NEXTCMD_ACCEPT_KEYSEQ:-'^I'}
typeset -g SHISA_NEXTCMD_REJECT_KEYSEQ=${SHISA_NEXTCMD_REJECT_KEYSEQ:-'^['}
typeset -g SHISA_NEXTCMD_NEXT_KEYSEQ=${SHISA_NEXTCMD_NEXT_KEYSEQ:-'^[]'}
typeset -g SHISA_NEXTCMD_SUGGESTION=
typeset -g SHISA_EXPLAIN_KEYSEQ=${SHISA_EXPLAIN_KEYSEQ:-'^X^E'}
typeset -g SHISA_EXPLAIN_LAST_COMMAND=
typeset -g SHISA_EXPLAIN_LAST_OUTPUT=

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
}

shisa_hook_once precmd shisa_precmd

shisa_preexec() {
  emulate -L zsh
  local command=${1:-}
  SHISA_LAST_COMMAND=${command}
  SHISA_PREEXEC_REALTIME=${EPOCHREALTIME:-}
  shisa_ai_risk_preexec "${command}" || return $?
  shisa_preexec_guard zsh "${command}"
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

shisa_ai_risk_preexec() {
  emulate -L zsh
  [[ ${SHISA_AI_RISK_GUARD:-0} == 1 ]] || return 0
  local command=${1:-}
  [[ -n ${command} ]] || return 0
  "${SHISA_BIN}" ai risk --preexec -- "${command}"
}

setopt prompt_subst
PROMPT='$(shisa_prompt_render)'

shisa_async_redraw() {
  emulate -L zsh
  zle reset-prompt 2>/dev/null || true
}

shisa_async_self_pipe_readable() {
  emulate -L zsh
  local fd=${1:-${SHISA_ASYNC_FD:-}}
  [[ -n ${fd} ]] || return 0
  local byte
  while read -r -k 1 -t 0 -u ${fd} byte 2>/dev/null; do
    :
  done
  shisa_async_redraw
}

shisa_async_self_pipe_notify() {
  emulate -L zsh
  if [[ -n ${SHISA_ASYNC_FD:-} ]]; then
    print -rn -- . >&${SHISA_ASYNC_FD} 2>/dev/null && return 0
  fi
  shisa_async_redraw
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
}

shisa_async_self_pipe_setup() {
  emulate -L zsh
  [[ ${SHISA_ASYNC_SELF_PIPE:-1} == 1 ]] || return 0
  [[ -o interactive ]] || return 0
  [[ -z ${SHISA_ASYNC_FD:-} ]] || return 0
  local dir="${TMPDIR:-/tmp}/shisa-${UID:-0}"
  mkdir -p -- "${dir}" 2>/dev/null || return 0
  SHISA_ASYNC_PIPE="${dir}/zsh-redraw-${$}.fifo"
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

shisa_accept_line() {
  emulate -L zsh
  print -Pnr -- $'\r\e[2K%~> '
  zle .accept-line
}

if [[ ${SHISA_TRANSIENT_PROMPT} == 1 ]]; then
  zle -N accept-line shisa_accept_line 2>/dev/null || true
fi

shisa_nextcmd_widget() {
  emulate -L zsh
  local suggestion
  suggestion=$("${SHISA_BIN}" ai nextcmd --shell zsh --cwd "${PWD}" --last-command "${SHISA_LAST_COMMAND:-}" --last-exit "${SHISA_LAST_EXIT:-0}" --history-path "${HISTFILE:-}" 2>/dev/null) || return 0
  SHISA_NEXTCMD_SUGGESTION=
  [[ -n ${suggestion} ]] || return 0
  SHISA_NEXTCMD_SUGGESTION=${suggestion}
  zle -M $'\e[2mshisa next: '"${suggestion}"$'\e[0m'
  zle redisplay
}

shisa_nextcmd_accept_widget() {
  emulate -L zsh
  if [[ -n ${SHISA_NEXTCMD_SUGGESTION:-} ]]; then
    LBUFFER+="${SHISA_NEXTCMD_SUGGESTION}"
    SHISA_NEXTCMD_SUGGESTION=
    zle -M ''
    zle redisplay
  else
    zle .expand-or-complete
  fi
}

shisa_nextcmd_reject_widget() {
  emulate -L zsh
  SHISA_NEXTCMD_SUGGESTION=
  zle -M ''
  zle redisplay
}

shisa_nextcmd_next_widget() {
  emulate -L zsh
  SHISA_NEXTCMD_SUGGESTION=
  shisa_nextcmd_widget
}

shisa_explain_widget() {
  emulate -L zsh
  local output
  if [[ ${BUFFER} == "${SHISA_EXPLAIN_LAST_COMMAND}" && -n ${SHISA_EXPLAIN_LAST_OUTPUT} ]]; then
    output=${SHISA_EXPLAIN_LAST_OUTPUT}
  else
    output=$("${SHISA_BIN}" ai explain --command "${BUFFER}" 2>/dev/null) || return 0
    SHISA_EXPLAIN_LAST_COMMAND=${BUFFER}
    SHISA_EXPLAIN_LAST_OUTPUT=${output}
  fi
  [[ -n ${output} ]] || return 0
  print -r -- $'\n'"${output}"
  zle redisplay
}

zle -N shisa-nextcmd shisa_nextcmd_widget 2>/dev/null || true
zle -N shisa-nextcmd-accept shisa_nextcmd_accept_widget 2>/dev/null || true
zle -N shisa-nextcmd-reject shisa_nextcmd_reject_widget 2>/dev/null || true
zle -N shisa-nextcmd-next shisa_nextcmd_next_widget 2>/dev/null || true
zle -N shisa-explain shisa_explain_widget 2>/dev/null || true
bindkey "${SHISA_NEXTCMD_KEYSEQ}" shisa-nextcmd 2>/dev/null || true
bindkey "${SHISA_NEXTCMD_ACCEPT_KEYSEQ}" shisa-nextcmd-accept 2>/dev/null || true
bindkey "${SHISA_NEXTCMD_REJECT_KEYSEQ}" shisa-nextcmd-reject 2>/dev/null || true
bindkey "${SHISA_NEXTCMD_NEXT_KEYSEQ}" shisa-nextcmd-next 2>/dev/null || true
bindkey "${SHISA_EXPLAIN_KEYSEQ}" shisa-explain 2>/dev/null || true

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
  if [[ ! -S ${socket_path} ]]; then
    shisa_prompt_fallback
    return 0
  fi

  local -a args
  args=(prompt --shell zsh --exit "${SHISA_LAST_EXIT:-0}" --jobs "${SHISA_LAST_JOBS:-0}" --duration-ms "${SHISA_LAST_DURATION_MS:-0}" --socket "${socket_path}")
  [[ ${SHISA_A11Y:-0} == 1 ]] && args+=(--a11y)
  [[ ${SHISA_RTL:-0} == 1 ]] && args+=(--rtl)
  "${SHISA_BIN}" "${args[@]}"
}
