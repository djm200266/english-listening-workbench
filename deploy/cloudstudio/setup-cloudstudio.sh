#!/usr/bin/env bash
# ============================================================================
# setup-cloudstudio.sh — Install dependencies for English Listening Workbench
# ============================================================================
# Run once when the Cloud Studio workspace is first created.
# Does NOT download large model files (see MODELS_REQUIRED.md for that).
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "========================================"
echo " 英语听说课工作台 — Cloud Studio 环境安装"
echo "========================================"
echo ""

# ── 1. System dependencies ──
echo "[1/8] 检查系统依赖..."
if ! command -v python3 &>/dev/null; then
    echo "      安装 python3..."
    sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip
fi
echo "      python3: $(python3 --version)"

if ! command -v ffmpeg &>/dev/null; then
    echo "      安装 ffmpeg..."
    sudo apt-get install -y -qq ffmpeg
fi
echo "      ffmpeg: $(ffmpeg -version 2>&1 | head -1 || echo 'not found')"

# ── 2. Python virtual environment ──
echo ""
echo "[2/8] 创建 Python 虚拟环境..."
VENV_DIR="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    echo "      虚拟环境创建完成: $VENV_DIR"
else
    echo "      虚拟环境已存在，跳过"
fi
source "$VENV_DIR/bin/activate"

# ── 3. Install backend dependencies ──
echo ""
echo "[3/8] 安装后端 Python 依赖..."
pip install --upgrade pip -q
pip install -r "$PROJECT_ROOT/backend/requirements.txt" -q
echo "      后端依赖安装完成"

# ── 4. Check Node and npm ──
echo ""
echo "[4/8] 检查 Node.js 和 npm..."
if ! command -v node &>/dev/null; then
    echo "      安装 Node.js 22.x..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
fi
echo "      node: $(node --version)"
echo "      npm:  $(npm --version)"

# ── 5. Build frontend ──
echo ""
echo "[5/8] 构建前端 (npm ci + build)..."
cd "$PROJECT_ROOT/frontend"
npm ci --silent
npm run build
echo "      前端构建完成: frontend/dist/"

# ── 6. Check / install Ollama ──
echo ""
echo "[6/8] 检查 Ollama..."
if command -v ollama &>/dev/null; then
    echo "      ollama 已安装: $(ollama --version 2>&1 || echo 'ok')"
    # Start ollama serve in background briefly to check
    ollama serve &>/dev/null &
    OLLAMA_PID=$!
    sleep 2
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "      Ollama 服务可访问"
    else
        echo "      [警告] Ollama 已安装但服务未响应"
    fi
    kill $OLLAMA_PID 2>/dev/null || true
else
    echo "      安装 Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "      Ollama 安装完成。请拉取模型: ollama pull qwen3:4b-instruct && ollama pull qwen3-vl:4b"
fi

# ── 7. Check / clone ComfyUI ──
echo ""
echo "[7/8] 检查 ComfyUI..."
COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
if [ -d "$COMFYUI_DIR" ]; then
    echo "      ComfyUI 目录已存在: $COMFYUI_DIR"
    if [ -f "$COMFYUI_DIR/main.py" ]; then
        echo "      main.py 已就绪"
    else
        echo "      [警告] main.py 未找到，ComfyUI 可能不完整"
    fi
else
    echo "      克隆 ComfyUI..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR"
    echo "      ComfyUI 克隆完成"
fi

# ── 8. Check Piper / Whisper dependencies ──
echo ""
echo "[8/8] 检查 Piper / Whisper 依赖..."
# Piper: check if executable exists
if command -v piper &>/dev/null; then
    echo "      piper: $(which piper)"
else
    echo "      [信息] piper 未安装。如需 TTS，请从 https://github.com/rhasspy/piper 下载"
fi

# Whisper: check if importable
if python3 -c "import whisper" 2>/dev/null; then
    echo "      whisper: Python 模块可用"
else
    echo "      [信息] openai-whisper 未安装。运行: pip install openai-whisper"
fi

# ── Create data directories ──
echo ""
echo "创建数据目录..."
mkdir -p /workspace/data/assets
mkdir -p /workspace/data/exports
mkdir -p /workspace/models/piper
mkdir -p /workspace/models/whisper
mkdir -p /workspace/workflows
mkdir -p "$PROJECT_ROOT/logs/cloudstudio"

# ── Copy workflow ──
if [ -f "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" ]; then
    cp "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" /workspace/workflows/
    echo "      工作流文件已复制到 /workspace/workflows/"
fi

echo ""
echo "========================================"
echo " 环境安装完成！"
echo ""
echo " 下一步:"
echo " 1. 查看 deploy/cloudstudio/MODELS_REQUIRED.md"
echo " 2. 下载所需模型文件"
echo " 3. 运行: bash deploy/cloudstudio/start-cloudstudio.sh"
echo "========================================"
