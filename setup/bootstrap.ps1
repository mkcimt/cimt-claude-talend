# Thin PowerShell shim that finds Python and forwards to bootstrap.py.
# Use this on Windows so you don't have to type `python setup\bootstrap.py ...`.

$ErrorActionPreference = "Stop"

function Find-Python {
    foreach ($name in @("python3", "python", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python is not installed or not in PATH." -ForegroundColor Red
    Write-Host "Install Python 3.9+ from https://python.org (tick 'Add Python to PATH' in the installer) and re-run."
    exit 1
}

$dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
& $python "$dir\bootstrap.py" @args
exit $LASTEXITCODE
