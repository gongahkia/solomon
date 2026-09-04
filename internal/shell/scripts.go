package shell

const zshScript = `# solomon zsh integration
if (( ! ${+_SOLOMON_ZSH_LOADED} )); then
typeset -g _SOLOMON_ZSH_LOADED=1
function _solomon_decode {
  if base64 --decode </dev/null >/dev/null 2>&1; then
    print -rn -- "$1" | base64 --decode
  else
    print -rn -- "$1" | base64 -D
  fi
}
typeset -gi _SOLOMON_DIAGNOSTIC_COUNT=0
typeset -gi _SOLOMON_DIAGNOSTIC_LIMIT=5
typeset -gi _SOLOMON_DAEMON_READY=0
typeset -gi _SOLOMON_FAILURE_SEQUENCE=0
typeset -g _SOLOMON_PENDING_REWRITE=''
typeset -g _SOLOMON_PENDING_UNDO_TOKEN=''
typeset -g _SOLOMON_UNDO_WIDGET=''
typeset -g _SOLOMON_AUTOMATIC_REWRITE=''
typeset -g _SOLOMON_PENDING_FAILURE_TOKEN=''
typeset -g _SOLOMON_LAST_COMMAND_TOKEN=none
typeset -gA _SOLOMON_SEEN_SUGGESTIONS
function _solomon_allow_diagnostic {
  (( _SOLOMON_DIAGNOSTIC_COUNT < _SOLOMON_DIAGNOSTIC_LIMIT )) || return 1
  (( ++_SOLOMON_DIAGNOSTIC_COUNT ))
}
function _solomon_allow_suggestion {
  [[ -n "$1" ]] || return 1
  (( ${+_SOLOMON_SEEN_SUGGESTIONS[$1]} )) && return 1
  _solomon_allow_diagnostic || return 1
  _SOLOMON_SEEN_SUGGESTIONS[$1]=1
}
function _solomon_handshake {
  (( _SOLOMON_DAEMON_READY )) && return 0
  local record version action
  local -a fields
  record="$(command solomon daemon request --operation handshake --shell zsh --session "$$" --ensure=true --format record 2>/dev/null)" || return 1
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return 1
  version="${fields[1]}" action="${fields[2]}"
  [[ "$version" == "1" && "$action" == ready ]] || return 1
  _SOLOMON_DAEMON_READY=1
}
function _solomon_restore_undo {
  local binding
  [[ -n "$_SOLOMON_UNDO_WIDGET" ]] || return 0
  binding="$(bindkey -M main '^G')" || return 0
  [[ "$binding" == *" _solomon_undo_rewrite" ]] || return 0
  bindkey -M main '^G' "$_SOLOMON_UNDO_WIDGET"
  _SOLOMON_UNDO_WIDGET=''
}
function _solomon_clear_pending_undo {
  _SOLOMON_PENDING_UNDO_TOKEN=''
  _solomon_restore_undo
}
function _solomon_clear_pending_rewrite {
  _SOLOMON_PENDING_REWRITE=''
  _SOLOMON_AUTOMATIC_REWRITE=''
  _solomon_clear_pending_undo
}
function _solomon_bind_undo {
  local binding widget
  [[ -z "$_SOLOMON_UNDO_WIDGET" ]] || return 0
  binding="$(bindkey -M main '^G')" || return 1
  widget="${binding##* }"
  [[ -n "$widget" && "$widget" != \"* ]] || return 1
  _SOLOMON_UNDO_WIDGET="$widget"
  bindkey -M main '^G' _solomon_undo_rewrite || { _SOLOMON_UNDO_WIDGET=''; return 1; }
}
function _solomon_undo_rewrite {
  local record version action risk suggestion
  local -a fields
  [[ -n "$_SOLOMON_PENDING_REWRITE" && -n "$_SOLOMON_PENDING_UNDO_TOKEN" ]] || return 0
  record="$(command solomon daemon request --operation undo --shell zsh --session "$$" --token "$_SOLOMON_PENDING_UNDO_TOKEN" --ensure=false --format record 2>/dev/null)" || { _solomon_clear_pending_undo; return 0; }
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || { _solomon_clear_pending_undo; return 0; }
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" suggestion="${fields[7]}"
  [[ "$version" == "1" && "$action" == edit-in-buffer && "$risk" == safe ]] || { _solomon_clear_pending_undo; return 0; }
  suggestion="$(_solomon_decode "$suggestion")" || { _solomon_clear_pending_undo; return 0; }
  [[ -n "$suggestion" ]] || { _solomon_clear_pending_undo; return 0; }
  BUFFER="$suggestion"
  _solomon_clear_pending_rewrite
  zle -M "solomon restored: $suggestion"
  zle -R
}
function _solomon_check {
  local command record version action risk confidence cause consequence suggestion suggestion_key undo_token
  local -a fields
  command="$BUFFER"
  if [[ -n "$_SOLOMON_PENDING_REWRITE" ]]; then
    if [[ "$command" == "$_SOLOMON_PENDING_REWRITE" ]]; then
      _solomon_clear_pending_rewrite
      _SOLOMON_AUTOMATIC_REWRITE="$command"
      return 0
    fi
    _solomon_clear_pending_rewrite
  fi
  _solomon_handshake || return 0
  record="$(command solomon daemon request --operation pre-send --shell zsh --session "$$" --ensure=false --format undo-record --command "$command" 2>/dev/null)" || { _SOLOMON_DAEMON_READY=0; return 0; }
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 || ${#fields} == 8 )) || return 0
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" confidence="${fields[4]}" cause="${fields[5]}" consequence="${fields[6]}" suggestion="${fields[7]}"
  [[ "$version" == "1" ]] || return 0
  [[ "$action" == none ]] && return 0
  suggestion_key="$suggestion"
  suggestion="$(_solomon_decode "$suggestion")" || return 0
  cause="$(_solomon_decode "$cause")" || cause=''
  if [[ "$action" == submit ]]; then
    return 0
  fi
  if [[ "$action" == rewrite ]]; then
    if [[ "$risk" != safe || -z "$suggestion" ]]; then
      zle -M "solomon: refused unsafe rewrite"
      return 1
    fi
    BUFFER="$suggestion"
    _SOLOMON_PENDING_REWRITE="$suggestion"
    undo_token=''
    if (( ${#fields} == 8 )) && [[ -n "${fields[8]}" ]]; then
      undo_token="$(_solomon_decode "${fields[8]}")" || undo_token=''
      _SOLOMON_PENDING_UNDO_TOKEN="$undo_token"
      _solomon_bind_undo || _SOLOMON_PENDING_UNDO_TOKEN=''
    fi
    if [[ -n "$_SOLOMON_PENDING_UNDO_TOKEN" ]]; then
      zle -M "solomon corrected: $suggestion ($cause; press Ctrl-G to undo or Enter again)"
    else
      zle -M "solomon corrected: $suggestion ($cause; press Enter again)"
    fi
    zle -R
    return 1
  fi
  if [[ "$action" == hint ]]; then
    if _solomon_allow_suggestion "$suggestion_key"; then
      zle -M "solomon [$risk/$confidence]: $suggestion ($cause)"
    fi
    return 0
  fi
  if [[ "$action" == interrupt ]]; then
    zle -M "solomon [$risk/$confidence]: $suggestion ($cause)"
    return 1
  fi
  return 0
}
function _solomon_accept_line {
  if ! _solomon_check; then
    return 0
  fi
  zle "$_SOLOMON_ENTER_WIDGET"
}
zle -N _solomon_accept_line
zle -N _solomon_undo_rewrite
typeset -g _SOLOMON_ENTER_WIDGET=''
function _solomon_bind_enter {
  local binding widget
  binding="$(bindkey -M main '^M')" || return 0
  widget="${binding##* }"
  [[ -z "$widget" || "$widget" == \"* ]] && return 0
  _SOLOMON_ENTER_WIDGET="$widget"
  bindkey -M main '^M' _solomon_accept_line
}
function _solomon_restore_enter {
  local binding
  binding="$(bindkey -M main '^M')" || return 0
  [[ "$binding" == *" _solomon_accept_line" ]] || return 0
  bindkey -M main '^M' "$_SOLOMON_ENTER_WIDGET"
  _SOLOMON_ENTER_WIDGET=''
}
_solomon_bind_enter
typeset -g _SOLOMON_LAST_COMMAND=''
function _solomon_preexec {
  if [[ -n "${SOLOMON_CAPTURE_MARKER:-}" ]]; then
    [[ -z "${SOLOMON_CAPTURE_SOCKET:-}" ]] || command solomon capture reset --socket "$SOLOMON_CAPTURE_SOCKET" >/dev/null 2>&1
    print -rn -- $'\e]1337;Solomon='"$SOLOMON_CAPTURE_MARKER"$'\a'
  fi
  _SOLOMON_LAST_COMMAND="$1"
  _SOLOMON_PENDING_REWRITE=''
  _solomon_clear_pending_undo
  if [[ "$1" == "$_SOLOMON_AUTOMATIC_REWRITE" ]]; then
    _SOLOMON_LAST_COMMAND_TOKEN=none
  else
    _SOLOMON_LAST_COMMAND_TOKEN="${_SOLOMON_PENDING_FAILURE_TOKEN:-none}"
    _SOLOMON_PENDING_FAILURE_TOKEN=''
  fi
  _SOLOMON_AUTOMATIC_REWRITE=''
}
function _solomon_precmd {
  local exit_status=$? command="$_SOLOMON_LAST_COMMAND" token="$_SOLOMON_LAST_COMMAND_TOKEN" record version action risk confidence cause suggestion suggestion_key
  local -a fields
  _SOLOMON_LAST_COMMAND=''
  _SOLOMON_LAST_COMMAND_TOKEN=none
  [[ -z "$command" ]] && return
  if [[ $exit_status -eq 0 ]]; then
    command solomon daemon request --operation post-success --shell zsh --session "$$" --token "$token" --ensure=false --command "$command" >/dev/null 2>&1
    return
  fi
  (( ++_SOLOMON_FAILURE_SEQUENCE ))
  token="failure-$$-${_SOLOMON_FAILURE_SEQUENCE}"
  _SOLOMON_PENDING_FAILURE_TOKEN="$token"
  local failure_output="exit status $exit_status" captured
  if [[ -n "${SOLOMON_CAPTURE_SOCKET:-}" ]]; then
    captured="$(command solomon capture read --socket "$SOLOMON_CAPTURE_SOCKET" --command "$command" 2>/dev/null)" && [[ -n "$captured" ]] && failure_output="$captured"
  fi
  record="$(command solomon daemon request --operation post-failure --shell zsh --session "$$" --token "$token" --format record --command "$command" --failure-output "$failure_output" 2>/dev/null)" || return
  fields=("${(@ps:\t:)record}")
  (( ${#fields} == 7 )) || return
  version="${fields[1]}" action="${fields[2]}" risk="${fields[3]}" confidence="${fields[4]}" cause="${fields[5]}" suggestion="${fields[7]}"
  [[ "$version" == "1" && "$action" != none ]] || return
  suggestion_key="$suggestion"
  suggestion="$(_solomon_decode "$suggestion")" || return
  cause="$(_solomon_decode "$cause")" || cause=''
  [[ -n "$suggestion" ]] || return
  if _solomon_allow_suggestion "$suggestion_key"; then
    print -r -- "solomon [$risk/$confidence]: $suggestion ($cause)"
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook preexec _solomon_preexec
add-zsh-hook precmd _solomon_precmd
fi
`

const fishScript = `# solomon fish integration
if not set -q _SOLOMON_FISH_LOADED
  set -g _SOLOMON_FISH_LOADED 1
set -g _SOLOMON_DIAGNOSTIC_COUNT 0
set -g _SOLOMON_DIAGNOSTIC_LIMIT 5
set -g _SOLOMON_DAEMON_READY 0
set -g _SOLOMON_FAILURE_SEQUENCE 0
set -g _SOLOMON_PENDING_REWRITE
set -g _SOLOMON_PENDING_UNDO_TOKEN
set -g _SOLOMON_AUTOMATIC_REWRITE 0
set -g _SOLOMON_PENDING_FAILURE_TOKEN
set -g _SOLOMON_SEEN_SUGGESTIONS
function _solomon_allow_diagnostic
  if test $_SOLOMON_DIAGNOSTIC_COUNT -ge $_SOLOMON_DIAGNOSTIC_LIMIT
    return 1
  end
  set -g _SOLOMON_DIAGNOSTIC_COUNT (math $_SOLOMON_DIAGNOSTIC_COUNT + 1)
end
function _solomon_allow_suggestion
  set -l key $argv[1]
  test -n "$key"; or return 1
  contains -- "$key" $_SOLOMON_SEEN_SUGGESTIONS; and return 1
  _solomon_allow_diagnostic; or return 1
  set -ga _SOLOMON_SEEN_SUGGESTIONS "$key"
end
function _solomon_decode
  if base64 --decode </dev/null >/dev/null 2>&1
    printf '%s' "$argv[1]" | base64 --decode
  else
    printf '%s' "$argv[1]" | base64 -D
  end
end
function _solomon_handshake
  if test "$_SOLOMON_DAEMON_READY" = 1
    return
  end
  set -l record (command solomon daemon request --operation handshake --shell fish --session "$fish_pid" --ensure=true --format record 2>/dev/null)
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
  set -g _SOLOMON_DAEMON_READY 1
end
function _solomon_restore_undo
  if not set -q _SOLOMON_FISH_UNDO_BOUND
    return
  end
  if string match -q "* _solomon_undo_rewrite" -- (bind \cg)
    bind --erase \cg
  end
  set -e _SOLOMON_FISH_UNDO_BOUND
end
function _solomon_clear_pending_undo
  set -e _SOLOMON_PENDING_UNDO_TOKEN
  _solomon_restore_undo
end
function _solomon_clear_pending_rewrite
  set -e _SOLOMON_PENDING_REWRITE
  set -g _SOLOMON_AUTOMATIC_REWRITE 0
  _solomon_clear_pending_undo
end
function _solomon_bind_undo
  if set -q _SOLOMON_FISH_UNDO_BOUND
    return
  end
  bind \cg >/dev/null 2>&1
  if test $status -eq 0
    return 1
  end
  set -g _SOLOMON_FISH_UNDO_BOUND 1
  bind \cg _solomon_undo_rewrite; or begin
    set -e _SOLOMON_FISH_UNDO_BOUND
    return 1
  end
end
function _solomon_undo_rewrite
  if not set -q _SOLOMON_PENDING_REWRITE; or not set -q _SOLOMON_PENDING_UNDO_TOKEN
    return
  end
  set -l record (command solomon daemon request --operation undo --shell fish --session "$fish_pid" --token "$_SOLOMON_PENDING_UNDO_TOKEN" --ensure=false --format record 2>/dev/null)
  if test $status -ne 0
    _solomon_clear_pending_undo
    return
  end
  set -l fields (string split \t -- $record)
  if test (count $fields) -ne 7; or test "$fields[1]" != 1; or test "$fields[2]" != edit-in-buffer; or test "$fields[3]" != safe
    _solomon_clear_pending_undo
    return
  end
  set -l suggestion (_solomon_decode "$fields[7]")
  if test $status -ne 0; or test -z "$suggestion"
    _solomon_clear_pending_undo
    return
  end
  commandline -r "$suggestion"
  _solomon_clear_pending_rewrite
  echo "solomon restored: $suggestion" >&2
  commandline -f repaint
end
function _solomon_accept_line
  set -l command (commandline -b)
  if set -q _SOLOMON_PENDING_REWRITE; and test -n "$_SOLOMON_PENDING_REWRITE"
    if test "$command" = "$_SOLOMON_PENDING_REWRITE"
      _solomon_clear_pending_rewrite
      set -g _SOLOMON_AUTOMATIC_REWRITE 1
      commandline -f execute
      return
    end
    _solomon_clear_pending_rewrite
  end
  _solomon_handshake; or begin
    commandline -f execute
    return
  end
  set -l record (command solomon daemon request --operation pre-send --shell fish --session "$fish_pid" --ensure=false --format undo-record --command "$command" 2>/dev/null)
  if test $status -ne 0
    set -g _SOLOMON_DAEMON_READY 0
    commandline -f execute
    return
  end
  set -l fields (string split \t -- $record)
  if test (count $fields) -ne 7; and test (count $fields) -ne 8
    commandline -f execute
    return
  end
  if test "$fields[1]" != 1
    commandline -f execute
    return
  end
  if test "$fields[2]" = submit
    commandline -f execute
    return
  end
  if test "$fields[2]" = rewrite
    set -l suggestion (_solomon_decode "$fields[7]"); or begin
      commandline -f execute
      return
    end
    set -l cause (_solomon_decode "$fields[5]"); or begin
      commandline -f execute
      return
    end
    if test "$fields[3]" != safe; or test -z "$suggestion"
      echo "solomon: refused unsafe rewrite" >&2
      commandline -f repaint
      return
    end
    commandline -r "$suggestion"
    set -g _SOLOMON_PENDING_REWRITE "$suggestion"
    if test (count $fields) -eq 8; and test -n "$fields[8]"
      set -l undo_token (_solomon_decode "$fields[8]")
      if test $status -eq 0; and test -n "$undo_token"
        set -g _SOLOMON_PENDING_UNDO_TOKEN "$undo_token"
        _solomon_bind_undo; or set -e _SOLOMON_PENDING_UNDO_TOKEN
      end
    end
    if set -q _SOLOMON_PENDING_UNDO_TOKEN; and test -n "$_SOLOMON_PENDING_UNDO_TOKEN"
      echo "solomon corrected: $suggestion ($cause; press Ctrl-G to undo or Enter again)" >&2
    else
      echo "solomon corrected: $suggestion ($cause; press Enter again)" >&2
    end
    return
  end
  if test "$fields[2]" = hint
    set -l suggestion_key "$fields[7]"
    set -l suggestion (_solomon_decode "$fields[7]"); or begin
      commandline -f execute
      return
    end
    set -l cause (_solomon_decode "$fields[5]"); or begin
      commandline -f execute
      return
    end
    if _solomon_allow_suggestion "$suggestion_key"
      echo "solomon [$fields[3]/$fields[4]]: $suggestion ($cause)" >&2
    end
    commandline -f execute
    return
  end
  if test "$fields[2]" = interrupt
    set -l suggestion (_solomon_decode "$fields[7]"); or begin
      commandline -f execute
      return
    end
    set -l cause (_solomon_decode "$fields[5]"); or begin
      commandline -f execute
      return
    end
    echo "solomon [$fields[3]/$fields[4]]: $suggestion ($cause)" >&2
    commandline -f repaint
    return
  end
  commandline -f execute
end
function _solomon_bind_enter
  set -l binding (bind \r)
  if test "$binding" != "bind --preset enter execute"
    return
  end
  set -g _SOLOMON_FISH_ENTER_BOUND 1
  bind \r _solomon_accept_line
end
function _solomon_restore_enter
  if not set -q _SOLOMON_FISH_ENTER_BOUND
    return
  end
  if string match -q "* _solomon_accept_line" -- (bind \r)
    bind --erase \r
  end
  set -e _SOLOMON_FISH_ENTER_BOUND
end
_solomon_bind_enter
function _solomon_post_failure --on-event fish_postexec
  set -l command_status $status
  set -l command $argv[1]
  set -l token none
  if test -z "$command"
    return
  end
  if test "$_SOLOMON_AUTOMATIC_REWRITE" != 1
    if set -q _SOLOMON_PENDING_FAILURE_TOKEN; and test -n "$_SOLOMON_PENDING_FAILURE_TOKEN"
      set token "$_SOLOMON_PENDING_FAILURE_TOKEN"
      set -e _SOLOMON_PENDING_FAILURE_TOKEN
    end
  end
  set -g _SOLOMON_AUTOMATIC_REWRITE 0
  if test $command_status -eq 0
    command solomon daemon request --operation post-success --shell fish --session "$fish_pid" --token "$token" --ensure=false --command "$command" >/dev/null 2>/dev/null
    return
  end
  if test $command_status -ne 0
    set -g _SOLOMON_FAILURE_SEQUENCE (math $_SOLOMON_FAILURE_SEQUENCE + 1)
    set token "failure-$fish_pid-$_SOLOMON_FAILURE_SEQUENCE"
    set -g _SOLOMON_PENDING_FAILURE_TOKEN "$token"
    set -l record (command solomon daemon request --operation post-failure --shell fish --session "$fish_pid" --token "$token" --format record --command "$command" --failure-output "exit status $command_status" 2>/dev/null)
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
    set -l suggestion (_solomon_decode "$fields[7]")
    set -l cause (_solomon_decode "$fields[5]")
    or return
    if test -n "$suggestion"; and _solomon_allow_suggestion "$suggestion_key"
      echo "solomon [$fields[3]/$fields[4]]: $suggestion ($cause)"
    end
  end
end
end
`

const bashScript = `# solomon bash integration
if [[ -z "${_SOLOMON_BASH_LOADED:-}" ]]; then
_SOLOMON_BASH_LOADED=1
_SOLOMON_BASH_DIAGNOSTIC_COUNT=0
_SOLOMON_BASH_DIAGNOSTIC_LIMIT=5
_SOLOMON_BASH_FAILURE_SEQUENCE=0
_SOLOMON_BASH_LAST_COMMAND=''
_SOLOMON_BASH_SEEN_SUGGESTIONS=$'\n'
_solomon_bash_decode() {
  if base64 --decode </dev/null >/dev/null 2>&1; then
    printf '%s' "$1" | base64 --decode
  else
    printf '%s' "$1" | base64 -D
  fi
}
_solomon_bash_allow_suggestion() {
  local key="$1"
  [[ -n "$key" ]] || return 1
  case "$_SOLOMON_BASH_SEEN_SUGGESTIONS" in *$'\n'"$key"$'\n'*) return 1 ;; esac
  (( _SOLOMON_BASH_DIAGNOSTIC_COUNT < _SOLOMON_BASH_DIAGNOSTIC_LIMIT )) || return 1
  (( _SOLOMON_BASH_DIAGNOSTIC_COUNT++ ))
  _SOLOMON_BASH_SEEN_SUGGESTIONS+="$key"$'\n'
}
_solomon_bash_capture_mark() {
  [[ -n "${SOLOMON_CAPTURE_MARKER:-}" ]] || return 0
  [[ -z "${SOLOMON_CAPTURE_SOCKET:-}" ]] || command solomon capture reset --socket "$SOLOMON_CAPTURE_SOCKET" >/dev/null 2>&1
  printf '\033]1337;Solomon=%s\a' "$SOLOMON_CAPTURE_MARKER"
}
_solomon_bash_precmd() {
  local exit_status=$? command token record version action risk confidence cause suggestion suggestion_key failure_output captured
  command="$(builtin fc -ln -1 2>/dev/null)" || { _solomon_bash_capture_mark; return 0; }
  command="${command%$'\n'}"
  _solomon_bash_capture_mark
  [[ -n "$command" && "$command" != "$_SOLOMON_BASH_LAST_COMMAND" ]] || return 0
  _SOLOMON_BASH_LAST_COMMAND="$command"
  [[ "$exit_status" -ne 0 ]] || return 0
  (( _SOLOMON_BASH_FAILURE_SEQUENCE++ ))
  token="failure-$$-$_SOLOMON_BASH_FAILURE_SEQUENCE"
  failure_output="exit status $exit_status"
  if [[ -n "${SOLOMON_CAPTURE_SOCKET:-}" ]]; then
    captured="$(command solomon capture read --socket "$SOLOMON_CAPTURE_SOCKET" --command "$command" 2>/dev/null)" && [[ -n "$captured" ]] && failure_output="$captured"
  fi
  record="$(command solomon daemon request --operation post-failure --shell bash --session "$$" --token "$token" --format record --command "$command" --failure-output "$failure_output" 2>/dev/null)" || return 0
  IFS=$'\t' read -r version action risk confidence cause _ suggestion <<< "$record"
  [[ "$version" == 1 && "$action" != none && -n "$suggestion" ]] || return 0
  suggestion_key="$suggestion"
  suggestion="$(_solomon_bash_decode "$suggestion")" || return 0
  cause="$(_solomon_bash_decode "$cause")" || cause=''
  if _solomon_bash_allow_suggestion "$suggestion_key"; then
    printf 'solomon [%s/%s]: %s (%s)\n' "$risk" "$confidence" "$suggestion" "$cause"
  fi
}
if [[ "${PROMPT_COMMAND:-}" != *"_solomon_bash_precmd"* ]]; then
  PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND};}_solomon_bash_precmd"
fi
fi
`

const powerShellScript = `# solomon PowerShell integration
if (-not $global:SolomonAdapterLoaded) {
$global:SolomonAdapterLoaded = $true
$global:SolomonLastHistoryId = 0
$global:SolomonDiagnosticCount = 0
$global:SolomonDiagnosticLimit = 5
$global:SolomonDaemonReady = $false
$global:SolomonFailureSequence = 0
$global:SolomonPendingRewrite = $null
$global:SolomonPendingUndoToken = $null
$global:SolomonPreviousUndoHandler = $null
$global:SolomonUndoBound = $false
$global:SolomonAutomaticRewrite = $false
$global:SolomonPendingFailureToken = $null
$global:SolomonPendingConfirmation = $null
$global:SolomonSeenSuggestions = [System.Collections.Generic.HashSet[string]]::new()
$global:SolomonPreviousPrompt = (Get-Command prompt -CommandType Function -ErrorAction SilentlyContinue).ScriptBlock
$global:SolomonPreviousEnterHandler = Get-PSReadLineKeyHandler -Chord Enter
if ($global:SolomonPreviousEnterHandler.Function -eq 'AcceptLine') {
Set-PSReadLineKeyHandler -Key Enter -ScriptBlock {
  $line = $null; $cursor = $null
  [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
  $command = $line
  if (-not [string]::IsNullOrEmpty($global:SolomonPendingRewrite)) {
    if ($command -eq $global:SolomonPendingRewrite) {
      Clear-SolomonPendingRewrite
      $global:SolomonAutomaticRewrite = $true
      [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
      return
    }
    Clear-SolomonPendingRewrite
  }
  if (-not [string]::IsNullOrEmpty($global:SolomonPendingConfirmation) -and $command -ne $global:SolomonPendingConfirmation) {
    $global:SolomonPendingConfirmation = $null
  }
  if (-not (Test-SolomonDaemonHandshake)) { [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine(); return }
  $record = & solomon daemon request --operation pre-send --shell powershell --session $PID --ensure=false --command $command 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)) { $global:SolomonDaemonReady = $false; $global:SolomonPendingConfirmation = $null; [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine(); return }
  try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { $global:SolomonDaemonReady = $false; $global:SolomonPendingConfirmation = $null; [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine(); return }
  if ($decision.version -ne 1) { $global:SolomonDaemonReady = $false; $global:SolomonPendingConfirmation = $null; [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine(); return }
  if ($decision.action -eq 'rewrite') {
    if ($decision.risk -ne 'safe' -or [string]::IsNullOrEmpty($decision.suggestion)) {
      Write-Host "solomon: refused unsafe rewrite"
      return
    }
    [Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $decision.suggestion)
    $global:SolomonPendingRewrite = $decision.suggestion
    $global:SolomonPendingUndoToken = $decision.undo_token
    if (-not [string]::IsNullOrEmpty($global:SolomonPendingUndoToken) -and (Enable-SolomonUndoBinding)) {
      Write-Host "solomon corrected: $($decision.suggestion) ($($decision.explanation); press Ctrl-G to undo or Enter again)"
    } else {
      $global:SolomonPendingUndoToken = $null
      Write-Host "solomon corrected: $($decision.suggestion) ($($decision.explanation); press Enter again)"
    }
    return
  }
  if ($decision.action -eq 'hint') {
    if (Allow-SolomonSuggestion $decision.suggestion) { Write-Host "solomon [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion) ($($decision.explanation))" }
    [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    return
  }
  if ($decision.action -eq 'submit') {
    $global:SolomonPendingConfirmation = $null
    [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
    return
  }
  if ($decision.action -eq 'interrupt') {
    Write-Host "solomon [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion) ($($decision.explanation))"
    $global:SolomonPendingConfirmation = $command
    return
  }
  [Microsoft.PowerShell.PSConsoleReadLine]::AcceptLine()
}
}
function global:Test-SolomonDaemonHandshake {
  if ($global:SolomonDaemonReady) { return $true }
  $record = & solomon daemon request --operation handshake --shell powershell --session $PID --ensure=true --format json 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)) { return $false }
  try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { return $false }
  if ($decision.version -ne 1 -or $decision.action -ne 'ready') { return $false }
  $global:SolomonDaemonReady = $true
  return $true
}
function global:Allow-SolomonDiagnostic {
  if ($global:SolomonDiagnosticCount -ge $global:SolomonDiagnosticLimit) { return $false }
  $global:SolomonDiagnosticCount += 1
  return $true
}
function global:Allow-SolomonSuggestion {
  param([string]$Suggestion)
  if ([string]::IsNullOrEmpty($Suggestion) -or $global:SolomonSeenSuggestions.Contains($Suggestion)) { return $false }
  if (-not (Allow-SolomonDiagnostic)) { return $false }
  [void]$global:SolomonSeenSuggestions.Add($Suggestion)
  return $true
}
function global:Restore-SolomonUndoBinding {
  if (-not $global:SolomonUndoBound) { return }
  if ($null -ne $global:SolomonPreviousUndoHandler -and -not [string]::IsNullOrEmpty($global:SolomonPreviousUndoHandler.Function)) {
    Set-PSReadLineKeyHandler -Key Ctrl+g -Function $global:SolomonPreviousUndoHandler.Function
  }
  $global:SolomonPreviousUndoHandler = $null
  $global:SolomonUndoBound = $false
}
function global:Clear-SolomonPendingUndo {
  $global:SolomonPendingUndoToken = $null
  Restore-SolomonUndoBinding
}
function global:Clear-SolomonPendingRewrite {
  $global:SolomonPendingRewrite = $null
  $global:SolomonAutomaticRewrite = $false
  Clear-SolomonPendingUndo
}
function global:Enable-SolomonUndoBinding {
  if ($global:SolomonUndoBound) { return $true }
  $handler = Get-PSReadLineKeyHandler -Chord Ctrl+g -ErrorAction SilentlyContinue
  if ($null -eq $handler -or [string]::IsNullOrEmpty($handler.Function)) { return $false }
  $global:SolomonPreviousUndoHandler = $handler
  try { Set-PSReadLineKeyHandler -Key Ctrl+g -ScriptBlock { Invoke-SolomonPendingRewriteUndo } } catch { $global:SolomonPreviousUndoHandler = $null; return $false }
  $global:SolomonUndoBound = $true
  return $true
}
function global:Invoke-SolomonPendingRewriteUndo {
  if ([string]::IsNullOrEmpty($global:SolomonPendingRewrite) -or [string]::IsNullOrEmpty($global:SolomonPendingUndoToken)) { return }
  $record = & solomon daemon request --operation undo --shell powershell --session $PID --token $global:SolomonPendingUndoToken --ensure=false --format json 2>$null
  if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($record)) { Clear-SolomonPendingUndo; return }
  try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { Clear-SolomonPendingUndo; return }
  if ($decision.version -ne 1 -or $decision.action -ne 'edit-in-buffer' -or $decision.risk -ne 'safe' -or [string]::IsNullOrEmpty($decision.suggestion)) { Clear-SolomonPendingUndo; return }
  $line = $null; $cursor = $null
  [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
  [Microsoft.PowerShell.PSConsoleReadLine]::Replace(0, $line.Length, $decision.suggestion)
  Clear-SolomonPendingRewrite
  Write-Host "solomon restored: $($decision.suggestion)"
}
function global:Restore-SolomonEnterHandler {
  if ($null -ne $global:SolomonPreviousEnterHandler -and $global:SolomonPreviousEnterHandler.Function -eq 'AcceptLine') {
    Set-PSReadLineKeyHandler -Key Enter -Function AcceptLine
  }
}
function global:prompt {
  $status = $?
  $entry = Get-History -Count 1
  $token = 'none'
  $automaticRewrite = $global:SolomonAutomaticRewrite
  $global:SolomonAutomaticRewrite = $false
  if ($status -and $null -ne $entry -and $entry.Id -ne $global:SolomonLastHistoryId -and -not [string]::IsNullOrEmpty($entry.CommandLine)) {
    $global:SolomonLastHistoryId = $entry.Id
    if (-not $automaticRewrite -and -not [string]::IsNullOrEmpty($global:SolomonPendingFailureToken)) {
      $token = $global:SolomonPendingFailureToken
      $global:SolomonPendingFailureToken = $null
    }
    & solomon daemon request --operation post-success --shell powershell --session $PID --token $token --ensure=false --command $entry.CommandLine 2>$null | Out-Null
  }
  if (-not $status -and $null -ne $entry -and $entry.Id -ne $global:SolomonLastHistoryId -and -not [string]::IsNullOrEmpty($entry.CommandLine)) {
    $global:SolomonLastHistoryId = $entry.Id
    $global:SolomonFailureSequence += 1
    $token = "failure-$PID-$($global:SolomonFailureSequence)"
    $global:SolomonPendingFailureToken = $token
    $failureOutput = "exit status $LASTEXITCODE"
    $record = & solomon daemon request --operation post-failure --shell powershell --session $PID --token $token --format json --command $entry.CommandLine --failure-output $failureOutput 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($record)) {
      try { $decision = $record | ConvertFrom-Json -ErrorAction Stop } catch { $decision = $null }
      if ($null -ne $decision -and $decision.version -eq 1 -and $decision.action -ne 'none' -and -not [string]::IsNullOrEmpty($decision.suggestion) -and (Allow-SolomonSuggestion $decision.suggestion)) { Write-Host "solomon [$($decision.risk)/$($decision.confidence)]: $($decision.suggestion) ($($decision.explanation))" }
    }
  }
  if ($null -ne $global:SolomonPreviousPrompt) { & $global:SolomonPreviousPrompt }
}
}
`
