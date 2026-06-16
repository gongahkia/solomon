if ($script:__SHISA_PWSH_INIT) { return }

$script:__SHISA_PWSH_INIT = $true
if (-not $env:SHISA_BIN) { $env:SHISA_BIN = "shisa" }
if (-not $env:SHISA_SOCKET) { $env:SHISA_SOCKET = "" }
if (-not $env:SHISA_INSTANT) { $env:SHISA_INSTANT = "0" }

function global:shisa_socket_path {
    if ($env:SHISA_SOCKET) { return $env:SHISA_SOCKET }
    if ($IsMacOS) { return (Join-Path $HOME "Library/Caches/shisa/shisa.sock") }
    if ($env:XDG_RUNTIME_DIR) { return (Join-Path $env:XDG_RUNTIME_DIR "shisa.sock") }
    $uid = (& id -u 2>$null)
    if ($uid) { return "/run/user/$uid/shisa.sock" }
    return (Join-Path $HOME ".cache/shisa/shisa.sock")
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
    if (-not $instant -and -not (Test-Path -LiteralPath $socketPath)) {
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

function global:Invoke-ShisaRedraw {
    [Console]::Write("`e[2K`r")
}
