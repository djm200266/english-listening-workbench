# detect-comfyui.ps1 - Auto-discover ComfyUI install path
param([switch]$Quiet)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$configPath = Join-Path $root "config.json"

function Write-Log($msg, $color = "White") { if (-not $Quiet) { Write-Host $msg -ForegroundColor $color } }

function Get-ProcInfo($procId) {
    try {
        $p = Get-Process -Id $procId -ErrorAction Stop
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        return @{ PID=$procId; Name=$p.ProcessName; Path=$p.Path; CommandLine=$cim.CommandLine; ParentPID=$cim.ParentProcessId }
    } catch { return $null }
}

function Get-ParentChain($procId) {
    $chain = @(); $cur = $procId
    for ($i=0; $i -lt 8; $i++) {
        $info = Get-ProcInfo $cur; if (-not $info) { break }
        $chain += $info; $cur = $info.ParentPID
        if ($cur -eq 0 -or $cur -eq 4) { break }
    }
    return $chain
}

function Infer-ComfyRoot($info) {
    $candidates = @()
    if ($info.Path) {
        if ($info.Path -like "*ComfyUI*") {
            $idx = $info.Path.IndexOf("ComfyUI")
            if ($idx -gt 0) { $candidates += $info.Path.Substring(0, $idx).TrimEnd("\") }
        }
        if ($info.Path -like "*python_embeded*") {
            $idx = $info.Path.IndexOf("python_embeded")
            if ($idx -gt 0) { $candidates += $info.Path.Substring(0, $idx).TrimEnd("\") }
        }
    }
    if ($info.CommandLine) {
        $cl = $info.CommandLine
        if ($cl -like "*ComfyUI\main.py*") {
            $idx = $cl.IndexOf("python_embeded")
            if ($idx -gt 0) { $candidates += $cl.Substring(0, $idx).TrimEnd("\") }
        }
    }
    return $candidates | Select-Object -Unique
}

function Find-StartScript($dir) {
    $priority = @("run_nvidia_gpu.bat","run_nvidia_gpu_fp16_accumulation.bat","run_cpu.bat","ComfyUI.exe","comfyui.exe")
    foreach ($name in $priority) {
        $p = Join-Path $dir $name
        if (Test-Path $p) { return $p }
    }
    $parent = $dir
    for ($i=0; $i -lt 5; $i++) {
        foreach ($name in $priority) {
            $p = Join-Path $parent $name
            if (Test-Path $p) { return $p }
        }
        foreach ($name in $priority) {
            $p = Join-Path (Join-Path $parent "ComfyUI") $name
            if (Test-Path $p) { return $p }
        }
        $parent = Split-Path $parent -Parent
        if (-not $parent) { break }
    }
    return $null
}

function Score-ComfyDir($dir) {
    $score = 0
    if (Test-Path (Join-Path $dir "ComfyUI" "main.py")) { $score += 10 }
    if (Test-Path (Join-Path $dir "python_embeded")) { $score += 8 }
    if (Test-Path (Join-Path $dir "ComfyUI" "models" "checkpoints")) { $score += 6 }
    return $score
}

function Update-Config($startScript) {
    if (-not (Test-Path $configPath)) { Write-Log "[ERROR] config.json not found" Red; return $false }
    $config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $existing = $config.comfyui.startScript
    if ($existing -and $existing -eq $startScript) {
        Write-Log "[CONFIG] startScript already set correctly." Green; return $true
    }
    if ($existing -and (Test-Path $existing) -and $existing -ne $startScript) {
        Write-Log "[CONFIG] WARNING: existing startScript is valid but different." Yellow
        Write-Log "  Existing: $existing" Yellow
        Write-Log "  Detected: $startScript" Yellow
        Write-Log "  Keeping existing config." Yellow; return $true
    }
    Copy-Item $configPath "$configPath.bak" -Force
    $config.comfyui | Add-Member -MemberType NoteProperty -Name "startScript" -Value $startScript -Force
    $config | ConvertTo-Json -Depth 10 | Set-Content $configPath -Encoding UTF8
    Write-Log "[CONFIG] Updated startScript: $startScript" Green; return $true
}

# MAIN
Write-Log "ComfyUI Auto-Detection" Cyan
$result = @{detected=$false; listen_pid=$null; process_name=""; install_root=""; start_script=""; source=""}

$conn = Get-NetTCPConnection -LocalPort 8188 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conn) {
    $cPid = $conn.OwningProcess
    Write-Log "[PORT] 8188 listening (PID $cPid)" Green
    $result.listen_pid = $cPid
    $chain = Get-ParentChain $cPid
    foreach ($info in $chain) {
        $proc = Get-Process -Id $info.PID -ErrorAction SilentlyContinue
        Write-Log "  PID=$($info.PID) Name=$($info.Name)" Gray
        if ($info.CommandLine) {
            $clShort = $info.CommandLine
            if ($clShort.Length -gt 120) { $clShort = $clShort.Substring(0,120) + "..." }
            Write-Log "    CmdLine: $clShort" Gray
        }
        $roots = Infer-ComfyRoot $info
        foreach ($r in $roots) {
            $sf = Find-StartScript $r
            if ($sf) {
                $result.detected=$true; $result.install_root=$r; $result.start_script=$sf
                $result.source="port_process_command_line"; $result.process_name=$info.Name
                Write-Log "[FOUND] Install: $r" Green
                Write-Log "[FOUND] Start: $sf" Green
                break
            }
        }
        if ($result.detected) { break }
    }
}

$result | ConvertTo-Json | Write-Host -ForegroundColor White
if ($result.detected -and $result.start_script) { Update-Config $result.start_script }
if (-not $Quiet) { Read-Host "Press Enter..." }
