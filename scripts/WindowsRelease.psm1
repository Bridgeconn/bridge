# Windows release checks only. Never change Defender settings or exclusions.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-BridgeSigningConfiguration {
    if ([string]::IsNullOrWhiteSpace($env:BRIDGE_WINDOWS_SIGN_COMMAND)) {
        throw 'Windows signing is not configured. Set BRIDGE_WINDOWS_SIGN_COMMAND after provisioning a trusted signing identity; public Windows releases must not fall back to unsigned.'
    }
    $config = $env:BRIDGE_WINDOWS_SIGN_COMMAND | ConvertFrom-Json
    if (-not $config.PSObject.Properties['cmd'] -or $config.cmd -isnot [string] -or
        [string]::IsNullOrWhiteSpace($config.cmd) -or
        -not $config.PSObject.Properties['args'] -or $config.args -isnot [array]) {
        throw 'BRIDGE_WINDOWS_SIGN_COMMAND must be a JSON object with cmd and an args array.'
    }
    if (@($config.args | Where-Object { $_ -isnot [string] }).Count -gt 0 -or
        @($config.args | Where-Object { $_ -eq '%1' }).Count -ne 1) {
        throw 'Signing arguments must be strings with exactly one standalone %1 path placeholder.'
    }
    return $config
}

function Assert-BridgeSignature {
    param([Parameter(Mandatory)][string]$Path)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or
        $null -eq $signature.TimeStamperCertificate) {
        throw "A trusted, timestamped Authenticode signature is required: $Path (status: $($signature.Status))."
    }
    return $signature
}

function Invoke-BridgeSign {
    param([Parameter(Mandatory)][string[]]$Path)
    $config = Get-BridgeSigningConfiguration
    foreach ($item in $Path) {
        $file = Get-Item -LiteralPath $item
        if ($file.PSIsContainer) { throw "Expected a file: $item" }
        $arguments = @($config.args | ForEach-Object {
            if ($_ -eq '%1') { $file.FullName } else { $_ }
        })
        # Structured invocation, never Invoke-Expression or a shell-built command.
        $global:LASTEXITCODE = 0
        & $config.cmd @arguments
        if (-not $? -or $LASTEXITCODE -ne 0) {
            throw "Windows signing failed for $($file.Name)."
        }
        $null = Assert-BridgeSignature -Path $file.FullName
    }
}

function Get-BridgeFileRecord {
    param([Parameter(Mandatory)][string]$Path, [switch]$RequireSignature)
    $file = Get-Item -LiteralPath $Path
    if ($file.PSIsContainer) { throw "Expected a file: $Path" }
    $signature = if ($RequireSignature) {
        Assert-BridgeSignature -Path $file.FullName
    } else {
        Get-AuthenticodeSignature -LiteralPath $file.FullName
    }
    return [pscustomobject]@{
        path = $file.FullName
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
        signatureStatus = [string]$signature.Status
        signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
        scanExitCode = $null
        scanOutput = $null
    }
}

function Get-BridgeDefenderCommand {
    $platform = Join-Path $env:ProgramData 'Microsoft/Windows Defender/Platform'
    $candidates = @(Get-ChildItem -LiteralPath $platform -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+(-\d+)?$' } |
        Sort-Object { [version]($_.Name -replace '-.*$', '') } -Descending |
        ForEach-Object { Join-Path $_.FullName 'MpCmdRun.exe' })
    $candidates += Join-Path $env:ProgramFiles 'Windows Defender/MpCmdRun.exe'
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Microsoft Defender MpCmdRun.exe is unavailable; scanning cannot be skipped.'
}

function Invoke-BridgeDefenderCommand {
    param([Parameter(Mandatory)][string[]]$ArgumentList)
    $command = Get-BridgeDefenderCommand
    $global:LASTEXITCODE = 0
    $output = @(& $command @ArgumentList 2>&1 | ForEach-Object { [string]$_ })
    return [pscustomobject]@{ exitCode = $LASTEXITCODE; output = ($output -join "`n") }
}

function Assert-BridgeDefenderEnabled {
    $status = Get-MpComputerStatus -ErrorAction Stop
    if (-not $status.AMServiceEnabled -or -not $status.AntivirusEnabled -or
        -not $status.RealTimeProtectionEnabled -or $status.AMRunningMode -ne 'Normal') {
        throw 'Microsoft Defender must be active with real-time protection enabled; this release was not verified.'
    }
    return $status
}

function Invoke-BridgeReleaseScan {
    param(
        [Parameter(Mandatory)][string[]]$Path,
        [Parameter(Mandatory)][string]$ReportPath,
        [switch]$RequireSignature
    )
    $reportFile = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ReportPath)
    foreach ($item in $Path) {
        if ($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($item) -eq $reportFile) {
            throw 'The security report must not overwrite a release artifact.'
        }
    }
    $report = [ordered]@{
        schemaVersion = 1
        status = 'failed'
        scannedAtUtc = [DateTime]::UtcNow.ToString('o')
        signaturesRequired = [bool]$RequireSignature
        defenderSignatureVersion = $null
        defenderSignatureUpdatedAt = $null
        updateOutput = $null
        files = @()
        error = $null
    }
    try {
        if ($Path.Count -eq 0) { throw 'No files supplied for scanning.' }
        $report.files = @($Path | ForEach-Object {
            Get-BridgeFileRecord -Path $_ -RequireSignature:$RequireSignature
        } | Sort-Object path -Unique)
        $null = Assert-BridgeDefenderEnabled
        $update = Invoke-BridgeDefenderCommand -ArgumentList @('-SignatureUpdate')
        $report.updateOutput = $update.output
        if ($update.exitCode -ne 0) { throw "Defender definition update failed ($($update.exitCode))." }
        $status = Assert-BridgeDefenderEnabled
        $report.defenderSignatureVersion = $status.AntivirusSignatureVersion
        $report.defenderSignatureUpdatedAt = $status.AntivirusSignatureLastUpdated.ToUniversalTime().ToString('o')
        if ([DateTime]::UtcNow - $status.AntivirusSignatureLastUpdated.ToUniversalTime() -gt [TimeSpan]::FromDays(1)) {
            throw 'Defender definitions are more than 24 hours old after updating.'
        }
        foreach ($file in $report.files) {
            # DisableRemediation ignores file exclusions and scans archives. It also
            # prevents this custom scan from deleting evidence. Nonzero is failure,
            # including detection or scan errors; never interpret either as clean.
            $scan = Invoke-BridgeDefenderCommand -ArgumentList @(
                '-Scan', '-ScanType', '3', '-File', $file.path, '-DisableRemediation'
            )
            $file.scanExitCode = $scan.exitCode
            $file.scanOutput = $scan.output
            if ($scan.exitCode -ne 0) { throw "Defender rejected or could not scan $($file.path) (exit $($scan.exitCode))." }
        }
        foreach ($file in $report.files) {
            if ((Get-FileHash -LiteralPath $file.path -Algorithm SHA256).Hash -ne $file.sha256) {
                throw "A release file changed during scanning: $($file.path)"
            }
        }
        $null = Assert-BridgeDefenderEnabled
        $report.status = 'passed'
    } catch {
        $report.error = $_.Exception.Message
        throw
    } finally {
        $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
    }
}

function Test-BridgeReleaseReport {
    param(
        [Parameter(Mandatory)][string]$ReportPath,
        [Parameter(Mandatory)][string[]]$Path,
        [switch]$RequireSignature
    )
    $report = Get-Content -LiteralPath $ReportPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($report.schemaVersion -ne 1 -or $report.status -ne 'passed' -or @($report.files).Count -eq 0) {
        throw 'No successful Windows security report is available.'
    }
    $scanTime = [DateTime]::Parse($report.scannedAtUtc).ToUniversalTime()
    if ($scanTime -gt [DateTime]::UtcNow.AddMinutes(5) -or $scanTime -lt [DateTime]::UtcNow.AddDays(-1)) {
        throw 'The Windows security report is expired or has an invalid date.'
    }
    if ($RequireSignature -and -not $report.signaturesRequired) {
        throw 'An unsigned internal build cannot be published as a signed release.'
    }
    $expected = @($Path | ForEach-Object { (Get-Item -LiteralPath $_).FullName } | Sort-Object -Unique)
    $actual = @($report.files | ForEach-Object { $_.path } | Sort-Object -Unique)
    if ($expected.Count -eq 0 -or $actual.Count -ne @($report.files).Count -or
        @(Compare-Object -ReferenceObject $expected -DifferenceObject $actual).Count -ne 0) {
        throw 'The security report does not cover exactly the expected release files.'
    }
    foreach ($file in $report.files) {
        if ($null -eq $file.scanExitCode -or $file.scanExitCode -ne 0 -or
            (Get-FileHash -LiteralPath $file.path -Algorithm SHA256).Hash -ne $file.sha256) {
            throw "A release file is unscanned, missing or changed: $($file.path)"
        }
        if ($RequireSignature) { $null = Assert-BridgeSignature -Path $file.path }
    }
}

Export-ModuleMember -Function Get-BridgeSigningConfiguration, Invoke-BridgeSign, Invoke-BridgeReleaseScan, Test-BridgeReleaseReport
