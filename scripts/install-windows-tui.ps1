$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Update-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $processPath = [Environment]::GetEnvironmentVariable("Path", "Process")
    $pathParts = (($processPath, $machinePath, $userPath) -join ";").Split(";") |
        Where-Object { $_ } |
        Select-Object -Unique
    $env:Path = [string]::Join(";", $pathParts)
}

function Install-WingetPackage {
    param(
        [string]$Id,
        [string]$Name
    )
    if (-not (Test-Command winget)) {
        throw "winget is not available. Install 'App Installer' from the Microsoft Store, then run this command again."
    }

    Write-Step "Installing $Name"
    winget install --id $Id --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget could not install $Name. Close PowerShell, open a fresh normal PowerShell window, and run this command again."
    }
    Update-ProcessPath
}

Write-Host "sfxworkbench Windows installer" -ForegroundColor Green

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Tip: normal PowerShell is recommended; continuing in your user folder." -ForegroundColor Yellow
}

Write-Step "Preparing user folder"
Set-Location $HOME

Update-ProcessPath

if (-not (Test-Command git)) {
    Install-WingetPackage -Id "Git.Git" -Name "Git"
}
if (-not (Test-Command git)) {
    throw "Git was installed but is not visible yet. Close PowerShell, open a fresh normal PowerShell window, and run this command again."
}

if (-not (Test-Command uv)) {
    Install-WingetPackage -Id "astral-sh.uv" -Name "uv"
}
if (-not (Test-Command uv)) {
    throw "uv was installed but is not visible yet. Close PowerShell, open a fresh normal PowerShell window, and run this command again."
}

Write-Step "Using tools"
git --version
uv --version

$repoDir = Join-Path $HOME "sfxworkbench"
if (Test-Path $repoDir) {
    if (-not (Test-Path (Join-Path $repoDir ".git"))) {
        throw "$repoDir already exists but is not a git checkout. Rename that folder, then run this command again."
    }
    Write-Step "Updating sfxworkbench"
    git -C $repoDir pull --ff-only
} else {
    Write-Step "Cloning sfxworkbench"
    git clone https://github.com/cmyklops/sfxworkbench.git $repoDir
}

Set-Location $repoDir

Write-Step "Installing Python 3.11 and dependencies"
uv python install 3.11
uv sync --python 3.11 --extra dev --extra metadata --extra tui

New-Item -ItemType Directory -Force reports | Out-Null
$env:PYTHONUTF8 = "1"

$sfx = Join-Path $repoDir ".venv\Scripts\sfx.exe"
if (-not (Test-Path $sfx)) {
    throw "Expected launcher was not created at $sfx."
}

Write-Step "Launching sfxworkbench"
& $sfx tui --db .\win_test.db --report .\reports
