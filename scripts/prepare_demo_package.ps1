param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$DestinationRoot = (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "catalyst-agent-demo")
)

$ErrorActionPreference = "Stop"
$taskId = "external-c-dft-20260725-145226"

if (Test-Path -LiteralPath $DestinationRoot) {
    throw "Destination already exists: $DestinationRoot. Choose another path or remove it after reviewing its contents."
}

New-Item -ItemType Directory -Path $DestinationRoot | Out-Null

$copyExcluded = {
    param([System.IO.FileInfo]$File)
    $File.FullName -notmatch "\\(node_modules|\.next|venv|__pycache__)(\\|$)" -and
        $File.FullName -notmatch "\\database\\PBE(\\|$)"
}

function Copy-FilteredTree {
    param(
        [string]$SourceDirectory,
        [string]$DestinationDirectory
    )
    Get-ChildItem -LiteralPath $SourceDirectory -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object $copyExcluded |
        ForEach-Object {
            $childRelative = $_.FullName.Substring($SourceDirectory.Length).TrimStart("\\")
            $destination = Join-Path $DestinationDirectory $childRelative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $destination
        }
}

$rootItems = @(
    "app", "configs", "frontend", "prompts", "tools",
    "Dockerfile.backend", "requirements.txt", ".dockerignore",
    "docker-compose.demo.yml", ".env.demo.example"
)
foreach ($item in $rootItems) {
    $source = Join-Path $SourceRoot $item
    if (Test-Path -LiteralPath $source -PathType Container) {
        Copy-FilteredTree $source (Join-Path $DestinationRoot $item)
    } else {
        Copy-Item -LiteralPath $source -Destination $DestinationRoot
    }
}

# Copy source code and scientific data while excluding local environments and licensed POTCAR data.
foreach ($relative in @("models", "database")) {
    Copy-FilteredTree (Join-Path $SourceRoot $relative) (Join-Path $DestinationRoot $relative)
}

$scriptDestination = Join-Path $DestinationRoot "scripts"
New-Item -ItemType Directory -Path $scriptDestination | Out-Null
Copy-Item -LiteralPath (Join-Path $SourceRoot "scripts\start_demo.ps1") -Destination $scriptDestination
Copy-Item -LiteralPath (Join-Path $SourceRoot "scripts\stop_demo.ps1") -Destination $scriptDestination

$dataRoot = Join-Path $DestinationRoot "data"
$dataSources = @(
    "workflow_runs\$taskId.json",
    "cluster_jobs\records\61817369.json",
    "cluster_jobs\records\61822297.json",
    "cluster_results\$taskId",
    "adsorption_structures\$taskId",
    "adsorption_dft_inputs\$taskId",
    "dft_inputs\$taskId"
)
foreach ($relative in $dataSources) {
    $source = Join-Path $SourceRoot "data\$relative"
    if (-not (Test-Path -LiteralPath $source)) {
        Write-Warning "Demo data was not found and will be omitted: $relative"
        continue
    }
    $destination = Join-Path $dataRoot $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $source -Destination $destination -Recurse
}

@("reports", "cluster_results", "cluster_jobs", "workflow_runs", "adsorption_structures", "adsorption_dft_inputs", "dft_inputs") | ForEach-Object {
    New-Item -ItemType Directory -Path (Join-Path $dataRoot $_) -Force | Out-Null
}

New-Item -ItemType Directory -Path (Join-Path $DestinationRoot "docs") -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $SourceRoot "docs\DOCKER_DEMO_BEGINNER_GUIDE.md") -Destination (Join-Path $DestinationRoot "docs")
Copy-Item -LiteralPath (Join-Path $SourceRoot "README_DEMO.md") -Destination $DestinationRoot

Write-Host "Demo package created: $DestinationRoot" -ForegroundColor Green
Write-Host "Create .env on the destination computer from .env.demo.example." -ForegroundColor Cyan
