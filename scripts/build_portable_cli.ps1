#Requires -Version 5.1
<#
.SYNOPSIS
    Freeze photo-workflow + photo-cartridge into a self-contained onedir
    build for a portable cartridge's runtime\win\ (portable-drive plan,
    Task 6).

.DESCRIPTION
    Builds in a FRESH, throwaway venv and installs the package NON-EDITABLE,
    so the frozen build reflects exactly what "pip install ." would ship --
    never an editable install pointing back at this checkout's src\ tree,
    which would make the frozen exe silently depend on files that will not
    travel with it.

    NOTE: kept to the same plain PowerShell subset as update_install.ps1 --
    pure ASCII, no $(if ...) string interpolation -- so it parses identically
    under Windows PowerShell 5.1 and PowerShell 7. See that script's header
    for why this matters; it is not a style preference.

.PARAMETER OutputDir
    Where the frozen build lands. Defaults to <repo>\runtime\win. Point it at
    a mounted cartridge's runtime\win\ to build straight onto the drive.

.EXAMPLE
    .\scripts\build_portable_cli.ps1
    .\scripts\build_portable_cli.ps1 -OutputDir "F:\runtime\win"
#>
param(
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot "runtime\win"
}

function Write-Log($msg) { Write-Host "[build] $msg" }

# Prefer the 'py' launcher pinned to 3.11 (dev-machine-setup.md's own
# convention); fall back to whatever 'python' resolves to.
function Resolve-Python311 {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $probe = & py -3.11 -c "print(1)" 2>$null
        if ($probe -eq "1") { return @("py", "-3.11") }
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @("python") }
    throw "No Python 3.11 interpreter found (tried 'py -3.11' and 'python'). Install Python 3.11 first."
}

$pythonCmd = Resolve-Python311
Write-Log ("repo:   " + $repoRoot)
Write-Log ("output: " + $OutputDir)

$buildTmp = Join-Path ([System.IO.Path]::GetTempPath()) ("pf-build-" + [System.Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $buildTmp | Out-Null
$buildVenv = Join-Path $buildTmp "venv"
$distDir = Join-Path $buildTmp "dist"
$workDir = Join-Path $buildTmp "work"

try {
    Write-Log "creating a fresh build venv..."
    & $pythonCmd[0] $pythonCmd[1..($pythonCmd.Length - 1)] -m venv $buildVenv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }

    $venvPython = Join-Path $buildVenv "Scripts\python.exe"
    & $venvPython -m pip install --quiet --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed (exit $LASTEXITCODE)" }

    Write-Log "installing photo-workflow[build] (non-editable)..."
    $buildTarget = $repoRoot + "[build]"
    & $venvPython -m pip install --quiet $buildTarget
    if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }

    $venvPyinstaller = Join-Path $buildVenv "Scripts\pyinstaller.exe"
    $specPath = Join-Path $repoRoot "scripts\photonforge.spec"

    Write-Log "running pyinstaller..."
    & $venvPyinstaller --noconfirm --clean --distpath $distDir --workpath $workDir $specPath
    if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed (exit $LASTEXITCODE)" }

    # The spec's single COLLECT() call already produces a flat directory with
    # both executables and one shared _internal\ -- exactly the shape
    # runner.lua's portable_exe() probes for. Nothing to flatten; just place it.
    $builtDir = Join-Path $distDir "photonforge-runtime"
    if (Test-Path $OutputDir) { Remove-Item -Recurse -Force $OutputDir }
    $outputParent = Split-Path $OutputDir -Parent
    if ($outputParent -and -not (Test-Path $outputParent)) {
        New-Item -ItemType Directory -Force -Path $outputParent | Out-Null
    }
    Move-Item $builtDir $OutputDir

    Write-Log "smoke-testing the frozen executables..."
    $workflowExe = Join-Path $OutputDir "photo-workflow.exe"
    $cartridgeExe = Join-Path $OutputDir "photo-cartridge.exe"
    & $workflowExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "$workflowExe --help failed (exit $LASTEXITCODE)" }
    & $cartridgeExe --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "$cartridgeExe --help failed (exit $LASTEXITCODE)" }

    $sizeBytes = (Get-ChildItem -Recurse -File $OutputDir | Measure-Object -Property Length -Sum).Sum
    $sizeMB = [math]::Round($sizeBytes / 1MB, 0)
    Write-Log ("OK: " + $OutputDir + " (" + $sizeMB + " MB) -- photo-workflow.exe, photo-cartridge.exe, _internal\")
} finally {
    if (Test-Path $buildTmp) { Remove-Item -Recurse -Force $buildTmp -ErrorAction SilentlyContinue }
}
