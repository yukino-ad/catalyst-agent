param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$WithHpc
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $ProjectRoot

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found. Install Docker Desktop first."
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start it and run this script again."
}
if (-not (Test-Path -LiteralPath ".env")) {
    throw "Missing .env. Copy .env.full.example to .env and fill in the Kimi key."
}

$composeFiles = @("-f", "docker-compose.full.yml")
if ($WithHpc) {
    $required = @("CLUSTER_SSH_KEY_HOST_PATH", "CLUSTER_KNOWN_HOSTS_HOST_PATH", "VASP_PBE_HOST_PATH")
    $envText = Get-Content -Raw -LiteralPath ".env"
    foreach ($name in $required) {
        if ($envText -notmatch "(?m)^$name=(?!replace-with|C:/path/to|$).+") {
            throw "HPC mode requires a real $name value in .env."
        }
    }
    $composeFiles += @("-f", "docker-compose.hpc.yml")
}

Write-Host "Starting the full Catalyst Agent package..." -ForegroundColor Cyan
docker compose @composeFiles up -d --build
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed. Inspect logs with: docker compose $($composeFiles -join ' ') logs"
}

docker compose @composeFiles ps
$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 5
        if ($health.status -eq "ok") { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if ($healthy) {
    Write-Host "Backend health check: OK" -ForegroundColor Green
} else {
    Write-Warning "Backend health check did not complete. Inspect backend logs."
}
Write-Host "Open: http://127.0.0.1:3000" -ForegroundColor Green
