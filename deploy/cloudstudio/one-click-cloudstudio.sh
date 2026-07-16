#!/usr/bin/env bash
# ============================================================================
# one-click-cloudstudio.sh — English Listening Workbench 一键安装+启动
# ============================================================================
# Cloud Studio 中唯一需要执行的命令：
#   bash deploy/cloudstudio/one-click-cloudstudio.sh
#
# 自动完成：环境检查 → 依赖安装 → 虚拟环境 → 前端构建 → AI 服务 →
#           Ollama 模型拉取 → ComfyUI → Whisper/Piper → 环境变量 → 启动
#
# 特性：
#   - 重复执行安全（已安装的跳过，已运行的复用）
#   - 可选组件失败不阻止网页启动
#   - CPU/GPU 自动识别
#   - 日志写入 /workspace/logs/cloudstudio/
# ============================================================================
set -uo pipefail

# ── 路径计算（不依赖 CWD）────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"

# ── 颜色 ─────────────────────────────────────────────────────────────
C_RESET='\033[0m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'
C_CYAN='\033[0;36m'
C_BOLD='\033[1m'

# ── 全局状态 ─────────────────────────────────────────────────────────
START_TIME=$(date +%s)
TOTAL_STEPS=14
CURRENT_STEP=0
HAS_GPU=false
HAS_NVIDIA_SMI=false
GPU_NAME=""
GPU_VRAM=""

# Core status
BACKEND_OK=false
FRONTEND_OK=false
FASTAPI_STARTED=false

# Optional status
FFMPEG_OK=false
OLLAMA_INSTALLED=false
OLLAMA_RUNNING=false
TEXT_MODEL_OK=false
VISION_MODEL_OK=false
COMFYUI_INSTALLED=false
COMFYUI_RUNNING=false
CHECKPOINT_OK=false
PIPER_OK=false
WHISPER_OK=false
ZSTD_OK=false

# Process tracking
FASTAPI_PID=""
OLLAMA_PID=""
COMFYUI_PID=""

# ── 初始化 ───────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
exec 2> >(tee -a "$LOG_DIR/one-click-error.log" >&2)

# ── 工具函数 ─────────────────────────────────────────────────────────

_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "${C_BOLD}[${CURRENT_STEP}/${TOTAL_STEPS}]${C_RESET} $1"
    echo -e "${C_CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
}

_log()   { echo -e "        ${C_GREEN}✓${C_RESET} $1"; }
_warn()  { echo -e "        ${C_YELLOW}⚠${C_RESET}  $1"; }
_error() { echo -e "        ${C_RED}✗${C_RESET} $1"; }
_info()  { echo -e "        $1"; }

_has_cmd() { command -v "$1" &>/dev/null; }
_http_ok() {
    # Args: URL [timeout_sec=3]
    local url="$1" timeout="${2:-3}"
    curl -sf --max-time "$timeout" "$url" >/dev/null 2>&1
}
_wait_http() {
    # Args: URL description [timeout_sec=60]
    local url="$1" desc="$2" timeout="${3:-60}" i
    for ((i=1; i<=timeout; i++)); do
        if _http_ok "$url"; then
            _log "$desc 就绪 (${i}s)"
            return 0
        fi
        sleep 1
    done
    _warn "$desc 超时 (${timeout}s)"
    return 1
}
_json_val() {
    # Extract a JSON value by key path from config.json
    python3 -c "
import json, sys
with open('$PROJECT_ROOT/config.json','r',encoding='utf-8-sig') as f:
    d = json.load(f)
keys = '$1'.split('.')
for k in keys:
    if isinstance(d, dict):
        d = d.get(k, {})
    else:
        d = {}
if isinstance(d, str):
    print(d)
elif d:
    print(json.dumps(d))
" 2>/dev/null
}
_no_windows_paths() {
    # Ensure no Windows paths leak into environment
    local val="$1"
    if [[ "$val" =~ ^[A-Za-z]:[\\/] ]] || [[ "$val" =~ python_embeded ]] || [[ "$val" =~ run_nvidia_gpu ]]; then
        return 1
    fi
    return 0
}

# ══════════════════════════════════════════════════════════════════════
# STARTUP BANNER
# ══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${C_BOLD}╔══════════════════════════════════════════════════════════╗${C_RESET}"
echo -e "${C_BOLD}║  初中英语听说课AI备课助手 — Cloud Studio 一键安装启动  ║${C_RESET}"
echo -e "${C_BOLD}╚══════════════════════════════════════════════════════════╝${C_RESET}"
echo ""
echo -e "  PROJECT_ROOT: ${C_CYAN}$PROJECT_ROOT${C_RESET}"
echo -e "  LOG_DIR:      ${C_CYAN}$LOG_DIR${C_RESET}"
echo -e "  开始时间:     $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ══════════════════════════════════════════════════════════════════════
# STEP 1: System environment check
# ══════════════════════════════════════════════════════════════════════
_step "检查系统环境"

# CPU info
CPU_CORES=$(nproc 2>/dev/null || echo "unknown")
CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | xargs || echo "unknown")
_info "CPU: ${CPU_MODEL} (${CPU_CORES} cores)"

# Disk
DISK_INFO=$(df -h /workspace 2>/dev/null | tail -1 | awk '{print "total="$2" used="$3" avail="$4}' || echo "unknown")
_info "Disk (/workspace): $DISK_INFO"

# Memory
MEM_TOTAL=$(free -h 2>/dev/null | awk '/Mem:/{print $2}' || echo "unknown")
_info "Memory: $MEM_TOTAL"

# GPU detection
if _has_cmd nvidia-smi; then
    HAS_NVIDIA_SMI=true
    if nvidia-smi -L &>/dev/null; then
        HAS_GPU=true
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
        GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 | xargs || echo "unknown")
        _log "GPU: ${GPU_NAME} | VRAM: ${GPU_VRAM}"
    else
        _info "nvidia-smi 可用但未检测到 GPU"
    fi
fi
if ! $HAS_GPU; then
    _warn "当前为 CPU 工作空间 — AI 推理受限，Web 服务正常启动"
    _info "切换 GPU 后重新运行本脚本将自动启用 AI 功能"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 2: Install base system dependencies
# ══════════════════════════════════════════════════════════════════════
_step "安装基础系统依赖"

_install_apt_pkg() {
    local pkg="$1"
    if _has_cmd "$pkg"; then
        _info "$pkg: $(command -v "$pkg") ($($pkg --version 2>&1 | head -1 || echo 'ok'))"
        return 0
    fi
    if command -v apt-get &>/dev/null; then
        apt-get update -qq 2>/dev/null || true
        if apt-cache policy "$pkg" 2>/dev/null | grep -q 'Candidate:'; then
            apt-get install -y -qq "$pkg" 2>/dev/null && return 0
        fi
    fi
    _warn "$pkg: 无安装候选，跳过"
    return 1
}

BASE_PKGS=("python3" "python3-venv" "python3-pip" "nodejs" "npm" "git" "curl" "wget")
for pkg in "${BASE_PKGS[@]}"; do
    _install_apt_pkg "$pkg"
done

# zstd (critical for Ollama)
if _has_cmd zstd; then
    _log "zstd: $(zstd --version 2>&1 | head -1 || echo 'ok')"
    ZSTD_OK=true
else
    if _install_apt_pkg "zstd"; then
        _log "zstd: $(zstd --version 2>&1 | head -1 || echo 'ok')"
        ZSTD_OK=true
    elif _has_cmd apt-get; then
        apt-get update -qq 2>/dev/null || true
        if apt-get install -y -qq zstd 2>/dev/null; then
            _log "zstd: installed"
            ZSTD_OK=true
        else
            _error "zstd 安装失败 — Ollama 将无法安装"
        fi
    else
        _warn "zstd: 未安装且无 apt-get — 尝试从 pip 安装"
        if pip install zstandard -q 2>/dev/null; then
            _log "zstd (via zstandard pip): ok"
            ZSTD_OK=true
        fi
    fi
fi

# ── ffmpeg (multi-level fallback) ──
if _has_cmd ffmpeg; then
    _log "ffmpeg: $(ffmpeg -version 2>&1 | head -1 || echo 'ok')"
    FFMPEG_OK=true
elif _install_apt_pkg "ffmpeg"; then
    _log "ffmpeg (apt): $(ffmpeg -version 2>&1 | head -1 || echo 'ok')"
    FFMPEG_OK=true
else
    # imageio-ffmpeg fallback
    _info "尝试 imageio-ffmpeg..."
    if pip install imageio-ffmpeg -q 2>/dev/null; then
        IMAGEIO_BIN=$(python3 -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null || echo "")
        if [ -n "$IMAGEIO_BIN" ] && [ -f "$IMAGEIO_BIN" ]; then
            mkdir -p "$PROJECT_ROOT/.local/bin"
            ln -sf "$IMAGEIO_BIN" "$PROJECT_ROOT/.local/bin/ffmpeg" 2>/dev/null || true
            _IMAGEIO_PROBE="${IMAGEIO_BIN%ffmpeg}ffprobe"
            [ -f "$_IMAGEIO_PROBE" ] && ln -sf "$_IMAGEIO_PROBE" "$PROJECT_ROOT/.local/bin/ffprobe" 2>/dev/null || true
            export PATH="$PROJECT_ROOT/.local/bin:$PATH"
            if _has_cmd ffmpeg; then
                _log "ffmpeg (imageio-ffmpeg): ok"
                FFMPEG_OK=true
            else
                _warn "ffmpeg 不可用 — 音频处理功能受限"
            fi
        else
            _warn "ffmpeg 不可用 — 音频处理功能受限"
        fi
    else
        _warn "ffmpeg 不可用 — 音频处理功能受限"
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 3: Create runtime directories
# ══════════════════════════════════════════════════════════════════════
_step "创建运行时目录"

mkdir -p /workspace/data/assets
mkdir -p /workspace/data/exports
mkdir -p /workspace/models/whisper
mkdir -p /workspace/models/piper
mkdir -p /workspace/workflows
mkdir -p "$LOG_DIR"
mkdir -p "$PROJECT_ROOT/.local/bin"
export PATH="$PROJECT_ROOT/.local/bin:$PATH"
_log "/workspace/data/assets"
_log "/workspace/data/exports"
_log "/workspace/models/whisper"
_log "/workspace/models/piper"
_log "/workspace/workflows"
_log "$LOG_DIR"

# ══════════════════════════════════════════════════════════════════════
# STEP 4: Python virtual environment
# ══════════════════════════════════════════════════════════════════════
_step "Python 虚拟环境与后端依赖"

VENV_DIR="/workspace/.venv"
if [ -d "$VENV_DIR" ]; then
    _log "虚拟环境已存在，复用: $VENV_DIR"
else
    python3 -m venv "$VENV_DIR" || {
        _error "Python 虚拟环境创建失败"
        BACKEND_OK=false
    }
    if [ -d "$VENV_DIR" ]; then
        _log "虚拟环境创建: $VENV_DIR"
    fi
fi

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip -q 2>&1 | tail -1

    # Find requirements file
    REQ_FILE=""
    for candidate in \
        "$PROJECT_ROOT/backend/requirements.txt" \
        "$PROJECT_ROOT/requirements.txt"; do
        if [ -f "$candidate" ]; then
            REQ_FILE="$candidate"
            break
        fi
    done

    if [ -n "$REQ_FILE" ]; then
        _info "安装依赖: $(basename "$REQ_FILE")"
        if pip install -r "$REQ_FILE" -q 2>&1; then
            _log "后端依赖安装完成"
            BACKEND_OK=true
        else
            _error "后端依赖安装失败"
            BACKEND_OK=false
        fi
    else
        _warn "未找到 requirements.txt，尝试 pyproject.toml"
        if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
            pip install -e "$PROJECT_ROOT" -q 2>&1 && {
                _log "后端依赖 (pyproject.toml) 安装完成"
                BACKEND_OK=true
            }
        fi
    fi

    # Explicit uvicorn
    pip install uvicorn -q 2>&1
else
    BACKEND_OK=false
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 5: Build React frontend
# ══════════════════════════════════════════════════════════════════════
_step "构建 React 前端"

FRONTEND_DIR="$PROJECT_ROOT/frontend"
FRONTEND_DIST="$FRONTEND_DIR/dist"
FRONTEND_INDEX="$FRONTEND_DIST/index.html"

# Check if rebuild needed
NEED_BUILD=true
if [ -f "$FRONTEND_INDEX" ]; then
    # Check if any source file is newer than dist
    NEWEST_SRC=$(find "$FRONTEND_DIR/src" -type f -newer "$FRONTEND_INDEX" 2>/dev/null | head -1)
    if [ -z "$NEWEST_SRC" ]; then
        _log "前端 dist 已是最新，跳过构建"
        _info "dist: $FRONTEND_DIST"
        _info "index.html: OK"
        NEED_BUILD=false
        FRONTEND_OK=true
    else
        _info "检测到源码更新，重新构建..."
    fi
fi

if $NEED_BUILD; then
    cd "$FRONTEND_DIR"
    BUILD_START=$(date +%s)

    if [ -f "package-lock.json" ]; then
        _info "npm ci..."
        npm ci --silent 2>&1 || {
            _warn "npm ci 失败，回退到 npm install"
            rm -rf node_modules
            npm install --silent 2>&1 || {
                _error "前端依赖安装失败"
                FRONTEND_OK=false
            }
        }
    else
        _info "npm install..."
        npm install --silent 2>&1 || {
            _error "前端依赖安装失败"
            FRONTEND_OK=false
        }
    fi

    if [ -d "node_modules" ]; then
        _info "npm run build..."
        if npm run build 2>&1; then
            BUILD_END=$(date +%s)
            _log "前端构建完成 ($((BUILD_END - BUILD_START))s)"
            FRONTEND_OK=true
        else
            _error "前端构建失败"
            FRONTEND_OK=false
        fi
    fi
fi

# Verify dist
if [ -f "$FRONTEND_INDEX" ]; then
    FRONTEND_OK=true
    _info "dist/index.html: $(test -f "$FRONTEND_INDEX" && echo 'OK' || echo 'MISSING')"
    _info "dist/assets: $(test -d "$FRONTEND_DIST/assets" && echo 'OK' || echo 'MISSING')"
else
    _warn "前端未构建 — Web UI 将不可用，但 API 仍可访问"
    FRONTEND_OK=false
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 6: Install & start Ollama
# ══════════════════════════════════════════════════════════════════════
_step "安装 Ollama"

if _has_cmd ollama; then
    _log "ollama: 已安装 ($(ollama --version 2>&1))"
    OLLAMA_INSTALLED=true
elif $ZSTD_OK; then
    _info "安装 Ollama (官方 Linux 安装)..."
    if curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tail -5; then
        if _has_cmd ollama; then
            _log "ollama: 安装完成"
            OLLAMA_INSTALLED=true
        else
            _warn "Ollama 安装脚本完成但命令不可用"
        fi
    else
        _warn "Ollama 安装失败 — AI 文本功能不可用"
    fi
else
    _warn "Ollama 安装跳过（缺少 zstd）— AI 文本功能不可用"
fi

# Start Ollama if installed
if $OLLAMA_INSTALLED; then
    if _http_ok "http://127.0.0.1:11434/api/tags"; then
        _log "Ollama 已在运行"
        OLLAMA_RUNNING=true
    else
        _info "启动 Ollama..."
        ollama serve &> "$LOG_DIR/ollama.log" &
        OLLAMA_PID=$!
        echo "$OLLAMA_PID" > "$LOG_DIR/ollama.pid"

        if _wait_http "http://127.0.0.1:11434/api/tags" "Ollama" 60; then
            OLLAMA_RUNNING=true
        else
            if kill -0 "$OLLAMA_PID" 2>/dev/null; then
                _warn "Ollama 进程运行但 HTTP 未响应 — 检查 $LOG_DIR/ollama.log"
            else
                _warn "Ollama 进程已退出 — 检查 $LOG_DIR/ollama.log"
            fi
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 7: Pull Ollama models (from real config, not guesswork)
# ══════════════════════════════════════════════════════════════════════
_step "拉取 Ollama 模型"

# Read real model names from config.json
TEXT_MODEL=$(_json_val "ollama.model")
VISION_MODEL=$(_json_val "evaluation.visualModel")

# Clean quotes if any
TEXT_MODEL=$(echo "$TEXT_MODEL" | tr -d '"')
VISION_MODEL=$(echo "$VISION_MODEL" | tr -d '"')

_info "配置中的模型:"
_info "  文本模型:  ${TEXT_MODEL:-未配置}"
_info "  视觉模型:  ${VISION_MODEL:-未配置}"

if $OLLAMA_RUNNING; then
    EXISTING_MODELS=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null | \
        python3 -c "import json,sys; data=json.load(sys.stdin); print('\n'.join(m['name'] for m in data.get('models',[])))" 2>/dev/null || echo "")

    # ── Text model ──
    if [ -n "$TEXT_MODEL" ]; then
        if echo "$EXISTING_MODELS" | grep -qF "$TEXT_MODEL" 2>/dev/null; then
            _log "文本模型 $TEXT_MODEL: 已存在"
            TEXT_MODEL_OK=true
        else
            _info "正在拉取: ollama pull $TEXT_MODEL"
            if ollama pull "$TEXT_MODEL" 2>&1 | tail -3; then
                _log "文本模型 $TEXT_MODEL: 拉取完成"
                TEXT_MODEL_OK=true
            else
                _warn "文本模型 $TEXT_MODEL 拉取失败 — 文本生成不可用"
                _info "可稍后手动: ollama pull $TEXT_MODEL"
            fi
        fi
    else
        _warn "配置中未找到 ollama.model，跳过文本模型"
    fi

    # ── Vision model ──
    if [ -n "$VISION_MODEL" ]; then
        if echo "$EXISTING_MODELS" | grep -qF "$VISION_MODEL" 2>/dev/null; then
            _log "视觉模型 $VISION_MODEL: 已存在"
            VISION_MODEL_OK=true
        else
            _info "正在拉取: ollama pull $VISION_MODEL"
            if ollama pull "$VISION_MODEL" 2>&1 | tail -3; then
                _log "视觉模型 $VISION_MODEL: 拉取完成"
                VISION_MODEL_OK=true
            else
                _warn "视觉模型 $VISION_MODEL 拉取失败 — 图片评估不可用"
                _info "可稍后手动: ollama pull $VISION_MODEL"
            fi
        fi
    else
        _warn "配置中未找到 evaluation.visualModel，跳过视觉模型"
    fi
else
    _warn "Ollama 未运行，跳过模型拉取"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 8: Prepare ComfyUI
# ══════════════════════════════════════════════════════════════════════
_step "准备 ComfyUI"

COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
COMFYUI_PORT=8188

if [ -f "$COMFYUI_DIR/main.py" ]; then
    _log "ComfyUI 已安装: $COMFYUI_DIR"
    COMFYUI_INSTALLED=true
else
    _info "克隆 ComfyUI 官方仓库..."
    if git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR" 2>&1 | tail -3; then
        _log "ComfyUI 克隆完成: $COMFYUI_DIR"
        COMFYUI_INSTALLED=true
    else
        _warn "ComfyUI 克隆失败 — 图片生成功能不可用"
        _info "可稍后手动: git clone https://github.com/comfyanonymous/ComfyUI.git $COMFYUI_DIR"
    fi
fi

# Create sub-directories
if $COMFYUI_INSTALLED; then
    mkdir -p "$COMFYUI_DIR/models/checkpoints"
    mkdir -p "$COMFYUI_DIR/models/vae"
    mkdir -p "$COMFYUI_DIR/models/loras"
    mkdir -p "$COMFYUI_DIR/output"
    _log "模型目录创建完成"

    # Install ComfyUI Python deps
    if [ -f "$COMFYUI_DIR/requirements.txt" ]; then
        if [ -d "$VENV_DIR" ]; then
            source "$VENV_DIR/bin/activate"
            _info "安装 ComfyUI Python 依赖..."
            pip install -r "$COMFYUI_DIR/requirements.txt" -q 2>&1 || {
                _warn "部分 ComfyUI 依赖安装失败（可能不影响基本功能）"
            }
        fi
    fi

    # ── Check checkpoint ──
    CHECKPOINT_NAME=$(echo "$(_json_val "comfyui.checkpoint")" | tr -d '"')
    _info "checkpoint 名称: ${CHECKPOINT_NAME:-未配置}"

    if [ -n "$CHECKPOINT_NAME" ]; then
        for ckpt_candidate in \
            "$COMFYUI_DIR/models/checkpoints/$CHECKPOINT_NAME" \
            "$COMFYUI_DIR/ComfyUI/models/checkpoints/$CHECKPOINT_NAME"; do
            if [ -f "$ckpt_candidate" ]; then
                _log "checkpoint: $ckpt_candidate"
                CHECKPOINT_OK=true
                break
            fi
        done
        if ! $CHECKPOINT_OK; then
            _warn "checkpoint 缺失: $CHECKPOINT_NAME"
            _info "目标目录: $COMFYUI_DIR/models/checkpoints/"
            _info "下载后放置即可，ComfyUI 可启动但图片生成标记为 degraded"
        fi
    fi

    # ── Copy workflow ──
    if [ -f "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" ]; then
        cp "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" /workspace/workflows/ 2>/dev/null
        _log "工作流已复制: /workspace/workflows/"
    fi

    # ── Start ComfyUI (CPU: start but mark degraded; GPU: full start) ──
    if _http_ok "http://127.0.0.1:${COMFYUI_PORT}/system_stats"; then
        _log "ComfyUI 已在运行 (port ${COMFYUI_PORT})"
        COMFYUI_RUNNING=true
    else
        if $HAS_GPU; then
            _info "启动 ComfyUI (GPU 模式)..."
        else
            _info "启动 ComfyUI (CPU 模式 — 仅服务可用，不建议推理)..."
        fi

        # Use venv python to start ComfyUI
        VENV_PYTHON="$VENV_DIR/bin/python"
        if [ ! -f "$VENV_PYTHON" ]; then
            VENV_PYTHON="python3"
        fi

        "$VENV_PYTHON" -s "$COMFYUI_DIR/main.py" \
            --listen 127.0.0.1 \
            --port "$COMFYUI_PORT" \
            &> "$LOG_DIR/comfyui.log" &
        COMFYUI_PID=$!
        echo "$COMFYUI_PID" > "$LOG_DIR/comfyui.pid"

        # GPU: wait 180s, CPU: wait 60s
        _COMFY_TIMEOUT=180
        if ! $HAS_GPU; then
            _COMFY_TIMEOUT=60
        fi

        if _wait_http "http://127.0.0.1:${COMFYUI_PORT}/system_stats" "ComfyUI" $_COMFY_TIMEOUT; then
            COMFYUI_RUNNING=true
        else
            _warn "ComfyUI 启动超时 — 图片生成不可用"
            if [ -f "$LOG_DIR/comfyui.log" ]; then
                _info "检查日志: tail -50 $LOG_DIR/comfyui.log"
            fi
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 9: Install Whisper
# ══════════════════════════════════════════════════════════════════════
_step "安装 Whisper (ASR 语音识别)"

WHISPER_MODEL_NAME=$(echo "$(_json_val "whisper.model")" | tr -d '"')
_info "模型名称: ${WHISPER_MODEL_NAME:-base.en}"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"

    if python3 -c "import whisper" 2>/dev/null; then
        _log "openai-whisper: 已安装"
        WHISPER_OK=true
    else
        _info "安装 openai-whisper..."
        if pip install openai-whisper -q 2>&1; then
            _log "openai-whisper: 安装完成"
            WHISPER_OK=true
        else
            # Try faster-whisper as fallback
            _info "尝试 faster-whisper..."
            if pip install faster-whisper -q 2>&1; then
                _log "faster-whisper: 安装完成"
                WHISPER_OK=true
            else
                _warn "Whisper 安装失败 — 语音识别不可用"
                _info "可稍后手动: pip install openai-whisper"
            fi
        fi
    fi

    # Whisper will auto-download model on first use; pre-download is optional
    # The model cache goes to ~/.cache/whisper/ by default
    # We can set it up to use /workspace/models/whisper
    export WHISPER_CACHE_DIR="/workspace/models/whisper"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 10: Install Piper (TTS)
# ══════════════════════════════════════════════════════════════════════
_step "安装 Piper TTS"

VOICE_FEMALE=$(echo "$(_json_val "piper.voices.female")" | tr -d '"')
VOICE_MALE=$(echo "$(_json_val "piper.voices.male")" | tr -d '"')
_info "需要音色: ${VOICE_FEMALE:-en_US-lessac-medium}, ${VOICE_MALE:-en_US-ryan-medium}"

if _has_cmd piper; then
    _log "piper: $(piper --version 2>&1 | head -1 || echo 'ok')"
    PIPER_OK=true
elif [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
    _log "piper: $PROJECT_ROOT/.local/bin/piper"
    PIPER_OK=true
else
    # Try to install piper-tts via pip
    if [ -d "$VENV_DIR" ]; then
        source "$VENV_DIR/bin/activate"
        if pip install piper-tts -q 2>&1; then
            if _has_cmd piper || python3 -c "import piper" 2>/dev/null; then
                _log "piper (pip): 安装完成"
                PIPER_OK=true
            fi
        else
            _warn "Piper pip 安装失败"
        fi
    fi

    if ! $PIPER_OK; then
        # Try downloading prebuilt piper binary
        _info "尝试下载 Piper 预编译二进制..."
        PIPER_URL="https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz"
        _PIPER_TMP="/tmp/piper.tar.gz"
        if curl -fsSL "$PIPER_URL" -o "$_PIPER_TMP" 2>/dev/null; then
            mkdir -p "$PROJECT_ROOT/.local/bin"
            tar -xzf "$_PIPER_TMP" -C "$PROJECT_ROOT/.local/bin/" piper/piper --strip-components=1 2>/dev/null || true
            rm -f "$_PIPER_TMP"
            if _has_cmd piper || [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
                chmod +x "$PROJECT_ROOT/.local/bin/piper" 2>/dev/null || true
                _log "piper (binary): $PROJECT_ROOT/.local/bin/piper"
                PIPER_OK=true
            fi
        fi
    fi

    if ! $PIPER_OK; then
        _warn "Piper 未安装 — TTS 音频生成不可用"
        _info "可稍后手动安装: https://github.com/rhasspy/piper"
    fi
fi

# Check voice models
if $PIPER_OK; then
    PIPER_MODEL_DIR="/workspace/models/piper"
    mkdir -p "$PIPER_MODEL_DIR"

    for voice_name in "$VOICE_FEMALE" "$VOICE_MALE"; do
        if [ -n "$voice_name" ]; then
            if [ -f "$PIPER_MODEL_DIR/${voice_name}.onnx" ]; then
                _log "音色 $voice_name: 已存在"
            else
                _warn "音色缺失: $voice_name"
                _info "需放置在: $PIPER_MODEL_DIR/${voice_name}.onnx 和 ${voice_name}.onnx.json"
                PIPER_OK=false
            fi
        fi
    done
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 11: Set Cloud Studio environment variables
# ══════════════════════════════════════════════════════════════════════
_step "设置 Cloud Studio 环境变量"

export APP_ENV=cloudstudio
export PROJECT_ROOT="$PROJECT_ROOT"
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

_log "APP_ENV=$APP_ENV"
_log "OLLAMA_BASE_URL=$OLLAMA_BASE_URL"
_log "COMFYUI_BASE_URL=$COMFYUI_BASE_URL"
_log "COMFYUI_DIR=$COMFYUI_DIR"
_log "PIPER_MODEL_DIR=$PIPER_MODEL_DIR"
_log "WHISPER_MODEL_DIR=$WHISPER_MODEL_DIR"

# ══════════════════════════════════════════════════════════════════════
# STEP 12: Verify backend imports
# ══════════════════════════════════════════════════════════════════════
_step "验证后端 Python 导入"

if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"

    cd "$PROJECT_ROOT"
    if python3 -c "
import sys
sys.path.insert(0, 'backend')
from config import load_config, is_cloudstudio, get_config
load_config()
cfg = get_config()
assert is_cloudstudio(), 'APP_ENV should be cloudstudio'
# Verify no Windows paths
cf = cfg.get('comfyui', {})
assert 'python_embeded' not in cf.get('pythonExe',''), 'Windows pythonExe leaked'
assert 'run_nvidia_gpu' not in cf.get('startScript',''), 'Windows startScript leaked'
print('OK')
" 2>&1; then
        _log "后端导入: OK (Cloud Studio 模式，无 Windows 路径)"
    else
        _warn "后端导入验证有警告 — 检查 config.json 覆盖"
    fi
else
    _warn "跳过 — 虚拟环境不可用"
fi

# ══════════════════════════════════════════════════════════════════════
# STEP 13: Pre-start status summary
# ══════════════════════════════════════════════════════════════════════
_step "启动前状态摘要"

_print_status() {
    echo ""
    echo -e "${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
    echo -e "  ${C_BOLD}System${C_RESET}"
    echo -e "    environment: ${C_CYAN}cloudstudio${C_RESET}"
    echo -e "    cpu:         ${CPU_MODEL} (${CPU_CORES} cores)"
    echo -e "    gpu:         $($HAS_GPU && echo -e "${C_GREEN}${GPU_NAME} | ${GPU_VRAM}${C_RESET}" || echo -e "${C_YELLOW}N/A (CPU only)${C_RESET}")"
    echo -e "    disk:        $DISK_INFO"
    echo ""
    echo -e "  ${C_BOLD}Core${C_RESET}"
    echo -e "    backend:    $($BACKEND_OK && echo -e "${C_GREEN}ready${C_RESET}" || echo -e "${C_RED}failed${C_RESET}")"
    echo -e "    frontend:   $($FRONTEND_OK && echo -e "${C_GREEN}ready${C_RESET}" || echo -e "${C_RED}not built${C_RESET}")"
    echo -e "    fastapi:    pending (next step)"
    echo ""
    echo -e "  ${C_BOLD}Services${C_RESET}"
    echo -e "    ffmpeg:     $($FFMPEG_OK && echo -e "${C_GREEN}available${C_RESET}" || echo -e "${C_YELLOW}unavailable${C_RESET}")"
    echo -e "    ollama:     $($OLLAMA_RUNNING && echo -e "${C_GREEN}running${C_RESET}" || echo -e "${C_YELLOW}stopped${C_RESET}")"
    echo -e "    comfyui:    $($COMFYUI_RUNNING && echo -e "${C_GREEN}running${C_RESET}" || echo -e "${C_YELLOW}stopped${C_RESET}")"
    echo ""
    echo -e "  ${C_BOLD}AI Models${C_RESET}"
    echo -e "    text_model:   $($TEXT_MODEL_OK && echo -e "${C_GREEN}${TEXT_MODEL} ✓${C_RESET}" || echo -e "${C_YELLOW}${TEXT_MODEL:-N/A}${C_RESET}")"
    echo -e "    vision_model: $($VISION_MODEL_OK && echo -e "${C_GREEN}${VISION_MODEL} ✓${C_RESET}" || echo -e "${C_YELLOW}${VISION_MODEL:-N/A}${C_RESET}")"
    echo -e "    checkpoint:   $($CHECKPOINT_OK && echo -e "${C_GREEN}${CHECKPOINT_NAME} ✓${C_RESET}" || echo -e "${C_YELLOW}${CHECKPOINT_NAME:-N/A}${C_RESET}")"
    echo -e "    piper:        $($PIPER_OK && echo -e "${C_GREEN}available${C_RESET}" || echo -e "${C_YELLOW}unavailable${C_RESET}")"
    echo -e "    whisper:      $($WHISPER_OK && echo -e "${C_GREEN}available${C_RESET}" || echo -e "${C_YELLOW}unavailable${C_RESET}")"
    echo ""
    echo -e "  ${C_BOLD}URLs${C_RESET}"
    echo -e "    local_health: http://127.0.0.1:8000/api/health"
    echo -e "    local_web:    http://127.0.0.1:8000"
    echo -e "${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
    echo ""
}

_print_status

# ══════════════════════════════════════════════════════════════════════
# STEP 14: Start FastAPI
# ══════════════════════════════════════════════════════════════════════
_step "启动 FastAPI"

# Check if 8000 already occupied
if _http_ok "http://127.0.0.1:8000/api/ping" 2; then
    _log "FastAPI 已在运行 (port 8000)"
    FASTAPI_STARTED=true
else
    # Check frontend
    if [ ! -f "$FRONTEND_INDEX" ]; then
        _warn "前端未构建 — / 将返回 503，但 /api/* 正常"
    else
        _log "前端 dist 就绪: $FRONTEND_INDEX"
    fi

    # Activate venv
    if [ -d "$VENV_DIR" ]; then
        source "$VENV_DIR/bin/activate"
    fi

    _info "启动 FastAPI (0.0.0.0:8000)..."
    cd "$PROJECT_ROOT/backend"

    # Detach: use nohup and background, then verify
    nohup "$VENV_DIR/bin/python" -m uvicorn main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --log-level info \
        &> "$LOG_DIR/fastapi.log" &
    FASTAPI_PID=$!
    echo "$FASTAPI_PID" > "$LOG_DIR/fastapi.pid"

    # Wait for health
    if _wait_http "http://127.0.0.1:8000/api/ping" "FastAPI" 60; then
        FASTAPI_STARTED=true
        _log "FastAPI 启动成功 (PID: $FASTAPI_PID)"

        # Verify key routes
        if _http_ok "http://127.0.0.1:8000/api/health"; then
            _log "/api/health: OK"
        fi
        if _http_ok "http://127.0.0.1:8000/"; then
            _log "/ (root): OK"
        else
            _warn "/ (root): 未响应（可能前端未构建，返回 503 属正常）"
        fi
    else
        _error "FastAPI 启动超时 — 检查 $LOG_DIR/fastapi.log"
        _info "tail -50 $LOG_DIR/fastapi.log"
        if [ -f "$LOG_DIR/fastapi.log" ]; then
            tail -30 "$LOG_DIR/fastapi.log"
        fi
    fi
fi

# ══════════════════════════════════════════════════════════════════════
# FINAL: Summary
# ══════════════════════════════════════════════════════════════════════
END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))
MIN=$((ELAPSED / 60))
SEC=$((ELAPSED % 60))

echo ""
echo -e "${C_BOLD}╔══════════════════════════════════════════════════════════╗${C_RESET}"
echo -e "${C_BOLD}║                   最终状态摘要                          ║${C_RESET}"
echo -e "${C_BOLD}╚══════════════════════════════════════════════════════════╝${C_RESET}"
echo ""
echo -e "  执行耗时: ${MIN}分${SEC}秒"
echo ""

_print_status

# Additional post-start info
if $FASTAPI_STARTED; then
    echo -e "  ${C_GREEN}▸ 网页可以打开: http://127.0.0.1:8000${C_RESET}"
else
    echo -e "  ${C_RED}▸ FastAPI 未启动 — 请检查日志: $LOG_DIR/fastapi.log${C_RESET}"
fi

echo ""
echo "  AI 功能状态:"
$TEXT_MODEL_OK && echo -e "    ${C_GREEN}✓${C_RESET} 文本生成 (Ollama + ${TEXT_MODEL})" || echo -e "    ${C_YELLOW}✗${C_RESET} 文本生成 — 需要: ollama pull ${TEXT_MODEL}"
$VISION_MODEL_OK && echo -e "    ${C_GREEN}✓${C_RESET} 图片评估 (Ollama + ${VISION_MODEL})" || echo -e "    ${C_YELLOW}✗${C_RESET} 图片评估 — 需要: ollama pull ${VISION_MODEL}"
$COMFYUI_RUNNING && $CHECKPOINT_OK && echo -e "    ${C_GREEN}✓${C_RESET} 图片生成 (ComfyUI + ${CHECKPOINT_NAME})" || true
$COMFYUI_RUNNING && ! $CHECKPOINT_OK && echo -e "    ${C_YELLOW}⚠${C_RESET}  图片生成 — ComfyUI 已运行但 checkpoint 缺失: ${CHECKPOINT_NAME}" || true
! $COMFYUI_RUNNING && echo -e "    ${C_YELLOW}✗${C_RESET} 图片生成 — ComfyUI 未运行"
$PIPER_OK && echo -e "    ${C_GREEN}✓${C_RESET} TTS 音频 (Piper + ${VOICE_FEMALE}/${VOICE_MALE})" || echo -e "    ${C_YELLOW}✗${C_RESET} TTS 音频 — 需要安装 piper 及音色文件"
$WHISPER_OK && echo -e "    ${C_GREEN}✓${C_RESET} 语音识别 (Whisper ${WHISPER_MODEL_NAME})" || echo -e "    ${C_YELLOW}✗${C_RESET} 语音识别 — 需要: pip install openai-whisper"

echo ""
if ! $HAS_GPU; then
    echo -e "  ${C_YELLOW}▸ 当前为 CPU 工作空间${C_RESET}"
    echo -e "  ${C_YELLOW}  切换 GPU 后重新运行本脚本将自动启用:${C_RESET}"
    echo -e "  ${C_YELLOW}  - ComfyUI 图片生成加速${C_RESET}"
    echo -e "  ${C_YELLOW}  - Ollama GPU 推理${C_RESET}"
    echo ""
fi

echo "  仍需人工准备的模型文件:"
$CHECKPOINT_OK || echo "    - $CHECKPOINT_NAME → $COMFYUI_DIR/models/checkpoints/"
$PIPER_OK || echo "    - $VOICE_FEMALE.onnx + .json  → /workspace/models/piper/"
$PIPER_OK || echo "    - $VOICE_MALE.onnx + .json  → /workspace/models/piper/"
if $PIPER_OK && $CHECKPOINT_OK && $TEXT_MODEL_OK && $VISION_MODEL_OK && $WHISPER_OK; then
    echo "    (无 — 所有模型已就绪)"
fi

echo ""
echo -e "  日志目录: ${C_CYAN}$LOG_DIR${C_RESET}"
echo -e "  ${C_CYAN}  tail -f $LOG_DIR/fastapi.log${C_RESET}"
echo ""
echo -e "${C_GREEN}  一键安装启动完成 ✓${C_RESET}"
echo ""

# Keep script running in foreground if fastapi was started by us
if $FASTAPI_STARTED && [ -n "${FASTAPI_PID:-}" ] && kill -0 "$FASTAPI_PID" 2>/dev/null; then
    echo -e "  ${C_CYAN}FastAPI 运行中 (PID: $FASTAPI_PID)，按 Ctrl+C 停止${C_RESET}"
    # Tail fastapi log in foreground
    if [ -f "$LOG_DIR/fastapi.log" ]; then
        tail -f "$LOG_DIR/fastapi.log" 2>/dev/null || true
    else
        # Wait on the process
        wait "$FASTAPI_PID" 2>/dev/null || true
    fi
fi
