[CmdletBinding()]
param(
    [switch]$Uninstall,
    [string]$Version = $env:SOLOMON_VERSION,
    [string]$Repository = $(if ($env:SOLOMON_REPOSITORY) { $env:SOLOMON_REPOSITORY } else { 'gongahkia/solomon' }),
    [string]$ReleaseBaseUrl = $env:SOLOMON_RELEASE_BASE_URL,
    [string]$InstallDir = $(if ($env:SOLOMON_INSTALL_DIR) { $env:SOLOMON_INSTALL_DIR } else { Join-Path $HOME '.local/bin' }),
    [string]$Shell = $(if ($env:SOLOMON_SHELL) { $env:SOLOMON_SHELL } else { 'powershell' }),
    [string]$ShellProfile = $env:SOLOMON_SHELL_RC
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$startMarker = '# >>> solomon initialize >>>'
$endMarker = '# <<< solomon initialize <<<'

function Fail([string]$Message) {
    throw "solomon installer: $Message"
}

function Test-Repository([string]$Value) {
    if ($Value -notmatch '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$' -or $Value.Contains('..')) {
        Fail 'invalid repository'
    }
}

function Test-Version([string]$Value) {
    if ($Value -notmatch '^v[0-9][0-9A-Za-z.+-]*$') {
        Fail 'invalid release version'
    }
}

function Resolve-Version {
    if ($Version) {
        Test-Version $Version
        return $Version
    }
    $apiBase = if ($env:SOLOMON_API_URL) { $env:SOLOMON_API_URL } else { 'https://api.github.com' }
    $release = Invoke-RestMethod -Uri "$apiBase/repos/$Repository/releases/latest"
    $resolved = [string]$release.tag_name
    Test-Version $resolved
    return $resolved
}

function Get-ReleaseBaseUrl {
    if ($ReleaseBaseUrl) {
        return $ReleaseBaseUrl.TrimEnd('/')
    }
    return "https://github.com/$Repository/releases/download/$Version"
}

function Get-TargetArchitecture {
    if (-not $IsWindows) {
        Fail 'unsupported operating system'
    }
    $architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    if ($architecture -ne 'x64') {
        Fail "unsupported architecture $architecture"
    }
    return 'amd64'
}

function Get-ShellProfilePath {
    if ($Shell -eq 'none') {
        return $null
    }
    if ($Shell -ne 'powershell' -and $Shell -ne 'pwsh') {
        Fail "unsupported shell $Shell"
    }
    if ($ShellProfile) {
        if (-not [System.IO.Path]::IsPathRooted($ShellProfile)) {
            Fail 'shell initialization path must be absolute'
        }
        return $ShellProfile
    }
    return $PROFILE.CurrentUserCurrentHost
}

function Remove-ShellInitialization {
    $profilePath = Get-ShellProfilePath
    if (-not $profilePath -or -not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
        return
    }
    $lines = [System.IO.File]::ReadAllLines($profilePath)
    $start = [Array]::IndexOf($lines, $startMarker)
    if ($start -lt 0) {
        return
    }
    $end = [Array]::IndexOf($lines, $endMarker)
    if ($end -lt $start) {
        Fail "managed shell initialization is incomplete in $profilePath"
    }
    $retained = [System.Collections.Generic.List[string]]::new()
    for ($index = 0; $index -lt $lines.Length; $index++) {
        if ($index -lt $start -or $index -gt $end) {
            $retained.Add($lines[$index])
        }
    }
    [System.IO.File]::WriteAllLines($profilePath, $retained)
}

function Add-ShellInitialization([string]$Binary) {
    $profilePath = Get-ShellProfilePath
    if (-not $profilePath) {
        return
    }
    $parent = Split-Path -Parent $profilePath
    if ($parent) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) {
        [System.IO.File]::WriteAllText($profilePath, '')
    }
    $lines = [System.IO.File]::ReadAllLines($profilePath)
    $start = [Array]::IndexOf($lines, $startMarker)
    if ($start -ge 0) {
        if ([Array]::IndexOf($lines, $endMarker) -lt $start) {
            Fail "managed shell initialization is incomplete in $profilePath"
        }
        return
    }
    $escapedBinary = $Binary.Replace("'", "''")
    $block = @(
        $startMarker,
        "if (Test-Path -LiteralPath '$escapedBinary' -PathType Leaf) {",
        "    & '$escapedBinary' init --shell powershell | Invoke-Expression",
        '}',
        $endMarker
    )
    if ((Get-Item -LiteralPath $profilePath).Length -gt 0) {
        [System.IO.File]::AppendAllText($profilePath, [Environment]::NewLine)
    }
    [System.IO.File]::AppendAllLines($profilePath, $block)
}

function Verify-Checksum([string]$Artifact, [string]$Manifest, [string]$ArtifactName) {
    $expected = $null
    if ([System.IO.File]::ReadAllText($Manifest).Contains("`r")) {
        Fail 'checksum manifest contains carriage returns'
    }
    foreach ($line in [System.IO.File]::ReadAllLines($Manifest)) {
        if ($line -notmatch '^([0-9a-f]{64})  ([^/\\ ]+)$') {
            Fail 'checksum manifest has an invalid entry'
        }
        if ($Matches[2] -ne $ArtifactName) {
            continue
        }
        if ($null -ne $expected) {
            Fail 'checksum manifest has duplicate artifacts'
        }
        $expected = $Matches[1]
    }
    if ($null -eq $expected) {
        Fail "checksum manifest does not contain $ArtifactName"
    }
    $actual = (Get-FileHash -LiteralPath $Artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {
        Fail "checksum mismatch for $ArtifactName"
    }
}

function Verify-Signature([string]$Artifact, [string]$Bundle) {
    $cosign = Get-Command cosign -ErrorAction SilentlyContinue
    if (-not $cosign) {
        Fail 'requires cosign'
    }
    $identity = "https://github.com/$Repository/.github/workflows/release.yml@refs/tags/$Version"
    & $cosign.Path verify-blob $Artifact --bundle $Bundle --certificate-identity $identity --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Fail 'Sigstore verification failed'
    }
}

function Install-Archive([string]$Artifact, [string]$Root, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Artifact)
    try {
        $entryName = "$Root/solomon.exe"
        $allowed = @("$Root/", $entryName)
        foreach ($entry in $archive.Entries) {
            if ($allowed -notcontains $entry.FullName) {
                Fail 'release archive has unexpected contents'
            }
        }
        $matches = @($archive.Entries | Where-Object { $_.FullName -eq $entryName })
        if ($matches.Count -ne 1) {
            Fail 'release archive has an invalid binary entry'
        }
        $entry = $matches[0]
        if ($null -eq $entry -or $entry.Length -eq 0) {
            Fail 'release binary is missing or empty'
        }
        [System.IO.Directory]::CreateDirectory($Destination) | Out-Null
        $temporary = Join-Path $Destination ('.solomon-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        try {
            $input = $entry.Open()
            try {
                $output = [System.IO.File]::Open($temporary, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                try {
                    $input.CopyTo($output)
                } finally {
                    $output.Dispose()
                }
            } finally {
                $input.Dispose()
            }
            Move-Item -LiteralPath $temporary -Destination (Join-Path $Destination 'solomon.exe') -Force
        } finally {
            if (Test-Path -LiteralPath $temporary) {
                Remove-Item -LiteralPath $temporary -Force
            }
        }
    } finally {
        $archive.Dispose()
    }
}

Test-Repository $Repository
if ($Uninstall) {
    if (-not [System.IO.Path]::IsPathRooted($InstallDir)) {
        Fail 'installation directory must be absolute'
    }
    $target = Join-Path $InstallDir 'solomon.exe'
    if (Test-Path -LiteralPath $target -PathType Container) {
        Fail "installation target is not a regular file"
    }
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
    }
    Remove-ShellInitialization
    exit 0
}

$Version = Resolve-Version
$architecture = Get-TargetArchitecture
if (-not [System.IO.Path]::IsPathRooted($InstallDir)) {
    Fail 'installation directory must be absolute'
}
$archiveName = "solomon_${Version}_windows_${architecture}.zip"
$root = [System.IO.Path]::GetFileNameWithoutExtension($archiveName)
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ('solomon-install-' + [Guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($temporary) | Out-Null
try {
    $baseUrl = Get-ReleaseBaseUrl
    $artifact = Join-Path $temporary $archiveName
    $manifest = Join-Path $temporary 'checksums.txt'
    $bundle = Join-Path $temporary ($archiveName + '.sigstore.json')
    Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/$archiveName" -OutFile $artifact
    Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/checksums.txt" -OutFile $manifest
    Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/$archiveName.sigstore.json" -OutFile $bundle
    Verify-Checksum $artifact $manifest $archiveName
    Verify-Signature $artifact $bundle
    Install-Archive $artifact $root $InstallDir
    Add-ShellInitialization (Join-Path $InstallDir 'solomon.exe')
    Write-Output "installed solomon $Version to $(Join-Path $InstallDir 'solomon.exe')"
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
