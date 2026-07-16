# start-workbench.ps1 - One-click stable startup for English Listening Workbench
# All services launched via Start-Process, fully independent of calling terminal.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

# ---- Paths ----
$logsDir = Join-Path $root "logs\runtime"
$procFile = Join-Path $logsDir "processes.json"
$configPath = Join-Path $root "config.json"

$pythonPath = "D:\english_eval\whisper_env\Scripts\python.exe"
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"

$backendUrl = "http://127.0.0.1:8000"
$frontendUrl = "http://127.0.0.1:5173"
$ollamaUrl = "http://127.0.0.1:11434"
$comfyuiUrl = "http://127.0.0.1:8188"

# ---- Startup ID ----
$startupId = [Guid]::NewGuid().ToString().Substring(0, 8)
$startupTime = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"

# ---- Helpers ----
function Write-Log($msg, $color = "White") {
    $time = Get-Date -Format "HH:mm:ss"
    Write-Host ("[" + $time + "] " + $msg) -ForegroundColor $color
}

function Write-Banner($msg) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
}

function Test-HttpOk($Url, $TimeoutSec = 3) {
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing -SkipHttpErrorCheck
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Invoke-JsonGet($Url, $TimeoutSec = 3) {
    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing
    } catch { return $null }
}

function Get-CommandLine($ProcId) {
    try {
        $cim = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $ProcId) -ErrorAction SilentlyContinue
        if ($cim) { return $cim.CommandLine }
    } catch { }
    return ""
}

function Get-ListeningPid($port) {
    try {
        $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) { return $c.OwningProcess }
    } catch { }
    return $null
}

function Show-Tail($FilePath, $Count = 50) {
    if (Test-Path $FilePath) {
        $lines = Get-Content $FilePath -Tail $Count -ErrorAction SilentlyContinue
        if ($lines) {
            Write-Host ("--- " + $FilePath + " (last " + $Count + " lines) ---") -ForegroundColor Red
            foreach ($l in $lines) { Write-Host ("  " + $l) -ForegroundColor Red }
            Write-Host "--- End ---" -ForegroundColor Red
        }
    }
}

# ---- Process tracking ----
$script:tracker = @{
    backend_parent = $null
    backend_listen = $null
    backend_all_pids = @()
    frontend_pid = $null
    comfyui_pid = $null
    comfyui_started = $false
    ollama_pid = $null
    ollama_started = $false
}

# ---- Main ----
Write-Banner ("English Listening Workbench [startup:" + $startupId + "]")

# ---- 1. Create log dir + archive old logs ----
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

$oldLogs = Get-ChildItem -Path $logsDir -Filter "*.log" -ErrorAction SilentlyContinue
if ($oldLogs) {
    $archiveTs = Get-Date -Format "yyyyMMdd-HHmmss"
    $archiveDir = Join-Path $logsDir ("archive-" + $archiveTs)
    New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
    foreach ($f in $oldLogs) {
        Move-Item -Path $f.FullName -Destination (Join-Path $archiveDir $f.Name) -Force -ErrorAction SilentlyContinue
    }
    Write-Log ("Archived " + $oldLogs.Count + " old log(s) to archive-" + $archiveTs) Gray
}

# Write startup marker to new logs
$startupMarker = ("=== Startup " + $startupId + " at " + $startupTime + " ===")
$startupMarker | Out-File -FilePath (Join-Path $logsDir "backend.log") -Encoding UTF8
$startupMarker | Out-File -FilePath (Join-Path $logsDir "backend-error.log") -Encoding UTF8
$startupMarker | Out-File -FilePath (Join-Path $logsDir "startup.log") -Encoding UTF8

# ---- 2. Verify config ----
Write-Log "[Config] Loading config.json ..." White
if (-not (Test-Path $configPath)) {
    Write-Log "[Config] FATAL: config.json not found" Red
    Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
}
$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.mode -ne "real") {
    $config.mode = "real"
    $config | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8
    $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
}
Write-Log ("[Config] Mode: " + $config.mode) Green

# ---- 3. Check dependencies ----
if (-not (Test-Path $pythonPath)) {
    Write-Log "[Deps] FATAL: Python not found: $pythonPath" Red
    Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
}
Write-Log ("[Deps] Python OK") Green

$npmPath = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npmPath) { $npmPath = (Get-Command npm -ErrorAction SilentlyContinue).Source }
if (-not $npmPath) {
    Write-Log "[Deps] FATAL: npm not found on PATH" Red
    Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
}
Write-Log ("[Deps] npm OK") Green

# ---- 4. Ollama (11434) ----
Write-Log "[Ollama] Checking port 11434 ..." White
$olListen = Get-ListeningPid 11434
if ($olListen -and (Get-Process -Id $olListen -ErrorAction SilentlyContinue)) {
    if (Test-HttpOk ($ollamaUrl + "/api/tags") 5) {
        Write-Log ("[Ollama] Running (PID " + $olListen + ") - reusing") Green
        $script:tracker.ollama_pid = $olListen
        $script:tracker.ollama_started = $false
    } else {
        Write-Log "[Ollama] Port occupied but API not responding" Yellow
    }
} else {
    Write-Log "[Ollama] Not running - attempting start ..." Yellow
    $olExe = Get-Command ollama -ErrorAction SilentlyContinue
    if ($olExe) {
        try {
            $olProc = Start-Process -FilePath "ollama" -ArgumentList @("serve") `
                -WorkingDirectory $root -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $logsDir "ollama.log") `
                -RedirectStandardError (Join-Path $logsDir "ollama-error.log")
            Start-Sleep -Seconds 3
            $olListen2 = Get-ListeningPid 11434
            if ($olListen2) {
                Write-Log ("[Ollama] Started (PID " + $olListen2 + ")") Green
                $script:tracker.ollama_pid = $olListen2
                $script:tracker.ollama_started = $true
            } else {
                Write-Log "[Ollama] Started but not listening on 11434" Yellow
            }
        } catch {
            Write-Log ("[Ollama] Start failed: " + $_.Exception.Message) Yellow
        }
    } else {
        Write-Log "[Ollama] Not found on PATH - continuing without" Yellow
    }
}

# ---- 5. ComfyUI (8188) ----
Write-Log "[ComfyUI] Checking port 8188 ..." White
$cuListen = Get-ListeningPid 8188
$cuRunning = $false

if ($cuListen) {
    $cuProc = Get-Process -Id $cuListen -ErrorAction SilentlyContinue
    if (-not $cuProc) {
        Write-Log ("[ComfyUI] Port 8188 shows PID " + $cuListen + " but process does not exist - phantom port") Yellow
    } elseif ($cuProc.HasExited) {
        Write-Log ("[ComfyUI] PID " + $cuListen + " is zombie (HasExited=True) - cleaning up ...") Yellow
        try {
            $cuProc.Kill()
            $cuProc.Dispose()
            Start-Sleep -Seconds 2
            Write-Log "[ComfyUI] Zombie process cleaned" Green
        } catch {
            Write-Log ("[ComfyUI] Could not clean zombie: " + $_.Exception.Message) Yellow
        }
        # Re-check port
        $cuListen = Get-ListeningPid 8188
        if (-not $cuListen) {
            Write-Log "[ComfyUI] Port 8188 now free" Green
        }
    } elseif (Test-HttpOk ($comfyuiUrl + "/system_stats") 5) {
        Write-Log ("[ComfyUI] Running (PID " + $cuListen + ") - reusing") Green
        $script:tracker.comfyui_pid = $cuListen
        $script:tracker.comfyui_started = $false
        $cuRunning = $true
    } else {
        Write-Log ("[ComfyUI] PID " + $cuListen + " alive but /system_stats unreachable") Yellow
        $cmdLine = Get-CommandLine $cuListen
        if ($cmdLine -match "ComfyUI") {
            Write-Log "[ComfyUI] Looks like ComfyUI still starting - waiting 10s ..." Yellow
            if (Test-HttpOk ($comfyuiUrl + "/system_stats") 10) {
                Write-Log "[ComfyUI] Now responding - reusing" Green
                $script:tracker.comfyui_pid = $cuListen
                $script:tracker.comfyui_started = $false
                $cuRunning = $true
            } else {
                Write-Log "[ComfyUI] Still not responding - will NOT restart to avoid DB lock/port conflict" Yellow
                Write-Log "[ComfyUI] Try killing PID manually: taskkill /F /PID $cuListen" Yellow
            }
        } else {
            Write-Log "[ComfyUI] Port 8188 occupied by non-ComfyUI process - cannot start" Yellow
        }
    }
}

if (-not $cuRunning) {
    $cPyExe = $config.comfyui.pythonExe
    $cMainPy = $config.comfyui.mainPy
    $cRoot = $config.comfyui.installRoot

    if ($cPyExe -and $cMainPy -and (Test-Path $cPyExe) -and (Test-Path $cMainPy)) {
        Write-Log "[ComfyUI] Starting (this may take 30-180s) ..." Yellow
        Write-Log "[ComfyUI] Do NOT open http://127.0.0.1:8188 in browser" Gray
        try {
            $cuProc = Start-Process -FilePath $cPyExe `
                -ArgumentList @("-s", $cMainPy, "--listen", "127.0.0.1", "--port", "8188") `
                -WorkingDirectory $cRoot -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput (Join-Path $logsDir "comfyui-manager.log") `
                -RedirectStandardError (Join-Path $logsDir "comfyui-error.log")

            Write-Log ("[ComfyUI] Started parent PID " + $cuProc.Id) Gray
            $script:tracker.comfyui_pid = $cuProc.Id
            $script:tracker.comfyui_started = $true

            Write-Log "[ComfyUI] Waiting for /system_stats (max 180s) ..." Yellow
            $cuDeadline = (Get-Date).AddSeconds(180)
            $cuReady = $false
            while ((Get-Date) -lt $cuDeadline) {
                if ($cuProc.HasExited) {
                    Write-Log "[ComfyUI] Process exited prematurely!" Red
                    Show-Tail (Join-Path $logsDir "comfyui-error.log") 30
                    break
                }
                if (Test-HttpOk ($comfyuiUrl + "/system_stats") 3) {
                    Write-Log "[ComfyUI] Ready" Green
                    $cuReady = $true
                    break
                }
                Start-Sleep -Seconds 2
            }
            if (-not $cuReady) {
                Write-Log "[ComfyUI] WARNING: Not ready after 180s. Continuing anyway." Yellow
                Write-Log "[ComfyUI] Image generation may fail - ComfyUI can be auto-started later." Yellow
            }
        } catch {
            Write-Log ("[ComfyUI] WARNING: Start failed: " + $_.Exception.Message) Yellow
            Write-Log "[ComfyUI] Continuing without ComfyUI." Yellow
        }
    } else {
        Write-Log "[ComfyUI] WARNING: Paths not configured. Check config.json." Yellow
    }
}

# ---- 6. FastAPI Backend (8000) ----
$backendArgs = @("-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000")
$backendCmd = ($pythonPath + " -m uvicorn main:app --host 127.0.0.1 --port 8000")

Write-Log "[Backend] Checking port 8000 ..." White
$beListen = Get-ListeningPid 8000
$backendReady = $false

if ($beListen) {
    $beProc = Get-Process -Id $beListen -ErrorAction SilentlyContinue
    if (-not $beProc) {
        Write-Log ("[Backend] Port 8000 shows PID " + $beListen + " but process is dead - treating as free") Yellow
    } else {
        Write-Log ("[Backend] Port 8000 LISTEN: PID " + $beListen) White
        $cmdLine = Get-CommandLine $beListen

        # Check if it is our project
        $verResult = Invoke-JsonGet ($backendUrl + "/api/version") 5
        if ($verResult -and $verResult.app -eq "english-listening-workbench") {
            if (Test-HttpOk ($backendUrl + "/api/ping") 5) {
                Write-Log ("[Backend] Verified v" + $verResult.version + " - reusing") Green
                $script:tracker.backend_listen = $beListen
                $script:tracker.backend_parent = $beListen
                $script:tracker.backend_all_pids = @($beListen)
                $backendReady = $true
            } else {
                Write-Log "[Backend] Project found but /api/ping failed - will restart" Yellow
                Write-Log ("[Backend] Stopping PID " + $beListen + " ...") Yellow
                Stop-Process -Id $beListen -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
            }
        } elseif ($cmdLine -and ($cmdLine -match "uvicorn.*main.*app.*8000")) {
            Write-Log "[Backend] uvicorn detected but /api/version failed (old version?) - restarting" Yellow
            Write-Log ("[Backend] Stopping PID " + $beListen + " ...") Yellow
            Stop-Process -Id $beListen -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        } else {
            Write-Log ("[Backend] ERROR: Port 8000 occupied by UNRELATED process!") Red
            Write-Log ("  PID: " + $beListen) Red
            Write-Log ("  Path: " + $beProc.Path) Red
            Write-Log ("  CmdLine: " + $cmdLine) Red
            Write-Log "  ERROR CODE: BACKEND_PORT_OCCUPIED" Red
            Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
        }
    }
}

if (-not $backendReady) {
    # Ensure port is really free
    $linger = Get-ListeningPid 8000
    if ($linger) {
        Write-Log ("[Backend] WARNING: Port 8000 still occupied by PID " + $linger + " - forcing stop") Yellow
        Stop-Process -Id $linger -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }

    Write-Log "[Backend] Starting uvicorn (no --reload, stable mode) ..." Yellow
    Write-Log ("[Backend] " + $backendCmd) Gray

    $beProc = Start-Process -FilePath $pythonPath -ArgumentList $backendArgs `
        -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logsDir "backend.log") `
        -RedirectStandardError (Join-Path $logsDir "backend-error.log")

    $beParentPid = $beProc.Id
    Write-Log ("[Backend] Parent PID: " + $beParentPid) Gray
    $script:tracker.backend_parent = $beParentPid

    # Wait for port to come up, track the real listening PID
    Write-Log "[Backend] Waiting for port 8000 (max 60s, using /api/ping) ..." Yellow
    $beDeadline = (Get-Date).AddSeconds(60)
    $beListenPid = $null

    while ((Get-Date) -lt $beDeadline) {
        # Check if parent process died prematurely
        if ($beProc.HasExited) {
            $exitCode = $beProc.ExitCode
            Write-Log ("[Backend] FATAL: uvicorn exited immediately (code " + $exitCode + ")!") Red
            Show-Tail (Join-Path $logsDir "backend-error.log") 50
            Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
        }

        # Check if port is being listened on
        $beListenPid = Get-ListeningPid 8000
        if ($beListenPid) {
            Write-Log ("[Backend] Port 8000 LISTEN: PID " + $beListenPid) Gray

            # The listening PID might be a child of our Start-Process PID
            if ($beListenPid -ne $beParentPid) {
                Write-Log ("[Backend] Worker PID " + $beListenPid + " (parent: " + $beParentPid + ")") Gray
                # Check if worker is a child of our parent process
                try {
                    $cimChild = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $beListenPid) -ErrorAction SilentlyContinue
                    if ($cimChild -and $cimChild.ParentProcessId -eq $beParentPid) {
                        Write-Log "[Backend] Confirmed: worker is child of our parent process" Green
                    }
                } catch { }
            }

            # Now try to ping the backend
            if (Test-HttpOk ($backendUrl + "/api/ping") 10) {
                Write-Log "[Backend] /api/ping OK!" Green
                $script:tracker.backend_listen = $beListenPid
                $script:tracker.backend_all_pids = @($beParentPid, $beListenPid)
                $backendReady = $true
                break
            } else {
                Write-Log "[Backend] Port listening but /api/ping not responding yet ..." Yellow
            }
        }

        Start-Sleep -Seconds 1
    }

    if (-not $backendReady) {
        Write-Log "[Backend] FATAL: Not ready after 60s!" Red
        Write-Log ("[Backend] Parent PID " + $beParentPid + " HasExited=" + $beProc.HasExited) Red
        if ($beListenPid) {
            Write-Log ("[Backend] Port 8000 LISTEN: PID " + $beListenPid + " but /api/ping failed") Red
            Show-Tail (Join-Path $logsDir "backend-error.log") 30
        } else {
            Write-Log "[Backend] Port 8000 NEVER came up as LISTENING" Red
            Show-Tail (Join-Path $logsDir "backend-error.log") 50
        }
        Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
    }
}

# ---- 7. Verify /api/version ----
if ($backendReady) {
    $ver = Invoke-JsonGet ($backendUrl + "/api/version") 5
    if ($ver -and $ver.app -eq "english-listening-workbench") {
        Write-Log ("[Backend] Version: " + $ver.app + " v" + $ver.version + " build=" + $ver.build_id) Green
    } else {
        Write-Log "[Backend] WARNING: /api/version verification failed" Yellow
    }

    # ---- 8. Triple stability check ----
    Write-Log "[Backend] Stability check (3 pings, 2s apart) ..." White
    $allOk = $true
    for ($i = 1; $i -le 3; $i++) {
        Start-Sleep -Seconds 2
        if (Test-HttpOk ($backendUrl + "/api/ping") 5) {
            Write-Log ("[Backend] Ping " + $i + "/3 OK") Green
        } else {
            Write-Log ("[Backend] Ping " + $i + "/3 FAILED") Red
            $allOk = $false
        }
    }
    if (-not $allOk) {
        Write-Log "[Backend] WARNING: Unstable - some pings failed" Yellow
    }
}

# ---- 9. Vite Frontend (5173) ----
$frontendArgs = @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort")
$frontendCmd = "npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort"

Write-Log "[Frontend] Checking port 5173 ..." White
$feListen = Get-ListeningPid 5173
$frontReady = $false

if ($feListen) {
    $feProc = Get-Process -Id $feListen -ErrorAction SilentlyContinue
    if (-not $feProc) {
        Write-Log ("[Frontend] Port 5173 PID " + $feListen + " is dead - treating as free") Yellow
    } elseif (Test-HttpOk $frontendUrl 3) {
        Write-Log ("[Frontend] HTTP 200 - reusing (PID " + $feListen + ")") Green
        $script:tracker.frontend_pid = $feListen
        $frontReady = $true
    } else {
        $cmdLine = Get-CommandLine $feListen
        Write-Log "[Frontend] Port 5173 occupied but not responding" Yellow
        if ($cmdLine -and ($cmdLine -match "english-listening-workbench|vite")) {
            Write-Log "[Frontend] Stale project process - restarting ..." Yellow
            Stop-Process -Id $feListen -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        } else {
            Write-Log "[Frontend] ERROR: Port 5173 occupied by UNRELATED process!" Red
            Write-Log ("  PID: " + $feListen) Red
            Write-Log ("  Path: " + $feProc.Path) Red
            Write-Log ("  CmdLine: " + $cmdLine) Red
            Write-Log "  ERROR CODE: FRONTEND_PORT_OCCUPIED" Red
            Write-Host "Press Enter to exit..." ; Read-Host ; exit 1
        }
    }
}

if (-not $frontReady) {
    Write-Log "[Frontend] Starting Vite ..." Yellow
    Write-Log ("[Frontend] " + $frontendCmd) Gray

    $feProc = Start-Process -FilePath $npmPath -ArgumentList $frontendArgs `
        -WorkingDirectory $frontendDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logsDir "frontend.log") `
        -RedirectStandardError (Join-Path $logsDir "frontend-error.log")

    $fePid = $feProc.Id
    Write-Log ("[Frontend] PID: " + $fePid) Gray

    Write-Log "[Frontend] Waiting for HTTP 200 (max 30s) ..." Yellow
    $feDeadline = (Get-Date).AddSeconds(30)
    $feOk = $false
    while ((Get-Date) -lt $feDeadline) {
        if ($feProc.HasExited) {
            Write-Log "[Frontend] Vite exited prematurely!" Red
            Show-Tail (Join-Path $logsDir "frontend-error.log") 30
            break
        }
        if (Test-HttpOk $frontendUrl 3) {
            Write-Log "[Frontend] HTTP 200!" Green
            $script:tracker.frontend_pid = $fePid
            $feOk = $true
            $frontReady = $true
            break
        }
        Start-Sleep -Seconds 1
    }

    if (-not $feOk) {
        Write-Log "[Frontend] WARNING: Not responding after 30s" Yellow
        Show-Tail (Join-Path $logsDir "frontend-error.log") 20
    }
}

# ---- 10. Frontend stability ----
if ($frontReady) {
    Write-Log "[Frontend] Stability check (2 pings, 2s apart) ..." White
    for ($i = 1; $i -le 2; $i++) {
        Start-Sleep -Seconds 2
        if (Test-HttpOk $frontendUrl 3) {
            Write-Log ("[Frontend] Ping " + $i + "/2 OK") Green
        } else {
            Write-Log ("[Frontend] Ping " + $i + "/2 FAILED") Red
        }
    }
}

# ---- 11. Save processes.json ----
$procData = @{
    startup_id = $startupId
    startup_time = $startupTime
    project_root = $root
    backend = @{
        parent_pid = $script:tracker.backend_parent
        listen_pid = $script:tracker.backend_listen
        all_pids = $script:tracker.backend_all_pids
        command = $backendCmd
        working_directory = $backendDir
        started_by_workbench = $true
        started_at = $startupTime
    }
    frontend = @{
        pid = $script:tracker.frontend_pid
        command = $frontendCmd
        working_directory = $frontendDir
        started_by_workbench = (-not $feListen)
        started_at = $startupTime
    }
    comfyui = @{
        pid = $script:tracker.comfyui_pid
        started_by_workbench = $script:tracker.comfyui_started
        started_at = $startupTime
    }
    ollama = @{
        pid = $script:tracker.ollama_pid
        started_by_workbench = $script:tracker.ollama_started
        started_at = $startupTime
    }
}
$procData | ConvertTo-Json -Depth 6 | Set-Content $procFile -Encoding UTF8
Write-Log "[Processes] Saved to processes.json" Green

# ---- 12. Status table ----
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Services [startup:" $startupId "]" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$svcList = @(
    @{Name="Backend";  Url=($backendUrl+"/api/ping");    Port=8000;  Pid=$script:tracker.backend_listen}
    @{Name="Frontend"; Url=$frontendUrl;                   Port=5173;  Pid=$script:tracker.frontend_pid}
    @{Name="Ollama";   Url=($ollamaUrl+"/api/tags");       Port=11434; Pid=$script:tracker.ollama_pid}
    @{Name="ComfyUI";  Url=($comfyuiUrl+"/system_stats");  Port=8188;  Pid=$script:tracker.comfyui_pid}
)

foreach ($svc in $svcList) {
    $ok = Test-HttpOk $svc.Url 3
    $icon = if ($ok) { "[OK]" } else { "[--]" }
    $color = if ($ok) { "Green" } else { "Yellow" }
    $pidStr = if ($svc.Pid) { ("PID " + $svc.Pid) } else { "not running" }
    Write-Host ("  " + $icon + " " + $svc.Name.PadRight(10) + ": " + $svc.Url + "  (" + $pidStr + ")") -ForegroundColor $color
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---- 13. Open browser ----
Write-Log "Opening http://127.0.0.1:5173 ..." Green
Start-Process "http://127.0.0.1:5173"

Write-Host ""
Write-Log "Startup complete. All services are running independently." Cyan
Write-Log "You may close this window. Services will continue to run." Gray
Write-Log "To stop: double-click stop-workbench.cmd" Gray
Write-Host ""
Write-Host "Press Enter to close this window..." -ForegroundColor Gray
Read-Host
