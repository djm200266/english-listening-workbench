#!/usr/bin/env bash
# ============================================================================
# start-cloudstudio.sh — Start English Listening Workbench in Cloud Studio
# ============================================================================
# Launches Ollama, ComfyUI (optional), and FastAPI in foreground.
# FastAPI serves both API + React frontend + generated assets on port 8000.
# Run setup-cloudstudio.sh first if frontend/dist doesn't exist.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs/cloudstudio"

mkdir -p "$LOG_DIR"

# ── Prevent duplicate start ──
PID_FILE="$LOG_DIR/start.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[start] 工作台已在运行 (PID: $OLD_PID)。如需重启，请先停止旧进程。"
        exit 1
    fi
fi
echo $$ > "$PID_FILE"
trap "rm -f $PID_FILE" EXIT

# ── Environment variables ──
export APP_ENV=cloudstudio
export PYTHONPATH="$PROJECT_ROOT/backend:$PROJECT_ROOT"
export PATH="$PROJECT_ROOT/.local/bin:$PATH"

export DATA_DIR="${DATA_DIR:-/workspace/data}"
export ASSET_DIR="${ASSET_DIR:-/workspace/data/assets}"
export EXPORT_DIR="${EXPORT_DIR:-/workspace/data/exports}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export COMFYUI_BASE_URL="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}"
export COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
export COMFYUI_WORKFLOW_DIR="${COMFYUI_WORKFLOW_DIR:-/workspace/workflows}"
export PIPER_MODEL_DIR="${PIPER_MODEL_DIR:-/workspace/models/piper}"
export WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/workspace/models/whisper}"

echo "[start] APP_ENV=$APP_ENV"
echo "[start] PROJECT_ROOT=$PROJECT_ROOT"
echo "[start] DATA_DIR=$DATA_DIR"

# ── Check frontend build ──
FRONTEND_INDEX="$PROJECT_ROOT/frontend/dist/index.html"
if [ -f "$FRONTEND_INDEX" ]; then
    echo "[start] 前端构建就绪: $FRONTEND_INDEX"
else
    echo "[start] =============================================="
    echo "[start] [警告] 前端未构建！"
    echo "[start] 路径: $FRONTEND_INDEX 不存在"
    echo "[start] Web UI 将不可用，但 API 仍可正常访问"
    echo "[start]"
    echo "[start] 请先运行: bash deploy/cloudstudio/setup-cloudstudio.sh"
    echo "[start] =============================================="
fi

# ── Activate virtual environment ──
VENV_DIR="$PROJECT_ROOT/.venv"
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    echo "[start] 虚拟环境已激活: $VENV_DIR"
else
    echo "[start] [警告] 未找到 .venv，使用系统 Python"
fi

# ── Start Ollama (background, optional) ──
echo "[start] 启动 Ollama..."
OLLAMA_STARTED=false
if command -v ollama &>/dev/null; then
    ollama serve &> "$LOG_DIR/ollama.log" &
    OLLAMA_PID=$!
    echo "[start] Ollama PID: $OLLAMA_PID"

    for i in $(seq 1 30); do
        if curl -sf "$OLLAMA_BASE_URL/api/tags" >/dev/null 2>&1; then
            echo "[start] Ollama 就绪 (${i}s)"
            OLLAMA_STARTED=true
            break
        fi
        if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
            echo "[start] [警告] Ollama 进程已退出，查看: $LOG_DIR/ollama.log"
            break
        fi
        sleep 1
    done
else
    echo "[start] [警告] ollama 未安装，跳过 — AI 文本功能不可用"
fi

# ── Start ComfyUI (background, optional) ──
echo "[start] 启动 ComfyUI..."
COMFYUI_STARTED=false
if [ -f "$COMFYUI_DIR/main.py" ]; then
    python3 -s "$COMFYUI_DIR/main.py" \
        --listen 127.0.0.1 \
        --port 8188 \
        &> "$LOG_DIR/comfyui.log" &
    COMFYUI_PID=$!
    echo "[start] ComfyUI PID: $COMFYUI_PID"

    for i in $(seq 1 150); do
        if curl -sf "$COMFYUI_BASE_URL/system_stats" >/dev/null 2>&1; then
            echo "[start] ComfyUI 就绪 (${i}s)"
            COMFYUI_STARTED=true
            break
        fi
        if ! kill -0 "$COMFYUI_PID" 2>/dev/null; then
            echo "[start] [警告] ComfyUI 进程已退出，查看: $LOG_DIR/comfyui.log"
            echo "[start] 后端仍可启动，图片生成功能不可用"
            break
        fi
        sleep 2
    done
else
    echo "[start] [警告] ComfyUI 未安装 ($COMFYUI_DIR/main.py 不存在)，跳过"
    echo "[start] 后端仍可启动，图片生成功能不可用"
fi

# ── Start FastAPI (foreground) ──
echo "[start] 启动 FastAPI (0.0.0.0:8000)..."
echo "[start] Ollama: $OLLAMA_STARTED | ComfyUI: $COMFYUI_STARTED"
echo "[start] 前端: $(test -f "$FRONTEND_INDEX" && echo 'ready' || echo 'NOT BUILT')"
echo "[start] 日志目录: $LOG_DIR"
echo "[start] ========================================"

cd "$PROJECT_ROOT/backend"

exec python -m uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info
