#Requires -Version 5.1
<#
.SYNOPSIS
    Deploy PHOTONForge Lua plugin to Darktable's lua directory.

.DESCRIPTION
    Copies lua/photonforge/*.lua from the repo to Darktable's lua/photonforge/
    and ensures luarc contains the require line.

    Run this after any change to a .lua file in the repo so Darktable
    picks it up on next restart.

.PARAMETER DarktableDir
    Override the Darktable config directory.
    Defaults to %LOCALAPPDATA%\darktable (standard Windows install).

.EXAMPLE
    .\scripts\deploy_lua.ps1
    .\scripts\deploy_lua.ps1 -DarktableDir "D:\darktable-config"
#>
param(
    [string]$DarktableDir = "$env:LOCALAPPDATA\darktable"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# --- Resolve paths -----------------------------------------------------------
$repoRoot  = Split-Path $PSScriptRoot -Parent
$srcDir    = Join-Path $repoRoot "lua\photonforge"
$dstDir    = Join-Path $DarktableDir "lua\photonforge"
$luarc     = Join-Path $DarktableDir "luarc"

if (-not (Test-Path $srcDir)) {
    Write-Error "Source not found: $srcDir"
    exit 1
}

# --- Create destination if needed --------------------------------------------
if (-not (Test-Path $dstDir)) {
    New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    Write-Host "[create] $dstDir"
}

# --- Copy Lua files ----------------------------------------------------------
$files = Get-ChildItem -Path $srcDir -Filter "*.lua"
if ($files.Count -eq 0) {
    Write-Error "No .lua files found in $srcDir"
    exit 1
}

$copied   = 0
$upToDate = 0

foreach ($f in $files) {
    $dst = Join-Path $dstDir $f.Name
    $needsCopy = $true

    if (Test-Path $dst) {
        $srcHash = (Get-FileHash $f.FullName -Algorithm MD5).Hash
        $dstHash = (Get-FileHash $dst        -Algorithm MD5).Hash
        if ($srcHash -eq $dstHash) {
            $needsCopy = $false
        }
    }

    if ($needsCopy) {
        Copy-Item $f.FullName $dst -Force
        Write-Host "[copy]  $($f.Name)"
        $copied++
    } else {
        Write-Host "[ok]    $($f.Name)"
        $upToDate++
    }
}

# --- Copy the companion CSS theme (optional polish) --------------------------
$cssSrc = Join-Path $srcDir "photonforge.css"
if (Test-Path $cssSrc) {
    $cssDst = Join-Path $dstDir "photonforge.css"
    Copy-Item $cssSrc $cssDst -Force
    Write-Host "[copy]  photonforge.css"
}

# --- Copy the full darktable theme(s) ---------------------------------------
# Themes live in <darktable config>/themes/ and appear in Preferences -> theme.
$themeSrcDir = Join-Path $srcDir "themes"
if (Test-Path $themeSrcDir) {
    $themeDstDir = Join-Path $DarktableDir "themes"
    if (-not (Test-Path $themeDstDir)) {
        New-Item -ItemType Directory -Force -Path $themeDstDir | Out-Null
        Write-Host "[create] $themeDstDir"
    }
    foreach ($t in Get-ChildItem -Path $themeSrcDir -Filter "*.css") {
        Copy-Item $t.FullName (Join-Path $themeDstDir $t.Name) -Force
        Write-Host "[theme] $($t.Name)"
    }
}

# --- Ensure luarc has the require line ---------------------------------------
$requireLine = 'require "photonforge/main"'
$luarcOk = $false

if (Test-Path $luarc) {
    $content = Get-Content $luarc -Raw
    if ($content -match [regex]::Escape($requireLine)) {
        $luarcOk = $true
    }
}

if (-not $luarcOk) {
    Add-Content -Path $luarc -Value $requireLine
    Write-Host "[luarc] Added: $requireLine"
} else {
    Write-Host "[luarc] Already present: $requireLine"
}

# --- Summary -----------------------------------------------------------------
Write-Host ""
if ($copied -gt 0) {
    Write-Host "Deployed $copied file(s) ($upToDate already up to date)."
    Write-Host "Restart Darktable to load the changes."
} else {
    Write-Host "All $upToDate file(s) already up to date - nothing to do."
}
Write-Host ""
Write-Host "Full theme: Preferences -> General -> theme = 'PHOTONForge', then restart"
Write-Host "  Darktable. Re-tints the whole UI dark-maroon to match the plugin."
Write-Host "Panel-only alt: paste lua\photonforge\photonforge.css into"
Write-Host "  Preferences -> 'user.css' -> Save and apply (no full theme needed)."
