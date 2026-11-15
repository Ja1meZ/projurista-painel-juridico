$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Write-Host "Python nao encontrado. Instale o Python 3 em https://www.python.org/downloads/ (marque Add python.exe to PATH) e rode de novo."; exit 1 }
$env:PYTHONUTF8 = "1"
python instalar.py @args
