# doctor-workbench.ps1 - Automated diagnostics
$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
Set-Location $root

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Workbench Doctor" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

function Test-Check($label, $ok, $detail = "") {
    $s = if ($ok) { "[OK]" } else { "[FAIL]" }
    $c = if ($ok) { "Green" } else { "Red" }
    Write-Host "  $s $label" -ForegroundColor $c
    if ($detail -and -not $ok) { Write-Host "    $detail" -ForegroundColor Gray }
}

# 1. Paths
Test-Check "Project root exists" (Test-Path $root) $root
Test-Check "config.json" (Test-Path (Join-Path $root "config.json"))
Test-Check "backend/main.py" (Test-Path (Join-Path $root "backend" "main.py"))
Test-Check "frontend/package.json" (Test-Path (Join-Path $root "frontend" "package.json"))

# 2. Python
$py = "D:\english_eval\whisper_env\Scripts\python.exe"
Test-Check "Python exists" (Test-Path $py) $py

# 3. Node
$npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $npm) { $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source }
Test-Check "npm exists" ($npm -ne $null) "$npm"

# 4. FastAPI import
if (Test-Path (Join-Path $root "backend" "main.py")) {
    Push-Location (Join-Path $root "backend")
    $result = & $py -c "from main import app; print('OK')" 2>&1
    Pop-Location
    Test-Check "FastAPI import" ($result -eq "OK") $result
}

# 5. PS parser
foreach ($f in @("start-workbench.ps1","stop-workbench.ps1","status-workbench.ps1","detect-comfyui.ps1")) {
    $t=$null; $e=$null
    $fp = Join-Path $root $f
    if (Test-Path $fp) {
        [System.Management.Automation.Language.Parser]::ParseFile($fp,[ref]$t,[ref]$e)|Out-Null
        Test-Check "PS parser: $f" ($e.Count -eq 0) "$($e.Count) errors"
    } else {
        Test-Check "PS parser: $f" $false "File not found"
    }
}

# 6. Ports
foreach ($port in @(5173,8000,11434,8188)) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
        $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Test-Check "Port $port" $true "PID=$($c.OwningProcess) $($p.ProcessName)"
    } else {
        Test-Check "Port $port" $false "Not listening"
    }
}

# 7. HTTP checks
$urls = @(
    @{URL="http://127.0.0.1:8000/api/health"; Label="Backend /api/health"},
    @{URL="http://127.0.0.1:8000/api/version"; Label="Backend /api/version"}
)
foreach ($u in $urls) {
    try {
        $r = Invoke-WebRequest -Uri $u.URL -TimeoutSec 3 -UseBasicParsing
        Test-Check $u.Label ($r.StatusCode -eq 200) "HTTP $($r.StatusCode)"
    } catch {
        Test-Check $u.Label $false $_.Exception.Message
    }
}

# 8. OpenAPI key routes
try {
    $schema = Invoke-RestMethod -Uri "http://127.0.0.1:8000/openapi.json" -TimeoutSec 3 -UseBasicParsing
    $paths = ($schema.paths | Get-Member -MemberType NoteProperty).Name
    $keys = @("/api/health","/api/version","/api/v1/script/generate","/api/v1/prompt-assistant/image")
    foreach ($k in $keys) {
        Test-Check "OpenAPI: $k" ($k -in $paths)
    }
} catch {
    Test-Check "OpenAPI" $false $_.Exception.Message
}

# 9. Logs
$logDir = Join-Path $root "logs\runtime"
if (Test-Path $logDir) {
    foreach ($log in @("backend-error.log","frontend-error.log")) {
        $lp = Join-Path $logDir $log
        if (Test-Path $lp) {
            $lines = Get-Content $lp -Tail 5 -ErrorAction SilentlyContinue
            if ($lines) {
                Write-Host "  [LOG] $log (last 5 lines):" -ForegroundColor Gray
                $lines | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
            }
        }
    }
}

Write-Host ""
Write-Host "Doctor check complete." -ForegroundColor Cyan
Read-Host "Press Enter to close..."
