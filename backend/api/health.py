"""Health check and service status."""

from __future__ import annotations

import os, subprocess
from typing import Any

from fastapi import APIRouter

from config import get_config, get_mode
from models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/ping")
def ping():
    """Fast ping endpoint for startup health polling. Returns immediately."""
    return {"status": "ok"}


def _check_ollama() -> dict[str, Any]:
    if get_mode() != "real":
        return {"available": False, "model": "", "model_present": False, "last_error": None}
    try:
        from services.ollama_client import OllamaClient
        return OllamaClient().health_check()
    except Exception as e:
        return {"available": False, "model": "", "model_present": False, "last_error": str(e)[:200]}


def _check_piper() -> dict[str, Any]:
    if get_mode() != "real":
        return {"available": False, "voice_a": False, "voice_b": False}
    cfg = get_config().get("piper", {})
    voice_dir = cfg.get("voice_dir", "")
    voices = cfg.get("voices", {})
    va = voices.get("female", "en_US-lessac-medium")
    vb = voices.get("male", "en_US-ryan-medium")
    a_ok = os.path.exists(os.path.join(voice_dir, f"{va}.onnx"))
    b_ok = os.path.exists(os.path.join(voice_dir, f"{vb}.onnx"))
    return {"available": a_ok and b_ok, "voice_a": a_ok, "voice_b": b_ok}


def _check_whisper() -> dict[str, Any]:
    if get_mode() != "real":
        return {"available": False, "model": "base.en"}
    python_exe = get_config().get("whisper", {}).get("pythonPath", "python")
    try:
        proc = subprocess.run([python_exe, "-c", "import whisper; print('ok')"], capture_output=True, text=True, timeout=15)
        return {"available": proc.returncode == 0 and "ok" in proc.stdout, "model": "base.en"}
    except Exception:
        return {"available": False, "model": "base.en"}


def _check_ffmpeg() -> dict[str, Any]:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return {"available": True}
    except Exception:
        return {"available": False}


def _check_comfyui() -> dict[str, Any]:
    """Check ComfyUI health with multi-endpoint fallback and process manager integration.

    Priority:
    1. If process manager says "starting", return that immediately (don't waste time on HTTP)
    2. Try /system_stats first, then /queue, then /history
    3. Combine with process manager info for PID and ownership
    """
    cfg = get_config().get("comfyui", {})
    base_url = cfg.get("baseUrl", "http://127.0.0.1:8188")
    checkpoint_name = cfg.get("checkpoint", "sd_xl_base_1.0.safetensors")

    # Default result for non-real mode
    result = {"available": False, "state": "stopped", "base_url": base_url,
              "workflow_available": False, "checkpoint": checkpoint_name,
              "checkpoint_available": False, "generation_ready": False,
              "last_error": None, "error_code": None, "owned": False, "pid": None,
              "health_endpoint": None}
    if get_mode() != "real":
        result["error_code"] = "NOT_REAL_MODE"
        return result

    from pathlib import Path

    # Always check with process manager first for accurate state
    try:
        from services.comfyui_process_manager import get_comfyui_manager
        mgr = get_comfyui_manager()
        mgr_status = mgr.get_status()
    except Exception:
        mgr_status = {"state": "stopped", "owned": False, "pid": None,
                      "checkpoint_available": False, "last_error": None}

    # If process manager says starting, return that immediately
    if mgr_status.get("state") == "starting":
        result.update(mgr_status)
        # Also check disk resources while starting
        install_root = cfg.get("installRoot", "")
        if install_root and checkpoint_name:
            ckpt_path = Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name
            result["checkpoint_available"] = ckpt_path.exists()
        wf_path = cfg.get("workflowPath", "")
        if wf_path:
            wf_full = Path(__file__).parent.parent.parent / wf_path
            result["workflow_available"] = wf_full.exists()
        return result

    # If process manager says failed, return that
    if mgr_status.get("state") == "failed":
        result.update(mgr_status)
        install_root = cfg.get("installRoot", "")
        if install_root and checkpoint_name:
            ckpt_path = Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name
            result["checkpoint_available"] = ckpt_path.exists()
        wf_path = cfg.get("workflowPath", "")
        if wf_path:
            wf_full = Path(__file__).parent.parent.parent / wf_path
            result["workflow_available"] = wf_full.exists()
        return result

    # Check checkpoint file on disk
    checkpoint_available = False
    install_root = cfg.get("installRoot", "")
    if install_root and checkpoint_name:
        ckpt_path = Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name
        checkpoint_available = ckpt_path.exists()

    # Check workflow
    wf_path = cfg.get("workflowPath", "")
    workflow_available = False
    if wf_path:
        wf_full = Path(__file__).parent.parent.parent / wf_path
        workflow_available = wf_full.exists()

    import requests

    errors = []
    # Try endpoints in priority order: /system_stats, /queue, /history
    for endpoint in ["/system_stats", "/queue", "/history"]:
        try:
            r = requests.get(f"{base_url}{endpoint}", timeout=3,
                           proxies={"http": None, "https": None})
            if r.status_code == 200:
                generation_ready = checkpoint_available and workflow_available
                return {
                    "available": True,
                    "state": "ready" if generation_ready else "degraded",
                    "base_url": base_url,
                    "generation_ready": generation_ready,
                    "workflow_available": workflow_available,
                    "checkpoint": checkpoint_name,
                    "checkpoint_available": checkpoint_available,
                    "owned": mgr_status.get("owned", False),
                    "pid": mgr_status.get("pid"),
                    "last_error": None,
                    "error_code": None if generation_ready else (
                        "CHECKPOINT_MISSING" if not checkpoint_available else
                        "WORKFLOW_MISSING" if not workflow_available else None
                    ),
                    "health_endpoint": endpoint,
                }
        except Exception as e:
            errors.append(f"{endpoint}: {str(e)[:80]}")
            continue

    # All endpoints failed — use process manager state if available
    if mgr_status.get("state") in ("stopped", "failed"):
        result["state"] = mgr_status["state"]
    else:
        result["state"] = "stopped"
    result["last_error"] = " | ".join(errors) if errors else "No endpoints reachable"
    result["error_code"] = "COMFYUI_OFFLINE"
    result["owned"] = mgr_status.get("owned", False)
    result["pid"] = mgr_status.get("pid")
    result["workflow_available"] = workflow_available
    result["checkpoint_available"] = checkpoint_available
    result["generation_ready"] = False
    return result


@router.get("/api/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        status="ok", mode=get_mode(),
        ollama=_check_ollama(),
        comfyui=_check_comfyui(),
        piper=_check_piper(),
        whisper=_check_whisper(),
        ffmpeg=_check_ffmpeg(),
    )
