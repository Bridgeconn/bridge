param(
    [string]$PythonCommand = "",
    [string]$TargetTriple = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$engineDir = Join-Path $repoRoot "engine"
# Forward slashes throughout: Windows PowerShell accepts them, and pwsh on
# macOS/Linux does NOT treat a backslash as a separator -- "src-tauri\binaries"
# there is one directory with a backslash in its name (#250).
$binaryDir = Join-Path $repoRoot "src-tauri/binaries"
$resourcesDir = Join-Path $repoRoot "src-tauri/resources"
$packsDir = Join-Path $repoRoot "src-tauri/language_packs"

if (-not $PythonCommand) {
    $venvPython = if ($IsWindows -or $env:OS -eq "Windows_NT") {
        Join-Path $engineDir ".venv\Scripts\python.exe"
    } else {
        Join-Path $engineDir ".venv/bin/python"
    }
    $PythonCommand = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { "python" }
}

& $PythonCommand -c "import PyInstaller, regex, uroman, usfmtc, wildebeest, fastapi, uvicorn"
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python environment is missing a release dependency. Run 'pip install -c constraints-py312-windows.txt -e .[dev,wildebeest]' in engine/ or pass -PythonCommand explicitly."
}

if (-not $TargetTriple) {
    $hostLine = & rustc -vV | Select-String '^host:' | Select-Object -First 1
    if (-not $hostLine) {
        throw "Could not determine the Rust host target. Pass -TargetTriple explicitly."
    }
    $TargetTriple = ($hostLine.Line -replace '^host:\s*', '').Trim()
}

$extension = if ($IsWindows -or $env:OS -eq "Windows_NT") { ".exe" } else { "" }

Push-Location $engineDir
try {
    & $PythonCommand -m PyInstaller --clean --noconfirm bridge-engine.spec
    if ($LASTEXITCODE -ne 0) { throw "bridge-engine PyInstaller build failed" }

    & $PythonCommand -m PyInstaller --clean --noconfirm bridge-usfm-checker.spec
    if ($LASTEXITCODE -ne 0) { throw "bridge-usfm-checker PyInstaller build failed" }

    New-Item -ItemType Directory -Force -Path $binaryDir | Out-Null
    $engineBinary = Join-Path $binaryDir "bridge-engine-$TargetTriple$extension"
    $checkerBinary = Join-Path $binaryDir "bridge-usfm-checker-$TargetTriple$extension"
    Copy-Item -LiteralPath (Join-Path $engineDir "dist/bridge-engine$extension") `
        -Destination $engineBinary -Force
    Copy-Item -LiteralPath (Join-Path $engineDir "dist/bridge-usfm-checker$extension") `
        -Destination $checkerBinary -Force
    if (-not $extension) {
        # Tauri spawns the sidecar as-is; a copy that lost its mode bit would
        # fail at launch with a permission error, not at bundle time.
        & chmod +x $engineBinary $checkerBinary
        if ($LASTEXITCODE -ne 0) { throw "chmod +x on the sidecars failed" }
    }

    # The bundled tN/tW/tA/UHB/UGNT snapshot (~45MB) is no longer part of
    # bridge-engine.spec's onefile archive (see that file's own comment) --
    # it ships instead via tauri.conf.json's bundle.resources, which reads
    # from src-tauri/resources at bundle time, same as binaries/ already
    # does for the sidecar exes. Rebuilt fresh each time rather than
    # incrementally patched, matching PyInstaller's own --clean above.
    if (Test-Path -LiteralPath $resourcesDir) {
        Remove-Item -LiteralPath $resourcesDir -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $engineDir "resources") -Destination $resourcesDir -Recurse -Force

    # The Language QA packs, the same way (docs/LANGUAGE_QA_PACKS.md): outside
    # the onefile archive, so a launch never re-extracts a lexicon.
    if (Test-Path -LiteralPath $packsDir) {
        Remove-Item -LiteralPath $packsDir -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $engineDir "language_packs") -Destination $packsDir -Recurse -Force
}
finally {
    Pop-Location
}

Write-Host "Built and copied Bridge sidecars for $TargetTriple"
