param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$WithHpc
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot
$composeFiles = @("-f", "docker-compose.full.yml")
if ($WithHpc) { $composeFiles += @("-f", "docker-compose.hpc.yml") }
docker compose @composeFiles down
Write-Host "Full Agent containers stopped. Data remains on disk." -ForegroundColor Green
