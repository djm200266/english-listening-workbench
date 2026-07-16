#!/usr/bin/env bash
# ============================================================================
# repair-ai-services.sh — 一键诊断并修复 Piper + ComfyUI AI 服务
# ============================================================================
# Cloud Studio 中唯一需要执行的命令：
#   bash deploy/cloudstudio/repair-ai-services.sh
#
# 支持安全重复运行：已存在的完整文件不会重复下载。
# 日志: /workspace/logs/cloudstudio/repair-ai-services.log
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"
REPAIR_LOG="$LOG_DIR/repair-ai-services.log"
VENV_DIR="/workspace/.venv"
PIPER_VOICE_DIR="/workspace/models/piper"
COMFYUI_DIR="${COMFYUI_DIR:-/workspace/ComfyUI}"
CHECKPOINT_DIR="$COMFYUI_DIR/models/checkpoints"
WORKFLOW_DIR="/workspace/workflows"
STATE_FILE="$LOG_DIR/startup-state.json"

mkdir -p "$LOG_DIR" "$PIPER_VOICE_DIR" "$CHECKPOINT_DIR" "$WORKFLOW_DIR"

# Redirect all output to log file + stdout
exec > >(tee -a "$REPAIR_LOG") 2>&1

START_TIME=$(date +%s)

# ── Colours ──
C_RESET='\033[0m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_RED='\033[0;31m'; C_CYAN='\033[0;36m'; C_BOLD='\033[1m'

_log()   { echo -e "    ${C_GREEN}OK${C_RESET}  $1"; }
_warn()  { echo -e "    ${C_YELLOW}WARN${C_RESET} $1"; }
_fail()  { echo -e "    ${C_RED}FAIL${C_RESET} $1"; }
_info()  { echo -e "         $1"; }
_title() { echo ""; echo -e "${C_BOLD}>>>${C_RESET} $1"; echo -e "${C_CYAN}────────────────────────────────────────────────────${C_RESET}"; }

echo ""
echo "══════════════════════════════════════════════════════"
echo "  AI 服务诊断与修复"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "══════════════════════════════════════════════════════"
echo ""

# ═══════════════════════════════════════════════════════════════
# Utility functions
# ═══════════════════════════════════════════════════════════════
_http_ok() { curl -sf --max-time "${2:-5}" "$1" >/dev/null 2>&1; }
_has_cmd() { command -v "$1" &>/dev/null; }

_wait_http() {
    url="$1"; desc="$2"; timeout="${3:-60}"
    for ((i=1; i<=timeout; i++)); do
        if _http_ok "$url" 3; then _log "$desc 就绪 (${i}s)"; return 0; fi
        sleep 1
    done
    _warn "$desc 超时 (${timeout}s)"; return 1
}

_download() {
    url="$1" dest="$2" desc="$3"
    if [ -f "$dest" ]; then
        sz=$(stat -c%s "$dest" 2>/dev/null || echo "0")
        if [ "$sz" -gt 1000000 ] 2>/dev/null; then
            _info "$desc: 已存在 ($(numfmt --to=iec $sz 2>/dev/null || echo ${sz} bytes))"
            return 0
        else
            _warn "$desc: 文件过小 (${sz} bytes)，重新下载"
            rm -f "$dest"
        fi
    fi
    _info "下载 $desc ..."
    part="${dest}.part"
    rm -f "$part"
    if curl -fSL --progress-bar -o "$part" "$url" 2>&1; then
        final_sz=$(stat -c%s "$part" 2>/dev/null || echo "0")
        if [ "$final_sz" -lt 10000 ] 2>/dev/null; then
            _fail "$desc: 下载文件过小 (${final_sz} bytes)，可能是错误页面"
            rm -f "$part"
            return 1
        fi
        # Check for HTML error page
        if head -c 100 "$part" 2>/dev/null | grep -qi '<!DOCTYPE html\|<html'; then
            _fail "$desc: 下载到 HTML 错误页面"
            rm -f "$part"
            return 1
        fi
        mv "$part" "$dest"
        _log "$desc: 下载完成 ($(numfmt --to=iec $final_sz 2>/dev/null || echo ${final_sz} bytes))"
        return 0
    else
        _fail "$desc: 下载失败"
        rm -f "$part"
        return 1
    fi
}

# ── Write repair progress to state file ──
_repair_state() {
    status="$1" stage="$2" message="$3"
    now=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date '+%Y-%m-%dT%H:%M:%SZ')
    python3 -c "
import json, os
f = '$STATE_FILE'
d = {}
if os.path.exists(f):
    try: d = json.load(open(f))
    except: pass
d.setdefault('repair', {})
d['repair']['status'] = '$status'
d['repair']['stage'] = '$stage'
d['repair']['message'] = '''$message'''
d['repair']['updated_at'] = '$now'
json.dump(d, open(f, 'w'), indent=2)
" 2>/dev/null || true
}

# ═══════════════════════════════════════════════════════════════
# STEP 1: Environment check
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "checking_environment" "正在检查环境"
_title "检查环境"

# GPU
GPU_NAME=""; GPU_VRAM=""; HAS_GPU=false
if _has_cmd nvidia-smi && nvidia-smi -L &>/dev/null; then
    HAS_GPU=true
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
    GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 | xargs || echo "?")
    _log "GPU: $GPU_NAME | VRAM: $GPU_VRAM"
    nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader 2>/dev/null | head -1 | while IFS=, read -r used free; do
        _info "  VRAM used=${used} free=${free}"
    done
else
    _warn "无 GPU 或 nvidia-smi 不可用"
fi

# Disk
DISK_AVAIL=$(df -BM /workspace 2>/dev/null | tail -1 | awk '{print $4}' | sed 's/M//' || echo "0")
_info "磁盘可用: ${DISK_AVAIL}MB"
if [ "${DISK_AVAIL:-0}" -lt 8000 ] 2>/dev/null; then
    _fail "磁盘空间不足 (< 8GB)。SDXL checkpoint 约 6.9GB。请清理后重试。"
    exit 1
fi

# Network
_info "检查网络..."
if _http_ok "https://huggingface.co" 10; then
    _log "huggingface.co: 可达"
elif _http_ok "https://hf-mirror.com" 10; then
    _log "huggingface.co 不可达，使用 hf-mirror.com 镜像"
    HF_ENDPOINT="https://hf-mirror.com"
else
    HF_ENDPOINT="https://huggingface.co"
    _warn "HuggingFace 可能不可达，将尝试直接下载"
fi
HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"

# Python venv
if [ -f "$VENV_DIR/bin/activate" ]; then
    source "$VENV_DIR/bin/activate"
    _log "Python venv: $VENV_DIR"
else
    _warn "venv 不存在，将创建"
    python3 -m venv "$VENV_DIR" || { _fail "venv 创建失败"; exit 1; }
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip -q 2>&1 | tail -1
fi

# ═══════════════════════════════════════════════════════════════
# STEP 2: Repair Piper
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "installing_piper" "正在安装/修复 Piper"
_title "修复 Piper TTS"

PIPER_OK=true

# ── 2a: Install piper binary ──
_info "检查 Piper 可执行文件..."
EXE_PATH=""

# Try piper-tts Python package (provides piper CLI in recent versions)
if pip show piper-tts &>/dev/null; then
    _info "piper-tts Python 包已安装"
fi

# Check if piper binary exists
if _has_cmd piper; then
    EXE_PATH=$(command -v piper)
    _log "piper: $EXE_PATH"
elif [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
    EXE_PATH="$PROJECT_ROOT/.local/bin/piper"
    _log "piper: $EXE_PATH (local)"
else
    _info "安装 piper-tts Python 包..."
    pip install piper-tts -q 2>&1 && _log "piper-tts 安装完成" || _warn "piper-tts pip 安装失败"

    # Fallback: download piper binary from GitHub
    if ! _has_cmd piper && [ ! -f "$PROJECT_ROOT/.local/bin/piper" ]; then
        _info "下载 piper 二进制..."
        mkdir -p "$PROJECT_ROOT/.local/bin"
        piper_tar="/tmp/piper_linux.tar.gz"
        if curl -fSL -o "$piper_tar" \
            "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz" 2>&1; then
            tar -xzf "$piper_tar" -C "$PROJECT_ROOT/.local/bin/" piper/piper --strip-components=1 2>/dev/null || true
            rm -f "$piper_tar"
            if [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
                chmod +x "$PROJECT_ROOT/.local/bin/piper" 2>/dev/null || true
                EXE_PATH="$PROJECT_ROOT/.local/bin/piper"
                export PATH="$PROJECT_ROOT/.local/bin:$PATH"
                _log "piper 二进制安装: $EXE_PATH"
            else
                _fail "piper 二进制解压失败"
                PIPER_OK=false
            fi
        else
            # Try latest release tag
            if curl -fSL -o "$piper_tar" \
                "https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz" 2>&1; then
                tar -xzf "$piper_tar" -C "$PROJECT_ROOT/.local/bin/" piper/piper --strip-components=1 2>/dev/null || true
                rm -f "$piper_tar"
                if [ -f "$PROJECT_ROOT/.local/bin/piper" ]; then
                    chmod +x "$PROJECT_ROOT/.local/bin/piper" 2>/dev/null || true
                    EXE_PATH="$PROJECT_ROOT/.local/bin/piper"
                    export PATH="$PROJECT_ROOT/.local/bin:$PATH"
                    _log "piper 二进制安装: $EXE_PATH (latest)"
                fi
            else
                _fail "piper 二进制下载失败"
                PIPER_OK=false
            fi
        fi
    fi
fi

# Verify piper works
if [ -n "$EXE_PATH" ] || _has_cmd piper; then
    piper_cmd="${EXE_PATH:-piper}"
    if "$piper_cmd" --help &>/dev/null 2>&1; then
        _log "$piper_cmd --help: OK"
    else
        _warn "$piper_cmd --help 失败，但将继续"
    fi
else
    _fail "Piper 可执行文件未找到"
    PIPER_OK=false
fi

# ── 2b: Download voice models ──
_repair_state "running" "downloading_piper_voices" "正在下载 Piper 语音模型"
_info "检查语音模型..."

VOICE_A="en_US-lessac-medium"
VOICE_B="en_US-ryan-medium"

# Official Piper voice URLs (HuggingFace)
VOICE_BASE="${HF_ENDPOINT}/rhasspy/piper-voices/resolve/main/en/en_US"

for vn in "$VOICE_A" "$VOICE_B"; do
    voice_dir="${vn%%/*}"  # Extract speaker dir
    onnx_dest="$PIPER_VOICE_DIR/${vn}.onnx"
    json_dest="$PIPER_VOICE_DIR/${vn}.onnx.json"

    # Determine speaker subdirectory for URL
    speaker="lessac"
    quality="medium"
    if echo "$vn" | grep -q "ryan"; then
        speaker="ryan"
    fi

    onnx_url="${VOICE_BASE}/${speaker}/${quality}/${vn}.onnx"
    json_url="${VOICE_BASE}/${speaker}/${quality}/${vn}.onnx.json"

    # Download ONNX
    _download "$onnx_url" "$onnx_dest" "$vn.onnx" || PIPER_OK=false

    # Download JSON config
    if [ ! -f "$json_dest" ]; then
        _info "下载 $vn.onnx.json ..."
        if curl -fSL -o "$json_dest" "$json_url" 2>&1; then
            # Validate JSON
            if python3 -c "import json; json.load(open('$json_dest'))" 2>/dev/null; then
                _log "$vn.onnx.json: OK"
            else
                _fail "$vn.onnx.json: JSON 解析失败"
                rm -f "$json_dest"
                PIPER_OK=false
            fi
        else
            _warn "$vn.onnx.json 下载失败"
        fi
    else
        # Validate existing JSON
        if python3 -c "import json; json.load(open('$json_dest'))" 2>/dev/null; then
            _info "$vn.onnx.json: 已存在且有效"
        else
            _warn "$vn.onnx.json: 已存在但无效，重新下载"
            rm -f "$json_dest"
            curl -fSL -o "$json_dest" "$json_url" 2>&1 && _log "$vn.onnx.json: OK" || _warn "$vn.onnx.json 下载失败"
        fi
    fi
done

# Set env var so FastAPI uses the correct path
export PIPER_MODEL_DIR="$PIPER_VOICE_DIR"

# ═══════════════════════════════════════════════════════════════
# STEP 3: Test Piper synthesis
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "testing_piper" "正在测试 Piper 语音合成"
_title "测试 Piper 语音合成"

if $PIPER_OK && [ -n "${EXE_PATH:-}" ] || _has_cmd piper; then
    test_piper="${EXE_PATH:-piper}"
    test_voice="$PIPER_VOICE_DIR/${VOICE_A}.onnx"
    test_config="$PIPER_VOICE_DIR/${VOICE_A}.onnx.json"
    test_wav="/tmp/piper_test_$$.wav"

    if [ -f "$test_voice" ] && [ -f "$test_config" ]; then
        _info "合成测试音频: 'Hello, this is a voice test.'"
        if "$test_piper" --model "$test_voice" --config "$test_config" \
            --output_file "$test_wav" <<< "Hello, this is a voice test." 2>&1; then
            if [ -f "$test_wav" ] && [ "$(stat -c%s "$test_wav" 2>/dev/null || echo 0)" -gt 0 ]; then
                wav_dur
                wav_dur=$(python3 -c "
import wave
with wave.open('$test_wav', 'rb') as wf:
    print(round(wf.getnframes()/wf.getframerate(), 2))
" 2>/dev/null || echo "0")
                if [ "${wav_dur:-0}" != "0" ]; then
                    _log "测试合成成功: ${test_wav} (${wav_dur}s)"
                    PIPER_TEST_OK=true
                else
                    _fail "测试 WAV 时长为 0"
                    PIPER_TEST_OK=false
                fi
            else
                _fail "测试 WAV 文件为空或不存在"
                PIPER_TEST_OK=false
            fi
        else
            rc=$?
            _fail "Piper 合成失败 (exit code: $rc)"
            PIPER_TEST_OK=false
        fi
        rm -f "$test_wav"
    else
        _fail "缺少语音模型文件，跳过合成测试"
        PIPER_TEST_OK=false
    fi
else
    _fail "Piper 不可用，跳过合成测试"
    PIPER_TEST_OK=false
fi

# ── Also test with ryan voice ──
if $PIPER_OK && [ -f "$PIPER_VOICE_DIR/${VOICE_B}.onnx" ] && [ -f "$PIPER_VOICE_DIR/${VOICE_B}.onnx.json" ]; then
    test2_wav="/tmp/piper_test2_$$.wav"
    test_piper2="${EXE_PATH:-piper}"
    if "$test_piper2" --model "$PIPER_VOICE_DIR/${VOICE_B}.onnx" \
        --config "$PIPER_VOICE_DIR/${VOICE_B}.onnx.json" \
        --output_file "$test2_wav" <<< "Testing the second voice." 2>&1; then
        if [ -f "$test2_wav" ] && [ "$(stat -c%s "$test2_wav" 2>/dev/null || echo 0)" -gt 0 ]; then
            _log "ryan 语音测试合成: OK"
        fi
    fi
    rm -f "$test2_wav"
fi

# Update config.json with Piper paths
python3 -c "
import json
cfg = json.load(open('$PROJECT_ROOT/config.json', 'r', encoding='utf-8-sig'))
cfg.setdefault('piper', {})['voice_dir'] = '$PIPER_VOICE_DIR'
cfg['piper']['executable'] = '${EXE_PATH:-piper}'
json.dump(cfg, open('$PROJECT_ROOT/config.json', 'w'), indent=2, ensure_ascii=False)
" 2>/dev/null && _info "config.json piper 路径已更新" || _warn "config.json 更新失败"

# ═══════════════════════════════════════════════════════════════
# STEP 4: Repair ComfyUI
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "checking_comfyui" "正在检查 ComfyUI"
_title "修复 ComfyUI"

COMFYUI_OK=true

# ── 4a: Ensure ComfyUI is installed ──
if [ ! -f "$COMFYUI_DIR/main.py" ]; then
    _info "克隆 ComfyUI..."
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR" 2>&1 | tail -2 && _log "ComfyUI 克隆完成" || {
        _fail "ComfyUI 克隆失败"
        COMFYUI_OK=false
    }
fi

if [ -f "$COMFYUI_DIR/main.py" ]; then
    _log "ComfyUI 目录: $COMFYUI_DIR"
    # Install requirements
    if [ -f "$COMFYUI_DIR/requirements.txt" ]; then
        pip install -r "$COMFYUI_DIR/requirements.txt" -q 2>&1 && _info "ComfyUI 依赖: OK" || _warn "部分依赖安装失败"
    fi
fi

# ── 4b: Check/Download checkpoint ──
_repair_state "running" "downloading_checkpoint" "正在检查/下载 SDXL checkpoint"
_info "检查 checkpoint..."

CHECKPOINT_NAME="sd_xl_base_1.0.safetensors"
CHECKPOINT_FILE="$CHECKPOINT_DIR/$CHECKPOINT_NAME"

# Read workflow to get actual checkpoint name
WF_PATH="$PROJECT_ROOT/backend/workflows/sdxl_cartoon_api.fixed.json"
if [ -f "$WF_PATH" ]; then
    WF_CKPT=$(python3 -c "
import json
wf = json.load(open('$WF_PATH'))
for nid, nd in wf.items():
    if isinstance(nd, dict) and nd.get('class_type') == 'CheckpointLoaderSimple':
        ckpt = nd.get('inputs', {}).get('ckpt_name', '')
        if ckpt:
            print(ckpt)
            break
" 2>/dev/null || echo "")
    if [ -n "$WF_CKPT" ]; then
        CHECKPOINT_NAME="$WF_CKPT"
        CHECKPOINT_FILE="$CHECKPOINT_DIR/$CHECKPOINT_NAME"
        _info "Workflow 引用的 checkpoint: $CHECKPOINT_NAME"
    fi
fi

if [ -f "$CHECKPOINT_FILE" ]; then
    ckpt_sz=$(stat -c%s "$CHECKPOINT_FILE" 2>/dev/null || echo "0")
    if [ "${ckpt_sz:-0}" -gt 5000000000 ] 2>/dev/null; then
        _log "checkpoint: $CHECKPOINT_NAME ($(numfmt --to=iec $ckpt_sz 2>/dev/null || echo ${ckpt_sz} bytes))"
    else
        _warn "checkpoint 过小 (${ckpt_sz} bytes)，可能损坏，重新下载"
        rm -f "$CHECKPOINT_FILE"
    fi
fi

if [ ! -f "$CHECKPOINT_FILE" ]; then
    _info "下载 SDXL checkpoint (约 6.9GB，支持断点续传)..."
    ckpt_part="${CHECKPOINT_FILE}.part"
    ckpt_url=""

    # Try official HuggingFace URL
    hf_path="stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
    ckpt_url="${HF_ENDPOINT}/${hf_path}"

    _info "URL: $ckpt_url"

    # Use curl with resume support for large file
    if curl -fSL -C - --progress-bar -o "$ckpt_part" "$ckpt_url" 2>&1; then
        final_sz=$(stat -c%s "$ckpt_part" 2>/dev/null || echo "0")
        if [ "${final_sz:-0}" -gt 5000000000 ] 2>/dev/null; then
            mv "$ckpt_part" "$CHECKPOINT_FILE"
            _log "checkpoint 下载完成 ($(numfmt --to=iec $final_sz 2>/dev/null || echo ${final_sz} bytes))"
        else
            _fail "checkpoint 下载不完整 (${final_sz} bytes)"
            rm -f "$ckpt_part"
            COMFYUI_OK=false
        fi
    else
        _fail "checkpoint 下载失败"
        rm -f "$ckpt_part"
        COMFYUI_OK=false
    fi
fi

# ── 4c: Check VAE ──
_info "检查 VAE..."
VAE_FILE="$COMFYUI_DIR/models/vae/sdxl_vae.safetensors"
if [ ! -f "$VAE_FILE" ]; then
    # SDXL uses built-in VAE, skip
    _info "SDXL 使用内置 VAE，无需额外下载"
fi

# ── 4d: Copy workflow ──
_repair_state "running" "checking_workflow" "正在检查 workflow"
_info "检查 workflow..."
if [ -f "$WF_PATH" ]; then
    cp "$WF_PATH" "$WORKFLOW_DIR/" 2>/dev/null
    _log "workflow 已复制到: $WORKFLOW_DIR/"
    # Validate JSON
    if python3 -c "import json; json.load(open('$WF_PATH'))" 2>/dev/null; then
        _log "workflow JSON: 有效"
    else
        _fail "workflow JSON: 无效"
    fi
else
    _warn "workflow 文件未找到: $WF_PATH"
fi

# ── 4e: Check custom nodes ──
_repair_state "running" "installing_nodes" "正在检查 ComfyUI 自定义节点"
_info "检查自定义节点..."

CUSTOM_NODES_DIR="$COMFYUI_DIR/custom_nodes"
mkdir -p "$CUSTOM_NODES_DIR"

# Check which nodes the workflow needs
if [ -f "$WF_PATH" ]; then
    MISSING_NODES=$(python3 -c "
import json
wf = json.load(open('$WF_PATH'))
# Get all class_types
types = set()
for nid, nd in wf.items():
    if isinstance(nd, dict) and nd.get('class_type'):
        types.add(nd['class_type'])
# Standard ComfyUI nodes
std = {'CheckpointLoaderSimple','CLIPTextEncode','VAEDecode','EmptyLatentImage','KSampler','SaveImage','LoadImage'}
extra = types - std
if extra:
    print(','.join(sorted(extra)))
" 2>/dev/null || echo "")

    if [ -n "$MISSING_NODES" ]; then
        _info "Workflow 使用的节点类型: $MISSING_NODES"
    else
        _info "Workflow 仅使用标准节点"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# STEP 5: Restart ComfyUI
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "restarting_comfyui" "正在重启 ComfyUI"
_title "重启 ComfyUI"

# Stop existing ComfyUI if running
if [ -f "$LOG_DIR/comfyui.pid" ]; then
    old_pid=$(cat "$LOG_DIR/comfyui.pid" 2>/dev/null || echo "")
    if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
        _info "停止旧 ComfyUI 进程 (PID: $old_pid)..."
        kill "$old_pid" 2>/dev/null || true
        sleep 3
        if kill -0 "$old_pid" 2>/dev/null; then
            kill -9 "$old_pid" 2>/dev/null || true
            sleep 1
        fi
        _log "旧 ComfyUI 已停止"
    fi
    rm -f "$LOG_DIR/comfyui.pid"
fi

# Start ComfyUI
if $COMFYUI_OK && [ -f "$COMFYUI_DIR/main.py" ]; then
    _info "启动 ComfyUI..."
    source "$VENV_DIR/bin/activate"
    nohup python3 -s "$COMFYUI_DIR/main.py" --listen 127.0.0.1 --port 8188 \
        &> "$LOG_DIR/comfyui_repair.log" &
    comfy_pid=$!
    echo "$comfy_pid" > "$LOG_DIR/comfyui.pid"
    _info "ComfyUI PID: $comfy_pid"

    # Wait for ready
    _wait_http "http://127.0.0.1:8188/system_stats" "ComfyUI" 120 && COMFYUI_RUNNING=true || {
        _warn "ComfyUI 启动超时，查看日志: tail -50 $LOG_DIR/comfyui_repair.log"
        COMFYUI_RUNNING=false
    }
else
    COMFYUI_RUNNING=false
    if _http_ok "http://127.0.0.1:8188/system_stats" 3; then
        _log "ComfyUI 已在运行 (复用已有实例)"
        COMFYUI_RUNNING=true
    fi
fi

# ═══════════════════════════════════════════════════════════════
# STEP 6: Test image generation
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "testing_image_generation" "正在测试图片生成"
_title "测试 ComfyUI 图片生成"

GEN_TEST_OK=false

if $COMFYUI_RUNNING && [ -f "$CHECKPOINT_FILE" ]; then
    _info "提交最小测试工作流..."

    # Create a minimal test workflow (just a small image)
    TEST_PROMPT="a simple red apple on white background, cartoon style"
    TEST_NEGATIVE="blurry, low quality, text, watermark"

    test_result
    test_result=$(python3 <<PYEOF
import json, requests, time, sys

base = "http://127.0.0.1:8188"

# Build minimal workflow
wf = {
    "1": {"inputs": {"ckpt_name": "$CHECKPOINT_NAME"}, "class_type": "CheckpointLoaderSimple"},
    "2": {"inputs": {"width": 512, "height": 512, "batch_size": 1}, "class_type": "EmptyLatentImage"},
    "3": {"inputs": {"text": "$TEST_PROMPT", "clip": ["1", 1]}, "class_type": "CLIPTextEncode"},
    "4": {"inputs": {"text": "$TEST_NEGATIVE", "clip": ["1", 1]}, "class_type": "CLIPTextEncode"},
    "5": {"inputs": {"seed": 42, "steps": 20, "cfg": 7.0, "sampler_name": "euler", "scheduler": "normal",
                       "denoise": 1.0, "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0],
                       "latent_image": ["2", 0]}, "class_type": "KSampler"},
    "6": {"inputs": {"samples": ["5", 0], "vae": ["1", 2]}, "class_type": "VAEDecode"},
    "7": {"inputs": {"filename_prefix": "repair_test", "images": ["6", 0]}, "class_type": "SaveImage"},
}

# Submit
try:
    r = requests.post(f"{base}/prompt", json={"prompt": wf}, timeout=30,
                     proxies={"http": None, "https": None})
    if r.status_code != 200:
        print(f"SUBMIT_FAILED:{r.status_code}:{r.text[:200]}")
        sys.exit(0)
    prompt_id = r.json().get("prompt_id", "")
    print(f"PROMPT_ID:{prompt_id}")

    # Poll for result
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            r2 = requests.get(f"{base}/history/{prompt_id}", timeout=10,
                            proxies={"http": None, "https": None})
            if r2.status_code == 200:
                data = r2.json()
                if prompt_id in data:
                    entry = data[prompt_id]
                    outputs = entry.get("outputs", {})
                    for nid, nd in outputs.items():
                        images = nd.get("images", [])
                        if images:
                            img = images[0]
                            print(f"SUCCESS:{img['filename']}:{img.get('subfolder','')}:{img.get('type','')}")
                            sys.exit(0)
                    # Check for errors
                    status_msg = entry.get("status", {})
                    if status_msg.get("status_str") == "error":
                        print(f"GEN_ERROR:{status_msg.get('messages','unknown')}")
                        sys.exit(0)
        except Exception as e2:
            pass
        time.sleep(3)
    print("TIMEOUT")
except Exception as e:
    print(f"EXCEPTION:{e}")
PYEOF
)

    if echo "$test_result" | grep -q "^SUCCESS:"; then
        gen_info=$(echo "$test_result" | grep "^SUCCESS:" | cut -d: -f2-)
        _log "测试图片生成成功!"
        _info "  文件: $(echo "$gen_info" | cut -d: -f1)"
        GEN_TEST_OK=true
    elif echo "$test_result" | grep -q "^PROMPT_ID:"; then
        pid_val=$(echo "$test_result" | grep "^PROMPT_ID:" | cut -d: -f2)
        _warn "生成任务已提交 (prompt_id=$pid_val) 但超时未完成"
    elif echo "$test_result" | grep -q "SUBMIT_FAILED"; then
        _fail "生成任务提交失败: $(echo "$test_result" | grep SUBMIT_FAILED)"
    else
        _warn "生成测试结果: $test_result"
    fi
else
    if ! $COMFYUI_RUNNING; then
        _warn "ComfyUI 未运行，跳过图片生成测试"
    fi
    if [ ! -f "$CHECKPOINT_FILE" ]; then
        _warn "Checkpoint 未就绪，跳过图片生成测试"
    fi
fi

# ═══════════════════════════════════════════════════════════════
# STEP 7: Update config for Cloud Studio
# ═══════════════════════════════════════════════════════════════
_title "更新配置"

# Ensure config.json has Cloud Studio paths
python3 <<PYEOF
import json, os

cfg_path = '$PROJECT_ROOT/config.json'
cfg = json.load(open(cfg_path, 'r', encoding='utf-8-sig'))

# Piper
cfg.setdefault('piper', {})['voice_dir'] = '$PIPER_VOICE_DIR'
cfg['piper']['executable'] = '${EXE_PATH:-piper}'

# ComfyUI - already set by config.py env override, but ensure consistency
cf = cfg.setdefault('comfyui', {})
cf['installRoot'] = '$COMFYUI_DIR'
cf['checkpoint'] = '$CHECKPOINT_NAME'

json.dump(cfg, open(cfg_path, 'w'), indent=2, ensure_ascii=False)
print("config.json updated")
PYEOF

# ═══════════════════════════════════════════════════════════════
# STEP 8: Final health check
# ═══════════════════════════════════════════════════════════════
_repair_state "running" "completed" "正在运行最终健康检查"
_title "最终健康检查"

if _http_ok "http://127.0.0.1:8000/api/health" 5; then
    _log "FastAPI /api/health: 200 OK"
    HEALTH_JSON=$(curl -s --max-time 10 http://127.0.0.1:8000/api/health 2>/dev/null || echo '{}')

    PIPER_STATUS=$(echo "$HEALTH_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('piper',{}).get('status','?'))" 2>/dev/null || echo '?')
    PIPER_AVAIL=$(echo "$HEALTH_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('piper',{}).get('available','?'))" 2>/dev/null || echo '?')
    COMFYUI_STATUS=$(echo "$HEALTH_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('comfyui',{}).get('status','?'))" 2>/dev/null || echo '?')
    COMFYUI_GEN=$(echo "$HEALTH_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('comfyui',{}).get('generation_ready','?'))" 2>/dev/null || echo '?')

    _info "Piper:     status=$PIPER_STATUS available=$PIPER_AVAIL"
    _info "ComfyUI:   status=$COMFYUI_STATUS generation_ready=$COMFYUI_GEN"
else
    _warn "FastAPI /api/health 不可达"
fi

# ═══════════════════════════════════════════════════════════════
# Final summary
# ═══════════════════════════════════════════════════════════════
ELAPSED=$(($(date +%s) - START_TIME))
echo ""
echo "══════════════════════════════════════════════════════"
echo "  修复完成"
echo "  耗时: ${ELAPSED}s"
echo "══════════════════════════════════════════════════════"
echo ""
echo "  Piper:"
echo "    可执行文件: ${EXE_PATH:-not found}"
echo "    Voice A: $([ -f "$PIPER_VOICE_DIR/${VOICE_A}.onnx" ] && echo 'OK' || echo 'MISSING')"
echo "    Voice B: $([ -f "$PIPER_VOICE_DIR/${VOICE_B}.onnx" ] && echo 'OK' || echo 'MISSING')"
echo "    测试合成: ${PIPER_TEST_OK:-false}"
echo ""
echo "  ComfyUI:"
echo "    进程运行: ${COMFYUI_RUNNING:-false}"
echo "    Checkpoint: $([ -f "$CHECKPOINT_FILE" ] && echo 'OK' || echo 'MISSING')"
echo "    测试生成: ${GEN_TEST_OK:-false}"
echo ""
echo "  日志: $REPAIR_LOG"
echo ""

if [ "${PIPER_TEST_OK:-false}" = "true" ] && [ "${GEN_TEST_OK:-false}" = "true" ]; then
    echo -e "  ${C_GREEN}所有 AI 服务已就绪！${C_RESET}"
    _repair_state "ready" "completed" "所有 AI 服务已就绪"
else
    echo -e "  ${C_YELLOW}部分服务未完全就绪，请检查上方日志。${C_RESET}"
    echo -e "  ${C_YELLOW}重新运行本脚本不会重复下载已有文件。${C_RESET}"
    _repair_state "degraded" "completed" "部分服务未就绪"
fi
echo ""
