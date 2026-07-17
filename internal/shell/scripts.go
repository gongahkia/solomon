package shell

const zshScript = `# close-enough zsh integration
function _close_enough_decode { print -rn -- "$1" | { base64 --decode 2>/dev/null || base64 -D; } }
function _close_enough_check {
  local record version action risk confidence cause consequence suggestion
  record="$(command close-enough check --stage pre --format record --command "$BUFFER" 2>/dev/null)" || return 0
  IFS=$'\t' read -r version action risk confidence cause consequence suggestion <<< "$record"
  [[ "$version" == "1" ]] || return 0
  [[ "$action" == none ]] && return 0
  suggestion="$(_close_enough_decode "$suggestion")"
  if [[ "$action" == rewrite ]]; then BUFFER="$suggestion"; zle -R; return 1; fi
  zle -M "close-enough [$risk/$confidence]: $suggestion"
  [[ "$action" == interrupt ]] && return 1
  return 0
}
function _close_enough_accept_line { _close_enough_check || return; zle .accept-line }
zle -N _close_enough_accept_line
bindkey '^M' _close_enough_accept_line
typeset -g _CLOSE_ENOUGH_LAST_COMMAND=''
function _close_enough_preexec { _CLOSE_ENOUGH_LAST_COMMAND="$1" }
function _close_enough_precmd {
  local status=$?
  [[ $status -eq 0 || -z "$_CLOSE_ENOUGH_LAST_COMMAND" ]] && return
  command close-enough check --stage post --format plain --command "$_CLOSE_ENOUGH_LAST_COMMAND" 2>/dev/null
}
autoload -Uz add-zsh-hook
add-zsh-hook preexec _close_enough_preexec
add-zsh-hook precmd _close_enough_precmd
`

const bashScript = `# close-enough bash integration
_close_enough_decode() { printf %s "$1" | { base64 --decode 2>/dev/null || base64 -D; }; }
_close_enough_accept_line() {
  local record version action risk confidence cause consequence suggestion
  record="$(command close-enough check --stage pre --format record --command "$READLINE_LINE" 2>/dev/null)" || return
  IFS=$'\t' read -r version action risk confidence cause consequence suggestion <<< "$record"
  [ "$version" = 1 ] || return
  [ "$action" = none ] && return
  suggestion="$(_close_enough_decode "$suggestion")"
  if [ "$action" = rewrite ]; then READLINE_LINE="$suggestion"; return; fi
  printf '\nclose-enough [%s/%s]: %s\n' "$risk" "$confidence" "$suggestion" >&2
  [ "$action" = interrupt ] && READLINE_LINE=''
}
bind -x '"\C-m":_close_enough_accept_line'
_close_enough_last_command=''
_close_enough_debug() { _close_enough_last_command=$BASH_COMMAND; }
trap _close_enough_debug DEBUG
_close_enough_prompt() {
  local status=$?
  [ "$status" -ne 0 ] && [ -n "$_close_enough_last_command" ] && command close-enough check --stage post --format plain --command "$_close_enough_last_command" 2>/dev/null
}
PROMPT_COMMAND="_close_enough_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
`

const fishScript = `# close-enough fish integration
function _close_enough_accept_line
  set -l record (command close-enough check --stage pre --format record --command (commandline -b) 2>/dev/null)
  set -l fields (string split \t -- $record)
  if test "$fields[1]" != 1
    return
  end
  if test "$fields[2]" = rewrite
    commandline -r (echo $fields[7] | base64 --decode 2>/dev/null; or echo $fields[7] | base64 -D)
    return
  end
  if test "$fields[2]" = hint
    echo "close-enough [$fields[3]/$fields[4]]: "(echo $fields[7] | base64 --decode 2>/dev/null; or echo $fields[7] | base64 -D) >&2
  end
  commandline -f execute
end
bind \r _close_enough_accept_line
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
