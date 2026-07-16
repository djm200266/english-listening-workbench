"""Configuration loader with environment variable override for Cloud Studio."""

from __future__ import annotations

import json, os
from pathlib import Path
from typing import Any

_CONFIG: dict[str, Any] = {}
_APP_ENV: str = os.environ.get("APP_ENV", "")


def is_cloudstudio() -> bool:
    """True when running inside Tencent Cloud Studio."""
    return _APP_ENV == "cloudstudio"


def load_config(path: str | None = None) -> dict[str, Any]:
    global _CONFIG
    if path is None:
        path = str(Path(__file__).parent.parent / "config.json")
    with open(path, "r", encoding="utf-8-sig") as f:
        _CONFIG = json.load(f)

    # ── Cloud Studio env-var overrides ──
    if is_cloudstudio():
        _apply_cloudstudio_overrides()

    return _CONFIG


def _apply_cloudstudio_overrides() -> None:
    """Override paths and URLs from environment variables (Cloud Studio / Linux).
    Environment variable values take priority over config.json.
    Windows-specific paths are explicitly wiped.
    """
    env = os.environ

    # Base directories
    data_dir = env.get("DATA_DIR", "/workspace/data")
    asset_dir = env.get("ASSET_DIR", f"{data_dir}/assets")
    export_dir = env.get("EXPORT_DIR", f"{data_dir}/exports")

    # Service URLs
    ollama_url = env.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    comfyui_url = env.get("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    comfyui_dir = env.get("COMFYUI_DIR", "/workspace/ComfyUI")
    comfyui_workflow_dir = env.get("COMFYUI_WORKFLOW_DIR", "/workspace/workflows")
    piper_model_dir = env.get("PIPER_MODEL_DIR", "/workspace/models/piper")
    whisper_model_dir = env.get("WHISPER_MODEL_DIR", "/workspace/models/whisper")

    # ── Override sections ──
    # Backend: listen on all interfaces
    _CONFIG.setdefault("backend", {})["host"] = "0.0.0.0"

    # Ollama
    _CONFIG.setdefault("ollama", {})["baseUrl"] = ollama_url

    # ComfyUI — fully replace Windows paths with Linux defaults
    cf = _CONFIG.setdefault("comfyui", {})
    cf["baseUrl"] = comfyui_url
    cf["installRoot"] = comfyui_dir
    cf["pythonExe"] = ""        # explicitly blank — not python_embeded on Windows
    cf["mainPy"] = f"{comfyui_dir}/main.py"
    cf["startScript"] = ""      # explicitly blank — not run_nvidia_gpu.bat
    cf["workflowPath"] = env.get("COMFYUI_WORKFLOW_PATH",
        cf.get("workflowPath", "backend/workflows/sdxl_cartoon_api.fixed.json"))
    cf["startupTimeoutSec"] = int(env.get("COMFYUI_STARTUP_TIMEOUT", "300"))
    # Auto-start only if ComfyUI is actually installed
    cf["autoStart"] = (
        env.get("COMFYUI_AUTO_START", "true").lower() == "true"
        and os.path.isdir(comfyui_dir)
        and os.path.isfile(f"{comfyui_dir}/main.py")
    )
    # Wipe any lingering Windows paths from config.json
    cf.pop("startScript", None)

    # Piper — Linux paths
    piper_cfg = _CONFIG.setdefault("piper", {})
    piper_cfg["voice_dir"] = piper_model_dir
    piper_cfg["executable"] = env.get("PIPER_EXECUTABLE", "piper")

    # Whisper — Linux paths
    whisper_cfg = _CONFIG.setdefault("whisper", {})
    whisper_cfg["pythonPath"] = env.get("WHISPER_PYTHON_PATH", "python3")

    # Assets
    assets_cfg = _CONFIG.setdefault("assets", {})
    assets_cfg["rootDir"] = asset_dir

    # Export
    _CONFIG.setdefault("export", {})["outputDir"] = export_dir


def get_config() -> dict[str, Any]:
    if not _CONFIG:
        return load_config()
    return _CONFIG


def get_mode() -> str:
    return get_config().get("mode", "mock")
