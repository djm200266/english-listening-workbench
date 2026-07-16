#!/usr/bin/env bash
# ============================================================================
# stop-cloudstudio.sh — 安全停止 English Listening Workbench 所有服务
# ============================================================================
# 只停止本项目启动的进程（通过 PID 文件识别），不误杀其他程序。
# 等待端口真实释放后才报告成功。
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"
STATE_FILE="$LOG_DIR/startup-state.json"
PID_FILE="$LOG_DIR/workbench.pid"
LOCK_FILE="$LOG_DIR/workbench.lock"

echo ""
echo "══════════════════════════════════════════════════════"
echo "  停止英语听说课工作台"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "══════════════════════════════════════════════════════"
echo ""

STOPPED=0
ALREADY_GONE=0

# ── Safe stop by PID file ──
_stop_pid() {
    local pidfile="$1" name="$2"
    if [ ! -f "$pidfile" ]; then
        echo "  $name: 未运行 (无 PID 文件)"
        ALREADY_GONE=$((ALREADY_GONE + 1))
        return 0
    fi
    local pid; pid=$(cat "$pidfile" 2>/dev/null || echo "")
    if [ -z "$pid" ]; then
        echo "  $name: PID 文件为空"; rm -f "$pidfile"
        ALREADY_GONE=$((ALREADY_GONE + 1)); return 0
    fi
    # Verify PID is a number
    if ! echo "$pid" | grep -qE '^[0-9]+$'; then
        echo "  $name: PID 无效 ($pid)"; rm -f "$pidfile"
        ALREADY_GONE=$((ALREADY_GONE + 1)); return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "  $name: 进程已退出 (PID: $pid)"; rm -f "$pidfile"
        ALREADY_GONE=$((ALREADY_GONE + 1)); return 0
    fi

    # Verify this is our project process (check cmdline)
    local cmdline=""
    if [ -f "/proc/$pid/cmdline" ]; then
        cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo "")
    fi
    if [ -n "$cmdline" ] && ! echo "$cmdline" | grep -qE "$PROJECT_ROOT|/workspace"; then
        echo "  $name (PID: $pid): NOT our process, refusing to kill"
        echo "    cmdline: $cmdline"
        rm -f "$pidfile"
        ALREADY_GONE=$((ALREADY_GONE + 1))
        return 0
    fi

    echo "  $name (PID: $pid): 发送 SIGTERM..."
    kill "$pid" 2>/dev/null || true

    # Wait up to 10 seconds for graceful exit
    local waited=0
    while [ $waited -lt 10 ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "  $name: 已停止 (${waited}s)"
            rm -f "$pidfile"
            STOPPED=$((STOPPED + 1))
            return 0
        fi
        sleep 1; waited=$((waited + 1))
    done

    # Force kill
    echo "  $name: SIGTERM 无效，发送 SIGKILL..."
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        echo "  $name: 无法停止 (PID: $pid) — 请手动: kill -9 $pid"
    else
        echo "  $name: 已停止 (SIGKILL)"
        rm -f "$pidfile"
        STOPPED=$((STOPPED + 1))
    fi
}

# ── Stop in reverse order: FastAPI → ComfyUI → Ollama → main script ──
_stop_pid "$LOG_DIR/fastapi.pid"   "FastAPI (port 8000)"
_stop_pid "$LOG_DIR/comfyui.pid"   "ComfyUI (port 8188)"
_stop_pid "$LOG_DIR/ollama.pid"    "Ollama (port 11434)"
_stop_pid "$PID_FILE"              "主启动脚本"
_stop_pid "$LOG_DIR/start.pid"     "旧版启动脚本"
_stop_pid "$LOG_DIR/oneclick.pid"  "one-click 脚本"

# ── Clean up lock files + state ──
rm -f "$LOCK_FILE" "$PID_FILE" "$LOG_DIR/oneclick.pid"

# Write final state
python3 -c "
import json, os
f = '$STATE_FILE'
if os.path.exists(f):
    d = json.load(open(f))
    d['status'] = 'stopped'
    d['stage'] = 'stopped'
    d['message'] = '用户已停止'
    json.dump(d, open(f, 'w'), indent=2)
" 2>/dev/null || true

# ── Search for any lingering project processes ──
echo ""
echo "  检查残留进程..."

_FIND_STOP() {
    local pattern="$1" name="$2"
    local pids; pids=$(pgrep -f "$pattern" 2>/dev/null || echo "")
    [ -z "$pids" ] && return 0
    for pid in $pids; do
        if ! echo "$pid" | grep -qE '^[0-9]+$'; then continue; fi
        local cmdline=""
        [ -f "/proc/$pid/cmdline" ] && cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo "")
        if echo "$cmdline" | grep -qE "$PROJECT_ROOT|/workspace"; then
            echo "  $name (PID: $pid): 残留, 已终止"
            kill "$pid" 2>/dev/null || true
            STOPPED=$((STOPPED + 1))
        fi
    done
}

_FIND_STOP "uvicorn main:app"   "uvicorn"
_FIND_STOP "ComfyUI/main.py"    "ComfyUI"
_FIND_STOP "ollama serve"       "ollama"

# ── Wait for ports to actually release ──
echo ""
echo "  等待端口释放..."

_wait_port_free() {
    local port="$1" max_wait=15 waited=0
    while [ $waited -lt $max_wait ]; do
        if ! curl -sf --max-time 1 "http://127.0.0.1:$port" >/dev/null 2>&1; then
            echo "  端口 $port: 已释放 ✓"
            return 0
        fi
        sleep 1; waited=$((waited + 1))
    done
    echo "  [警告] 端口 $port: 仍有服务响应 — 可能有非项目进程"
    return 1
}

_wait_port_free 8000
_wait_port_free 8188

echo ""
echo "══════════════════════════════════════════════════════"
echo "  停止完成"
echo "  停止: $STOPPED | 已退出: $ALREADY_GONE"
echo "══════════════════════════════════════════════════════"
echo ""
