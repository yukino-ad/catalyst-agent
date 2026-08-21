param(
    [string]$Python = "py -3.10",
    [string]$VenvName = ".venv-repro"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$parts = $Python -split " "
$pythonCommand = $parts[0]
$pythonArguments = @($parts | Select-Object -Skip 1)

& $pythonCommand @pythonArguments -c "import sys; assert sys.version_info[:2] in {(3,10),(3,11)}, 'Python 3.10 or 3.11 is required'; print(sys.version)"
if ($LASTEXITCODE -ne 0) {
    throw "A working Python 3.10 or 3.11 interpreter is required."
}

if (Test-Path -LiteralPath $VenvName) {
    throw "$VenvName already exists. Choose another -VenvName or remove it manually after inspection."
}

& $pythonCommand @pythonArguments -m venv $VenvName
$VenvPython = Join-Path $ProjectRoot "$VenvName\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r requirements.txt
& $VenvPython -m app.environment_check
& $VenvPython -m unittest discover -s tests -v

Write-Host "Environment created at $VenvName"
Write-Host "Activate with: .\$VenvName\Scripts\Activate.ps1"
