[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('backend', 'worker', 'frontend')]
    [string] $Service,
    [switch] $Check
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$environment = Join-Path $repo 'socra-backend\.venv'
$python = Join-Path $environment 'Scripts\python.exe'
$packages = $null
$appFolder = Join-Path $env:ProgramFiles 'WindowsApps'
$runtime = Get-ChildItem -LiteralPath $appFolder -Directory -Filter 'OpenAI.CodexPrimaryRuntime*' -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTimeUtc -Descending |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'dependencies\python\python.exe') } |
    Select-Object -First 1

if ($runtime) {
    $python = Join-Path $runtime.FullName 'dependencies\python\python.exe'
    $packages = Join-Path $environment 'Lib\site-packages'
    if (-not (Test-Path -LiteralPath $packages)) { throw 'Install the locked Socra backend dependencies first.' }
} elseif (-not (Test-Path -LiteralPath $python)) {
    throw 'A working Socra Python 3.12 environment is required.'
}

$previousPythonPath = $env:PYTHONPATH
if ($packages) { $env:PYTHONPATH = $packages }
try {
    $flags = @()
    if ($Check) { $flags += '--check' }
    & $python -B (Join-Path $PSScriptRoot 'run_socra_test.py') $Service @flags
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
