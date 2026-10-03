# Start the AirPower backend (port 5050) and frontend (port 3000) in two PowerShell windows.
# Usage, from the repo root:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# Port 5050: see docs/DECISIONS.md D-63.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$port = 5050

$busy = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($busy) {
    Write-Error "Port $port is already in use by process $($busy[0].OwningProcess). Close it and run again."
}

$envFile = Join-Path $root "frontend\.env.local"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $root "frontend\.env.local.example") $envFile
}

Start-Process powershell -WorkingDirectory (Join-Path $root "backend") -ArgumentList @(
    "-NoExit", "-Command", "python -m uvicorn app.main:app --reload --port $port"
)
Start-Process powershell -WorkingDirectory (Join-Path $root "frontend") -ArgumentList @(
    "-NoExit", "-Command", "npm run dev"
)

Write-Host "Backend:  http://localhost:$port/docs"
Write-Host "Frontend: http://localhost:3000"
