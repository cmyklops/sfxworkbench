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

$repoDir = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $repoDir

if (-not (Test-Path (Join-Path $repoDir ".git"))) {
    throw "$repoDir is not a git checkout. Run the one-line installer again."
}
if (-not (Test-Command git)) {
    throw "Git is not available. Run the one-line installer again, then reopen PowerShell if asked."
}
if (-not (Test-Command uv)) {
    throw "uv is not available. Run the one-line installer again, then reopen PowerShell if asked."
}

Write-Step "Checking GitHub for sfxworkbench updates"
git -C $repoDir fetch --prune origin main
if ($LASTEXITCODE -ne 0) {
    throw "Could not check GitHub for updates."
}
$branch = (git -C $repoDir rev-parse --abbrev-ref HEAD).Trim()
if ($branch -eq "main") {
    git -C $repoDir pull --ff-only origin main
} else {
    git -C $repoDir pull --ff-only
}
if ($LASTEXITCODE -ne 0) {
    throw "Could not update cleanly. If you edited files locally, commit or stash them, then run again."
}

Write-Step "Syncing Python 3.11 and dependencies"
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
