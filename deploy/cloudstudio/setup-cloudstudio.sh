#!/usr/bin/env bash
# ============================================================================
# setup-cloudstudio.sh — Install dependencies for English Listening Workbench
# ============================================================================
# Run once when the Cloud Studio workspace is first created.
# Core steps (must pass): Python venv, backend deps, frontend build
# Optional steps (fail gracefully): ffmpeg, Ollama, ComfyUI, Piper, Whisper
# Does NOT download large model files (see MODELS_REQUIRED.md for that).
# ============================================================================

# NOTE: Do NOT use "set -e" globally — optional steps may fail without aborting.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── Tracking ──
CORE_OK=true
FFMPEG_AVAILABLE=false
OLLAMA_AVAILABLE=false
COMFYUI_AVAILABLE=false
PIPER_AVAILABLE=false
WHISPER_AVAILABLE=false
BUILD_START_TIME=0
BUILD_END_TIME=0

echo "========================================"
echo " 英语听说课工作台 — Cloud Studio 环境安装"
echo "========================================"
echo ""

# ============================================================================
# CORE STEP 1: Check Python, Node, npm
# ============================================================================
echo "[CORE 1/6] 检查系统依赖..."

# Python
if ! command -v python3 &>/dev/null; then
    echo "        安装 python3..."
    sudo apt-get update -qq && sudo apt-get install -y -qq python3 python3-venv python3-pip || {
        echo "[FATAL] python3 安装失败，无法继续"
        exit 1
    }
fi
echo "        python3: $(python3 --version)"

# Node
if ! command -v node &>/dev/null; then
    echo "        安装 Node.js 22.x..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - || true
    sudo apt-get install -y -qq nodejs || {
        echo "[FATAL] Node.js 安装失败，无法继续"
        exit 1
    }
fi
echo "        node: $(node --version)"

# npm
if ! command -v npm &>/dev/null; then
    echo "[FATAL] npm 未找到，无法继续"
    exit 1
fi
echo "        npm:  $(npm --version)"

# ============================================================================
# CORE STEP 2: Create runtime directories
# ============================================================================
echo ""
echo "[CORE 2/6] 创建运行目录..."
mkdir -p /workspace/data/assets
mkdir -p /workspace/data/exports
mkdir -p /workspace/models/piper
mkdir -p /workspace/models/whisper
mkdir -p /workspace/workflows
mkdir -p "$PROJECT_ROOT/logs/cloudstudio"
mkdir -p "$PROJECT_ROOT/.local/bin"
echo "        目录创建完成"

# ============================================================================
# CORE STEP 3: Python virtual environment + backend dependencies
# ============================================================================
echo ""
echo "[CORE 3/6] Python 虚拟环境与后端依赖..."
VENV_DIR="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR" || {
        echo "[FATAL] Python 虚拟环境创建失败"
        exit 1
    }
    echo "        虚拟环境创建完成: $VENV_DIR"
else
    echo "        虚拟环境已存在，复用"
fi
source "$VENV_DIR/bin/activate"

echo "        安装后端依赖..."
pip install --upgrade pip -q
pip install -r "$PROJECT_ROOT/backend/requirements.txt" -q || {
    echo "[FATAL] 后端依赖安装失败"
    exit 1
}
echo "        后端依赖安装完成"

# Also install uvicorn explicitly (needed for start script)
pip install uvicorn -q

# ============================================================================
# CORE STEP 4: Build React frontend
# ============================================================================
echo ""
echo "[CORE 4/6] 构建 React 前端..."

cd "$PROJECT_ROOT/frontend"
BUILD_START_TIME=$(date +%s)

if [ -f "package-lock.json" ]; then
    echo "        使用 npm ci..."
    if ! npm ci --silent 2>&1; then
        echo "        [警告] npm ci 失败（锁文件可能不兼容），回退到 npm install..."
        rm -rf node_modules
        npm install --silent 2>&1 || {
            echo "[FATAL] npm install 失败，前端依赖无法安装"
            CORE_OK=false
        }
    fi
else
    echo "        使用 npm install（无 package-lock.json）..."
    npm install --silent 2>&1 || {
        echo "[FATAL] npm install 失败，前端依赖无法安装"
        CORE_OK=false
    }
fi

if $CORE_OK; then
    echo "        执行 npm run build..."
    if npm run build 2>&1; then
        BUILD_END_TIME=$(date +%s)
    else
        echo "[FATAL] npm run build 失败"
        CORE_OK=false
    fi
fi

# Verify build output
if $CORE_OK; then
    if [ -f "$PROJECT_ROOT/frontend/dist/index.html" ]; then
        BUILD_SEC=$((BUILD_END_TIME - BUILD_START_TIME))
        echo "        前端构建完成 (${BUILD_SEC}s)"
        echo "        dist 路径: $PROJECT_ROOT/frontend/dist"
        echo "        index.html: $(test -f "$PROJECT_ROOT/frontend/dist/index.html" && echo 'OK' || echo 'MISSING')"
        echo "        assets 目录: $(test -d "$PROJECT_ROOT/frontend/dist/assets" && echo 'OK' || echo 'MISSING')"
    else
        echo "[FATAL] frontend/dist/index.html 不存在，构建未生成预期输出"
        CORE_OK=false
    fi
fi

if ! $CORE_OK; then
    echo ""
    echo "========================================"
    echo " [FATAL] 核心步骤失败，安装中断"
    echo " 请检查以上错误信息后重新运行"
    echo "========================================"
    exit 1
fi

# ============================================================================
# OPTIONAL STEP 5: ffmpeg (multi-level fallback, never fatal)
# ============================================================================
echo ""
echo "[OPT 5/6] 检查 ffmpeg..."

_install_ffmpeg_apt() {
    # Attempt apt install with cache check
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq 2>/dev/null || true
        if apt-cache policy ffmpeg 2>/dev/null | grep -q 'Candidate:' 2>/dev/null; then
            if sudo apt-get install -y -qq ffmpeg 2>/dev/null; then
                return 0
            fi
        fi
    fi
    return 1
}

_install_ffmpeg_conda() {
    # Try conda / mamba / micromamba
    for mgr in conda mamba micromamba; do
        if command -v "$mgr" &>/dev/null; then
            echo "        尝试通过 $mgr (conda-forge) 安装 ffmpeg..."
            if "$mgr" install -y -c conda-forge ffmpeg 2>/dev/null; then
                return 0
            fi
        fi
    done
    return 1
}

_install_ffmpeg_imageio() {
    # Install imageio-ffmpeg in project venv + create wrapper
    echo "        尝试通过 imageio-ffmpeg 安装..."
    source "$VENV_DIR/bin/activate"
    if pip install imageio-ffmpeg -q 2>/dev/null; then
        local IMAGEIO_FFMPEG
        IMAGEIO_FFMPEG=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null || echo "")
        if [ -n "$IMAGEIO_FFMPEG" ] && [ -f "$IMAGEIO_FFMPEG" ]; then
            # Create wrapper scripts in .local/bin
            ln -sf "$IMAGEIO_FFMPEG" "$PROJECT_ROOT/.local/bin/ffmpeg" 2>/dev/null || true
            # ffprobe is usually bundled at same location
            local IMAGEIO_FFPROBE="${IMAGEIO_FFMPEG%ffmpeg}ffprobe"
            if [ -f "$IMAGEIO_FFPROBE" ]; then
                ln -sf "$IMAGEIO_FFPROBE" "$PROJECT_ROOT/.local/bin/ffprobe" 2>/dev/null || true
            fi
            export PATH="$PROJECT_ROOT/.local/bin:$PATH"
            if command -v ffmpeg &>/dev/null; then
                echo "        ffmpeg (imageio): $(ffmpeg -version 2>&1 | head -1 || echo 'ok')"
                return 0
            fi
        fi
    fi
    return 1
}

if command -v ffmpeg &>/dev/null; then
    echo "        ffmpeg 已可用: $(ffmpeg -version 2>&1 | head -1 || echo 'ok')"
    FFMPEG_AVAILABLE=true
elif _install_ffmpeg_apt; then
    echo "        ffmpeg (apt): $(ffmpeg -version 2>&1 | head -1)"
    FFMPEG_AVAILABLE=true
elif _install_ffmpeg_conda; then
    echo "        ffmpeg (conda): $(ffmpeg -version 2>&1 | head -1 || echo 'ok')"
    FFMPEG_AVAILABLE=true
elif _install_ffmpeg_imageio; then
    echo "        ffmpeg (imageio-ffmpeg) 已安装到 $PROJECT_ROOT/.local/bin/"
    FFMPEG_AVAILABLE=true
else
    echo "        [警告] ffmpeg 不可用 — 音频处理功能将受限"
    echo "        原因: apt 无安装候选, conda/mamba 未安装, imageio-ffmpeg 也失败"
    echo "        不影响 Web UI 启动，但音频生成/处理将不可用"
    FFMPEG_AVAILABLE=false
fi

# ============================================================================
# OPTIONAL STEP 6: Ollama, ComfyUI, Piper, Whisper (never fatal)
# ============================================================================
echo ""
echo "[OPT 6/6] 检查 AI 服务..."

# ── Ollama ──
if command -v ollama &>/dev/null; then
    echo "        ollama: 已安装"
    OLLAMA_AVAILABLE=true
else
    echo "        安装 Ollama..."
    if curl -fsSL https://ollama.com/install.sh | sh 2>/dev/null; then
        echo "        ollama: 安装完成"
        OLLAMA_AVAILABLE=true
    else
        echo "        [警告] Ollama 安装失败，AI 文本/评测功能不可用"
    fi
fi

# ── ComfyUI ──
COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
if [ -f "$COMFYUI_DIR/main.py" ]; then
    echo "        comfyui: 已安装 ($COMFYUI_DIR)"
    COMFYUI_AVAILABLE=true
else
    echo "        克隆 ComfyUI..."
    if git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR" 2>/dev/null; then
        echo "        comfyui: 克隆完成 ($COMFYUI_DIR)"
        COMFYUI_AVAILABLE=true
    else
        echo "        [警告] ComfyUI 克隆失败，图片生成功能不可用"
        echo "        可稍后手动克隆: git clone https://github.com/comfyanonymous/ComfyUI.git $COMFYUI_DIR"
    fi
fi

# ── Piper ──
if command -v piper &>/dev/null; then
    echo "        piper: $(which piper)"
    PIPER_AVAILABLE=true
elif [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
    echo "        piper: 已找到 ($PROJECT_ROOT/.local/bin/piper)"
    PIPER_AVAILABLE=true
else
    echo "        [信息] piper 未安装。TTS 音频生成需要: https://github.com/rhasspy/piper"
fi

# ── Whisper ──
if python3 -c "import whisper" 2>/dev/null; then
    echo "        whisper: Python 模块可用"
    WHISPER_AVAILABLE=true
else
    echo "        [信息] openai-whisper 未安装。运行: pip install openai-whisper"
fi

# ── Copy workflow ──
if [ -f "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" ]; then
    cp "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" /workspace/workflows/
    echo "        工作流文件已复制到 /workspace/workflows/"
fi

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo "========================================"
echo " 安装摘要"
echo "========================================"
echo ""
echo "Core:"
echo "  - backend_dependencies: ready"
echo "  - frontend_build:        ready"
echo "  - frontend_dist:         $PROJECT_ROOT/frontend/dist"
echo "  - dist/index.html:       $(test -f "$PROJECT_ROOT/frontend/dist/index.html" && echo 'OK' || echo 'MISSING')"
echo "  - dist/assets:           $(test -d "$PROJECT_ROOT/frontend/dist/assets" && echo 'OK' || echo 'MISSING')"
echo ""
echo "Optional:"
echo "  - ffmpeg:                $($FFMPEG_AVAILABLE && echo 'available' || echo 'unavailable')"
echo "  - ollama:                $($OLLAMA_AVAILABLE && echo 'available' || echo 'unavailable')"
echo "  - comfyui:               $($COMFYUI_AVAILABLE && echo 'available' || echo 'unavailable')"
echo "  - piper:                 $($PIPER_AVAILABLE && echo 'available' || echo 'unavailable')"
echo "  - whisper:               $($WHISPER_AVAILABLE && echo 'available' || echo 'unavailable')"
echo ""
echo "Result:"
echo "  - Web UI can start:      YES"
echo "  - AI features require:   optional services"
echo ""
echo "下一步:"
echo "  1. 查看 deploy/cloudstudio/MODELS_REQUIRED.md"
echo "  2. 下载所需模型文件"
echo "  3. 运行: bash deploy/cloudstudio/start-cloudstudio.sh"
echo "========================================"
