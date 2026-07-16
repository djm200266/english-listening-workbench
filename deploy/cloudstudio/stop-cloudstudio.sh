#!/usr/bin/env bash
# ============================================================================
# stop-cloudstudio.sh — 安全停止 English Listening Workbench 所有服务
# ============================================================================
# 只停止本项目启动的进程（通过 PID 文件识别），不误杀其他程序。
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"

echo ""
echo "═══════════════════════════════════════════"
echo "  停止英语听说课工作台"
echo "═══════════════════════════════════════════"
echo ""

STOPPED_COUNT=0
ALREADY_GONE=0

_stop_by_pidfile() {
    local file="$1" name="$2"
    if [ ! -f "$file" ]; then
        echo "  $name: 未运行 (无 PID 文件)"
        ALREADY_GONE=$((ALREADY_GONE + 1))
        return 0
    fi
    local pid
    pid=$(cat "$file" 2>/dev/null || echo "")
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        echo "  $name: 已退出"
        rm -f "$file"
        ALREADY_GONE=$((ALREADY_GONE + 1))
        return 0
    fi
    # Try graceful stop (SIGTERM)
    echo "  $name (PID: $pid): 发送 SIGTERM..."
    kill "$pid" 2>/dev/null || true
    # Wait up to 5 seconds
    for i in $(seq 1 5); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "  $name: 已停止"
            rm -f "$file"
            STOPPED_COUNT=$((STOPPED_COUNT + 1))
            return 0
        fi
        sleep 1
    done
    # Still running — force kill
    echo "  $name: SIGTERM 无效，发送 SIGKILL..."
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
        echo "  $name: 无法停止 (PID: $pid) — 请手动处理"
    else
        echo "  $name: 已停止 (SIGKILL)"
        rm -f "$file"
        STOPPED_COUNT=$((STOPPED_COUNT + 1))
    fi
}

# Stop in reverse order: FastAPI → ComfyUI → Ollama → main script
_stop_by_pidfile "$LOG_DIR/fastapi.pid"  "FastAPI (port 8000)"
_stop_by_pidfile "$LOG_DIR/comfyui.pid"  "ComfyUI (port 8188)"
_stop_by_pidfile "$LOG_DIR/ollama.pid"   "Ollama (port 11434)"
_stop_by_pidfile "$LOG_DIR/workbench.pid" "主启动脚本"
_stop_by_pidfile "$LOG_DIR/start.pid"    "旧版启动脚本"

# Also try port-based detection for any remaining project processes
# Only target processes clearly belonging to this project
echo ""
echo "  额外检查: 搜索残留项目进程..."

_find_and_stop() {
    local pattern="$1" name="$2"
    local pids
    pids=$(pgrep -f "$pattern" 2>/dev/null || echo "")
    if [ -n "$pids" ]; then
        for pid in $pids; do
            local cmdline
            cmdline=$(cat /proc/"$pid"/cmdline 2>/dev/null | tr '\0' ' ' || echo "")
            if echo "$cmdline" | grep -q "$PROJECT_ROOT"; then
                echo "  $name (PID: $pid): 残留进程，已终止"
                echo "    cmdline: $cmdline"
                kill "$pid" 2>/dev/null || true
                STOPPED_COUNT=$((STOPPED_COUNT + 1))
            fi
        done
    fi
}

_find_and_stop "uvicorn main:app" "uvicorn"
_find_and_stop "ComfyUI/main.py"  "ComfyUI"
_find_and_stop "ollama serve"     "ollama"

# Clean up lock files
rm -f "$LOG_DIR/workbench.lock"

echo ""
echo "═══════════════════════════════════════════"
echo "  停止完成"
echo "  停止: $STOPPED_COUNT | 已退出: $ALREADY_GONE"
echo "═══════════════════════════════════════════"
echo ""

# Verify nothing left on key ports
for port in 8000 8188; do
    if curl -sf --max-time 1 "http://127.0.0.1:$port" >/dev/null 2>&1; then
        echo "  [警告] 端口 $port 仍有服务响应 — 可能有非本项目的进程"
    else
        echo "  端口 $port: 已释放 ✓"
    fi
done
echo ""
