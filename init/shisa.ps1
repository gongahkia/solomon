if ($script:__SHISA_PWSH_INIT) { return }

$script:__SHISA_PWSH_INIT = $true
if (-not $env:SHISA_BIN) { $env:SHISA_BIN = "shisa" }
if (-not $env:SHISA_SOCKET) { $env:SHISA_SOCKET = "" }
if (-not $env:SHISA_INSTANT) { $env:SHISA_INSTANT = "0" }
if (-not $env:SHISA_A11Y) { $env:SHISA_A11Y = "0" }

function global:Get-ShisaRtlLocale {
    $locale = if ($env:LC_ALL) { $env:LC_ALL } elseif ($env:LC_CTYPE) { $env:LC_CTYPE } elseif ($env:LANG) { $env:LANG } else { "" }
    $tag = (($locale -split '[.@_-]', 2)[0]).ToLowerInvariant()
    if (@("ar", "he", "fa", "ur", "ps", "dv", "yi") -contains $tag) { return "1" }
    return "0"
}

if (-not $env:SHISA_RTL) { $env:SHISA_RTL = Get-ShisaRtlLocale }
if (-not $env:SHISA_PWSH_ASYNC_EVENT) { $env:SHISA_PWSH_ASYNC_EVENT = "1" }
if (-not $env:SHISA_NEXTCMD_CHORD) { $env:SHISA_NEXTCMD_CHORD = "Ctrl+x,Ctrl+n" }
if (-not $env:SHISA_NEXTCMD_ACCEPT_CHORD) { $env:SHISA_NEXTCMD_ACCEPT_CHORD = "Tab" }
if (-not $env:SHISA_NEXTCMD_REJECT_CHORD) { $env:SHISA_NEXTCMD_REJECT_CHORD = "Escape" }
if (-not $env:SHISA_NEXTCMD_NEXT_CHORD) { $env:SHISA_NEXTCMD_NEXT_CHORD = "Alt+]" }
if (-not $env:SHISA_EXPLAIN_CHORD) { $env:SHISA_EXPLAIN_CHORD = "Ctrl+x,Ctrl+e" }
$script:SHISA_NEXTCMD_SUGGESTION = ""
$script:SHISA_EXPLAIN_LAST_COMMAND = ""
$script:SHISA_EXPLAIN_LAST_OUTPUT = ""
$script:SHISA_PWSH_ASYNC_SOURCE = "Shisa.AsyncFill"
$script:SHISA_PWSH_ASYNC_SUBSCRIBER = $null

function global:shisa_socket_path {
    if ($env:SHISA_SOCKET) { return $env:SHISA_SOCKET }
    if ($IsWindows) {
        try {
            $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
            if ($sid) { return "\\.\pipe\shisa-$sid" }
        } catch {}
    }
    if ($IsMacOS) { return (Join-Path $HOME "Library/Caches/shisa/shisa.sock") }
    if ($env:XDG_RUNTIME_DIR) { return (Join-Path $env:XDG_RUNTIME_DIR "shisa.sock") }
    $uid = (& id -u 2>$null)
    if ($uid) { return "/run/user/$uid/shisa.sock" }
    return (Join-Path $HOME ".cache/shisa/shisa.sock")
}

function global:shisa_socket_available {
    param([string]$Path)
    if ($IsWindows -and $Path.StartsWith("\\.\pipe\")) { return $true }
    return (Test-Path -LiteralPath $Path)
}

function global:shisa_prompt_fallback {
    return "$((Get-Location).Path)> "
}

function global:shisa_prompt_render {
    $lastCommandSucceeded = $?
    $lastNativeExitCode = $global:LASTEXITCODE
    $exitCode = if ($lastCommandSucceeded) { 0 } elseif ($null -ne $lastNativeExitCode) { [int]$lastNativeExitCode } else { 1 }
    $socketPath = shisa_socket_path
    $instant = $env:SHISA_INSTANT -eq "1"
    if (-not $instant -and -not (shisa_socket_available $socketPath)) {
        return (shisa_prompt_fallback)
    }

    $location = Get-Location
    $cwd = if ($location.ProviderPath) { $location.ProviderPath } else { $location.Path }
    $jobs = @(Get-Job -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Running" }).Count
    $args = @(
        "prompt",
        "--shell", "pwsh",
        "--cwd", $cwd,
        "--exit", "$exitCode",
        "--jobs", "$jobs",
        "--duration-ms", "0",
        "--socket", $socketPath
    )
    if ($instant) { $args += "--instant" }
    if ($env:SHISA_A11Y -eq "1") { $args += "--a11y" }
    if ($env:SHISA_RTL -eq "1") { $args += "--rtl" }

    try {
        $rendered = & $env:SHISA_BIN @args 2>$null
        $shisaExitCode = $global:LASTEXITCODE
        $global:LASTEXITCODE = $lastNativeExitCode
        if ($shisaExitCode -eq 0 -and $null -ne $rendered) {
            return ($rendered -join "`n")
        }
    } catch {
        $global:LASTEXITCODE = $lastNativeExitCode
    }
    return (shisa_prompt_fallback)
}

function global:prompt {
    shisa_prompt_render
}

function global:shisa_right_prompt_render {
    $lastCommandSucceeded = $?
    $lastNativeExitCode = $global:LASTEXITCODE
    $socketPath = shisa_socket_path
    if (-not (shisa_socket_available $socketPath)) { return "" }

    $location = Get-Location
    $cwd = if ($location.ProviderPath) { $location.ProviderPath } else { $location.Path }
    $jobs = @(Get-Job -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Running" }).Count
    $lastExit = if ($lastCommandSucceeded) { 0 } elseif ($null -ne $lastNativeExitCode) { [int]$lastNativeExitCode } else { 1 }
    $args = @(
        "prompt",
        "--right",
        "--shell", "pwsh",
        "--cwd", $cwd,
        "--exit", "$lastExit",
        "--jobs", "$jobs",
        "--duration-ms", "0",
        "--socket", $socketPath
    )
    if ($env:SHISA_A11Y -eq "1") { $args += "--a11y" }
    if ($env:SHISA_RTL -eq "1") { $args += "--rtl" }

    try {
        $rendered = & $env:SHISA_BIN @args 2>$null
        $shisaExitCode = $global:LASTEXITCODE
        $global:LASTEXITCODE = $lastNativeExitCode
        if ($shisaExitCode -eq 0 -and $null -ne $rendered) {
            return ($rendered -join "`n")
        }
    } catch {
        $global:LASTEXITCODE = $lastNativeExitCode
    }
    return ""
}

function global:Invoke-ShisaRedraw {
    [Console]::Write("`e[2K`r")
}

function global:Register-ShisaAsyncFillEvent {
    if ($env:SHISA_PWSH_ASYNC_EVENT -ne "1") { return $false }
    if (-not (Get-Command Register-EngineEvent -ErrorAction SilentlyContinue)) { return $false }
    if (Get-EventSubscriber -SourceIdentifier $script:SHISA_PWSH_ASYNC_SOURCE -ErrorAction SilentlyContinue) { return $true }
    try {
        $script:SHISA_PWSH_ASYNC_SUBSCRIBER = Register-EngineEvent -SourceIdentifier $script:SHISA_PWSH_ASYNC_SOURCE -Action { Invoke-ShisaRedraw } -ErrorAction Stop
        return $true
    } catch {
        $script:SHISA_PWSH_ASYNC_SUBSCRIBER = $null
        return $false
    }
}

function global:Invoke-ShisaAsyncFill {
    if (Get-Command New-Event -ErrorAction SilentlyContinue) {
        try {
            New-Event -SourceIdentifier $script:SHISA_PWSH_ASYNC_SOURCE | Out-Null
            return $true
        } catch {}
    }
    Invoke-ShisaRedraw
    return $false
}

function global:Invoke-ShisaNextCommand {
    $location = Get-Location
    $cwd = if ($location.ProviderPath) { $location.ProviderPath } else { $location.Path }
    $lastExit = if ($null -ne $global:LASTEXITCODE) { [int]$global:LASTEXITCODE } else { 0 }
    try {
        $suggestion = & $env:SHISA_BIN ai nextcmd --shell pwsh --cwd $cwd --last-exit "$lastExit" 2>$null
        $script:SHISA_NEXTCMD_SUGGESTION = ""
        if ($suggestion) {
            $script:SHISA_NEXTCMD_SUGGESTION = (($suggestion -join "`n").Trim())
            if ($script:SHISA_NEXTCMD_SUGGESTION) {
                [Console]::WriteLine("")
                [Console]::WriteLine("`e[2mshisa next: $($script:SHISA_NEXTCMD_SUGGESTION)`e[0m")
            }
        }
    } catch {}
}

function global:Accept-ShisaNextCommand {
    if ($script:SHISA_NEXTCMD_SUGGESTION) {
        [Microsoft.PowerShell.PSConsoleReadLine]::Insert($script:SHISA_NEXTCMD_SUGGESTION)
        $script:SHISA_NEXTCMD_SUGGESTION = ""
    } else {
        try { [Microsoft.PowerShell.PSConsoleReadLine]::MenuComplete() } catch {}
    }
}

function global:Reject-ShisaNextCommand {
    $script:SHISA_NEXTCMD_SUGGESTION = ""
}

function global:Invoke-ShisaExplain {
    try {
        $line = ""
        $cursor = 0
        [Microsoft.PowerShell.PSConsoleReadLine]::GetBufferState([ref]$line, [ref]$cursor)
        if ($line) {
            if ($line -eq $script:SHISA_EXPLAIN_LAST_COMMAND -and $script:SHISA_EXPLAIN_LAST_OUTPUT) {
                $output = $script:SHISA_EXPLAIN_LAST_OUTPUT
            } else {
                $output = & $env:SHISA_BIN ai explain --command $line 2>$null
                $script:SHISA_EXPLAIN_LAST_COMMAND = $line
                $script:SHISA_EXPLAIN_LAST_OUTPUT = ($output -join "`n")
            }
            if ($output) {
                [Console]::WriteLine("")
                [Console]::WriteLine(($output -join "`n"))
            }
        }
    } catch {}
}

if (Get-Command Set-PSReadLineKeyHandler -ErrorAction SilentlyContinue) {
    Set-PSReadLineKeyHandler -Chord $env:SHISA_NEXTCMD_CHORD -ScriptBlock { Invoke-ShisaNextCommand } 2>$null
    Set-PSReadLineKeyHandler -Chord $env:SHISA_NEXTCMD_ACCEPT_CHORD -ScriptBlock { Accept-ShisaNextCommand } 2>$null
    Set-PSReadLineKeyHandler -Chord $env:SHISA_NEXTCMD_REJECT_CHORD -ScriptBlock { Reject-ShisaNextCommand } 2>$null
    Set-PSReadLineKeyHandler -Chord $env:SHISA_NEXTCMD_NEXT_CHORD -ScriptBlock { Invoke-ShisaNextCommand } 2>$null
    Set-PSReadLineKeyHandler -Chord $env:SHISA_EXPLAIN_CHORD -ScriptBlock { Invoke-ShisaExplain } 2>$null
}

Register-ShisaAsyncFillEvent | Out-Null
