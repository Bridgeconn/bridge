# Runs with Windows' bundled Pester 3.4.0; no signing key or Defender changes.
Import-Module (Join-Path $PSScriptRoot '../WindowsRelease.psm1') -Force

Describe 'Windows signing configuration' {
    BeforeEach {
        $script:savedSigningCommand = $env:BRIDGE_WINDOWS_SIGN_COMMAND
        $script:signingFile = Join-Path $TestDrive 'signing fixture.exe'
        Set-Content -LiteralPath $script:signingFile -Value 'not executable' -Encoding utf8
        Mock Get-AuthenticodeSignature -ModuleName WindowsRelease {
            [pscustomobject]@{ Status = 'NotSigned'; SignerCertificate = $null; TimeStamperCertificate = $null }
        }
    }
    AfterEach { $env:BRIDGE_WINDOWS_SIGN_COMMAND = $script:savedSigningCommand }

    It 'stops when no signing identity is configured' {
        $env:BRIDGE_WINDOWS_SIGN_COMMAND = ''
        { Get-BridgeSigningConfiguration } | Should Throw
    }

    It 'rejects a shell command instead of structured arguments' {
        $env:BRIDGE_WINDOWS_SIGN_COMMAND = 'signtool sign file.exe'
        { Get-BridgeSigningConfiguration } | Should Throw
    }

    It 'rejects a command without a standalone path placeholder' {
        $env:BRIDGE_WINDOWS_SIGN_COMMAND = '{"cmd":"signtool","args":["sign","prefix%1"]}'
        { Get-BridgeSigningConfiguration } | Should Throw
    }

    It 'preserves arguments containing spaces' {
        $env:BRIDGE_WINDOWS_SIGN_COMMAND = '{"cmd":"C:/Signing Tools/signer.exe","args":["--publisher","Bridge Publisher","%1"]}'
        $config = Get-BridgeSigningConfiguration
        $config.args[1] | Should Be 'Bridge Publisher'
        $config.cmd | Should Be 'C:/Signing Tools/signer.exe'
    }

    It 'rejects a failing signing command before signature verification' {
        $env:BRIDGE_WINDOWS_SIGN_COMMAND = @{ cmd = $env:ComSpec; args = @('/d', '/c', 'exit', '2', '%1') } | ConvertTo-Json -Compress
        { Invoke-BridgeSign -Path $script:signingFile } | Should Throw
        Assert-MockCalled Get-AuthenticodeSignature -Scope It -ModuleName WindowsRelease -Times 0 -Exactly
    }

    It 'rejects a signer that returns success without signing the file' {
        $env:BRIDGE_WINDOWS_SIGN_COMMAND = @{ cmd = $env:ComSpec; args = @('/d', '/c', 'exit', '0', '%1') } | ConvertTo-Json -Compress
        { Invoke-BridgeSign -Path $script:signingFile } | Should Throw
        Assert-MockCalled Get-AuthenticodeSignature -Scope It -ModuleName WindowsRelease -Times 1 -Exactly
    }
}

Describe 'Windows release scan gate' {
    BeforeEach {
        $script:binary = Join-Path $TestDrive 'engine with spaces.exe'
        $script:reportPath = Join-Path $TestDrive 'security.json'
        Set-Content -LiteralPath $script:binary -Value 'test fixture, not executable' -Encoding utf8
        Mock Get-AuthenticodeSignature -ModuleName WindowsRelease {
            [pscustomobject]@{
                Status = 'Valid'
                SignerCertificate = [pscustomobject]@{ Subject = 'CN=Test Publisher' }
                TimeStamperCertificate = [pscustomobject]@{ Subject = 'CN=Test Timestamp' }
            }
        }
        Mock Get-MpComputerStatus -ModuleName WindowsRelease {
            [pscustomobject]@{
                AMServiceEnabled = $true
                AntivirusEnabled = $true
                RealTimeProtectionEnabled = $true
                AMRunningMode = 'Normal'
                AntivirusSignatureVersion = 'test-definitions'
                AntivirusSignatureLastUpdated = [DateTime]::UtcNow
            }
        }
        Mock Invoke-BridgeDefenderCommand -ModuleName WindowsRelease {
            [pscustomobject]@{ exitCode = 0; output = 'test scanner result' }
        }
    }

    It 'records successful scans and verifies the same artifacts' {
        Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath -RequireSignature
        Test-BridgeReleaseReport -Path $script:binary -ReportPath $script:reportPath -RequireSignature
        $report = Get-Content $script:reportPath -Raw | ConvertFrom-Json
        $report.status | Should Be 'passed'
        $report.files[0].sha256 | Should Be (Get-FileHash -LiteralPath $script:binary -Algorithm SHA256).Hash
        Assert-MockCalled Invoke-BridgeDefenderCommand -Scope It -ModuleName WindowsRelease -Times 1 -Exactly -ParameterFilter {
            $ArgumentList[0] -eq '-Scan' -and $ArgumentList[-1] -eq '-DisableRemediation'
        }
    }

    It 'never overwrites an artifact with the security report' {
        $originalHash = (Get-FileHash -LiteralPath $script:binary -Algorithm SHA256).Hash
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:binary } | Should Throw
        (Get-FileHash -LiteralPath $script:binary -Algorithm SHA256).Hash | Should Be $originalHash
        Assert-MockCalled Invoke-BridgeDefenderCommand -Scope It -ModuleName WindowsRelease -Times 0 -Exactly
    }

    It 'fails on a detection or scanning error and retains diagnostics' {
        Mock Invoke-BridgeDefenderCommand -ModuleName WindowsRelease {
            $code = if ($ArgumentList[0] -eq '-Scan') { 2 } else { 0 }
            [pscustomobject]@{ exitCode = $code; output = 'detected or scan error' }
        }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath } | Should Throw
        $report = Get-Content $script:reportPath -Raw | ConvertFrom-Json
        $report.status | Should Be 'failed'
        $report.files[0].scanExitCode | Should Be 2
        $report.files[0].scanOutput | Should Be 'detected or scan error'
    }

    It 'fails if definition updates cannot run' {
        Mock Invoke-BridgeDefenderCommand -ModuleName WindowsRelease {
            [pscustomobject]@{ exitCode = 2; output = 'update failed' }
        }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath } | Should Throw
        Assert-MockCalled Invoke-BridgeDefenderCommand -Scope It -ModuleName WindowsRelease -Times 0 -Exactly -ParameterFilter {
            $ArgumentList[0] -eq '-Scan'
        }
    }

    It 'fails if Defender status is inaccessible' {
        Mock Get-MpComputerStatus -ModuleName WindowsRelease { throw 'Access denied' }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath } | Should Throw
        (Get-Content $script:reportPath -Raw | ConvertFrom-Json).status | Should Be 'failed'
        Assert-MockCalled Invoke-BridgeDefenderCommand -Scope It -ModuleName WindowsRelease -Times 0 -Exactly
    }

    It 'fails if real-time protection is disabled' {
        Mock Get-MpComputerStatus -ModuleName WindowsRelease {
            [pscustomobject]@{ AMServiceEnabled = $true; AntivirusEnabled = $true; RealTimeProtectionEnabled = $false; AMRunningMode = 'Normal' }
        }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath } | Should Throw
    }

    It 'fails if updated definitions are stale' {
        Mock Get-MpComputerStatus -ModuleName WindowsRelease {
            [pscustomobject]@{
                AMServiceEnabled = $true; AntivirusEnabled = $true; RealTimeProtectionEnabled = $true; AMRunningMode = 'Normal'
                AntivirusSignatureVersion = 'old'; AntivirusSignatureLastUpdated = [DateTime]::UtcNow.AddDays(-2)
            }
        }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath } | Should Throw
    }

    It 'rejects an unsigned public release before scanning' {
        Mock Get-AuthenticodeSignature -ModuleName WindowsRelease {
            [pscustomobject]@{ Status = 'NotSigned'; SignerCertificate = $null; TimeStamperCertificate = $null }
        }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath -RequireSignature } | Should Throw
        Assert-MockCalled Invoke-BridgeDefenderCommand -Scope It -ModuleName WindowsRelease -Times 0 -Exactly
    }

    It 'rejects a signature without a timestamp' {
        Mock Get-AuthenticodeSignature -ModuleName WindowsRelease {
            [pscustomobject]@{ Status = 'Valid'; SignerCertificate = [pscustomobject]@{ Subject = 'CN=Test' }; TimeStamperCertificate = $null }
        }
        { Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath -RequireSignature } | Should Throw
    }

    It 'rejects changes after a clean scan' {
        Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath -RequireSignature
        Add-Content -LiteralPath $script:binary -Value 'changed after scan' -Encoding utf8
        { Test-BridgeReleaseReport -Path $script:binary -ReportPath $script:reportPath -RequireSignature } | Should Throw
    }

    It 'rejects files omitted from the report' {
        Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath -RequireSignature
        $other = Join-Path $TestDrive 'other.exe'
        Set-Content -LiteralPath $other -Value 'another fixture' -Encoding utf8
        { Test-BridgeReleaseReport -Path @($script:binary, $other) -ReportPath $script:reportPath -RequireSignature } | Should Throw
    }

    It 'cannot promote an unsigned internal report to a public release' {
        Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath
        { Test-BridgeReleaseReport -Path $script:binary -ReportPath $script:reportPath -RequireSignature } | Should Throw
    }

    It 'rejects a report from an earlier day' {
        Invoke-BridgeReleaseScan -Path $script:binary -ReportPath $script:reportPath -RequireSignature
        $report = Get-Content $script:reportPath -Raw | ConvertFrom-Json
        $report.scannedAtUtc = [DateTime]::UtcNow.AddDays(-2).ToString('o')
        $report | ConvertTo-Json -Depth 8 | Set-Content $script:reportPath -Encoding utf8
        { Test-BridgeReleaseReport -Path $script:binary -ReportPath $script:reportPath -RequireSignature } | Should Throw
    }
}
