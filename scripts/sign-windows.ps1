param([Parameter(Mandatory)][string[]]$Path)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'WindowsRelease.psm1') -Force
Invoke-BridgeSign -Path $Path
