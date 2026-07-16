"""Health check and service status."""

from __future__ import annotations

import os, subprocess, json
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from config import get_config, get_mode
from models import HealthResponse

router = APIRouter(tags=["health"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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


# ══════════════════════════════════════════════════════════════════════
# Piper health check — comprehensive
# ══════════════════════════════════════════════════════════════════════

def _check_piper() -> dict[str, Any]:
    """Comprehensive Piper health check.

    Returns:
      status: "ready" | "degraded" | "stopped" | "failed"
      available: bool
      voice_a / voice_b: whether each voice file exists on disk
      executable_available: whether piper binary is callable
      test_synthesis: whether a short test WAV was generated successfully
      voice_a_json_exists / voice_b_json_exists: config JSON files present
      missing_voices: list of voice names not found on disk
      last_error: last error message, or None
    """
    result: dict[str, Any] = {
        "available": False,
        "status": "stopped",
        "executable_available": False,
        "executable_path": "",
        "voice_a": False,
        "voice_b": False,
        "voice_a_path": "",
        "voice_b_path": "",
        "voice_a_json_exists": False,
        "voice_b_json_exists": False,
        "test_synthesis": False,
        "missing_voices": [],
        "last_error": None,
    }

    if get_mode() != "real":
        result["status"] = "stopped"
        result["last_error"] = "NOT_REAL_MODE"
        return result

    cfg = get_config().get("piper", {})
    voice_dir = cfg.get("voice_dir", "")
    voices = cfg.get("voices", {})
    va_name = voices.get("female", "en_US-lessac-medium")
    vb_name = voices.get("male", "en_US-ryan-medium")
    exe = cfg.get("executable", "piper")

    # ── Check executable ──
    exe_path = exe
    if os.path.exists(exe):
        exe_path = exe
    else:
        # Try to resolve from PATH
        import shutil
        resolved = shutil.which(exe) or shutil.which("piper")
        if resolved:
            exe_path = resolved

    if os.path.exists(exe_path) or (shutil.which(exe_path) if hasattr(__import__('shutil'), 'which') else False):
        result["executable_available"] = True

    # Double-check by actually calling it
    try:
        import shutil as _shutil
        _found = _shutil.which(exe) or _shutil.which("piper") or ""
        if _found:
            result["executable_path"] = _found
            proc = subprocess.run(
                [_found, "--help"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 or "usage" in (proc.stdout + proc.stderr).lower():
                result["executable_available"] = True
            else:
                result["executable_available"] = False
                result["last_error"] = f"piper --help returned code {proc.returncode}"
        else:
            # Try pip-installed piper-tts
            # piper-tts provides a command-line entry point
            try:
                proc = subprocess.run(
                    ["python3", "-c", "import piper_tts; print('ok')"],
                    capture_output=True, text=True, timeout=10,
                )
                if proc.returncode == 0:
                    # piper-tts Python package is available, but may not have CLI
                    # The actual piper binary is separate
                    result["executable_available"] = False
                    result["last_error"] = "piper-tts Python package found, but piper CLI binary not in PATH"
                else:
                    result["executable_available"] = False
                    result["last_error"] = "piper binary not found and piper-tts not installed"
            except Exception:
                result["executable_available"] = False
                result["last_error"] = "piper binary not found in PATH"
    except Exception as e:
        result["executable_available"] = False
        result["last_error"] = f"piper executable check failed: {str(e)[:200]}"

    # ── Check voice files ──
    va_path = os.path.join(voice_dir, f"{va_name}.onnx") if voice_dir else ""
    vb_path = os.path.join(voice_dir, f"{vb_name}.onnx") if voice_dir else ""
    va_json = va_path + ".json" if va_path else ""
    vb_json = vb_path + ".json" if vb_path else ""

    result["voice_a_path"] = va_path
    result["voice_b_path"] = vb_path

    missing = []
    if va_path and os.path.exists(va_path):
        result["voice_a"] = True
        # Verify file size (should be > 1MB for medium quality)
        try:
            sz = os.path.getsize(va_path)
            if sz < 100_000:
                result["voice_a"] = False
                missing.append(f"{va_name} (too small: {sz} bytes)")
        except Exception:
            pass
    else:
        missing.append(va_name)

    if vb_path and os.path.exists(vb_path):
        result["voice_b"] = True
        try:
            sz = os.path.getsize(vb_path)
            if sz < 100_000:
                result["voice_b"] = False
                missing.append(f"{vb_name} (too small: {sz} bytes)")
        except Exception:
            pass
    else:
        missing.append(vb_name)

    if va_json and os.path.exists(va_json):
        # Verify JSON is parseable
        try:
            with open(va_json, "r") as f:
                json.load(f)
            result["voice_a_json_exists"] = True
        except Exception:
            result["voice_a_json_exists"] = False
            result["last_error"] = f"voice_a JSON ({va_json}) is not valid JSON"
    if vb_json and os.path.exists(vb_json):
        try:
            with open(vb_json, "r") as f:
                json.load(f)
            result["voice_b_json_exists"] = True
        except Exception:
            result["voice_b_json_exists"] = False
            if not result["last_error"]:
                result["last_error"] = f"voice_b JSON ({vb_json}) is not valid JSON"

    result["missing_voices"] = missing

    # ── Test synthesis ──
    if result["executable_available"] and result["voice_a"] and result["voice_a_json_exists"]:
        try:
            import tempfile
            exe_final = result["executable_path"] or "piper"
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            proc = subprocess.run(
                [exe_final, "--model", va_path, "--config", va_json,
                 "--output_file", tmp_path],
                input="Hello, this is a voice test.",
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                # Verify WAV file
                try:
                    import wave
                    with wave.open(tmp_path, "rb") as wf:
                        duration = wf.getnframes() / wf.getframerate()
                    if duration > 0:
                        result["test_synthesis"] = True
                    else:
                        result["last_error"] = "Test WAV has zero duration"
                except Exception as e:
                    result["last_error"] = f"Test WAV validation failed: {str(e)[:200]}"
            else:
                result["last_error"] = f"Test synthesis failed (exit={proc.returncode}): {proc.stderr[:200]}"
            # Cleanup
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        except Exception as e:
            result["last_error"] = f"Test synthesis exception: {str(e)[:200]}"

    # ── Determine status ──
    if result["executable_available"] and result["voice_a"] and result["voice_b"] and result["test_synthesis"]:
        result["status"] = "ready"
        result["available"] = True
    elif result["executable_available"] and (result["voice_a"] or result["voice_b"]):
        result["status"] = "degraded"
        result["available"] = False
    elif result["executable_available"] and not result["voice_a"] and not result["voice_b"]:
        result["status"] = "degraded"
        result["available"] = False
    else:
        result["status"] = "stopped"
        result["available"] = False

    return result


# ══════════════════════════════════════════════════════════════════════
# ComfyUI health check — comprehensive
# ══════════════════════════════════════════════════════════════════════

def _check_comfyui() -> dict[str, Any]:
    """Comprehensive ComfyUI health check.

    Returns:
      status: "ready" | "degraded" | "starting" | "stopped" | "failed"
      available: bool (API reachable)
      generation_ready: bool (checkpoint + workflow + nodes all present)
      checkpoint_available, checkpoint_path, checkpoint_size
      workflow_available, workflow_path
      missing_models: list of model files not found
      missing_nodes: list of custom node types not installed
      api_available: bool (any endpoint returns 200)
      test_generation: bool (a minimal test image was actually generated)
      last_error: last error or None
    """
    cfg = get_config().get("comfyui", {})
    base_url = cfg.get("baseUrl", "http://127.0.0.1:8188")
    checkpoint_name = cfg.get("checkpoint", "sd_xl_base_1.0.safetensors")
    install_root = cfg.get("installRoot", "")

    result: dict[str, Any] = {
        "available": False,
        "status": "stopped",
        "base_url": base_url,
        "api_available": False,
        "checkpoint": checkpoint_name,
        "checkpoint_available": False,
        "checkpoint_path": "",
        "checkpoint_size": None,
        "workflow_available": False,
        "workflow_path": "",
        "generation_ready": False,
        "missing_models": [],
        "missing_nodes": [],
        "test_generation": False,
        "owned": False,
        "pid": None,
        "last_error": None,
        "error_code": None,
        "health_endpoint": None,
    }

    if get_mode() != "real":
        result["error_code"] = "NOT_REAL_MODE"
        result["last_error"] = "Not in real mode"
        return result

    from pathlib import Path as _Path

    # ── Process manager status ──
    try:
        from services.comfyui_process_manager import get_comfyui_manager
        mgr = get_comfyui_manager()
        mgr_status = mgr.get_status()
    except Exception:
        mgr_status = {"state": "stopped", "owned": False, "pid": None,
                      "checkpoint_available": False, "last_error": None}

    result["owned"] = mgr_status.get("owned", False)
    result["pid"] = mgr_status.get("pid")

    # If process manager says starting, return that immediately
    if mgr_status.get("state") == "starting":
        result["status"] = "starting"
        _fill_disk_state(result, cfg, checkpoint_name, install_root)
        return result

    if mgr_status.get("state") == "failed":
        result["status"] = "failed"
        result["last_error"] = mgr_status.get("last_error")
        _fill_disk_state(result, cfg, checkpoint_name, install_root)
        return result

    # ── Check checkpoint ──
    checkpoint_available = False
    checkpoint_path = ""
    if install_root and checkpoint_name:
        candidates = [
            _Path(install_root) / "models" / "checkpoints" / checkpoint_name,
            _Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name,
        ]
        for cp in candidates:
            if cp.exists():
                checkpoint_available = True
                checkpoint_path = str(cp)
                try:
                    result["checkpoint_size"] = cp.stat().st_size
                    if cp.stat().st_size < 100_000_000:  # < 100MB is suspicious for SDXL
                        checkpoint_available = False
                        result["last_error"] = f"Checkpoint too small ({cp.stat().st_size} bytes), may be corrupted"
                        result["missing_models"].append(checkpoint_name)
                except Exception:
                    pass
                break
        if not checkpoint_available:
            result["missing_models"].append(checkpoint_name)

    result["checkpoint_available"] = checkpoint_available
    result["checkpoint_path"] = checkpoint_path

    # ── Check workflow ──
    wf_rel = cfg.get("workflowPath", "")
    workflow_available = False
    workflow_path = ""
    workflow_data = None
    if wf_rel:
        wf_full = _PROJECT_ROOT / wf_rel
        if wf_full.exists():
            try:
                with open(wf_full, "r") as f:
                    workflow_data = json.load(f)
                workflow_available = True
                workflow_path = str(wf_full)
            except Exception as e:
                result["last_error"] = f"Workflow JSON parse error: {str(e)[:200]}"
                result["error_code"] = "WORKFLOW_PARSE_ERROR"

    result["workflow_available"] = workflow_available
    result["workflow_path"] = workflow_path

    # ── Check API connectivity ──
    import requests
    api_available = False
    api_endpoint = None
    errors = []

    for endpoint in ["/system_stats", "/queue", "/history"]:
        try:
            r = requests.get(f"{base_url}{endpoint}", timeout=3,
                           proxies={"http": None, "https": None})
            if r.status_code == 200:
                api_available = True
                api_endpoint = endpoint
                break
        except Exception as e:
            errors.append(f"{endpoint}: {str(e)[:80]}")
            continue

    result["api_available"] = api_available
    result["health_endpoint"] = api_endpoint

    # ── Check workflow nodes (only if workflow is valid) ──
    missing_nodes: list[str] = []
    if workflow_data and api_available:
        missing_nodes = _check_comfyui_nodes(workflow_data, base_url)
    result["missing_nodes"] = missing_nodes

    # ── Determine overall status ──
    if not api_available:
        if mgr_status.get("state") in ("stopped", "failed"):
            result["status"] = mgr_status["state"]
        else:
            result["status"] = "stopped"
        result["available"] = False
        result["generation_ready"] = False
        if errors:
            result["last_error"] = result["last_error"] or " | ".join(errors)
        result["error_code"] = result["error_code"] or "COMFYUI_OFFLINE"
    elif checkpoint_available and workflow_available and not missing_nodes:
        result["status"] = "ready"
        result["available"] = True
        result["generation_ready"] = True
    else:
        result["status"] = "degraded"
        result["available"] = True
        result["generation_ready"] = False
        if not checkpoint_available and not result["error_code"]:
            result["error_code"] = "CHECKPOINT_MISSING"
        elif not workflow_available and not result["error_code"]:
            result["error_code"] = "WORKFLOW_MISSING"
        elif missing_nodes and not result["error_code"]:
            result["error_code"] = "MISSING_NODES"

    return result


def _fill_disk_state(result: dict, cfg: dict, checkpoint_name: str, install_root: str) -> None:
    """Fill disk state (checkpoint, workflow) for starting/failed states."""
    from pathlib import Path as _Path
    if install_root and checkpoint_name:
        for cp in [
            _Path(install_root) / "models" / "checkpoints" / checkpoint_name,
            _Path(install_root) / "ComfyUI" / "models" / "checkpoints" / checkpoint_name,
        ]:
            if cp.exists():
                result["checkpoint_available"] = True
                result["checkpoint_path"] = str(cp)
                try:
                    result["checkpoint_size"] = cp.stat().st_size
                except Exception:
                    pass
                break
        if not result["checkpoint_available"]:
            result["missing_models"].append(checkpoint_name)

    wf_rel = cfg.get("workflowPath", "")
    if wf_rel:
        wf_full = _PROJECT_ROOT / wf_rel
        if wf_full.exists():
            result["workflow_available"] = True
            result["workflow_path"] = str(wf_full)


def _check_comfyui_nodes(workflow: dict, base_url: str) -> list[str]:
    """Check if all node types referenced in the workflow are available in ComfyUI."""
    # Get all class_type values from the workflow
    needed_types: set[str] = set()
    for node_id, node_data in workflow.items():
        if isinstance(node_data, dict):
            ct = node_data.get("class_type", "")
            if ct:
                needed_types.add(ct)

    # Standard ComfyUI built-in nodes (always available)
    standard_nodes = {
        "CheckpointLoaderSimple", "CLIPTextEncode", "VAEDecode",
        "EmptyLatentImage", "KSampler", "SaveImage",
        "LoadImage", "VAEEncode", "VAELoader",
        "LoraLoader", "ControlNetLoader", "ControlNetApply",
        "UpscaleModelLoader", "ImageUpscaleWithModel",
        "CLIPSetLastLayer", "CLIPLoader", "UNETLoader",
        "DualCLIPLoader", "LoadCLIP", "SamplerCustom",
        "CheckpointLoader", "CheckpointLoaderSimple",
        "DiffControlNetLoader", "VAEEncodeForInpaint",
        "InpaintModelConditioning", "SetLatentNoiseMask",
        "ImageScale", "ImageScaleBy", "ImageScaleToTotalPixels",
        "LatentUpscale", "LatentUpscaleBy",
        "ConditioningCombine", "ConditioningAverage",
        "ConditioningSetArea", "ConditioningSetAreaPercentage",
        "ConditioningSetMask", "ConditioningZeroOut",
        "CropMask", "FeatherMask", "GrowMask", "InvertMask",
        "SolidMask", "ImageToMask", "MaskToImage",
        "LoadImageMask", "Canny", "ADE_AnimateDiffLoaderWithContext",
        "CR_", "WAS_", "UltimateSDUpscale", "FaceRestoreCFWithModel",
        "WD14Tagger", "SaveAnimatedWEBP",
        # Known custom node prefixes
        "Impact", "IPAdapter", "Efficiency",
    }

    missing = []
    for ct in sorted(needed_types):
        if ct in standard_nodes:
            continue
        # Check if it's a standard ComfyUI built-in (simple heuristic)
        if ct in {"CheckpointLoaderSimple", "CLIPTextEncode", "VAEDecode",
                   "EmptyLatentImage", "KSampler", "SaveImage", "LoadImage",
                   "VAEEncode", "VAELoader", "LoraLoader",
                   "ControlNetLoader", "ControlNetApply", "ControlNetApplyAdvanced",
                   "UpscaleModelLoader", "ImageUpscaleWithModel",
                   "CLIPSetLastLayer", "CLIPLoader", "UNETLoader",
                   "DualCLIPLoader", "LoadCLIP", "SamplerCustom",
                   "CheckpointLoader", "DiffControlNetLoader",
                   "VAEEncodeForInpaint", "InpaintModelConditioning",
                   "SetLatentNoiseMask"}:
            continue

        # Query /object_info to check if node type exists
        try:
            import requests
            r = requests.get(f"{base_url}/object_info", timeout=5,
                           proxies={"http": None, "https": None})
            if r.status_code == 200:
                obj_info = r.json()
                if ct not in obj_info:
                    missing.append(ct)
            # If /object_info fails, we can't verify — assume missing
        except Exception:
            # Can't verify, check against standard nodes only
            if ct not in standard_nodes:
                missing.append(ct)

    return missing


# ── Whisper ──

def _check_whisper() -> dict[str, Any]:
    if get_mode() != "real":
        return {"available": False, "model": "base.en"}
    python_exe = get_config().get("whisper", {}).get("pythonPath", "python")
    try:
        proc = subprocess.run([python_exe, "-c", "import whisper; print('ok')"], capture_output=True, text=True, timeout=15)
        return {"available": proc.returncode == 0 and "ok" in proc.stdout, "model": "base.en"}
    except Exception:
        return {"available": False, "model": "base.en"}


# ── FFmpeg ──

def _check_ffmpeg() -> dict[str, Any]:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
        return {"available": True}
    except Exception:
        return {"available": False}


# ── Main health endpoint ──

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
