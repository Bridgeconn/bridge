# Windows release security

Tracking: [#413](https://github.com/Bridgeconn/bridge/issues/413).

The v0.23.0 incident: Microsoft Defender quarantined the installed
`bridge-engine.exe` as `Trojan:Win32/Bearfoos.A!ml`, preventing Bridge startup
with OS error 225 (or error 2 after the file was removed). Benz's installer
matched GitHub's published SHA-256 digest; its Authenticode status was NotSigned.
Matching a release digest establishes provenance, not a malware determination.
Microsoft has not yet confirmed whether this detection is a false positive.

## Release gates

`release.yml` requires signing configuration for a Windows job that attaches to
a GitHub release. Missing configuration fails before the expensive build. A
manually dispatched run with `upload_to_release` blank may produce unsigned
internal artifacts; those are not eligible for public release.

The workflow signs both Python sidecars before packaging. Tauri invokes the
same signing wrapper for the application and installer via a temporary config
overlay. Each signing call must produce a valid, timestamped Authenticode
signature. No certificate material is written into the Tauri configuration.

After packaging, `check-windows-release.ps1` checks the application, both
sidecars and every Windows installer. It requires active Defender and real-time
protection, updates security intelligence, rejects definitions older than 24
hours, and performs custom scans with `-DisableRemediation`. That switch ignores
file exclusions, scans archives, and leaves detections in the command output;
the script does not set exclusions, disable protection, or restore threats.
Any inaccessible service, scan error, detection or missing/changed file fails
the job. The JSON report includes the definition version, file hashes, signature
status, scan output and error, and is retained as an Actions artifact on failure.

The final packaged sidecars then run the existing frozen smoke test. Hashes are
checked again after smoke testing and immediately before a release upload. A
per-platform `*-SHA256SUMS.txt` accompanies the exact final bundles in Actions
artifacts and release assets. Signing must happen before scanning and hashing;
never rebuild or re-sign an already reviewed release and reuse its old results.

A clean file scan does not guarantee a future Defender verdict, SmartScreen
reputation, or successful desktop installation. Clean Windows installed
acceptance remains a separate release task below.

## Signing setup still required

The publisher confirmed for this work is **Bridge Connectivity Solutions Pvt.
Ltd.**, registered in **India**. Benz confirmed the organization already has an
Azure subscription. `bundle.publisher` contains the confirmed legal name; this
is installer metadata and does not create a digital signature.

As checked on 30 Oct 2026, [Microsoft's Artifact Signing eligibility
requirements](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart)
do not include India for Public Trust organization certificates. An existing
Azure subscription does not remove that restriction. Do not provision Artifact
Signing as the public release signer for this Indian entity. [Private Trust and
Public Trust Test profiles are not publicly trusted by
default](https://learn.microsoft.com/en-us/azure/artifact-signing/concept-trust-models)
and are not substitutes for public Windows distribution.

The next step is to obtain a publicly trusted organization code-signing
certificate with a hardware/cloud signing service from a CA that confirms it can
validate this Indian entity. Keep the provider-neutral signing hook until an
issuer is selected. No Azure resources, paid accounts, signing identities or
credentials have been created by this work.

No signing certificate or service was known to be configured when this work was
prepared. Provision a trusted signing identity for the publisher first. A
self-signed certificate is not a substitute for trusted public signing.

The integration is provider-neutral: set the GitHub repository variable
`BRIDGE_WINDOWS_SIGN_COMMAND` to a JSON object with `cmd` and an `args` array.
Exactly one argument must be the standalone `%1` placeholder for the file path.
The script invokes that executable directly; it does not evaluate a shell
expression. Arguments with spaces stay separate arguments.

For example, on a runner where the publisher's hardware/service-backed
certificate is already accessible to SignTool:

```json
{
  "cmd": "C:/SigningTools/signtool.exe",
  "args": ["sign", "/sha1", "YOUR_CERTIFICATE_THUMBPRINT", "/fd", "SHA256", "/tr", "YOUR_PROVIDER_RFC3161_TIMESTAMP_URL", "/td", "SHA256", "%1"]
}
```

This example is a configuration shape, not a working credential setup. The
tool's path, signing identity and timestamp service must be supplied by the
chosen provider. Do not paste private keys, passwords or tokens into the
repository variable or command arguments. Use the provider's supported runner
authentication and protected GitHub secrets/OIDC. A cloud service needs its own
tool installation and authentication steps before the sidecar signing step;
those cannot be filled in until the publisher selects and provisions a service.
Do not add a PFX export workflow for a modern non-exportable signing key.

Tauri's wrapper validates signatures after each signing call and the final gate
checks all four executables, rather than trusting an exit code from the signer.
Run a `workflow_dispatch` artifact-only build first. Record the signer identity,
timestamp/signature results, Defender report and installed-acceptance results
before a public release. Do not buy a certificate or create a signing account
automatically as part of a build.

## Microsoft review for v0.23.0

Submit through <https://www.microsoft.com/en-us/wdsi/filesubmission> as a
**Software developer**, reporting an incorrectly detected file. Microsoft
requires sign-in. Submit the exact flagged `bridge-engine.exe` from v0.23.0's
build output, not an older local build, and identify the corresponding installer:

- Release: <https://github.com/Bridgeconn/bridge/releases/tag/v0.23.0>
- Installer: `Bridge_0.23.0_x64-setup.exe`
- Installer SHA-256: `9d5b5fdd4d349005417a61d97f38f2306b17560e0ba497ff35db0e0ac346a6cb`
- Detection: `Trojan:Win32/Bearfoos.A!ml`
- Affected installed file: `%LOCALAPPDATA%/Bridge/bridge-engine.exe`
- Observed installed engine SHA-256 (30 Oct 2026):
  `6b2da6f2e34ed833e66bdd7fdaae8f18815abfde9f5990479df4ea2b5702c651`.
  This identifies the observed file, not an independently published engine digest.
- Symptom: Windows refuses to spawn the sidecar with OS error 225, then error 2
  after quarantine; no engine ready handshake is received.

Suggested submission description:

> Please investigate a suspected false-positive detection in Bridge v0.23.0,
> an offline Bible translation QA desktop application. Defender reports
> Trojan:Win32/Bearfoos.A!ml for bridge-engine.exe, the application's
> PyInstaller-packaged Python sidecar. The affected Windows installer matches
> the SHA-256 digest published on the linked GitHub release. Please analyze the
> exact supplied file and advise whether the detection is correct. We have not
> established that it is a false positive and are not requesting that protection
> be disabled. Source and release: https://github.com/Bridgeconn/bridge/releases/tag/v0.23.0.

Retain the submission ID and final determination. If Microsoft clears the file,
update Defender definitions and rescan the same bytes before distributing them.
Do not claim a submission or clearance without those results.

On 30 Oct 2026, a local custom scan with definitions `1.463.31.0` reported no
threats in the installed app, both installed sidecars and the matching installer.
Their bytes were unchanged across the scans; all four were unsigned. This is
local scan evidence, not a Microsoft submission determination or fresh-VM
acceptance. The public-release gate correctly rejected the real unsigned
installer when signature enforcement was enabled.

## Installed Windows acceptance

Use a fresh Windows VM with current Defender definitions and protection enabled,
without exclusions or an earlier allow decision. Download the final installer,
verify its published SHA-256, install it and start Bridge. Check the main app and
both installed sidecars for valid publisher signatures and timestamps; confirm
the engine reaches `Engine ready`, the UI opens, and a disposable imported book
can run checks. Restart Bridge and confirm startup again. Save the exact hashes,
definition version, OS version, startup log and observed result. A file scan or
the stdio frozen smoke alone is not this installed-desktop evidence.

## Local checks

Run the security gate tests in Windows PowerShell with the bundled Pester:

```powershell
Import-Module Pester -RequiredVersion 3.4.0
$result = Invoke-Pester -Script scripts/tests/windows-release.Tests.ps1 -PassThru
if ($result.FailedCount -ne 0 -or $result.TotalCount -eq 0) { throw 'Release tests failed' }
```

For a real release scan, run an elevated PowerShell terminal on a dedicated
Windows release machine. Supply literal file paths for the app, both sidecars
and installer, and an existing directory for the JSON report:

```powershell
$files = @('path/to/app.exe', 'path/to/bridge-engine.exe', 'path/to/bridge-usfm-checker.exe', 'path/to/setup.exe')
./scripts/check-windows-release.ps1 -Path $files -ReportPath ./windows-security-report.json -RequireSignature
./scripts/check-windows-release.ps1 -VerifyOnly -Path $files -ReportPath ./windows-security-report.json -RequireSignature
```

The unit tests mock Defender and signature results to exercise failure handling;
they are not an antivirus verdict on a release executable.

## Primary references

- [Microsoft: submit files for analysis](https://learn.microsoft.com/en-us/defender-xdr/submission-guide)
- [Microsoft: software developer FAQ](https://learn.microsoft.com/en-us/defender-xdr/developer-faq)
- [Microsoft: MpCmdRun scan behavior](https://learn.microsoft.com/en-us/defender-endpoint/command-line-arguments-microsoft-defender-antivirus)
- [Tauri: Windows signing and custom sign commands](https://v2.tauri.app/distribute/sign/windows/)
