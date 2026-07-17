package shell

const zshScript = `# close-enough zsh integration
if (( ! ${+_CLOSE_ENOUGH_ZSH_LOADED} )); then
typeset -g _CLOSE_ENOUGH_ZSH_LOADED=1
function _close_enough_decode { print -rn -- "$1" | { base64 --decode 2>/dev/null || base64 -D; } }
function _close_enough_check {
  local command record version action risk confidence cause consequence suggestion
  local -a fields
  command="$BUFFER"
  record="$(command close-enough check --stage pre --format record --command "$command" 2>/dev/null)" || return 0
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return 0
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" confidence="${fields[4]}" cause="${fields[5]}" consequence="${fields[6]}" suggestion="${fields[7]}"
  [[ "$version" == "1" ]] || return 0
  [[ "$action" == none ]] && return 0
  suggestion="$(_close_enough_decode "$suggestion")" || return 0
  if [[ "$action" == rewrite ]]; then
    if [[ "$risk" != safe || -z "$suggestion" ]]; then
      zle -M "close-enough: refused unsafe rewrite"
      return 1
    fi
    BUFFER="$suggestion"
    zle -R
    return 1
  fi
  if [[ "$action" == hint ]]; then
    zle -M "close-enough [$risk/$confidence]: $suggestion"
    return 0
  fi
  if [[ "$action" == interrupt ]]; then
    zle -M "close-enough [$risk/$confidence]: $suggestion"
    return 1
  fi
  return 0
}
function _close_enough_accept_line {
  if ! _close_enough_check; then
    return 0
  fi
  zle "$_CLOSE_ENOUGH_ENTER_WIDGET"
}
zle -N _close_enough_accept_line
typeset -g _CLOSE_ENOUGH_ENTER_WIDGET=''
function _close_enough_bind_enter {
  local binding widget
  binding="$(bindkey -M main '^M')" || return 0
  widget="${binding##* }"
  [[ -z "$widget" || "$widget" == \"* ]] && return 0
  _CLOSE_ENOUGH_ENTER_WIDGET="$widget"
  bindkey -M main '^M' _close_enough_accept_line
}
function _close_enough_restore_enter {
  local binding
  binding="$(bindkey -M main '^M')" || return 0
  [[ "$binding" == *" _close_enough_accept_line" ]] || return 0
  bindkey -M main '^M' "$_CLOSE_ENOUGH_ENTER_WIDGET"
  _CLOSE_ENOUGH_ENTER_WIDGET=''
}
_close_enough_bind_enter
typeset -g _CLOSE_ENOUGH_LAST_COMMAND=''
function _close_enough_preexec { _CLOSE_ENOUGH_LAST_COMMAND="$1" }
function _close_enough_precmd {
  local status=$? command="$_CLOSE_ENOUGH_LAST_COMMAND"
  _CLOSE_ENOUGH_LAST_COMMAND=''
  [[ $status -eq 0 || -z "$command" ]] && return
  command close-enough check --stage post --format plain --command "$command" 2>/dev/null
}
autoload -Uz add-zsh-hook
add-zsh-hook preexec _close_enough_preexec
add-zsh-hook precmd _close_enough_precmd
fi
`

const bashScript = `# close-enough bash integration
if [ -z "${_CLOSE_ENOUGH_BASH_LOADED+x}" ]; then
_CLOSE_ENOUGH_BASH_LOADED=1
_close_enough_decode() { printf %s "$1" | { base64 --decode 2>/dev/null || base64 -D; }; }
_close_enough_accept_line() {
  local command record version action risk confidence cause consequence suggestion separator
  local -a fields
  command="$READLINE_LINE"
  record="$(command close-enough check --stage pre --format record --command "$command" 2>/dev/null)" || return
  separator=$'\034'
  record="${record//$'\t'/$separator}"
  IFS="$separator" read -r -a fields <<< "$record"
  [ "${#fields[@]}" -eq 7 ] || return
  version="${fields[0]}" action="${fields[1]}" risk="${fields[2]}" confidence="${fields[3]}" cause="${fields[4]}" consequence="${fields[5]}" suggestion="${fields[6]}"
  [ "$version" = 1 ] || return
  [ "$action" = none ] && return
  suggestion="$(_close_enough_decode "$suggestion")" || return
  if [ "$action" = rewrite ]; then
    if [ "$risk" != safe ] || [ -z "$suggestion" ]; then
      printf '\nclose-enough: refused unsafe rewrite\n' >&2
      READLINE_LINE=''
      return 1
    fi
    READLINE_LINE="$suggestion"
    return 1
  fi
  if [ "$action" = hint ]; then
    printf '\nclose-enough [%s/%s]: %s\n' "$risk" "$confidence" "$suggestion" >&2
    return
  fi
  if [ "$action" = interrupt ]; then
    printf '\nclose-enough [%s/%s]: %s\n' "$risk" "$confidence" "$suggestion" >&2
    READLINE_LINE=''
    return 1
  fi
}
_close_enough_enter_binding=''
_close_enough_bind_enter() {
  local binding
  binding="$(bind -p 2>/dev/null | command grep '^"\\C-m": ')" || return 0
  [ "$binding" = '"\C-m": accept-line' ] || return 0
  _close_enough_enter_binding=accept-line
  bind -x '"\C-m":_close_enough_accept_line'
}
_close_enough_restore_enter() {
  [ "$_close_enough_enter_binding" = accept-line ] || return 0
  bind -X 2>/dev/null | command grep -F '"\C-m": _close_enough_accept_line' >/dev/null || return 0
  bind '"\C-m": accept-line'
  _close_enough_enter_binding=''
}
_close_enough_bind_enter
_close_enough_last_command=''
_close_enough_debug() { _close_enough_last_command=$BASH_COMMAND; }
trap _close_enough_debug DEBUG
_close_enough_prompt() {
  local status=$? command="$_close_enough_last_command"
  _close_enough_last_command=''
  [ "$status" -ne 0 ] && [ -n "$command" ] && command close-enough check --stage post --format plain --command "$command" 2>/dev/null
}
PROMPT_COMMAND="_close_enough_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
fi
`

const fishScript = `# close-enough fish integration
if not set -q _CLOSE_ENOUGH_FISH_LOADED
  set -g _CLOSE_ENOUGH_FISH_LOADED 1
function _close_enough_accept_line
  set -l command (commandline -b)
  set -l record (command close-enough check --stage pre --format record --command "$command" 2>/dev/null)
  set -l fields (string split \t -- $record)
  if test "$fields[1]" != 1
    return
  end
  if test "$fields[2]" = rewrite
    set -l suggestion (echo $fields[7] | base64 --decode 2>/dev/null; or echo $fields[7] | base64 -D)
    if test "$fields[3]" != safe; or test -z "$suggestion"
      echo "close-enough: refused unsafe rewrite" >&2
      commandline -f repaint
      return
    end
    commandline -r "$suggestion"
    return
  end
  if test "$fields[2]" = hint
    echo "close-enough [$fields[3]/$fields[4]]: "(echo $fields[7] | base64 --decode 2>/dev/null; or echo $fields[7] | base64 -D) >&2
    commandline -f execute
    return
  end
  if test "$fields[2]" = interrupt
    echo "close-enough [$fields[3]/$fields[4]]: "(echo $fields[7] | base64 --decode 2>/dev/null; or echo $fields[7] | base64 -D) >&2
    commandline -f repaint
    return
  end
  commandline -f execute
end
bind \r _close_enough_accept_line
end
`

const powerShellScript = `# close-enough PowerShell integration
Set-PSReadLineKeyHandler -Key Enter -ScriptBlock {
  $line = $null; $cursor = $null
  [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
  $decision = & close-enough check --stage pre --format json --command $line 2>$null | ConvertFrom-Json
  if ($decision.version -ne 1) { return }
  if ($decision.action -eq 'rewrite') { [Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $decision.suggestion); return }
  if ($decision.action -eq 'hint') { Write-Host "close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion)" }
  if ($decision.action -ne 'interrupt') { [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine() }
}
`
