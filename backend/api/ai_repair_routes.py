"""AI service repair endpoints — diagnostics + repair orchestration."""

from __future__ import annotations

import asyncio, os, subprocess, json, threading, time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from config import get_config, get_mode, is_cloudstudio
from api.health import _check_piper, _check_comfyui

router = APIRouter(prefix="/api/v1/services/ai", tags=["ai-services"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = Path("/workspace/logs/cloudstudio/startup-state.json")
_REPAIR_SCRIPT = _PROJECT_ROOT / "deploy" / "cloudstudio" / "repair-ai-services.sh"

# ── Repair job tracking ──
_repair_job: dict[str, Any] | None = None
_repair_lock = threading.Lock()


def _read_repair_state() -> dict[str, Any]:
    """Read repair progress from startup-state.json."""
    try:
        if _STATE_FILE.exists():
            data = json.loads(_STATE_FILE.read_text())
            return data.get("repair", {})
    except Exception:
        pass
    return {}


@router.get("/status")
def ai_services_status():
    """Get combined AI service status: Piper + ComfyUI."""
    if get_mode() != "real":
        return {
            "mode": "mock",
            "piper": {"available": False, "status": "stopped"},
            "comfyui": {"available": False, "status": "stopped"},
        }

    piper_status = _check_piper()
    comfyui_status = _check_comfyui()

    # Determine overall AI status
    piper_ok = piper_status.get("status") == "ready"
    comfyui_ok = comfyui_status.get("status") == "ready"

    if piper_ok and comfyui_ok:
        overall = "ready"
    elif piper_ok or comfyui_ok:
        overall = "degraded"
    else:
        overall = "unavailable"

    return {
        "overall": overall,
        "mode": get_mode(),
        "piper": piper_status,
        "comfyui": comfyui_status,
    }


@router.post("/repair")
def trigger_repair():
    """Trigger AI service repair asynchronously. Returns immediately with job_id."""
    global _repair_job

    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "AI 服务修复仅在 Real 模式下可用。",
        })

    if not is_cloudstudio():
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_CLOUDSTUDIO",
            "message": "repair-ai-services.sh 仅在 Cloud Studio/Linux 环境中可用。",
        })

    if not _REPAIR_SCRIPT.exists():
        raise HTTPException(status_code=500, detail={
            "error_code": "REPAIR_SCRIPT_MISSING",
            "message": f"修复脚本不存在: {_REPAIR_SCRIPT}",
        })

    with _repair_lock:
        if _repair_job and _repair_job.get("status") == "running":
            # Check if process is still alive
            pid = _repair_job.get("pid")
            if pid:
                import signal
                try:
                    os.kill(pid, 0)
                    raise HTTPException(status_code=409, detail={
                        "error_code": "REPAIR_ALREADY_RUNNING",
                        "message": "修复任务已在运行中",
                        "job_id": _repair_job["job_id"],
                        "started_at": _repair_job["started_at"],
                    })
                except OSError:
                    pass  # Process dead, allow new repair

    job_id = f"repair_{int(time.time())}"
    log_file = Path("/workspace/logs/cloudstudio/repair-ai-services.log")

    def _run_repair():
        global _repair_job
        try:
            subprocess.run(
                ["bash", str(_REPAIR_SCRIPT)],
                capture_output=False,
                timeout=3600,  # 1 hour max
            )
        except subprocess.TimeoutExpired:
            _repair_job = {
                "job_id": job_id,
                "status": "failed",
                "stage": "timeout",
                "message": "修复超时 (3600s)",
                "started_at": _repair_job["started_at"] if _repair_job else "",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except Exception as e:
            _repair_job = {
                "job_id": job_id,
                "status": "failed",
                "stage": "exception",
                "message": str(e)[:500],
                "started_at": _repair_job["started_at"] if _repair_job else "",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

    thread = threading.Thread(target=_run_repair, daemon=True)
    thread.start()

    _repair_job = {
        "job_id": job_id,
        "status": "running",
        "stage": "starting",
        "message": "修复任务已启动",
        "pid": thread.ident,  # Not the real PID but a tracking ID
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "log_file": str(log_file),
    }

    return {
        "ok": True,
        "message": "修复任务已启动。查询进度: GET /api/v1/services/ai/repair/status",
        "job_id": job_id,
        "log_file": str(log_file),
    }


@router.get("/repair/status")
def repair_status():
    """Get current repair job status. Reads from both in-memory tracker and startup-state.json."""

    # Combine in-memory tracker with file-based state
    file_state = _read_repair_state()

    if _repair_job is None and not file_state:
        return {
            "status": "none",
            "message": "没有正在运行或最近完成的修复任务",
            "job_id": None,
            "stage": None,
            "started_at": None,
            "completed_at": None,
            "stages": [],
        }

    # Define stage order for progress display
    stage_order = [
        "checking_environment",
        "installing_piper",
        "downloading_piper_voices",
        "testing_piper",
        "checking_comfyui",
        "downloading_checkpoint",
        "checking_workflow",
        "installing_nodes",
        "restarting_comfyui",
        "testing_image_generation",
        "completed",
        "failed",
    ]

    current_stage = file_state.get("stage") or (_repair_job.get("stage") if _repair_job else None) or "unknown"
    current_idx = stage_order.index(current_stage) if current_stage in stage_order else -1

    return {
        "job_id": _repair_job.get("job_id") if _repair_job else None,
        "status": file_state.get("status") or (_repair_job.get("status") if _repair_job else "unknown"),
        "stage": current_stage,
        "stage_index": current_idx,
        "total_stages": len(stage_order),
        "message": file_state.get("message") or (_repair_job.get("message") if _repair_job else ""),
        "started_at": _repair_job.get("started_at") if _repair_job else None,
        "completed_at": file_state.get("completed_at") or (_repair_job.get("completed_at") if _repair_job else None),
        "log_file": str(_repair_job.get("log_file", "/workspace/logs/cloudstudio/repair-ai-services.log")) if _repair_job else "/workspace/logs/cloudstudio/repair-ai-services.log",
        "stages": [{"name": s, "completed": stage_order.index(s) < current_idx if s in stage_order else False,
                     "current": s == current_stage} for s in stage_order],
    }
