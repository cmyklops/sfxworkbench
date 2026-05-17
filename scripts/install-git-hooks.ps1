$ErrorActionPreference = "Stop"

git config core.hooksPath .githooks
Write-Host "Git hooks installed: pre-push will run the platform preflight."
