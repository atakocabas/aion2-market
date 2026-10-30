# Authenticode-signs files with signtool (SHA-256 + RFC 3161 timestamp) so Windows shows a publisher instead of
# "Unknown publisher". With no certificate configured it only says so and exits 0, so unsigned builds keep working.
#   installer\sign.ps1 dist\Aion2Market.exe
# Certificate, one of:
#   AION2_SIGN_THUMBPRINT                      certificate in the Windows store (hardware token, Certum SimplySign...)
#   AION2_SIGN_PFX + AION2_SIGN_PFX_PASSWORD   path to a .pfx file and its password (CI)
# AION2_SIGN_TIMESTAMP overrides the timestamp server.
param([Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Files)

$ErrorActionPreference = "Stop"

if (-not ($env:AION2_SIGN_THUMBPRINT -or $env:AION2_SIGN_PFX)) {
    Write-Host "sign.ps1: no certificate configured, leaving unsigned: $($Files -join ', ')"
    exit 0
}

# signtool ships with the Windows SDK; take the newest x64 one.
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Sort-Object { [version]$_.Directory.Parent.Name } -ErrorAction SilentlyContinue | Select-Object -Last 1
if (-not $signtool) {
    throw "signtool.exe not found; install the Windows SDK (Signing Tools for Desktop Apps)"
}

$timestamp = if ($env:AION2_SIGN_TIMESTAMP) { $env:AION2_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
$certArgs = if ($env:AION2_SIGN_THUMBPRINT) {
    @("/sha1", $env:AION2_SIGN_THUMBPRINT)
} else {
    @("/f", $env:AION2_SIGN_PFX, "/p", $env:AION2_SIGN_PFX_PASSWORD)
}

foreach ($file in $Files) {
    & $signtool.FullName sign @certArgs /fd sha256 /tr $timestamp /td sha256 /d "Aion 2 Market" $file
    if ($LASTEXITCODE) { throw "signing failed: $file" }
    & $signtool.FullName verify /pa $file
    if ($LASTEXITCODE) { throw "signature does not verify: $file" }
}
