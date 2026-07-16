#!/usr/bin/env bash
# ============================================================================
# start-background.sh — 后台启动 English Listening Workbench
# ============================================================================
# 用法:
#   bash deploy/cloudstudio/start-background.sh           启动（后台）
#   bash deploy/cloudstudio/start-background.sh --status  查看状态
#   bash deploy/cloudstudio/stop-cloudstudio.sh           停止
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"
PID_FILE="$LOG_DIR/workbench.pid"
LOCK_FILE="$LOG_DIR/workbench.lock"

mkdir -p "$LOG_DIR"

# ── Status check mode ──
if [ "${1:-}" = "--status" ] || [ "${1:-}" = "status" ]; then
    echo ""
    echo "═══════════════════════════════════════════"
    echo "  English Listening Workbench — 状态"
    echo "═══════════════════════════════════════════"
    echo ""

    # PID
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "  主进程: 运行中 (PID: $PID)"
        else
            echo "  主进程: 已退出 (stale PID: $PID)"
        fi
    else
        echo "  主进程: 未运行"
    fi
    echo ""

    # FastAPI
    if curl -sf --max-time 2 http://127.0.0.1:8000/api/ping >/dev/null 2>&1; then
        echo "  FastAPI:  http://127.0.0.1:8000 ✓"
        HEALTH=$(curl -sf --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null || echo '{}')
        echo "  /api/health: $(echo "$HEALTH" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo '?')"
    else
        echo "  FastAPI:  未运行"
    fi

    # Ollama
    if curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "  Ollama:   http://127.0.0.1:11434 ✓"
    else
        echo "  Ollama:   未运行"
    fi

    # ComfyUI
    if curl -sf --max-time 2 http://127.0.0.1:8188/system_stats >/dev/null 2>&1; then
        echo "  ComfyUI:  http://127.0.0.1:8188 ✓"
    else
        echo "  ComfyUI:  未运行"
    fi

    echo ""
    echo "  日志:     $LOG_DIR/"
    echo "  PID 文件: $PID_FILE"
    echo ""
    exit 0
fi

# ── Prevent duplicate start ──
if [ -f "$LOCK_FILE" ]; then
    LOCK_PID=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "[start-background] 已在运行 (PID: $LOCK_PID)"
        echo "[start-background] 查看状态: bash deploy/cloudstudio/start-background.sh --status"
        echo "[start-background] 如需重启: bash deploy/cloudstudio/stop-cloudstudio.sh && bash deploy/cloudstudio/start-background.sh"
        exit 1
    fi
    # Stale lock — clean up
    rm -f "$LOCK_FILE" "$PID_FILE"
fi

# ── Launch ──
echo "[start-background] 后台启动英语听说课工作台..."
echo "[start-background] 日志: $LOG_DIR/workbench.log"

nohup bash "$SCRIPT_DIR/one-click-cloudstudio.sh" \
    &> "$LOG_DIR/workbench.log" &
BG_PID=$!

echo "$BG_PID" > "$LOCK_FILE"
echo "$BG_PID" > "$PID_FILE"

echo ""
echo "═══════════════════════════════════════════"
echo "  工作台已后台启动"
echo "  PID: $BG_PID"
echo "═══════════════════════════════════════════"
echo ""
echo "  查看状态:  bash deploy/cloudstudio/start-background.sh --status"
echo "  查看日志:  tail -f $LOG_DIR/workbench.log"
echo "  停止服务:  bash deploy/cloudstudio/stop-cloudstudio.sh"
echo ""
echo "  (启动需要 2-5 分钟，请耐心等待)"
echo ""
