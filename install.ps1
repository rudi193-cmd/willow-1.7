# install.ps1 — Willow Windows Bootstrap
# b17: WIN1  ΔΣ=42
#
# Run once from PowerShell (as Administrator):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
#   .\install.ps1
#
# Phase 1: Preflight   — Windows build, WSL2, Ubuntu
# Phase 2: WSL2 setup  — enable features, install Ubuntu, set default
# Phase 3: Handoff     — clone willow-1.7 into WSL2, run seed.py

$ErrorActionPreference = "Stop"
$WILLOW_REPO  = "https://github.com/rudi193-cmd/willow-1.7"
$WILLOW_WSL   = "/opt/willow-1.7"
$RESUME_KEY   = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$RESUME_NAME  = "WillowInstallResume"
$RESUME_FLAG  = "$env:TEMP\willow-resume.flag"

function Write-Step { param($msg) Write-Host "`n  >>> $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  [ok] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [xx] $msg" -ForegroundColor Red }

# ── Banner ────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  Willow — Windows Bootstrap" -ForegroundColor White
Write-Host "  Everything runs inside Ubuntu after this." -ForegroundColor DarkGray
Write-Host ""

# ── Phase 1: Preflight ────────────────────────────────────────────────────────

Write-Step "Phase 1 — Preflight"

# Windows build check (WSL2 requires 19041+)
$build = [System.Environment]::OSVersion.Version.Build
if ($build -lt 19041) {
    Write-Fail "Windows build $build is too old. WSL2 requires build 19041 or later."
    Write-Warn "Update Windows and try again."
    exit 1
}
Write-Ok "Windows build: $build"

# Check if this is a resume after reboot
$isResume = Test-Path $RESUME_FLAG

# WSL2 feature check
$wslFeature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction SilentlyContinue
$vmFeature  = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction SilentlyContinue
$wslEnabled = ($wslFeature.State -eq "Enabled")
$vmEnabled  = ($vmFeature.State  -eq "Enabled")

# Ubuntu presence check
$ubuntuInstalled = $false
try {
    $distros = wsl --list --quiet 2>$null
    $ubuntuInstalled = ($distros -match "Ubuntu")
} catch { }

Write-Ok "WSL feature:  $(if ($wslEnabled) { 'enabled' } else { 'not enabled' })"
Write-Ok "VM platform:  $(if ($vmEnabled)  { 'enabled' } else { 'not enabled' })"
Write-Ok "Ubuntu:       $(if ($ubuntuInstalled) { 'found' } else { 'not found' })"

# ── Phase 2: WSL2 Setup ───────────────────────────────────────────────────────

Write-Step "Phase 2 — WSL2 setup"

$featuresJustEnabled = $false

if (-not $wslEnabled) {
    Write-Warn "Enabling Windows Subsystem for Linux..."
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -NoRestart | Out-Null
    $featuresJustEnabled = $true
}

if (-not $vmEnabled) {
    Write-Warn "Enabling Virtual Machine Platform..."
    Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -NoRestart | Out-Null
    $featuresJustEnabled = $true
}

if ($featuresJustEnabled) {
    # Register resume key so install continues after reboot
    $scriptPath = $MyInvocation.MyCommand.Path
    $resumeCmd  = "powershell -ExecutionPolicy RemoteSigned -File `"$scriptPath`""
    Set-ItemProperty -Path $RESUME_KEY -Name $RESUME_NAME -Value $resumeCmd
    New-Item -Path $RESUME_FLAG -ItemType File -Force | Out-Null

    Write-Host ""
    Write-Host "  WSL2 features enabled. A reboot is required." -ForegroundColor Yellow
    Write-Host "  Willow will resume automatically after restart." -ForegroundColor Yellow
    Write-Host ""
    $reboot = Read-Host "  Reboot now? [Y/N]"
    if ($reboot -match "^[Yy]") {
        Restart-Computer -Force
    } else {
        Write-Warn "Reboot manually and re-run this script to continue."
    }
    exit 0
}

# Clean up resume flag and registry key if we got here after reboot
if ($isResume) {
    Remove-Item $RESUME_FLAG -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $RESUME_KEY -Name $RESUME_NAME -ErrorAction SilentlyContinue
    Write-Ok "Resumed after reboot."
}

# Set WSL2 as default version
wsl --set-default-version 2 2>$null
Write-Ok "WSL default version set to 2"

# Install Ubuntu 22.04 if not present
if (-not $ubuntuInstalled) {
    Write-Warn "Installing Ubuntu 22.04..."

    $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
    if ($wingetAvailable) {
        winget install --id Canonical.Ubuntu.2204 --source msstore --accept-package-agreements --accept-source-agreements
    } else {
        Write-Fail "winget not found. Install Ubuntu 22.04 manually from the Microsoft Store, then re-run."
        exit 1
    }

    Write-Ok "Ubuntu 22.04 installed."
    Write-Warn "Ubuntu will ask you to create a username and password on first launch."
    Write-Warn "Open Ubuntu once from the Start menu to complete setup, then re-run this script."
    exit 0
}

Write-Ok "Ubuntu 22.04 ready."

# ── Phase 3: Handoff to WSL2 ──────────────────────────────────────────────────

Write-Step "Phase 3 — Handoff to WSL2"

# Ensure git is available inside WSL
$gitCheck = wsl bash -c "command -v git" 2>$null
if (-not $gitCheck) {
    Write-Warn "git not found in WSL — installing..."
    wsl bash -c "sudo apt-get update -qq && sudo apt-get install -y git"
}

# Clone willow-1.7 into WSL system path if not present
$cloneCheck = wsl bash -c "test -f $WILLOW_WSL/willow.sh && echo yes" 2>$null
if ($cloneCheck -ne "yes") {
    Write-Warn "Cloning willow-1.7 into WSL at $WILLOW_WSL ..."
    wsl bash -c "sudo git clone $WILLOW_REPO $WILLOW_WSL"
    Write-Ok "Cloned to $WILLOW_WSL"
} else {
    Write-Ok "willow-1.7 already at $WILLOW_WSL"
}

# Run seed.py inside WSL — this is where Linux takes over
Write-Host ""
Write-Host "  Handing off to seed.py inside Ubuntu..." -ForegroundColor Cyan
Write-Host "  Everything from here runs inside Linux." -ForegroundColor DarkGray
Write-Host ""

wsl python3 $WILLOW_WSL/seed.py

Write-Host ""
Write-Ok "Willow planted. Open Ubuntu to use it."
Write-Host ""
