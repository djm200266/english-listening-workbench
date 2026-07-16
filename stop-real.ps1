# stop-real.ps1 — Safely stop only project services
# Does NOT stop Ollama or ComfyUI

$ErrorActionPreference = "Continue"
Write-Host "Stopping English Listening Workbench services..." -ForegroundColor Yellow

# ── FastAPI Backend (port 8000) ──
$backendPid = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($backendPid) {
    $proc = Get-Process -Id $backendPid -ErrorAction SilentlyContinue
    if ($proc -and $proc.Path -like "*python*") {
        Stop-Process -Id $backendPid -Force
        Write-Host "[Backend] Stopped (PID $backendPid)" -ForegroundColor Green
    } else {
        Write-Host "[Backend] Port 8000 in use but not by Python — skipping (PID $backendPid)" -ForegroundColor Yellow
    }
} else {
    Write-Host "[Backend] Not running" -ForegroundColor Gray
}

# ── Vite Frontend (port 5173) ──
$frontendPid = (Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
if ($frontendPid) {
    $proc = Get-Process -Id $frontendPid -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -eq "node") {
        Stop-Process -Id $frontendPid -Force
        Write-Host "[Frontend] Stopped (PID $frontendPid)" -ForegroundColor Green
    } else {
        Write-Host "[Frontend] Port 5173 in use but not by node — skipping (PID $frontendPid)" -ForegroundColor Yellow
    }
} else {
    Write-Host "[Frontend] Not running" -ForegroundColor Gray
}

Write-Host ""
Write-Host "Done. Ollama and ComfyUI were NOT stopped." -ForegroundColor Cyan
Write-Host "Press any key to close..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
