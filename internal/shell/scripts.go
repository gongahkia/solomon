package shell

const zshScript = `# close-enough zsh integration
if (( ! ${+_CLOSE_ENOUGH_ZSH_LOADED} )); then
typeset -g _CLOSE_ENOUGH_ZSH_LOADED=1
function _close_enough_decode { print -rn -- "$1" | { base64 --decode 2>/dev/null || base64 -D; } }
typeset -gi _CLOSE_ENOUGH_DIAGNOSTIC_COUNT=0
typeset -gi _CLOSE_ENOUGH_DIAGNOSTIC_LIMIT=5
typeset -gA _CLOSE_ENOUGH_SEEN_SUGGESTIONS
function _close_enough_allow_diagnostic {
  (( _CLOSE_ENOUGH_DIAGNOSTIC_COUNT < _CLOSE_ENOUGH_DIAGNOSTIC_LIMIT )) || return 1
  (( ++_CLOSE_ENOUGH_DIAGNOSTIC_COUNT ))
}
function _close_enough_allow_suggestion {
  [[ -n "$1" ]] || return 1
  (( ${+_CLOSE_ENOUGH_SEEN_SUGGESTIONS[$1]} )) && return 1
  _close_enough_allow_diagnostic || return 1
  _CLOSE_ENOUGH_SEEN_SUGGESTIONS[$1]=1
}
function _close_enough_check {
  local command record version action risk confidence cause consequence suggestion suggestion_key
  local -a fields
  command="$BUFFER"
  record="$(command close-enough check --stage pre --format record --command "$command" 2>/dev/null)" || return 0
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return 0
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" confidence="${fields[4]}" cause="${fields[5]}" consequence="${fields[6]}" suggestion="${fields[7]}"
  [[ "$version" == "1" ]] || return 0
  [[ "$action" == none ]] && return 0
  suggestion_key="$suggestion"
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
    if _close_enough_allow_suggestion "$suggestion_key"; then
      zle -M "close-enough [$risk/$confidence]: $suggestion"
    fi
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
  local status=$? command="$_CLOSE_ENOUGH_LAST_COMMAND" output
  _CLOSE_ENOUGH_LAST_COMMAND=''
  [[ $status -eq 0 || -z "$command" ]] && return
  output="$(command close-enough check --stage post --format plain --command "$command" 2>/dev/null)" || return
  [[ -z "$output" || "$output" == "no suggestion" ]] && return
  _close_enough_allow_diagnostic || return
  print -r -- "$output"
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
_close_enough_diagnostic_count=0
_close_enough_diagnostic_limit=5
_close_enough_seen_suggestions=$'\n'
_close_enough_allow_diagnostic() {
  [ "$_close_enough_diagnostic_count" -lt "$_close_enough_diagnostic_limit" ] || return 1
  _close_enough_diagnostic_count=$((_close_enough_diagnostic_count + 1))
}
_close_enough_allow_suggestion() {
  local key=$1
  [ -n "$key" ] || return 1
  case "$_close_enough_seen_suggestions" in *$'\n'"$key"$'\n'*) return 1 ;; esac
  _close_enough_allow_diagnostic || return 1
  _close_enough_seen_suggestions+="$key"$'\n'
}
_close_enough_accept_line() {
  local command record version action risk confidence cause consequence suggestion suggestion_key separator
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
  suggestion_key="$suggestion"
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
    if _close_enough_allow_suggestion "$suggestion_key"; then
      printf '\nclose-enough [%s/%s]: %s\n' "$risk" "$confidence" "$suggestion" >&2
    fi
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
  local status=$? command="$_close_enough_last_command" output
  _close_enough_last_command=''
  [ "$status" -ne 0 ] && [ -n "$command" ] || return
  output="$(command close-enough check --stage post --format plain --command "$command" 2>/dev/null)" || return
  [ -n "$output" ] && [ "$output" != "no suggestion" ] || return
  _close_enough_allow_diagnostic || return
  printf '%s\n' "$output"
}
PROMPT_COMMAND="_close_enough_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
fi
`

const fishScript = `# close-enough fish integration
if not set -q _CLOSE_ENOUGH_FISH_LOADED
  set -g _CLOSE_ENOUGH_FISH_LOADED 1
set -g _CLOSE_ENOUGH_DIAGNOSTIC_COUNT 0
set -g _CLOSE_ENOUGH_DIAGNOSTIC_LIMIT 5
set -g _CLOSE_ENOUGH_SEEN_SUGGESTIONS
function _close_enough_allow_diagnostic
  if test $_CLOSE_ENOUGH_DIAGNOSTIC_COUNT -ge $_CLOSE_ENOUGH_DIAGNOSTIC_LIMIT
    return 1
  end
  set -g _CLOSE_ENOUGH_DIAGNOSTIC_COUNT (math $_CLOSE_ENOUGH_DIAGNOSTIC_COUNT + 1)
end
function _close_enough_allow_suggestion
  set -l key $argv[1]
  test -n "$key"; or return 1
  contains -- "$key" $_CLOSE_ENOUGH_SEEN_SUGGESTIONS; and return 1
  _close_enough_allow_diagnostic; or return 1
  set -ga _CLOSE_ENOUGH_SEEN_SUGGESTIONS "$key"
end
function _close_enough_decode
  printf '%s' "$argv[1]" | base64 --decode 2>/dev/null; or printf '%s' "$argv[1]" | base64 -D
end
function _close_enough_accept_line
  set -l command (commandline -b)
  set -l record (command close-enough check --stage pre --format record --command "$command" 2>/dev/null)
  set -l fields (string split \t -- $record)
  if test (count $fields) -ne 7
    return
  end
  if test "$fields[1]" != 1
    return
  end
  if test "$fields[2]" = rewrite
    set -l suggestion (_close_enough_decode "$fields[7]")
    or return
    if test "$fields[3]" != safe; or test -z "$suggestion"
      echo "close-enough: refused unsafe rewrite" >&2
      commandline -f repaint
      return
    end
    commandline -r "$suggestion"
    return
  end
  if test "$fields[2]" = hint
    set -l suggestion_key "$fields[7]"
    set -l suggestion (_close_enough_decode "$fields[7]")
    or return
    if _close_enough_allow_suggestion "$suggestion_key"
      echo "close-enough [$fields[3]/$fields[4]]: $suggestion" >&2
    end
    commandline -f execute
    return
  end
  if test "$fields[2]" = interrupt
    set -l suggestion (_close_enough_decode "$fields[7]")
    or return
    echo "close-enough [$fields[3]/$fields[4]]: $suggestion" >&2
    commandline -f repaint
    return
  end
  commandline -f execute
end
function _close_enough_bind_enter
  set -l binding (bind \r)
  if test "$binding" != "bind --preset enter execute"
    return
  end
  set -g _CLOSE_ENOUGH_FISH_ENTER_BOUND 1
  bind \r _close_enough_accept_line
end
function _close_enough_restore_enter
  if not set -q _CLOSE_ENOUGH_FISH_ENTER_BOUND
    return
  end
  if string match -q "* _close_enough_accept_line" -- (bind \r)
    bind --erase \r
  end
  set -e _CLOSE_ENOUGH_FISH_ENTER_BOUND
end
_close_enough_bind_enter
function _close_enough_post_failure --on-event fish_postexec
  set -l status $status
  set -l command $argv[1]
  if test $status -ne 0; and test -n "$command"
    set -l output (command close-enough check --stage post --format plain --command "$command" 2>/dev/null | string collect)
    if test -n "$output"; and test "$output" != "no suggestion"; and _close_enough_allow_diagnostic
      printf '%s\n' "$output"
    end
  end
end
end
`

const powerShellScript = `# close-enough PowerShell integration
if (-not $global:CloseEnoughAdapterLoaded) {
$global:CloseEnoughAdapterLoaded = $true
$global:CloseEnoughLastHistoryId = 0
$global:CloseEnoughDiagnosticCount = 0
$global:CloseEnoughDiagnosticLimit = 5
$global:CloseEnoughSeenSuggestions = [System.Collections.Generic.HashSet[string]]::new()
$global:CloseEnoughPreviousPrompt = (Get-Command prompt -CommandType Function -ErrorAction SilentlyContinue).ScriptBlock
$global:CloseEnoughPreviousEnterHandler = Get-PSReadLineKeyHandler -Chord Enter
if ($global:CloseEnoughPreviousEnterHandler.Function -eq 'AcceptLine') {
Set-PSReadLineKeyHandler -Key Enter -ScriptBlock {
  $line = $null; $cursor = $null
  [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
  $command = $line
  $record = & close-enough check --stage pre --format json --command $command 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)) { return }
  try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { return }
  if ($decision.version -ne 1) { return }
  if ($decision.action -eq 'rewrite') {
    if ($decision.risk -ne 'safe' -or [string]::IsNullOrEmpty($decision.suggestion)) {
      Write-Host "close-enough: refused unsafe rewrite"
      return
    }
    [Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $decision.suggestion)
    return
  }
  if ($decision.action -eq 'hint') {
    if (Allow-CloseEnoughSuggestion $decision.suggestion) { Write-Host "close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion)" }
    [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    return
  }
  if ($decision.action -eq 'interrupt') {
    Write-Host "close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion)"
    return
  }
  [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
}
}
function global:Allow-CloseEnoughDiagnostic {
  if ($global:CloseEnoughDiagnosticCount -ge $global:CloseEnoughDiagnosticLimit) { return $false }
  $global:CloseEnoughDiagnosticCount += 1
  return $true
}
function global:Allow-CloseEnoughSuggestion {
  param([string]$Suggestion)
  if ([string]::IsNullOrEmpty($Suggestion) -or $global:CloseEnoughSeenSuggestions.Contains($Suggestion)) { return $false }
  if (-not (Allow-CloseEnoughDiagnostic)) { return $false }
  [void]$global:CloseEnoughSeenSuggestions.Add($Suggestion)
  return $true
}
function global:Restore-CloseEnoughEnterHandler {
  if ($null -ne $global:CloseEnoughPreviousEnterHandler -and $global:CloseEnoughPreviousEnterHandler.Function -eq 'AcceptLine') {
    Set-PSReadLineKeyHandler -Key Enter -Function AcceptLine
  }
}
function global:prompt {
  $status = $?
  $entry = Get-History -Count 1
  if (-not $status -and $null -ne $entry -and $entry.Id -ne $global:CloseEnoughLastHistoryId -and -not [string]::IsNullOrEmpty($entry.CommandLine)) {
    $global:CloseEnoughLastHistoryId = $entry.Id
    $output = (& close-enough check --stage post --format plain --command $entry.CommandLine 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($output) -and $output -ne 'no suggestion' -and (Allow-CloseEnoughDiagnostic)) { Write-Host $output }
  }
  if ($null -ne $global:CloseEnoughPreviousPrompt) { & $global:CloseEnoughPreviousPrompt }
}
}
`
