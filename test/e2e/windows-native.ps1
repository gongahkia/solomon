$ErrorActionPreference = "Stop"

. .\init\shisa.ps1

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ShisaPipeNative {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateFileW(
        string name,
        UInt32 desiredAccess,
        UInt32 shareMode,
        IntPtr securityAttributes,
        UInt32 creationDisposition,
        UInt32 flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool CloseHandle(IntPtr handle);

    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern UInt32 GetSecurityInfo(
        IntPtr handle,
        UInt32 objectType,
        UInt32 securityInfo,
        out IntPtr owner,
        out IntPtr group,
        out IntPtr dacl,
        out IntPtr sacl,
        out IntPtr securityDescriptor);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool ConvertSecurityDescriptorToStringSecurityDescriptorW(
        IntPtr securityDescriptor,
        UInt32 revision,
        UInt32 securityInformation,
        out IntPtr stringSecurityDescriptor,
        out UInt32 stringSecurityDescriptorLength);

    [DllImport("kernel32.dll")]
    public static extern IntPtr LocalFree(IntPtr memory);
}
'@

function Assert-PipeDacl([string]$Pipe) {
    # FILE_READ_DATA | FILE_WRITE_DATA | READ_CONTROL | SYNCHRONIZE. This is
    # intentionally not GENERIC_WRITE, which includes FILE_CREATE_PIPE_INSTANCE.
    $clientAccess = [uint32]0x00120003
    $handle = [ShisaPipeNative]::CreateFileW($Pipe, $clientAccess, 3, [IntPtr]::Zero, 3, 0x80, [IntPtr]::Zero)
    if ($handle.ToInt64() -eq -1) {
        throw "could not open pipe to inspect its DACL: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }

    $securityDescriptor = [IntPtr]::Zero
    $sddlPointer = [IntPtr]::Zero
    try {
        $owner = [IntPtr]::Zero
        $group = [IntPtr]::Zero
        $dacl = [IntPtr]::Zero
        $sacl = [IntPtr]::Zero
        $result = [ShisaPipeNative]::GetSecurityInfo($handle, 1, 4, [ref]$owner, [ref]$group, [ref]$dacl, [ref]$sacl, [ref]$securityDescriptor)
        if ($result -ne 0) {
            throw "GetSecurityInfo failed: $result"
        }

        [uint32]$sddlLength = 0
        if (-not [ShisaPipeNative]::ConvertSecurityDescriptorToStringSecurityDescriptorW($securityDescriptor, 1, 4, [ref]$sddlPointer, [ref]$sddlLength)) {
            throw "ConvertSecurityDescriptorToStringSecurityDescriptorW failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
        }
        $sddl = [Runtime.InteropServices.Marshal]::PtrToStringUni($sddlPointer)
        $logonSid = @([Security.Principal.WindowsIdentity]::GetCurrent().Groups | Where-Object { $_.Value -match '^S-1-5-5-\d+-\d+$' })[0]
        if ($null -eq $logonSid) {
            throw "current token has no logon SID"
        }
        $expected = "D:P(A;;0x00120003;;;$($logonSid.Value))"
        if ($sddl -ne $expected) {
            throw "unexpected pipe DACL: $sddl"
        }
    } finally {
        if ($sddlPointer -ne [IntPtr]::Zero) {
            [void][ShisaPipeNative]::LocalFree($sddlPointer)
        }
        if ($securityDescriptor -ne [IntPtr]::Zero) {
            [void][ShisaPipeNative]::LocalFree($securityDescriptor)
        }
        [void][ShisaPipeNative]::CloseHandle($handle)
    }
}

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

    Assert-PipeDacl $pipe

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
