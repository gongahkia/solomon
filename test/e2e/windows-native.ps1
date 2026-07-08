$ErrorActionPreference = "Stop"

. .\init\shisa.ps1

$pipe = shisa_socket_path
if ($pipe -notmatch '^\\\\\.\\pipe\\shisa-S-') {
    throw "unexpected pipe path: $pipe"
}

$log = Join-Path $env:TEMP "shisad.log"
$daemon = Start-Process -FilePath ".\zig-out\bin\shisad.exe" -ArgumentList @("--foreground", "--socket", $pipe, "--log", $log) -NoNewWindow -PassThru

try {
    $ready = $false
    for ($i = 0; $i -lt 50; $i++) {
        Start-Sleep -Milliseconds 100
        & .\zig-out\bin\shisad.exe --health --socket $pipe *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
        if ($daemon.HasExited) {
            throw "shisad exited early with $($daemon.ExitCode)"
        }
    }
    if (-not $ready) {
        throw "shisad did not become healthy"
    }

    $prompt = & .\zig-out\bin\shisa.exe prompt --socket $pipe --cwd (Get-Location).Path --shell pwsh --cols 80 --rows 24
    if ($LASTEXITCODE -ne 0) {
        throw "prompt failed"
    }
    if (-not (($prompt -join "`n").Trim())) {
        throw "empty prompt"
    }

    & .\zig-out\bin\shisa.exe doctor
    if ($LASTEXITCODE -ne 0) {
        throw "doctor failed"
    }
} finally {
    if ($daemon -and -not $daemon.HasExited) {
        Stop-Process -Id $daemon.Id -Force
        $daemon.WaitForExit()
    }
}
