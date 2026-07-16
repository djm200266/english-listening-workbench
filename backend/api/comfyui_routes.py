"""ComfyUI service management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import get_config, get_mode
from api.health import _check_comfyui

router = APIRouter(prefix="/api/v1/services/comfyui", tags=["comfyui"])


@router.get("/status")
def comfyui_status():
    """Get detailed ComfyUI status including state, PID, and errors."""
    return _check_comfyui()


@router.post("/start")
def comfyui_start():
    """
    Start ComfyUI if not already running. Idempotent.

    Returns current state after the operation.
    - If already running: returns {"launched": false, "state": "ready"}
    - If starting: returns {"launched": false, "state": "starting"}
    - If started successfully: returns {"launched": true, "state": "ready"}
    - If failed: returns {"launched": false, "state": "failed", "error": "..."}
    """
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "ComfyUI 启动仅在 Real 模式下可用。",
        })

    from services.comfyui_process_manager import get_comfyui_manager

    mgr = get_comfyui_manager()
    result = mgr.ensure_running()

    # Also return full status for convenience
    status = _check_comfyui()

    return {
        "ok": result["ok"],
        "launched": result.get("launched", False),
        "message": result["message"],
        "state": result.get("state", status.get("state", "stopped")),
        "pid": result.get("pid") or status.get("pid"),
        "comfyui": status,
    }


@router.post("/stop")
def comfyui_stop():
    """
    Stop ComfyUI if it was started by this workbench.
    Does NOT stop externally-managed ComfyUI instances.
    """
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "ComfyUI 停止仅在 Real 模式下可用。",
        })

    from services.comfyui_process_manager import get_comfyui_manager

    mgr = get_comfyui_manager()
    if not mgr._owned:
        return {
            "ok": False,
            "message": "ComfyUI was not started by this workbench and will not be stopped.",
        }
    mgr.stop_if_owned()
    return {"ok": True, "message": "ComfyUI stopped."}
