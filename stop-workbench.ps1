# stop-workbench.ps1 - Safely stop ONLY processes started by start-workbench.ps1
# Uses processes.json to identify workbench-owned processes.
# Never kills Ollama, ComfyUI, or other unrelated processes.
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

$procFile = Join-Path $root "logs\runtime\processes.json"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Stop - English Listening Workbench" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $procFile)) {
    Write-Host "No processes.json found. Nothing tracked by workbench." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Press Enter to close..." -ForegroundColor Gray ; Read-Host
    return
}

try {
    $procs = Get-Content $procFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Host "ERROR: Cannot parse processes.json" -ForegroundColor Red
    Write-Host "Press Enter to close..." -ForegroundColor Gray ; Read-Host
    return
}

$stopped = 0
$skipped = 0

Write-Host ("Session: startup_id=" + $procs.startup_id + " at " + $procs.startup_time) -ForegroundColor Gray
Write-Host ""

# ---- Stop Backend ----
$be = $procs.backend
if ($be) {
    $pidsToStop = @()
    if ($be.all_pids) {
        # New format with all_pids array
        $pidsToStop = $be.all_pids
    } elseif ($be.listen_pid) {
        $pidsToStop = @($be.listen_pid)
        if ($be.parent_pid -and $be.parent_pid -ne $be.listen_pid) {
            $pidsToStop += $be.parent_pid
        }
    } elseif ($be.pid) {
        $pidsToStop = @($be.pid)
    }

    if ($be.started_by_workbench -eq $false) {
        Write-Host ("SKIP: Backend was not started by workbench (PID(s): " + ($pidsToStop -join ",") + ")") -ForegroundColor Gray
        $skipped += $pidsToStop.Count
    } else {
        foreach ($bepid in $pidsToStop) {
            if (-not $bepid) { continue }
            $proc = Get-Process -Id $bepid -ErrorAction SilentlyContinue
            if (-not $proc) {
                Write-Host ("Backend PID " + $bepid + ": already stopped") -ForegroundColor Gray
                $stopped += 1
                continue
            }
            $cmdLine = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $bepid) -ErrorAction SilentlyContinue).CommandLine
            $isOurs = $cmdLine -and ($cmdLine -match "uvicorn.*main.*app|english-listening-workbench|whisper_env")
            if ($isOurs) {
                Write-Host ("Stopping Backend PID " + $bepid + " ...") -ForegroundColor Yellow
                Stop-Process -Id $bepid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
                $still = Get-Process -Id $bepid -ErrorAction SilentlyContinue
                if ($still) {
                    Write-Host ("  WARNING: PID " + $bepid + " still alive after Stop-Process") -ForegroundColor Yellow
                } else {
                    Write-Host ("  Stopped PID " + $bepid) -ForegroundColor Green
                    $stopped += 1
                }
            } else {
                Write-Host ("SKIP: PID " + $bepid + " - command line does not match project") -ForegroundColor Gray
                $skipped += 1
            }
        }
    }
}

# ---- Stop Frontend ----
$fe = $procs.frontend
if ($fe) {
    $fePid = $fe.pid
    if (-not $fePid) { $fePid = 0 }
    if ($fe.started_by_workbench -eq $false) {
        Write-Host ("SKIP: Frontend was not started by workbench (PID " + $fePid + ")") -ForegroundColor Gray
        $skipped += 1
    } elseif ($fePid) {
        $proc = Get-Process -Id $fePid -ErrorAction SilentlyContinue
        if (-not $proc) {
            Write-Host ("Frontend PID " + $fePid + ": already stopped") -ForegroundColor Gray
            $stopped += 1
        } else {
            $cmdLine = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $fePid) -ErrorAction SilentlyContinue).CommandLine
            $isOurs = $cmdLine -and ($cmdLine -match "english-listening-workbench|vite|npm")
            if ($isOurs) {
                Write-Host ("Stopping Frontend PID " + $fePid + " ...") -ForegroundColor Yellow
                Stop-Process -Id $fePid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
                $still = Get-Process -Id $fePid -ErrorAction SilentlyContinue
                if ($still) {
                    Write-Host ("  WARNING: PID " + $fePid + " still alive") -ForegroundColor Yellow
                } else {
                    Write-Host ("  Stopped PID " + $fePid) -ForegroundColor Green
                    $stopped += 1
                }
            } else {
                Write-Host ("SKIP: PID " + $fePid + " - not a project process") -ForegroundColor Gray
                $skipped += 1
            }
        }
    }
}

# ---- NEVER stop Ollama or ComfyUI ----
$cu = $procs.comfyui
if ($cu -and $cu.pid) {
    if ($cu.started_by_workbench -eq $true) {
        Write-Host ("NOTE: ComfyUI PID " + $cu.pid + " was started by workbench but will be LEFT RUNNING.") -ForegroundColor Gray
        Write-Host "  Use Task Manager if you need to stop ComfyUI." -ForegroundColor Gray
    } else {
        Write-Host ("ComfyUI PID " + $cu.pid + ": pre-existing - left running") -ForegroundColor Gray
    }
}

$ol = $procs.ollama
if ($ol -and $ol.pid) {
    Write-Host ("Ollama PID " + $ol.pid + ": left running") -ForegroundColor Gray
}

Write-Host ""

# ---- Verify clean ports ----
foreach ($port in @(8000, 5173)) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) {
            $cmdLine = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $conn.OwningProcess) -ErrorAction SilentlyContinue).CommandLine
            if ($cmdLine -and ($cmdLine -match "english-listening-workbench|uvicorn|vite")) {
                Write-Host ("WARNING: Port " + $port + " still occupied by project process (PID " + $conn.OwningProcess + ")") -ForegroundColor Yellow
            } else {
                Write-Host ("Port " + $port + ": occupied by unrelated process (PID " + $conn.OwningProcess + ")") -ForegroundColor Gray
            }
        } else {
            Write-Host ("Port " + $port + ": free") -ForegroundColor Green
        }
    } catch { }
}

# ---- Clean up ----
Remove-Item $procFile -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host ("[Stop] Stopped: " + $stopped + ", Skipped: " + $skipped) -ForegroundColor Cyan
Write-Host "[Stop] Ollama and ComfyUI were NOT stopped." -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Enter to close..." -ForegroundColor Gray
Read-Host
