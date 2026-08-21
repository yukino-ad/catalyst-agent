param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

docker compose -f docker-compose.demo.yml down
Write-Host "Demonstration containers stopped. Persistent data remains in the data folder." -ForegroundColor Green
