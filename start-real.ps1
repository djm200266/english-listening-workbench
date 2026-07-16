# start-real.ps1 — One-click startup for Real mode
# Run from project root: right-click → "Run with PowerShell"

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  English Listening Workbench" -ForegroundColor Cyan
Write-Host "  Starting Real mode services..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Check config ──
$config = Get-Content "config.json" -Raw | ConvertFrom-Json
if ($config.mode -ne "real") {
    Write-Host "[CONFIG] mode is '$($config.mode)', switching to 'real'..." -ForegroundColor Yellow
    $config.mode = "real"
    $config | ConvertTo-Json -Depth 10 | Set-Content "config.json" -Encoding UTF8
    Write-Host "[CONFIG] mode set to 'real'" -ForegroundColor Green
}

# ── Helper: Test-Port ──
function Test-Port($port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
    try { $listener.Start(); $listener.Stop(); return $false } catch { return $true }
}

# ── Helper: Start-Process-Bg ──
function Start-Process-Bg($exe, $args, $title, $workDir) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.Arguments = $args
    $psi.WorkingDirectory = $workDir
    $psi.UseShellExecute = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
    [System.Diagnostics.Process]::Start($psi) | Out-Null
    Write-Host "  Started: $title" -ForegroundColor Green
}

# ── 2. Ollama (port 11434) ──
$ollamaPort = 11434
if (Test-Port $ollamaPort) {
    Write-Host "[Ollama] Already running on port $ollamaPort" -ForegroundColor Green
} else {
    Write-Host "[Ollama] Not running — attempting to start..." -ForegroundColor Yellow
    $ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
    if ($ollamaPath) {
        Start-Process-Bg "ollama" "serve" "Ollama" $root
        Start-Sleep -Seconds 3
        Write-Host "[Ollama] Started" -ForegroundColor Green
    } else {
        Write-Host "[Ollama] WARNING: 'ollama' not found on PATH. Please start manually." -ForegroundColor Red
    }
}

# ── 3. ComfyUI (port 8188) ──
$comfyPort = 8188
if (Test-Port $comfyPort) {
    Write-Host "[ComfyUI] Already running on port $comfyPort" -ForegroundColor Green
} else {
    Write-Host "[ComfyUI] NOT running on port $comfyPort." -ForegroundColor Yellow
    Write-Host "[ComfyUI] Please start ComfyUI manually (e.g. run_nvidia_gpu.bat)." -ForegroundColor Yellow
    Write-Host "[ComfyUI] We do NOT guess the ComfyUI install directory." -ForegroundColor Yellow
}

# ── 4. FastAPI Backend (port 8000) ──
$backendPort = 8000
$backendDir = Join-Path $root "backend"
$pythonExe = "D:\english_eval\whisper_env\Scripts\python.exe"

if (Test-Port $backendPort) {
    Write-Host "[Backend] Already running on port $backendPort" -ForegroundColor Green
} else {
    if (-not (Test-Path $pythonExe)) {
        Write-Host "[Backend] ERROR: Python not found at $pythonExe" -ForegroundColor Red
    } else {
        Write-Host "[Backend] Starting FastAPI on port $backendPort..." -ForegroundColor Yellow
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $pythonExe
        $psi.Arguments = "-m uvicorn main:app --host 127.0.0.1 --port $backendPort"
        $psi.WorkingDirectory = $backendDir
        $psi.UseShellExecute = $true
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
        # Set window title via cmd start
        $proc = [System.Diagnostics.Process]::Start($psi)
        Start-Sleep -Seconds 3
        Write-Host "[Backend] Started (PID $($proc.Id))" -ForegroundColor Green
    }
}

# ── 5. Frontend (port 5173) ──
$frontendPort = 5173
$frontendDir = Join-Path $root "frontend"

if (Test-Port $frontendPort) {
    Write-Host "[Frontend] Already running on port $frontendPort" -ForegroundColor Green
} else {
    $npmPath = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmPath) { $npmPath = Get-Command npm -ErrorAction SilentlyContinue }
    if ($npmPath) {
        Write-Host "[Frontend] Starting Vite dev server on port $frontendPort..." -ForegroundColor Yellow
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "cmd.exe"
        $psi.Arguments = "/c `"cd /d $frontendDir && title EnglishWorkbench-Frontend && npm.cmd run dev`""
        $psi.UseShellExecute = $true
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
        [System.Diagnostics.Process]::Start($psi) | Out-Null
        Start-Sleep -Seconds 3
        Write-Host "[Frontend] Started" -ForegroundColor Green
    } else {
        Write-Host "[Frontend] ERROR: npm not found on PATH." -ForegroundColor Red
    }
}

# ── 6. Open browser ──
$frontendUrl = "http://127.0.0.1:5173"
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Frontend : $frontendUrl" -ForegroundColor White
Write-Host "  Backend  : http://127.0.0.1:8000/api/health" -ForegroundColor White
Write-Host "  API Docs : http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "  ComfyUI  : http://127.0.0.1:8188" -ForegroundColor White
Write-Host "  Ollama   : http://127.0.0.1:11434/api/tags" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Start-Process $frontendUrl
Write-Host "Opening browser to $frontendUrl ..." -ForegroundColor Green
Write-Host ""
Write-Host "To stop: run stop-real.ps1" -ForegroundColor Gray
Write-Host "Press any key to close this window (services keep running)..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
