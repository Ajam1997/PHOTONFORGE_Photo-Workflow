#Requires -Version 5.1
<#
.SYNOPSIS
    Update an existing PHOTONForge install from the current working tree.

.DESCRIPTION
    Refreshes the Python package in the repo venv, deploys the Darktable Lua
    plugin, then VERIFIES the result — console scripts resolve, the expected
    photo-cartridge subcommands exist, every deployed .lua matches the repo,
    luarc has the require line, and darktablerc points at the venv CLI.

    It deploys whatever is checked out. It never runs git, so it cannot
    surprise you by moving your working tree.

    Idempotent: re-running when nothing changed reports "already up to date"
    and touches nothing.

    ⚠ RUN THIS YOURSELF IN A NORMAL POWERSHELL WINDOW — not through an AI
    agent. Agent tooling on this machine writes %LOCALAPPDATA% through a
    copy-on-write overlay, so files land at the same path string but a
    different backing store than the Darktable you launch. Everything
    "passes" and the panel never appears. See dev-docs/dev-machine-setup.md §3.

    ⚠ CLOSE DARKTABLE FIRST. It rewrites darktablerc on exit and will drop
    the cli_path preference this script sets.

.PARAMETER DarktableDir
    Darktable's CONFIG directory (not the install dir).
    Defaults to %LOCALAPPDATA%\darktable. For a portable install, pass the
    directory its launcher's --configdir points at.

.PARAMETER VerifyOnly
    Change nothing; just report whether the install is current. Use this to
    confirm the real state after deploying (especially if you suspect the
    overlay problem above).

.PARAMETER SkipPip
    Skip the venv package refresh. The install is editable, so new modules
    and new CLI subcommands are normally picked up without reinstalling;
    this switch makes that skip explicit and fast.

.PARAMETER Force
    Proceed even if Darktable is running. Not recommended — see above.

.EXAMPLE
    .\scripts\update_install.ps1
    .\scripts\update_install.ps1 -VerifyOnly
    .\scripts\update_install.ps1 -DarktableDir "F:\54-creative\Darktable\config"
#>
param(
    [string]$DarktableDir = $(if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "darktable" } else { "" }),
    [switch]$VerifyOnly,
    [switch]$SkipPip,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# photo-cartridge subcommands the Darktable panel invokes. Keep in step with
# runner.lua's CARTRIDGE_IMPLEMENTED table and IF-1.1 sub-contract 4 — if the
# panel can press it, this script checks the CLI actually has it.
$ExpectedCommands = @("init", "snapshot", "backup", "verify-backup", "restore-backup")

$script:Problems = @()

function Write-Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  [ok]   $msg" }
function Write-Act($msg)  { Write-Host "  [do]   $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  [warn] $msg" -ForegroundColor Yellow }
function Write-Bad($msg)  {
    Write-Host "  [FAIL] $msg" -ForegroundColor Red
    $script:Problems += $msg
}

# --- Resolve repo + venv -----------------------------------------------------
$repoRoot = Split-Path $PSScriptRoot -Parent

# Windows venvs put entry points in Scripts\; POSIX ones in bin/. Handling both
# keeps this runnable (and testable) outside Windows.
$venvDirs = @(
    (Join-Path $repoRoot ".venv\Scripts"),
    (Join-Path $repoRoot ".venv/bin")
)
$venvBin = $venvDirs | Where-Object { Test-Path $_ } | Select-Object -First 1

function Resolve-Entry($name) {
    if (-not $venvBin) { return $null }
    foreach ($candidate in @("$name.exe", $name)) {
        $p = Join-Path $venvBin $candidate
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "PHOTONForge install updater"
Write-Host "  repo:      $repoRoot"
Write-Host "  darktable: $(if ($DarktableDir) { $DarktableDir } else { '(not set)' })"
Write-Host "  venv:      $(if ($venvBin) { $venvBin } else { '(not found)' })"
if ($VerifyOnly) { Write-Host "  mode:      VERIFY ONLY (nothing will be changed)" -ForegroundColor Yellow }

# --- Preflight ---------------------------------------------------------------
Write-Step "Preflight"

if (-not $DarktableDir) {
    Write-Bad "No Darktable config dir. Pass -DarktableDir explicitly."
} elseif (-not (Test-Path $DarktableDir)) {
    Write-Bad "Darktable config dir not found: $DarktableDir"
} else {
    Write-Ok "Darktable config dir exists"
}

if (-not $venvBin) {
    Write-Bad "No venv at $repoRoot\.venv — see dev-docs/dev-machine-setup.md §2"
} else {
    Write-Ok "venv found"
}

$dtProcs = @(Get-Process -Name darktable -ErrorAction SilentlyContinue)
if ($dtProcs.Count -gt 0) {
    if ($VerifyOnly) {
        Write-Warn2 "Darktable is running (fine for -VerifyOnly)"
    } elseif ($Force) {
        Write-Warn2 "Darktable is running and -Force was given; it will overwrite darktablerc on exit and drop cli_path"
    } else {
        Write-Bad "Darktable is running. Close it first (it rewrites darktablerc on exit), or pass -Force."
    }
} else {
    Write-Ok "Darktable is not running"
}

if ($script:Problems.Count -gt 0) {
    Write-Host ""
    Write-Host "Preflight failed:" -ForegroundColor Red
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}

# --- 1. Python package -------------------------------------------------------
Write-Step "Python package"
if ($VerifyOnly -or $SkipPip) {
    Write-Ok "skipped$(if ($SkipPip) { ' (-SkipPip)' } else { ' (-VerifyOnly)' })"
} else {
    # `python -m pip`, not pip.exe: on Windows pip cannot replace itself while
    # its own .exe is running, and this works even in venvs created without a
    # bundled pip shim.
    $python = Resolve-Entry "python"
    if (-not $python) {
        Write-Bad "python not found in $venvBin"
    } else {
        # Absolute path, not "." — the script must work from any working
        # directory, and pip resolves "." against the caller's CWD.
        $target = "$repoRoot[dev]"
        Write-Act "python -m pip install -e `"$target`""
        & $python -m pip install -e $target --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Bad "pip install failed (exit $LASTEXITCODE)"
        } else {
            Write-Ok "package refreshed"
        }
    }
}

# --- 2. Lua plugin -----------------------------------------------------------
Write-Step "Darktable Lua plugin"
if ($VerifyOnly) {
    Write-Ok "skipped (-VerifyOnly)"
} else {
    $deploy = Join-Path $PSScriptRoot "deploy_lua.ps1"
    if (-not (Test-Path $deploy)) {
        Write-Bad "deploy_lua.ps1 not found next to this script"
    } else {
        Write-Act "deploy_lua.ps1 -DarktableDir `"$DarktableDir`""
        & $deploy -DarktableDir $DarktableDir | ForEach-Object { Write-Host "         $_" }
    }
}

# --- 3. Verify ---------------------------------------------------------------
Write-Step "Verify: console scripts"
$cartridge = Resolve-Entry "photo-cartridge"
$workflow  = Resolve-Entry "photo-workflow"

if (-not $workflow)  { Write-Bad "photo-workflow entry point missing" }  else { Write-Ok "photo-workflow" }
if (-not $cartridge) { Write-Bad "photo-cartridge entry point missing" } else { Write-Ok "photo-cartridge" }

if ($cartridge) {
    Write-Step "Verify: photo-cartridge subcommands"
    $help = (& $cartridge --help 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "photo-cartridge --help failed (exit $LASTEXITCODE)"
    } else {
        foreach ($cmd in $ExpectedCommands) {
            if ($help -match "(?m)^\s+$([regex]::Escape($cmd))\b") {
                Write-Ok "$cmd"
            } else {
                Write-Bad "$cmd missing from photo-cartridge --help"
            }
        }
    }
}

Write-Step "Verify: deployed plugin matches the repo"
$srcDir = Join-Path $repoRoot "lua\photonforge"
$dstDir = Join-Path $DarktableDir "lua\photonforge"
if (-not (Test-Path $dstDir)) {
    Write-Bad "plugin not deployed: $dstDir does not exist"
} else {
    $stale = 0
    foreach ($f in Get-ChildItem -Path $srcDir -Filter "*.lua") {
        $dst = Join-Path $dstDir $f.Name
        if (-not (Test-Path $dst)) {
            Write-Bad "$($f.Name) not deployed"
            $stale++
        } elseif ((Get-FileHash $f.FullName -Algorithm MD5).Hash -ne
                  (Get-FileHash $dst        -Algorithm MD5).Hash) {
            Write-Bad "$($f.Name) is STALE (deployed copy differs from the repo)"
            $stale++
        }
    }
    if ($stale -eq 0) { Write-Ok "all .lua files match the repo" }
}

Write-Step "Verify: Darktable wiring"
$luarc = Join-Path $DarktableDir "luarc"
$requireLine = 'require "photonforge/main"'
if ((Test-Path $luarc) -and ((Get-Content $luarc -Raw) -match [regex]::Escape($requireLine))) {
    Write-Ok "luarc loads the plugin"
} else {
    Write-Bad "luarc is missing: $requireLine"
}

$rc = Join-Path $DarktableDir "darktablerc"
if (Test-Path $rc) {
    $cliPref = Get-Content $rc | Where-Object { $_ -like 'lua/photonforge/cli_path=*' } | Select-Object -First 1
    if (-not $cliPref) {
        Write-Warn2 "cli_path not set in darktablerc — the panel will call bare 'photo-workflow', which a GUI-launched Darktable usually cannot see"
    } elseif ($workflow -and $cliPref -ne "lua/photonforge/cli_path=$workflow") {
        Write-Warn2 "cli_path points elsewhere: $cliPref"
    } else {
        Write-Ok "cli_path -> $workflow"
    }
} else {
    Write-Warn2 "no darktablerc yet (Darktable writes it on first exit)"
}

# --- Summary -----------------------------------------------------------------
Write-Host ""
if ($script:Problems.Count -gt 0) {
    Write-Host "FAILED — $($script:Problems.Count) problem(s):" -ForegroundColor Red
    $script:Problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "If every check looks like it should pass but the panel is still missing," -ForegroundColor Yellow
    Write-Host "you are probably seeing the AppData overlay described in" -ForegroundColor Yellow
    Write-Host "dev-docs/dev-machine-setup.md §3. Re-run this in a normal PowerShell window." -ForegroundColor Yellow
    exit 1
}

Write-Host "Install is up to date." -ForegroundColor Green
if (-not $VerifyOnly) {
    Write-Host ""
    Write-Host "Restart Darktable, then look for the CARTRIDGE strip in the lighttable panel:"
    Write-Host "  Row 1  Snapshot / Backup / Verify   <- working"
    Write-Host "  Row 2  Provision / Archive / Restore <- refuse with a message; not built yet"
    Write-Host ""
    Write-Host "Set 'Backup destination' under Preferences -> Lua options before using Backup or Verify."
}
exit 0
