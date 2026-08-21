param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DestinationRoot = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "catalyst-agent-full")
)

$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $DestinationRoot) {
    throw "Destination already exists: $DestinationRoot. Review it before removing or choosing another path."
}
New-Item -ItemType Directory -Path $DestinationRoot | Out-Null

function Copy-FullTree {
    param([string]$SourceDirectory, [string]$DestinationDirectory)
    Get-ChildItem -LiteralPath $SourceDirectory -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch "\\(node_modules|\.next|\.venv|venv|__pycache__|\.git)(\\|$)" -and
            $_.FullName -notmatch "\\database\\PBE(\\|$)" -and
            $_.Extension -notin @(".pyc", ".pyo") -and
            $_.Name -notin @(".env", ".env.bak")
        } |
        ForEach-Object {
            $relative = $_.FullName.Substring($SourceDirectory.Length).TrimStart("\\")
            $destination = Join-Path $DestinationDirectory $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination
        }
}

$directories = @("app", "configs", "database", "data", "frontend", "models", "prompts", "scripts", "tools")
foreach ($directory in $directories) {
    Copy-FullTree (Join-Path $SourceRoot $directory) (Join-Path $DestinationRoot $directory)
}
$files = @(
    ".dockerignore", "Dockerfile.backend", "docker-compose.full.yml",
    "docker-compose.hpc.yml", ".env.full.example", "requirements.txt",
    "README_FULL.md"
)
foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $SourceRoot $file) -Destination $DestinationRoot }
New-Item -ItemType Directory -Path (Join-Path $DestinationRoot "docs") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $SourceRoot "docs\DOCKER_FULL_BEGINNER_GUIDE.md") -Destination (Join-Path $DestinationRoot "docs")

Write-Host "Full package created: $DestinationRoot" -ForegroundColor Green
Write-Host "Licensed PBE/POTCAR data, .env, SSH keys, and known_hosts were intentionally excluded." -ForegroundColor Yellow
