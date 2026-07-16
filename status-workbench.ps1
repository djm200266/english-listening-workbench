# status-workbench.ps1 - Display status of all services with workbench session info
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

$procFile = Join-Path $root "logs\runtime\processes.json"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  English Listening Workbench - Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ---- Workbench session info ----
if (Test-Path $procFile) {
    try {
        $procs = Get-Content $procFile -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host ""
        Write-Host "  Workbench Session:" -ForegroundColor White
        Write-Host "    Project root: $($procs.project_root)" -ForegroundColor Gray
        if ($procs.workbench_version) {
            Write-Host "    Version: $($procs.workbench_version)" -ForegroundColor Gray
        }
        if ($procs.started_at) {
            Write-Host "    Started at: $($procs.started_at)" -ForegroundColor Gray
        }
    } catch {
        Write-Host "  WARNING: Cannot parse processes.json" -ForegroundColor Yellow
        $procs = $null
    }
} else {
    Write-Host ""
    Write-Host "  No workbench session found (processes.json missing)" -ForegroundColor Yellow
    $procs = $null
}

# ---- Service checks ----
$services = @()

# Backend
$bePid = $null
$beStarted = $false
if ($procs -and $procs.backend) {
    $bePid = $procs.backend.pid
    $beStarted = $procs.backend.started_by_workbench
}

$beStatus = @{
    Name = "Backend"; Port = 8000; Url = "http://127.0.0.1:8000/api/health"
    Pid = $bePid; StartedByWorkbench = $beStarted
    Health = "unknown"; Details = @{}
}

try {
    $conn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $beStatus.Pid = if ($beStatus.Pid) { $beStatus.Pid } else { $conn.OwningProcess }
        $beProc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        $beStatus.ProcessName = $beProc.ProcessName
        $beStatus.CmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine

        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 5 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                $h = $r.Content | ConvertFrom-Json
                $beStatus.Health = "ok"
                $beStatus.Details = @{
                    mode = $h.mode
                    ollama = $h.ollama.available
                    piper = $h.piper.available
                    whisper = $h.whisper.available
                    comfyui = $h.comfyui.available
                    ffmpeg = $h.ffmpeg.available
                }
            } else {
                $beStatus.Health = "unhealthy"
                $beStatus.Details = @{ status_code = $r.StatusCode }
            }
        } catch {
            $beStatus.Health = "unreachable"
            $beStatus.Details = @{ error = $_.Exception.Message }
        }
    } else {
        $beStatus.Health = "not_listening"
    }
} catch {
    $beStatus.Health = "error"
}
$services += $beStatus

# Frontend
$fePid = $null
$feStarted = $false
if ($procs -and $procs.frontend) {
    $fePid = $procs.frontend.pid
    $feStarted = $procs.frontend.started_by_workbench
}

$feStatus = @{
    Name = "Frontend"; Port = 5173; Url = "http://127.0.0.1:5173"
    Pid = $fePid; StartedByWorkbench = $feStarted
    Health = "unknown"; Details = @{}
}

try {
    $conn = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $feStatus.Pid = if ($feStatus.Pid) { $feStatus.Pid } else { $conn.OwningProcess }
        $feProc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        $feStatus.ProcessName = $feProc.ProcessName

        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 3 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                $feStatus.Health = "ok"
            } else {
                $feStatus.Health = "unhealthy"
                $feStatus.Details = @{ status_code = $r.StatusCode }
            }
        } catch {
            $feStatus.Health = "unreachable"
        }
    } else {
        $feStatus.Health = "not_listening"
    }
} catch {
    $feStatus.Health = "error"
}
$services += $feStatus

# Ollama
$olPid = $null
$olStarted = $false
if ($procs -and $procs.ollama) {
    $olPid = $procs.ollama.pid
    $olStarted = $procs.ollama.started_by_workbench
}

$olStatus = @{
    Name = "Ollama"; Port = 11434; Url = "http://127.0.0.1:11434/api/tags"
    Pid = $olPid; StartedByWorkbench = $olStarted
    Health = "unknown"; Details = @{}
}

try {
    $conn = Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $olStatus.Pid = if ($olStatus.Pid) { $olStatus.Pid } else { $conn.OwningProcess }
        try {
            $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5 -UseBasicParsing
            $modelNames = if ($tags.models) { ($tags.models | Select-Object -ExpandProperty name | Select-Object -First 5) -join ", " } else { "none" }
            $olStatus.Health = "ok"
            $olStatus.Details = @{ models = $modelNames }
        } catch {
            $olStatus.Health = "unreachable"
        }
    } else {
        $olStatus.Health = "not_listening"
    }
} catch {
    $olStatus.Health = "error"
}
$services += $olStatus

# ComfyUI
$cuPid = $null
$cuStarted = $false
if ($procs -and $procs.comfyui) {
    $cuPid = $procs.comfyui.pid
    $cuStarted = $procs.comfyui.started_by_workbench
}

$cuStatus = @{
    Name = "ComfyUI"; Port = 8188; Url = "http://127.0.0.1:8188/system_stats"
    Pid = $cuPid; StartedByWorkbench = $cuStarted
    Health = "unknown"; Details = @{}
}

try {
    $conn = Get-NetTCPConnection -LocalPort 8188 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $cuStatus.Pid = if ($cuStatus.Pid) { $cuStatus.Pid } else { $conn.OwningProcess }
        $cuProc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        $cuStatus.ProcessName = $cuProc.ProcessName
        $cuCmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine
        $cuStatus.CmdLine = $cuCmdLine

        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8188/system_stats" -TimeoutSec 5 -UseBasicParsing
            if ($r.StatusCode -eq 200) {
                $cuStatus.Health = "ok"
                # Try to detect install root from command line
                if ($cuCmdLine -and $cuCmdLine -like "*python_embeded*ComfyUI*main.py*") {
                    $idx = $cuCmdLine.IndexOf("python_embeded")
                    if ($idx -gt 0) {
                        $cuStatus.Details = @{ install_root = $cuCmdLine.Substring(0, $idx).TrimEnd("\") }
                    }
                }
            } else {
                $cuStatus.Health = "unhealthy"
            }
        } catch {
            $cuStatus.Health = "unreachable"
        }
    } else {
        $cuStatus.Health = "not_listening"
    }
} catch {
    $cuStatus.Health = "error"
}
$services += $cuStatus

# ---- Display ----
Write-Host ""
Write-Host "  Services:" -ForegroundColor White
Write-Host ""

foreach ($svc in $services) {
    $icon = switch ($svc.Health) {
        "ok" { "[OK]" }
        "unhealthy" { "[??]" }
        "unreachable" { "[--]" }
        "not_listening" { "[  ]" }
        default { "[??]" }
    }
    $color = switch ($svc.Health) {
        "ok" { "Green" }
        "unhealthy" { "Yellow" }
        "unreachable" { "Red" }
        "not_listening" { "Red" }
        default { "Yellow" }
    }

    $pidStr = if ($svc.Pid) { "PID $($svc.Pid)" } else { "PID=N/A" }
    $source = if ($svc.StartedByWorkbench) { "started by workbench" } else { "external/pre-existing" }

    Write-Host "  $icon $($svc.Name.PadRight(10)) : $($svc.Url)" -ForegroundColor $color
    Write-Host "           $pidStr, $source" -ForegroundColor Gray

    if ($svc.ProcessName) {
        Write-Host "           Process: $($svc.ProcessName)" -ForegroundColor Gray
    }

    # Show truncated command line
    if ($svc.CmdLine) {
        $trunc = if ($svc.CmdLine.Length -gt 120) { $svc.CmdLine.Substring(0, 120) + "..." } else { $svc.CmdLine }
        Write-Host "           CmdLine: $trunc" -ForegroundColor Gray
    }

    # Show health details
    if ($svc.Name -eq "Backend" -and $svc.Health -eq "ok") {
        Write-Host "           Ollama: $($svc.Details.ollama)  Piper: $($svc.Details.piper)  Whisper: $($svc.Details.whisper)  ComfyUI: $($svc.Details.comfyui)  FFmpeg: $($svc.Details.ffmpeg)" -ForegroundColor Gray
    }
    if ($svc.Name -eq "Ollama" -and $svc.Details.models) {
        Write-Host "           Models: $($svc.Details.models)" -ForegroundColor Gray
    }
    if ($svc.Name -eq "ComfyUI" -and $svc.Details.install_root) {
        Write-Host "           Install: $($svc.Details.install_root)" -ForegroundColor Gray
    }

    Write-Host ""
}

Write-Host "========================================" -ForegroundColor Cyan

# ---- Backend version check ----
if ($beStatus.Health -eq "ok") {
    try {
        $ver = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/version" -TimeoutSec 3 -UseBasicParsing
        Write-Host ""
        Write-Host "  Backend Identity:" -ForegroundColor White
        Write-Host "    App     : $($ver.app)" -ForegroundColor Green
        Write-Host "    Version : $($ver.version)" -ForegroundColor White
        Write-Host "    Build   : $($ver.build_id)" -ForegroundColor Gray
        Write-Host "    Mode    : $($ver.mode)" -ForegroundColor White
        Write-Host "    Features: $($ver.features -join ', ')" -ForegroundColor Gray
    } catch { }
}

Write-Host ""
Write-Host "Press Enter to close..." -ForegroundColor Gray
Read-Host
