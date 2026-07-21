package shell

const zshScript = `# close-enough zsh integration
if (( ! ${+_CLOSE_ENOUGH_ZSH_LOADED} )); then
typeset -g _CLOSE_ENOUGH_ZSH_LOADED=1
function _close_enough_decode {
  if base64 --decode </dev/null >/dev/null 2>&1; then
    print -rn -- "$1" | base64 --decode
  else
    print -rn -- "$1" | base64 -D
  fi
}
typeset -gi _CLOSE_ENOUGH_DIAGNOSTIC_COUNT=0
typeset -gi _CLOSE_ENOUGH_DIAGNOSTIC_LIMIT=5
typeset -gi _CLOSE_ENOUGH_DAEMON_READY=0
typeset -g _CLOSE_ENOUGH_PENDING_REWRITE=''
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
function _close_enough_handshake {
  (( _CLOSE_ENOUGH_DAEMON_READY )) && return 0
  local record version action
  local -a fields
  record="$(command close-enough daemon request --operation handshake --shell zsh --session "$$" --ensure=true --format record 2>/dev/null)" || return 1
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return 1
  version="${fields[1]}" action="${fields[2]}"
  [[ "$version" == "1" && "$action" == ready ]] || return 1
  _CLOSE_ENOUGH_DAEMON_READY=1
}
function _close_enough_check {
  local command record version action risk confidence cause consequence suggestion suggestion_key
  local -a fields
  command="$BUFFER"
  if [[ -n "$_CLOSE_ENOUGH_PENDING_REWRITE" ]]; then
    if [[ "$command" == "$_CLOSE_ENOUGH_PENDING_REWRITE" ]]; then
      _CLOSE_ENOUGH_PENDING_REWRITE=''
      return 0
    fi
    _CLOSE_ENOUGH_PENDING_REWRITE=''
  fi
  _close_enough_handshake || return 0
  record="$(command close-enough daemon request --operation pre-send --shell zsh --session "$$" --ensure=false --format record --command "$command" 2>/dev/null)" || { _CLOSE_ENOUGH_DAEMON_READY=0; return 0; }
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return 0
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" confidence="${fields[4]}" cause="${fields[5]}" consequence="${fields[6]}" suggestion="${fields[7]}"
  [[ "$version" == "1" ]] || return 0
  [[ "$action" == none ]] && return 0
  suggestion_key="$suggestion"
  suggestion="$(_close_enough_decode "$suggestion")" || return 0
  cause="$(_close_enough_decode "$cause")" || cause=''
  if [[ "$action" == submit ]]; then
    return 0
  fi
  if [[ "$action" == rewrite ]]; then
    if [[ "$risk" != safe || -z "$suggestion" ]]; then
      zle -M "close-enough: refused unsafe rewrite"
      return 1
    fi
    BUFFER="$suggestion"
    _CLOSE_ENOUGH_PENDING_REWRITE="$suggestion"
    zle -M "close-enough corrected: $suggestion ($cause; press Enter again)"
    zle -R
    return 1
  fi
  if [[ "$action" == hint ]]; then
    if _close_enough_allow_suggestion "$suggestion_key"; then
      zle -M "close-enough [$risk/$confidence]: $suggestion ($cause)"
    fi
    return 0
  fi
  if [[ "$action" == interrupt ]]; then
    zle -M "close-enough [$risk/$confidence]: $suggestion ($cause)"
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
function _close_enough_preexec { _CLOSE_ENOUGH_LAST_COMMAND="$1"; _CLOSE_ENOUGH_PENDING_REWRITE='' }
function _close_enough_precmd {
  local status=$? command="$_CLOSE_ENOUGH_LAST_COMMAND" record version action risk confidence cause suggestion suggestion_key
  local -a fields
  _CLOSE_ENOUGH_LAST_COMMAND=''
  [[ -z "$command" ]] && return
  if [[ $status -eq 0 ]]; then
    command close-enough daemon request --operation post-success --shell zsh --session "$$" --ensure=false --command "$command" >/dev/null 2>&1
    return
  fi
  record="$(command close-enough daemon request --operation post-failure --shell zsh --session "$$" --format record --command "$command" 2>/dev/null)" || return
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" confidence="${fields[4]}" cause="${fields[5]}" suggestion="${fields[7]}"
  [[ "$version" == "1" && "$action" != none ]] || return
  suggestion_key="$suggestion"
  suggestion="$(_close_enough_decode "$suggestion")" || return
  cause="$(_close_enough_decode "$cause")" || cause=''
  [[ -n "$suggestion" ]] || return
  if _close_enough_allow_suggestion "$suggestion_key"; then
    print -r -- "close-enough [$risk/$confidence]: $suggestion ($cause)"
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook preexec _close_enough_preexec
add-zsh-hook precmd _close_enough_precmd
fi
`

const bashScript = `# close-enough bash integration
if [ -z "${_CLOSE_ENOUGH_BASH_LOADED+x}" ]; then
_CLOSE_ENOUGH_BASH_LOADED=1
_close_enough_decode() {
  if base64 --decode </dev/null >/dev/null 2>&1; then
    printf %s "$1" | base64 --decode
  else
    printf %s "$1" | base64 -D
  fi
}
_close_enough_diagnostic_count=0
_close_enough_diagnostic_limit=5
_close_enough_daemon_ready=0
_close_enough_pending_rewrite=''
_close_enough_pending_confirmation=''
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
_close_enough_handshake() {
  [ "$_close_enough_daemon_ready" = 1 ] && return 0
  local record version action separator
  local -a fields
  record="$(command close-enough daemon request --operation handshake --shell bash --session "$$" --ensure=true --format record 2>/dev/null)" || return 1
  separator=$'\034'
  record="${record//$'\t'/$separator}"
  IFS="$separator" read -r -a fields <<< "$record"
  [ "${#fields[@]}" -ge 2 ] || return 1
  version="${fields[0]}" action="${fields[1]}"
  [ "$version" = 1 ] && [ "$action" = ready ] || return 1
  _close_enough_daemon_ready=1
}
_close_enough_accept_line() {
  local command record version action risk confidence cause consequence suggestion suggestion_key separator
  local -a fields
  command="$READLINE_LINE"
  if [ -n "$_close_enough_pending_rewrite" ]; then
    if [ "$command" = "$_close_enough_pending_rewrite" ]; then
      _close_enough_pending_rewrite=''
      return
    fi
    _close_enough_pending_rewrite=''
  fi
  if [ -n "$_close_enough_pending_confirmation" ] && [ "$command" != "$_close_enough_pending_confirmation" ]; then
    _close_enough_pending_confirmation=''
  fi
  _close_enough_handshake || return
  record="$(command close-enough daemon request --operation pre-send --shell bash --session "$$" --ensure=false --format record --command "$command" 2>/dev/null)" || { _close_enough_daemon_ready=0; _close_enough_pending_confirmation=''; return; }
  separator=$'\034'
  record="${record//$'\t'/$separator}"
  IFS="$separator" read -r -a fields <<< "$record"
  [ "${#fields[@]}" -eq 7 ] || return
  version="${fields[0]}" action="${fields[1]}" risk="${fields[2]}" confidence="${fields[3]}" cause="${fields[4]}" consequence="${fields[5]}" suggestion="${fields[6]}"
  [ "$version" = 1 ] || return
  [ "$action" = none ] && return
  suggestion_key="$suggestion"
  suggestion="$(_close_enough_decode "$suggestion")" || return
  cause="$(_close_enough_decode "$cause")" || cause=''
  if [ "$action" = submit ]; then
    _close_enough_pending_confirmation=''
    return
  fi
  if [ "$action" = rewrite ]; then
    if [ "$risk" != safe ] || [ -z "$suggestion" ]; then
      printf '\nclose-enough: refused unsafe rewrite\n' >&2
      READLINE_LINE=':'
      return 1
    fi
    READLINE_LINE="$suggestion"
    _close_enough_pending_rewrite="$suggestion"
    printf '\nclose-enough corrected: %s (%s; press Enter again)\n' "$suggestion" "$cause" >&2
    return 1
  fi
  if [ "$action" = hint ]; then
    if _close_enough_allow_suggestion "$suggestion_key"; then
      printf '\nclose-enough [%s/%s]: %s (%s)\n' "$risk" "$confidence" "$suggestion" "$cause" >&2
    fi
    return
  fi
  if [ "$action" = interrupt ]; then
    printf '\nclose-enough [%s/%s]: %s (%s)\n' "$risk" "$confidence" "$suggestion" "$cause" >&2
    _close_enough_pending_confirmation="$command"
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
  local status=$? command="$_close_enough_last_command" record version action risk confidence cause suggestion suggestion_key separator
  local -a fields
  _close_enough_last_command=''
  [ -n "$command" ] || return
  if [ "$status" -eq 0 ]; then
    command close-enough daemon request --operation post-success --shell bash --session "$$" --ensure=false --command "$command" >/dev/null 2>&1
    return
  fi
  record="$(command close-enough daemon request --operation post-failure --shell bash --session "$$" --format record --command "$command" 2>/dev/null)" || return
  separator=$'\034'
  record="${record//$'\t'/$separator}"
  IFS="$separator" read -r -a fields <<< "$record"
  [ "${#fields[@]}" -eq 7 ] || return
  version="${fields[0]}" action="${fields[1]}" risk="${fields[2]}" confidence="${fields[3]}" cause="${fields[4]}" suggestion="${fields[6]}"
  [ "$version" = 1 ] && [ "$action" != none ] || return
  suggestion_key="$suggestion"
  suggestion="$(_close_enough_decode "$suggestion")" || return
  cause="$(_close_enough_decode "$cause")" || cause=''
  [ -n "$suggestion" ] || return
  if _close_enough_allow_suggestion "$suggestion_key"; then
    printf '\nclose-enough [%s/%s]: %s (%s)\n' "$risk" "$confidence" "$suggestion" "$cause"
  fi
}
PROMPT_COMMAND="_close_enough_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
fi
`

const fishScript = `# close-enough fish integration
if not set -q _CLOSE_ENOUGH_FISH_LOADED
  set -g _CLOSE_ENOUGH_FISH_LOADED 1
set -g _CLOSE_ENOUGH_DIAGNOSTIC_COUNT 0
set -g _CLOSE_ENOUGH_DIAGNOSTIC_LIMIT 5
set -g _CLOSE_ENOUGH_DAEMON_READY 0
set -g _CLOSE_ENOUGH_PENDING_REWRITE
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
  if base64 --decode </dev/null >/dev/null 2>&1
    printf '%s' "$argv[1]" | base64 --decode
  else
    printf '%s' "$argv[1]" | base64 -D
  end
end
function _close_enough_handshake
  if test "$_CLOSE_ENOUGH_DAEMON_READY" = 1
    return
  end
  set -l record (command close-enough daemon request --operation handshake --shell fish --session "$fish_pid" --ensure=true --format record 2>/dev/null)
  if test $status -ne 0
    return 1
  end
  set -l fields (string split \t -- $record)
  if test (count $fields) -lt 2
    return 1
  end
  if test "$fields[1]" != 1; or test "$fields[2]" != ready
    return 1
  end
  set -g _CLOSE_ENOUGH_DAEMON_READY 1
end
function _close_enough_accept_line
  set -l command (commandline -b)
  if set -q _CLOSE_ENOUGH_PENDING_REWRITE; and test -n "$_CLOSE_ENOUGH_PENDING_REWRITE"
    if test "$command" = "$_CLOSE_ENOUGH_PENDING_REWRITE"
      set -e _CLOSE_ENOUGH_PENDING_REWRITE
      commandline -f execute
      return
    end
    set -e _CLOSE_ENOUGH_PENDING_REWRITE
  end
  _close_enough_handshake; or return
  set -l record (command close-enough daemon request --operation pre-send --shell fish --session "$fish_pid" --ensure=false --format record --command "$command" 2>/dev/null)
  if test $status -ne 0
    set -g _CLOSE_ENOUGH_DAEMON_READY 0
    return
  end
  set -l fields (string split \t -- $record)
  if test (count $fields) -ne 7
    return
  end
  if test "$fields[1]" != 1
    return
  end
  if test "$fields[2]" = submit
    commandline -f execute
    return
  end
  if test "$fields[2]" = rewrite
    set -l suggestion (_close_enough_decode "$fields[7]")
    set -l cause (_close_enough_decode "$fields[5]")
    or return
    if test "$fields[3]" != safe; or test -z "$suggestion"
      echo "close-enough: refused unsafe rewrite" >&2
      commandline -f repaint
      return
    end
    commandline -r "$suggestion"
    set -g _CLOSE_ENOUGH_PENDING_REWRITE "$suggestion"
    echo "close-enough corrected: $suggestion ($cause; press Enter again)" >&2
    return
  end
  if test "$fields[2]" = hint
    set -l suggestion_key "$fields[7]"
    set -l suggestion (_close_enough_decode "$fields[7]")
    set -l cause (_close_enough_decode "$fields[5]")
    or return
    if _close_enough_allow_suggestion "$suggestion_key"
      echo "close-enough [$fields[3]/$fields[4]]: $suggestion ($cause)" >&2
    end
    commandline -f execute
    return
  end
  if test "$fields[2]" = interrupt
    set -l suggestion (_close_enough_decode "$fields[7]")
    set -l cause (_close_enough_decode "$fields[5]")
    or return
    echo "close-enough [$fields[3]/$fields[4]]: $suggestion ($cause)" >&2
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
  set -l command_status $status
  set -l command $argv[1]
  if test -z "$command"
    return
  end
  if test $command_status -eq 0
    command close-enough daemon request --operation post-success --shell fish --session "$fish_pid" --ensure=false --command "$command" >/dev/null 2>/dev/null
    return
  end
  if test $command_status -ne 0
    set -l record (command close-enough daemon request --operation post-failure --shell fish --session "$fish_pid" --format record --command "$command" 2>/dev/null)
    if test $status -ne 0
      return
    end
    set -l fields (string split \t -- $record)
    if test (count $fields) -ne 7
      return
    end
    if test "$fields[1]" != 1; or test "$fields[2]" = none
      return
    end
    set -l suggestion_key "$fields[7]"
    set -l suggestion (_close_enough_decode "$fields[7]")
    set -l cause (_close_enough_decode "$fields[5]")
    or return
    if test -n "$suggestion"; and _close_enough_allow_suggestion "$suggestion_key"
      echo "close-enough [$fields[3]/$fields[4]]: $suggestion ($cause)"
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
  $record = & close-enough daemon request --operation pre-send --shell powershell --session $PID --command $command 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)) { return }
  try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { return }
  if ($decision.version -ne 1) { return }
  if ($decision.action -eq 'rewrite') {
    if ($decision.risk -ne 'safe' -or [string]::IsNullOrEmpty($decision.suggestion)) {
      Write-Host "close-enough: refused unsafe rewrite"
      return
    }
    [Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $decision.suggestion)
    Write-Host "close-enough corrected: $($decision.suggestion) ($($decision.explanation); press Enter again)"
    return
  }
  if ($decision.action -eq 'hint') {
    if (Allow-CloseEnoughSuggestion $decision.suggestion) { Write-Host "close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion) ($($decision.explanation))" }
    [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    return
  }
  if ($decision.action -eq 'submit') {
    [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    return
  }
  if ($decision.action -eq 'interrupt') {
    Write-Host "close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion) ($($decision.explanation))"
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
  if ($status -and $null -ne $entry -and $entry.Id -ne $global:CloseEnoughLastHistoryId -and -not [string]::IsNullOrEmpty($entry.CommandLine)) {
    $global:CloseEnoughLastHistoryId = $entry.Id
    & close-enough daemon request --operation post-success --shell powershell --session $PID --ensure=false --command $entry.CommandLine 2>$null | Out-Null
  }
  if (-not $status -and $null -ne $entry -and $entry.Id -ne $global:CloseEnoughLastHistoryId -and -not [string]::IsNullOrEmpty($entry.CommandLine)) {
    $global:CloseEnoughLastHistoryId = $entry.Id
    $record = & close-enough daemon request --operation post-failure --shell powershell --session $PID --format json --command $entry.CommandLine 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($record)) {
      try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { $decision = $null }
      if ($null -ne $decision -and $decision.version -eq 1 -and $decision.action -ne 'none' -and -not [string]::IsNullOrEmpty($decision.suggestion) -and (Allow-CloseEnoughSuggestion $decision.suggestion)) { Write-Host "close-enough [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion) ($($decision.explanation))" }
    }
  }
  if ($null -ne $global:CloseEnoughPreviousPrompt) { & $global:CloseEnoughPreviousPrompt }
}
}
`
