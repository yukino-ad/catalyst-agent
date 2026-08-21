param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install Docker Desktop, restart PowerShell, and run this script again."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start Docker Desktop and wait until it reports Engine running."
}

if (-not (Test-Path -LiteralPath ".env")) {
    throw "Missing .env. Run: Copy-Item .env.demo.example .env, then enter your Kimi K3 API key."
}

Write-Host "Building and starting the safe demonstration mode..." -ForegroundColor Cyan
docker compose -f docker-compose.demo.yml up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed. Run 'docker compose -f docker-compose.demo.yml logs' for details."
}

Write-Host "Container status:" -ForegroundColor Cyan
docker compose -f docker-compose.demo.yml ps

$healthUrl = "http://127.0.0.1:8000/api/health"
$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
        if ($health.status -eq "ok") {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    Write-Warning "Backend health check did not complete. Inspect: docker compose -f docker-compose.demo.yml logs backend"
} else {
    Write-Host "Backend health check: OK" -ForegroundColor Green
}

Write-Host "Open the demonstration site: http://127.0.0.1:3000" -ForegroundColor Green
