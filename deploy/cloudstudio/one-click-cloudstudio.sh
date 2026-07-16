#!/usr/bin/env bash
# ============================================================================
# one-click-cloudstudio.sh — English Listening Workbench 一键安装+启动
# ============================================================================
# Cloud Studio 中唯一需要执行的命令：
#   bash deploy/cloudstudio/one-click-cloudstudio.sh
#
# 启动顺序（FastAPI 优先）：
#   1. 环境检查 → 2. 系统依赖 → 3. 虚拟环境 → 4. 前端检查 →
#   5. 启动 FastAPI → 6. Ollama → 7. ComfyUI → 8. Piper/Whisper
#
# FastAPI 在步骤 5 即启动，约 30 秒内网页可打开，不等待 AI 服务。
# 每一步都写入 /workspace/logs/cloudstudio/startup-state.json
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"
STATE_FILE="$LOG_DIR/startup-state.json"
PID_FILE="$LOG_DIR/oneclick.pid"

mkdir -p "$LOG_DIR"
echo $$ > "$PID_FILE"

# ── 全局状态 ─────────────────────────────────────────────────────────
SCRIPT_START_TIME=$(date +%s)
HAS_GPU=false
GPU_NAME="" GPU_VRAM=""

FFMPEG_OK=false
OLLAMA_INSTALLED=false OLLAMA_RUNNING=false
TEXT_MODEL_OK=false VISION_MODEL_OK=false
COMFYUI_INSTALLED=false COMFYUI_RUNNING=false CHECKPOINT_OK=false
PIPER_OK=false WHISPER_OK=false ZSTD_OK=false
FASTAPI_PID="" OLLAMA_PID="" COMFYUI_PID=""

# ── 颜色 ─────────────────────────────────────────────────────────────
C_RESET='\033[0m' C_GREEN='\033[0;32m' C_YELLOW='\033[0;33m' C_RED='\033[0;31m' C_CYAN='\033[0;36m' C_BOLD='\033[1m'

# ── 工具函数 ─────────────────────────────────────────────────────────
_now_iso() { date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%Y-%m-%dT%H:%M:%SZ'; }

_write_state() {
    # Args: status stage message
    local status="$1" stage="$2" message="$3"
    local now; now=$(_now_iso)
    python3 <<PYEOF 2>/dev/null || true
import json, os
f = '$STATE_FILE'
d = {}
if os.path.exists(f):
    try:
        d = json.load(open(f))
    except: pass
d['status'] = '$status'
d['stage'] = '$stage'
d['message'] = r'''$message'''
d['pid'] = $$
d['updated_at'] = '$now'
if not d.get('started_at'):
    d['started_at'] = '$now'
json.dump(d, open(f, 'w'), indent=2)
PYEOF
}

_has_cmd() { command -v "$1" &>/dev/null; }
_http_ok() { curl -sf --max-time "${2:-3}" "$1" >/dev/null 2>&1; }
_step_title() { echo ""; echo -e "${C_BOLD}>>>${C_RESET} $1"; echo -e "${C_CYAN}────────────────────────────────────────────────────${C_RESET}"; }
_log()   { echo -e "    ${C_GREEN}OK${C_RESET}  $1"; }
_warn()  { echo -e "    ${C_YELLOW}WARN${C_RESET} $1"; }
_fail()  { echo -e "    ${C_RED}FAIL${C_RESET} $1"; }
_info()  { echo -e "         $1"; }
_json_val() {
    python3 -c "
import json; f=open('$PROJECT_ROOT/config.json','r',encoding='utf-8-sig'); d=json.load(f)
keys='$1'.split('.'); v=d
for k in keys: v=v.get(k,{}) if isinstance(v,dict) else {}
print(v if isinstance(v,str) else json.dumps(v) if v else '')
" 2>/dev/null | tr -d '"'
}

_wait_http() {
    local url="$1" desc="$2" timeout="${3:-60}" i
    for ((i=1; i<=timeout; i++)); do
        if _http_ok "$url"; then _log "$desc 就绪 (${i}s)"; return 0; fi
        sleep 1
    done
    _warn "$desc 超时 (${timeout}s)"; return 1
}

# ══════════════════════════════════════════════════════════════════════
echo ""
echo -e "${C_BOLD}  初中英语听说课AI备课助手 — Cloud Studio 一键安装启动${C_RESET}"
echo "  PROJECT_ROOT: $PROJECT_ROOT"
echo "  LOG_DIR:      $LOG_DIR"
echo ""

# ══════════════════════════════════════════════════════════════════════
# STAGE 1: environment_check
# ══════════════════════════════════════════════════════════════════════
_write_state "starting" "environment_check" "正在检查系统环境"
_step_title "[1/8] 检查系统环境"

CPU_CORES=$(nproc 2>/dev/null || echo "?")
CPU_MODEL=$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | xargs || echo "unknown")
DISK_INFO=$(df -h /workspace 2>/dev/null | tail -1 | awk '{print "total="$2" used="$3" avail="$4}' || echo "?")
MEM_TOTAL=$(free -h 2>/dev/null | awk '/Mem:/{print $2}' || echo "?")
_info "CPU: ${CPU_MODEL} (${CPU_CORES} cores) | Mem: ${MEM_TOTAL} | Disk: ${DISK_INFO}"

if _has_cmd nvidia-smi && nvidia-smi -L &>/dev/null; then
    HAS_GPU=true
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 | xargs || echo "?")
    _log "GPU: ${GPU_NAME} | VRAM: ${GPU_VRAM}"
else
    _warn "CPU 工作空间 — AI 推理受限，Web 服务正常启动"
fi

# ── Install base deps (quick, needed for everything else) ──
_install_pkg() {
    local pkg="$1"
    _has_cmd "$pkg" && { _info "$pkg: $(command -v "$pkg")"; return 0; }
    command -v apt-get &>/dev/null || { _warn "$pkg: 无 apt-get，跳过"; return 1; }
    apt-get update -qq 2>/dev/null || true
    apt-cache policy "$pkg" 2>/dev/null | grep -q 'Candidate:' || { _warn "$pkg: 无安装候选"; return 1; }
    apt-get install -y -qq "$pkg" 2>/dev/null && { _info "$pkg: installed"; return 0; }
    _warn "$pkg: 安装失败"; return 1
}

for pkg in python3 python3-venv python3-pip nodejs npm git curl wget; do
    _install_pkg "$pkg" || true
done

# zstd (critical for Ollama)
if _has_cmd zstd; then
    ZSTD_OK=true; _info "zstd: ok"
elif _install_pkg "zstd"; then
    ZSTD_OK=true
else
    _warn "zstd 未安装 — Ollama 将无法安装"
fi

# ffmpeg (multi-level fallback)
if _has_cmd ffmpeg; then
    FFMPEG_OK=true; _info "ffmpeg: $(ffmpeg -version 2>&1 | head -1 || echo ok)"
elif _install_pkg "ffmpeg"; then
    FFMPEG_OK=true; _info "ffmpeg (apt): ok"
else
    pip install imageio-ffmpeg -q 2>/dev/null && {
        local IMG_BIN; IMG_BIN=$(python3 -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null || echo "")
        if [ -n "$IMG_BIN" ] && [ -f "$IMG_BIN" ]; then
            mkdir -p "$PROJECT_ROOT/.local/bin"
            ln -sf "$IMG_BIN" "$PROJECT_ROOT/.local/bin/ffmpeg" 2>/dev/null || true
            export PATH="$PROJECT_ROOT/.local/bin:$PATH"
            _has_cmd ffmpeg && FFMPEG_OK=true
        fi
    }
    $FFMPEG_OK && _info "ffmpeg (imageio): ok" || _warn "ffmpeg 不可用 — 音频处理受限"
fi

# ══════════════════════════════════════════════════════════════════════
# STAGE 2: backend_dependencies
# ══════════════════════════════════════════════════════════════════════
_write_state "starting" "backend_dependencies" "正在安装 Python 后端依赖"
_step_title "[2/8] Python 后端依赖"

VENV_DIR="/workspace/.venv"
mkdir -p /workspace/data/assets /workspace/data/exports /workspace/models/whisper /workspace/models/piper /workspace/workflows "$PROJECT_ROOT/.local/bin"
export PATH="$PROJECT_ROOT/.local/bin:$PATH"

if [ -d "$VENV_DIR" ]; then
    _log "虚拟环境已存在，复用: $VENV_DIR"
else
    python3 -m venv "$VENV_DIR" || { _write_state "failed" "backend_dependencies" "虚拟环境创建失败"; echo "FATAL: venv failed"; exit 1; }
    _log "虚拟环境创建: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q 2>&1 | tail -1

REQ_FILE=""
for f in "$PROJECT_ROOT/backend/requirements.txt" "$PROJECT_ROOT/requirements.txt"; do
    [ -f "$f" ] && { REQ_FILE="$f"; break; }
done
if [ -n "$REQ_FILE" ]; then
    pip install -r "$REQ_FILE" -q 2>&1 && _log "后端依赖安装完成" || { _write_state "failed" "backend_dependencies" "pip install 失败"; echo "FATAL: pip install failed"; exit 1; }
else
    _warn "未找到 requirements.txt"
fi
pip install uvicorn -q 2>&1

# ══════════════════════════════════════════════════════════════════════
# STAGE 3: frontend_build
# ══════════════════════════════════════════════════════════════════════
_write_state "starting" "frontend_build" "正在检查前端构建"
_step_title "[3/8] 前端构建"

FRONTEND_DIST="$PROJECT_ROOT/frontend/dist"
FRONTEND_INDEX="$FRONTEND_DIST/index.html"
FRONTEND_OK=false

NEED_BUILD=true
if [ -f "$FRONTEND_INDEX" ]; then
    NEWEST_SRC=$(find "$PROJECT_ROOT/frontend/src" -type f -newer "$FRONTEND_INDEX" 2>/dev/null | head -1)
    if [ -z "$NEWEST_SRC" ]; then
        _log "前端 dist 已是最新，跳过构建"
        NEED_BUILD=false; FRONTEND_OK=true
    fi
fi

if $NEED_BUILD; then
    cd "$PROJECT_ROOT/frontend"
    T0=$(date +%s)
    if [ -f "package-lock.json" ]; then
        npm ci --silent 2>&1 || { _warn "npm ci 失败，回退 npm install"; rm -rf node_modules; npm install --silent 2>&1; }
    else
        npm install --silent 2>&1
    fi
    if [ -d "node_modules" ]; then
        npm run build 2>&1 && { T1=$(date +%s); _log "前端构建完成 ($((T1-T0))s)"; FRONTEND_OK=true; } || _warn "前端构建失败"
    fi
fi

if [ -f "$FRONTEND_INDEX" ]; then
    FRONTEND_OK=true
    _info "dist/index.html: OK | dist/assets: $(test -d "$FRONTEND_DIST/assets" && echo 'OK' || echo 'MISSING')"
fi

# ══════════════════════════════════════════════════════════════════════
# STAGE 4: fastapi_start  ← START FASTAPI NOW, DON'T WAIT FOR AI
# ══════════════════════════════════════════════════════════════════════
_write_state "starting" "fastapi_start" "正在启动 FastAPI (0.0.0.0:8000)"
_step_title "[4/8] 启动 FastAPI (网页服务)"

# Check if port 8000 is already occupied by our own process
FASTAPI_ALREADY_RUNNING=false
if _http_ok "http://127.0.0.1:8000/api/ping" 2; then
    _log "FastAPI 已在运行 (port 8000)"
    FASTAPI_ALREADY_RUNNING=true
fi

if ! $FASTAPI_ALREADY_RUNNING; then
    # Export env vars for FastAPI + config
    export APP_ENV=cloudstudio
    export PYTHONPATH="$PROJECT_ROOT/backend:$PROJECT_ROOT"
    export DATA_DIR="${DATA_DIR:-/workspace/data}"
    export ASSET_DIR="${ASSET_DIR:-/workspace/data/assets}"
    export EXPORT_DIR="${EXPORT_DIR:-/workspace/data/exports}"
    export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
    export COMFYUI_BASE_URL="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}"
    export COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
    export COMFYUI_WORKFLOW_DIR="${COMFYUI_WORKFLOW_DIR:-/workspace/workflows}"
    export PIPER_MODEL_DIR="${PIPER_MODEL_DIR:-/workspace/models/piper}"
    export WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-/workspace/models/whisper}"

    source "$VENV_DIR/bin/activate"
    cd "$PROJECT_ROOT/backend"

    nohup "$VENV_DIR/bin/python" -m uvicorn main:app \
        --host 0.0.0.0 --port 8000 --log-level info \
        &> "$LOG_DIR/fastapi.log" &
    FASTAPI_PID=$!
    echo "$FASTAPI_PID" > "$LOG_DIR/fastapi.pid"
    _info "FastAPI PID: $FASTAPI_PID"

    # Poll /api/ping first (lighter), then /api/health
    _info "等待 FastAPI 监听..."
    if ! _wait_http "http://127.0.0.1:8000/api/ping" "FastAPI /api/ping" 60; then
        _write_state "failed" "fastapi_start" "FastAPI 启动超时 (60s)"
        _fail "FastAPI 启动超时 — 查看 tail -50 $LOG_DIR/fastapi.log"
        tail -30 "$LOG_DIR/fastapi.log" 2>/dev/null || true
        exit 1
    fi
    _log "FastAPI 已监听 port 8000"
fi

# Verify /api/health
if _http_ok "http://127.0.0.1:8000/api/health"; then
    _log "/api/health: 200 OK"
else
    _warn "/api/health 未就绪"
fi

# Verify frontend SPA root
FRONTEND_READY=false
if _http_ok "http://127.0.0.1:8000/"; then
    ROOT_CT=$(curl -s -o /dev/null -w '%{content_type}' --max-time 3 http://127.0.0.1:8000/ 2>/dev/null || echo "")
    if echo "$ROOT_CT" | grep -q "text/html"; then
        _log "/ (root): 200 text/html"
        FRONTEND_READY=true
    else
        _warn "/ 返回了 200 但 Content-Type 不是 text/html: $ROOT_CT"
    fi
else
    if [ -f "$FRONTEND_INDEX" ]; then
        _warn "/ (root): 未返回 200 — frontend/dist 存在但 SPA 路由未生效"
    else
        _warn "/ (root): 未就绪 — 前端未构建（API 正常）"
    fi
fi

# ── Post-FastAPI state ──
FASTAPI_STARTED=true
if $FRONTEND_READY; then
    _write_state "running" "fastapi_start" "FastAPI + 前端已就绪，继续安装可选服务"
else
    _write_state "degraded_frontend" "fastapi_start" "FastAPI 已就绪但前端未完全挂载，继续安装可选服务"
fi

_log "网页服务已启动 ($(date +%H:%M:%S))"
_log "URL: http://127.0.0.1:8000"

# ══════════════════════════════════════════════════════════════════════
# STAGE 5: optional_dependencies (Ollama, ComfyUI, Piper, Whisper)
# ALL of these are OPTIONAL — failure does NOT block the web app
# ══════════════════════════════════════════════════════════════════════
_step_title "[5/8] 可选服务: Ollama"

# ── Ollama ──
_write_state "running" "ollama_start" "正在检查 Ollama"
if _has_cmd ollama; then
    _log "ollama: 已安装"
    OLLAMA_INSTALLED=true
elif $ZSTD_OK; then
    _info "安装 Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tail -3 && _has_cmd ollama && OLLAMA_INSTALLED=true
    $OLLAMA_INSTALLED && _log "ollama 安装完成" || _warn "Ollama 安装失败 — AI 文本功能不可用"
else
    _warn "Ollama 跳过（缺少 zstd）"
fi

if $OLLAMA_INSTALLED; then
    if _http_ok "http://127.0.0.1:11434/api/tags"; then
        _log "Ollama 已在运行"; OLLAMA_RUNNING=true
    else
        ollama serve &> "$LOG_DIR/ollama.log" &
        OLLAMA_PID=$!; echo "$OLLAMA_PID" > "$LOG_DIR/ollama.pid"
        _wait_http "http://127.0.0.1:11434/api/tags" "Ollama" 60 && OLLAMA_RUNNING=true || _warn "Ollama 启动超时"
    fi
fi

# Pull models
if $OLLAMA_RUNNING; then
    TEXT_MODEL=$(_json_val "ollama.model")
    VISION_MODEL=$(_json_val "evaluation.visualModel")
    _info "模型配置: text=$TEXT_MODEL  vision=$VISION_MODEL"

    EXISTING=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null | python3 -c "import json,sys; print('\n'.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "")

    for model_info in "$TEXT_MODEL:text_model" "$VISION_MODEL:vision_model"; do
        MODEL="${model_info%%:*}" TAG="${model_info##*:}"
        [ -z "$MODEL" ] && continue
        if echo "$EXISTING" | grep -qF "$MODEL" 2>/dev/null; then
            _log "$TAG: $MODEL (已存在)"
            [ "$TAG" = "text_model" ] && TEXT_MODEL_OK=true || VISION_MODEL_OK=true
        else
            _info "ollama pull $MODEL ..."
            ollama pull "$MODEL" 2>&1 | tail -2 && {
                _log "$TAG: $MODEL 拉取完成"
                [ "$TAG" = "text_model" ] && TEXT_MODEL_OK=true || VISION_MODEL_OK=true
            } || _warn "$TAG: $MODEL 拉取失败 (不影响网页)"
        fi
    done
fi

# ══════════════════════════════════════════════════════════════════════
_step_title "[6/8] 可选服务: ComfyUI"
_write_state "running" "comfyui_start" "正在检查 ComfyUI"

COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
if [ -f "$COMFYUI_DIR/main.py" ]; then
    _log "ComfyUI 已安装: $COMFYUI_DIR"; COMFYUI_INSTALLED=true
else
    _info "克隆 ComfyUI..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR" 2>&1 | tail -2 && COMFYUI_INSTALLED=true || _warn "ComfyUI 克隆失败"
fi

if $COMFYUI_INSTALLED; then
    mkdir -p "$COMFYUI_DIR/models/checkpoints" "$COMFYUI_DIR/models/vae" "$COMFYUI_DIR/models/loras" "$COMFYUI_DIR/output"
    [ -f "$COMFYUI_DIR/requirements.txt" ] && { source "$VENV_DIR/bin/activate"; pip install -r "$COMFYUI_DIR/requirements.txt" -q 2>&1 || true; }

    CHECKPOINT_NAME=$(_json_val "comfyui.checkpoint")
    if [ -n "$CHECKPOINT_NAME" ]; then
        for ckpt in "$COMFYUI_DIR/models/checkpoints/$CHECKPOINT_NAME" "$COMFYUI_DIR/ComfyUI/models/checkpoints/$CHECKPOINT_NAME"; do
            [ -f "$ckpt" ] && { CHECKPOINT_OK=true; _log "checkpoint: $CHECKPOINT_NAME"; break; }
        done
        $CHECKPOINT_OK || _warn "checkpoint 缺失: $CHECKPOINT_NAME → $COMFYUI_DIR/models/checkpoints/"
    fi

    # Start ComfyUI
    if _http_ok "http://127.0.0.1:8188/system_stats"; then
        _log "ComfyUI 已在运行"; COMFYUI_RUNNING=true
    else
        _CTO=180; $HAS_GPU || _CTO=60
        "$VENV_DIR/bin/python" -s "$COMFYUI_DIR/main.py" --listen 127.0.0.1 --port 8188 &> "$LOG_DIR/comfyui.log" &
        COMFYUI_PID=$!; echo "$COMFYUI_PID" > "$LOG_DIR/comfyui.pid"
        _wait_http "http://127.0.0.1:8188/system_stats" "ComfyUI" $_CTO && COMFYUI_RUNNING=true || _warn "ComfyUI 启动超时 (不影响网页)"
    fi
fi
# Copy workflow
[ -f "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" ] && cp "$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json" /workspace/workflows/ 2>/dev/null

# ══════════════════════════════════════════════════════════════════════
_step_title "[7/8] 可选服务: Whisper + Piper"
_write_state "running" "optional_dependencies" "正在安装 Whisper / Piper"

# Whisper
WHISPER_MODEL_NAME=$(_json_val "whisper.model")
source "$VENV_DIR/bin/activate"
if python3 -c "import whisper" 2>/dev/null; then
    _log "whisper: 已安装"; WHISPER_OK=true
else
    pip install openai-whisper -q 2>&1 && { _log "whisper: 安装完成"; WHISPER_OK=true; } || _warn "whisper 安装失败"
fi
export WHISPER_CACHE_DIR="/workspace/models/whisper"

# Piper
if _has_cmd piper || [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
    _log "piper: 已安装"; PIPER_OK=true
else
    pip install piper-tts -q 2>&1 && _has_cmd piper && PIPER_OK=true
    if ! $PIPER_OK; then
        _PT="/tmp/piper.tar.gz"
        curl -fsSL "https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz" -o "$_PT" 2>/dev/null && {
            mkdir -p "$PROJECT_ROOT/.local/bin"
            tar -xzf "$_PT" -C "$PROJECT_ROOT/.local/bin/" piper/piper --strip-components=1 2>/dev/null || true
            rm -f "$_PT"
            [ -f "$PROJECT_ROOT/.local/bin/piper" ] && { chmod +x "$PROJECT_ROOT/.local/bin/piper" 2>/dev/null; PIPER_OK=true; _log "piper: binary installed"; }
        }
    fi
    $PIPER_OK || _warn "piper 未安装 — TTS 不可用"
fi

# Check voice models
if $PIPER_OK; then
    VOICE_F=$(_json_val "piper.voices.female")
    VOICE_M=$(_json_val "piper.voices.male")
    for vn in "$VOICE_F" "$VOICE_M"; do
        [ -z "$vn" ] && continue
        [ -f "/workspace/models/piper/${vn}.onnx" ] && _log "音色 $vn: OK" || { _warn "音色缺失: $vn → /workspace/models/piper/"; PIPER_OK=false; }
    done
fi

# ══════════════════════════════════════════════════════════════════════
# STAGE 8: health_check + final status
# ══════════════════════════════════════════════════════════════════════
_step_title "[8/8] 健康检查 + 最终状态"
_write_state "running" "health_check" "正在运行最终健康检查"

# Determine final status
FINAL_STATUS="ready"
DEGRADED_REASONS=""
$FRONTEND_READY || { FINAL_STATUS="degraded_frontend"; DEGRADED_REASONS="$DEGRADED_REASONS frontend"; }

# Build summary
SUMMARY_LINES=""
SUMMARY_LINES="$SUMMARY_LINES\n  System:  CPU=${CPU_CORES}cores GPU=$($HAS_GPU && echo $GPU_NAME || echo 'N/A')"
SUMMARY_LINES="$SUMMARY_LINES\n  Backend: $(python3 -c 'import sys; sys.path.insert(0,"'$PROJECT_ROOT'/backend"); from config import is_cloudstudio; print("cloudstudio" if is_cloudstudio() else "windows")' 2>/dev/null || echo 'ok')"
SUMMARY_LINES="$SUMMARY_LINES\n  FastAPI: http://127.0.0.1:8000 ($(curl -s --max-time 2 http://127.0.0.1:8000/api/ping 2>/dev/null && echo '200' || echo 'offline'))"
SUMMARY_LINES="$SUMMARY_LINES\n  Frontend: $($FRONTEND_READY && echo 'online' || echo 'degraded')"
SUMMARY_LINES="$SUMMARY_LINES\n  /api/health: $(curl -s --max-time 2 http://127.0.0.1:8000/api/health 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(\"status\",\"?\"))' 2>/dev/null || echo 'offline')"
SUMMARY_LINES="$SUMMARY_LINES\n  Ollama: $($OLLAMA_RUNNING && echo 'running' || echo 'offline')"
SUMMARY_LINES="$SUMMARY_LINES\n  ComfyUI: $($COMFYUI_RUNNING && echo 'running' || echo 'offline')"
SUMMARY_LINES="$SUMMARY_LINES\n  Text model: $($TEXT_MODEL_OK && echo $TEXT_MODEL || echo 'missing')"
SUMMARY_LINES="$SUMMARY_LINES\n  Vision model: $($VISION_MODEL_OK && echo $VISION_MODEL || echo 'missing')"
SUMMARY_LINES="$SUMMARY_LINES\n  Checkpoint: $($CHECKPOINT_OK && echo $CHECKPOINT_NAME || echo 'missing')"
SUMMARY_LINES="$SUMMARY_LINES\n  Piper: $($PIPER_OK && echo 'available' || echo 'unavailable')"
SUMMARY_LINES="$SUMMARY_LINES\n  Whisper: $($WHISPER_OK && echo 'available' || echo 'unavailable')"
SUMMARY_LINES="$SUMMARY_LINES\n  ffmpeg: $($FFMPEG_OK && echo 'available' || echo 'unavailable')"

# Write final state
_write_state "$FINAL_STATUS" "ready" "工作台已就绪${DEGRADED_REASONS:+ (degraded:$DEGRADED_REASONS)}"

ELAPSED=$(($(date +%s) - SCRIPT_START_TIME))
echo ""
echo -e "${C_BOLD}══════════════════════════════════════════════════════${C_RESET}"
echo -e "${C_BOLD}  最终状态: ${FINAL_STATUS}${C_RESET}  (耗时: ${ELAPSED}s)"
echo -e "${C_BOLD}══════════════════════════════════════════════════════${C_RESET}"
echo -e "$SUMMARY_LINES"
echo ""
echo "  Web UI:  http://127.0.0.1:8000"
echo "  Health:  http://127.0.0.1:8000/api/health"
echo "  Logs:    $LOG_DIR/"
echo ""

# If degraded, show what's missing
if [ "$FINAL_STATUS" != "ready" ]; then
    echo -e "  ${C_YELLOW}注意:${C_RESET}"
    $FRONTEND_READY || echo "    - 前端未就绪: / 返回非 200 HTML"
fi
if ! $HAS_GPU; then
    echo -e "  ${C_YELLOW}CPU 模式: 切换 GPU 后重新运行本脚本可启用完整 AI 功能${C_RESET}"
fi

echo ""
echo -e "${C_GREEN}  一键安装启动完成${C_RESET}"
echo ""

# ── Keep in foreground ──
if [ -n "${FASTAPI_PID:-}" ] && kill -0 "$FASTAPI_PID" 2>/dev/null; then
    echo -e "  FastAPI 运行中 (PID: $FASTAPI_PID)，Ctrl+C 停止"
    if [ -f "$LOG_DIR/fastapi.log" ]; then
        tail -f "$LOG_DIR/fastapi.log" 2>/dev/null || wait "$FASTAPI_PID" 2>/dev/null || true
    else
        wait "$FASTAPI_PID" 2>/dev/null || true
    fi
fi
