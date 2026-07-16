#!/usr/bin/env bash
# ============================================================================
# start-background.sh — 后台启动 + 自动等待就绪
# ============================================================================
# 用法:
#   bash deploy/cloudstudio/start-background.sh            启动并等待就绪
#   bash deploy/cloudstudio/start-background.sh --status   查看详细状态
#   bash deploy/cloudstudio/start-background.sh --wait     等待现有任务就绪
#   bash deploy/cloudstudio/start-background.sh --recover  工作空间重连后恢复
#   bash deploy/cloudstudio/stop-cloudstudio.sh            停止所有服务
# ============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="/workspace/logs/cloudstudio"
STATE_FILE="$LOG_DIR/startup-state.json"
PID_FILE="$LOG_DIR/workbench.pid"
LOCK_FILE="$LOG_DIR/workbench.lock"

# ══════════════════════════════════════════════════════════════════════
# UTILITY FUNCTIONS
# ══════════════════════════════════════════════════════════════════════
_http_ok() { curl -sf --max-time "${2:-3}" "$1" >/dev/null 2>&1; }
_now_iso() { date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S'; }

_read_state() {
    # Read a key from startup-state.json.  Never crashes — returns default on any failure.
    local key="$1" default="${2:-}"
    if [ -f "$STATE_FILE" ]; then
        python3 -c "import json; d=json.load(open('$STATE_FILE')); print(d.get('$key','$default'))" 2>/dev/null || echo "$default"
    else
        echo "$default"
    fi
}

_get_uptime() {
    local pid="$1"
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then echo "N/A"; return; fi
    local etime; etime=$(ps -o etime= -p "$pid" 2>/dev/null | xargs || echo "?")
    echo "$etime"
}

_check_fastapi() {
    # Returns: "ready" | "online_no_health" | "offline"
    if _http_ok "http://127.0.0.1:8000/api/health" 3; then
        echo "ready"
    elif _http_ok "http://127.0.0.1:8000/api/ping" 2; then
        echo "online_no_health"
    else
        echo "offline"
    fi
}

_check_frontend() {
    # Returns: "ready" | "degraded" | "offline"
    local code ct
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/ 2>/dev/null || echo "000")
    ct=$(curl -s -o /dev/null -w '%{content_type}' --max-time 3 http://127.0.0.1:8000/ 2>/dev/null || echo "")
    if [ "$code" = "200" ] && echo "$ct" | grep -q "text/html"; then
        echo "ready"
    elif [ "$code" = "200" ]; then
        echo "degraded"
    elif [ "$code" = "503" ]; then
        echo "no_frontend"
    else
        echo "offline"
    fi
}

# ══════════════════════════════════════════════════════════════════════
# show_status — detailed status of all services
# ══════════════════════════════════════════════════════════════════════
show_status() {
    echo ""
    echo "══════════════════════════════════════════════════════"
    echo "  English Listening Workbench — 详细状态"
    echo "  $(date '+%Y-%m-%d %H:%M:%S')"
    echo "══════════════════════════════════════════════════════"
    echo ""

    # ── Main process ──
    local MAIN_PID=""
    if [ -f "$PID_FILE" ]; then
        MAIN_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")
    fi

    local main_alive=false
    if [ -n "$MAIN_PID" ] && kill -0 "$MAIN_PID" 2>/dev/null; then
        main_alive=true
        local uptime; uptime=$(_get_uptime "$MAIN_PID")
        echo "  ── 主进程 ──"
        echo "  PID:        $MAIN_PID (alive)"
        echo "  运行时间:   $uptime"
    else
        echo "  ── 主进程 ──"
        echo "  PID:        ${MAIN_PID:-N/A} (not running)"
        [ -f "$PID_FILE" ] && [ -n "${MAIN_PID:-}" ] && echo "  (PID 文件存在但进程已退出 — 将自动清理)" && rm -f "$PID_FILE" "$LOCK_FILE"
    fi

    # ── Startup state ──
    echo ""
    echo "  ── 启动状态 ──"
    local s_status s_stage s_msg s_updated
    s_status=$(_read_state "status" "unknown")
    s_stage=$(_read_state "stage" "unknown")
    s_msg=$(_read_state "message" "")
    s_updated=$(_read_state "updated_at" "")
    echo "  Status:     $s_status"
    echo "  Stage:      $s_stage"
    echo "  Message:    ${s_msg:-N/A}"
    echo "  Updated:    ${s_updated:-N/A}"

    # ── FastAPI / Port 8000 ──
    echo ""
    echo "  ── FastAPI (port 8000) ──"
    local fa_status; fa_status=$(_check_fastapi)
    local fe_status; fe_status=$(_check_frontend)

    case "$fa_status" in
        ready)
            echo "  /api/health: 200 OK ✓"
            local health_json; health_json=$(curl -s --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null || echo '{}')
            local h_status h_mode
            h_status=$(echo "$health_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo '?')
            h_mode=$(echo "$health_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('mode','?'))" 2>/dev/null || echo '?')
            echo "  health:     status=$h_status mode=$h_mode"
            ;;
        online_no_health)
            echo "  /api/ping:  200 OK"
            echo "  /api/health: 未响应"
            ;;
        offline)
            echo "  FastAPI:    未运行"
            ;;
    esac

    echo "  / (root):   $fe_status"
    case "$fe_status" in
        ready)    echo "  前端:       正常 (200 text/html)" ;;
        degraded) echo "  前端:       异常 (200 但非 text/html)" ;;
        no_frontend) echo "  前端:       未构建 (503)" ;;
        offline)  echo "  前端:       不可达" ;;
    esac

    # ── Ollama ──
    echo ""
    echo "  ── Ollama (port 11434) ──"
    if _http_ok "http://127.0.0.1:11434/api/tags" 2; then
        local o_models; o_models=$(curl -sf --max-time 3 http://127.0.0.1:11434/api/tags 2>/dev/null | python3 -c "import json,sys; ms=json.load(sys.stdin).get('models',[]); print(len(ms),'models:',', '.join(m['name'] for m in ms[:5]))" 2>/dev/null || echo '?')
        echo "  Ollama:     running ($o_models)"
    else
        echo "  Ollama:     offline"
    fi

    # ── ComfyUI ──
    echo ""
    echo "  ── ComfyUI (port 8188) ──"
    if _http_ok "http://127.0.0.1:8188/system_stats" 2; then
        echo "  ComfyUI:    running"
    else
        echo "  ComfyUI:    offline"
    fi

    # ── Disk ──
    echo ""
    echo "  ── 磁盘 ──"
    df -h /workspace 2>/dev/null | tail -1 | awk '{print "  /workspace: "$3" used / "$2" total ("$5" used)"}' || true

    # ── Logs ──
    echo ""
    echo "  ── 日志 ──"
    echo "  目录:       $LOG_DIR/"
    echo "  主日志:     $LOG_DIR/workbench.log"
    echo "  FastAPI:    $LOG_DIR/fastapi.log"
    echo "  State:      $STATE_FILE"
    echo ""

    # ── Overall assessment ──
    echo "══════════════════════════════════════════════════════"
    if [ "$fa_status" = "ready" ] && [ "$fe_status" = "ready" ]; then
        echo "  整体状态: READY — 工作台完全就绪"
        echo "  Web UI:  http://127.0.0.1:8000"
    elif [ "$fa_status" = "ready" ] && [ "$fe_status" != "ready" ]; then
        echo "  整体状态: DEGRADED — API 正常但前端未就绪"
    elif [ "$fa_status" = "online_no_health" ]; then
        echo "  整体状态: STARTING — FastAPI 正在启动"
    elif $main_alive; then
        echo "  整体状态: STARTING — 进程运行中，等待 FastAPI 监听"
    elif [ "$s_status" = "failed" ]; then
        echo "  整体状态: FAILED — 启动失败"
    else
        echo "  整体状态: STOPPED"
    fi
    echo "══════════════════════════════════════════════════════"
    echo ""
}

# ══════════════════════════════════════════════════════════════════════
# show_error_summary — extract error lines from workbench.log
# ══════════════════════════════════════════════════════════════════════
show_error_summary() {
    local log="$LOG_DIR/workbench.log"
    if [ ! -f "$log" ]; then
        echo "  (无 workbench.log)"
        return
    fi
    echo ""
    echo "  ── 错误摘要 (最后 150 行中匹配的关键错误) ──"
    local errors
    errors=$(tail -150 "$log" 2>/dev/null | grep -iE 'error|failed|traceback|exception|not found|permission denied|no module|fatal|ModuleNotFoundError|SyntaxError|ImportError|cannot|refused' 2>/dev/null | tail -20 || echo "")
    if [ -n "$errors" ]; then
        echo "$errors" | while IFS= read -r line; do echo "    $line"; done
    else
        echo "    (未找到匹配的错误行)"
    fi
    echo ""
    echo "  完整日志: $log"
    echo "  FastAPI日志: $LOG_DIR/fastapi.log"
}

# ══════════════════════════════════════════════════════════════════════
# wait_for_ready — poll until FastAPI + frontend are ready or timeout
# ══════════════════════════════════════════════════════════════════════
wait_for_ready() {
    local max_wait="${1:-300}"
    local interval="${2:-3}"
    local waited=0

    echo "[wait] 等待工作台就绪..."
    echo "[wait] 最长等待: ${max_wait}s  |  检查间隔: ${interval}s"
    echo ""

    while [ $waited -lt $max_wait ]; do
        # ── Check if main process still alive ──
        local mpid=""
        [ -f "$PID_FILE" ] && mpid=$(cat "$PID_FILE" 2>/dev/null || echo "")

        if [ -n "$mpid" ] && ! kill -0 "$mpid" 2>/dev/null; then
            # Process died — check if it ended successfully
            local s_stat; s_stat=$(_read_state "status" "unknown")
            if [ "$s_stat" = "ready" ] || [ "$s_stat" = "running" ]; then
                # Script completed, services may still be running — verify
                local fa; fa=$(_check_fastapi)
                local fe; fe=$(_check_frontend)
                if [ "$fa" = "ready" ] && [ "$fe" = "ready" ]; then
                    echo ""
                    echo "═══════════════════════════════════════════"
                    echo "  工作台已就绪！"
                    echo "  Web UI:  http://127.0.0.1:8000"
                    echo "  Health:  http://127.0.0.1:8000/api/health"
                    echo "  Status:  ready"
                    echo "═══════════════════════════════════════════"
                    return 0
                fi
            elif [ "$s_stat" = "failed" ]; then
                echo ""
                echo "[wait] 启动失败"
                show_error_summary
                return 1
            else
                echo ""
                echo "[wait] 主进程已退出 (PID $mpid)"
                show_error_summary
                return 1
            fi
        fi

        # ── Check if ready ──
        local fa_now; fa_now=$(_check_fastapi)
        local fe_now; fe_now=$(_check_frontend)

        if [ "$fa_now" = "ready" ] && [ "$fe_now" = "ready" ]; then
            echo ""
            echo "═══════════════════════════════════════════"
            echo "  工作台已就绪！ (等待 ${waited}s)"
            echo "  Web UI:  http://127.0.0.1:8000"
            echo "  Health:  http://127.0.0.1:8000/api/health"
            echo "  Status:  ready"
            echo "═══════════════════════════════════════════"
            return 0
        fi

        # ── Show progress every 30 seconds ──
        local stage; stage=$(_read_state "stage" "unknown")
        local msg; msg=$(_read_state "message" "")
        local mod=$((waited % 30))
        if [ $waited -eq 0 ] || [ $mod -eq 0 ]; then
            printf "  [starting] 已等待 %3d秒 | 阶段: %-24s | %s\n" "$waited" "$stage" "${msg:-...}"
        fi

        sleep "$interval"
        waited=$((waited + interval))
    done

    # ── Timeout ──
    echo ""
    echo "[wait] 超时 (${max_wait}s)"
    local fa_end; fa_end=$(_check_fastapi)
    if [ "$fa_end" = "ready" ]; then
        echo "[wait] FastAPI 正常但前端未就绪 — 可能前端未构建"
        echo "[wait] API 功能可用: http://127.0.0.1:8000/api/health"
        return 2
    fi
    show_error_summary
    return 1
}

# ══════════════════════════════════════════════════════════════════════
# start_process — launch one-click script in background
# ══════════════════════════════════════════════════════════════════════
start_process() {
    # ── Check for existing instance ──
    if [ -f "$LOCK_FILE" ]; then
        local lock_pid; lock_pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
        if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
            echo "[start] 工作台已在启动中 (PID: $lock_pid)"
            local s; s=$(_read_state "status" "unknown")
            local stg; stg=$(_read_state "stage" "unknown")
            echo "[start] 当前状态: $s / $stg"
            echo "[start] 进入等待模式..."
            echo ""
            return 0
        fi
        # Stale lock
        rm -f "$LOCK_FILE" "$PID_FILE"
    fi

    # ── Clean up stale PID ──
    if [ -f "$PID_FILE" ]; then
        local old_pid; old_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [ -n "$old_pid" ] && ! kill -0 "$old_pid" 2>/dev/null; then
            echo "[start] 清理过期 PID: $old_pid"
            rm -f "$PID_FILE"
        fi
    fi

    # ── Check if port 8000 already has a non-project process ──
    if _http_ok "http://127.0.0.1:8000/api/ping" 2; then
        echo "[start] Port 8000 已有服务运行 — 检查是否为本项目..."
        local h_json; h_json=$(curl -s --max-time 5 http://127.0.0.1:8000/api/health 2>/dev/null || echo '{}')
        local h_title; h_title=$(echo "$h_json" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo '?')
        if [ "$h_title" != "?" ] && [ "$h_title" != "" ]; then
            echo "[start] 检测到本项目 FastAPI 已在运行"
            echo "[start] Web UI: http://127.0.0.1:8000"
            echo ""
            show_status
            exit 0
        else
            echo "[start] 警告: 端口 8000 被非项目进程占用"
            echo "[start] 请手动检查: lsof -i :8000 或 ss -tlnp | grep 8000"
            exit 1
        fi
    fi

    # ── Launch one-click script in background ──
    echo "[start] 后台启动英语听说课工作台..."
    echo "[start] 日志: $LOG_DIR/workbench.log"
    echo ""

    nohup bash "$SCRIPT_DIR/one-click-cloudstudio.sh" \
        &> "$LOG_DIR/workbench.log" &
    local bg_pid=$!

    echo "$bg_pid" > "$LOCK_FILE"
    echo "$bg_pid" > "$PID_FILE"

    echo "══════════════════════════════════════════════════════"
    echo "  工作台已后台启动 (PID: $bg_pid)"
    echo "  日志: $LOG_DIR/workbench.log"
    echo "══════════════════════════════════════════════════════"
    echo ""
}

# ══════════════════════════════════════════════════════════════════════
# recover — workspace reconnection: check services, clean stale PIDs, restart missing
# ══════════════════════════════════════════════════════════════════════
recover_services() {
    echo "[recover] 检查服务状态..."

    # Clean stale PIDs
    for pf in "$PID_FILE" "$LOCK_FILE" "$LOG_DIR/fastapi.pid" "$LOG_DIR/ollama.pid" "$LOG_DIR/comfyui.pid"; do
        if [ -f "$pf" ]; then
            local old_pid; old_pid=$(cat "$pf" 2>/dev/null || echo "")
            if [ -n "$old_pid" ] && ! kill -0 "$old_pid" 2>/dev/null; then
                echo "[recover] 清理过期 PID 文件: $pf ($old_pid)"
                rm -f "$pf"
            fi
        fi
    done

    # Check FastAPI (port 8000)
    if _http_ok "http://127.0.0.1:8000/api/ping" 2; then
        echo "[recover] FastAPI: running ✓"
    else
        echo "[recover] FastAPI: offline — 尝试重启..."
        export APP_ENV=cloudstudio
        export PYTHONPATH="$PROJECT_ROOT/backend:$PROJECT_ROOT"
        local venv_dir="/workspace/.venv"
        if [ -f "$venv_dir/bin/python" ]; then
            source "$venv_dir/bin/activate"
            nohup "$venv_dir/bin/python" -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level info \
                &> "$LOG_DIR/fastapi.log" &
            local new_pid=$!
            echo "$new_pid" > "$LOG_DIR/fastapi.pid"
            echo "[recover] FastAPI 重启中 (PID: $new_pid)..."
            _wait_http "http://127.0.0.1:8000/api/ping" "FastAPI" 60 && echo "[recover] FastAPI: 已恢复 ✓" || echo "[recover] FastAPI: 启动失败 ✗"
        else
            echo "[recover] FastAPI: 虚拟环境不存在，请先运行 one-click-cloudstudio.sh"
        fi
    fi

    # Check Ollama (port 11434)
    if _http_ok "http://127.0.0.1:11434/api/tags" 2; then
        echo "[recover] Ollama: running ✓"
    else
        echo "[recover] Ollama: offline — 尝试重启..."
        if command -v ollama &>/dev/null; then
            ollama serve &> "$LOG_DIR/ollama.log" &
            local o_pid=$!
            echo "$o_pid" > "$LOG_DIR/ollama.pid"
            sleep 3
            _http_ok "http://127.0.0.1:11434/api/tags" 3 && echo "[recover] Ollama: 已恢复 ✓" || echo "[recover] Ollama: 未恢复（可能需要更长时间）"
        else
            echo "[recover] Ollama: 未安装"
        fi
    fi

    # Check ComfyUI (port 8188)
    if _http_ok "http://127.0.0.1:8188/system_stats" 2; then
        echo "[recover] ComfyUI: running ✓"
    else
        echo "[recover] ComfyUI: offline — 尝试重启..."
        local comfyui_dir="${COMFYUI_DIR:-/workspace/ComfyUI}"
        if [ -f "$comfyui_dir/main.py" ] && [ -f "/workspace/.venv/bin/python" ]; then
            "/workspace/.venv/bin/python" -s "$comfyui_dir/main.py" --listen 127.0.0.1 --port 8188 &> "$LOG_DIR/comfyui.log" &
            local c_pid=$!
            echo "$c_pid" > "$LOG_DIR/comfyui.pid"
            echo "[recover] ComfyUI 重启中 (PID: $c_pid)..."
            _wait_http "http://127.0.0.1:8188/system_stats" "ComfyUI" 180 && echo "[recover] ComfyUI: 已恢复 ✓" || echo "[recover] ComfyUI: 启动超时（可能仍需初始化）"
        else
            echo "[recover] ComfyUI: 未安装"
        fi
    fi

    echo ""
    echo "[recover] 恢复检查完成。运行 --status 查看详细状态。"
}

# ══════════════════════════════════════════════════════════════════════
# main — parse arguments and dispatch
# ══════════════════════════════════════════════════════════════════════
main() {
    local action="${1:-start}"

    # Normalize action
    case "$action" in
        --status|status)   action="status" ;;
        --wait|wait)       action="wait" ;;
        --recover|recover) action="recover" ;;
        --start|start|"")  action="start" ;;
        *) echo "用法: bash $0 [--status|--wait|--recover]"; exit 1 ;;
    esac

    mkdir -p "$LOG_DIR"

    case "$action" in
        status)
            show_status
            ;;
        wait)
            wait_for_ready
            ;;
        recover)
            recover_services
            show_status
            ;;
        start)
            start_process
            wait_for_ready
            ;;
    esac
}

main "$@"
