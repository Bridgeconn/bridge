param(
    [Parameter(Mandatory)][string[]]$Path,
    [Parameter(Mandatory)][string]$ReportPath,
    [switch]$RequireSignature,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'WindowsRelease.psm1') -Force
if ($VerifyOnly) {
    Test-BridgeReleaseReport -Path $Path -ReportPath $ReportPath -RequireSignature:$RequireSignature
} else {
    Invoke-BridgeReleaseScan -Path $Path -ReportPath $ReportPath -RequireSignature:$RequireSignature
}
