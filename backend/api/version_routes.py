"""Lightweight version endpoint for backend identity verification."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from config import get_mode

router = APIRouter(tags=["version"])

BUILD_ID = datetime.now(timezone.utc).strftime("build-%Y%m%d-%H%M%S")


@router.get("/api/version")
def get_version():
    return {
        "app": "english-listening-workbench",
        "mode": get_mode(),
        "version": "0.1.0",
        "build_id": BUILD_ID,
        "features": [
            "script_generation",
            "prompt_assistant",
            "image_generation",
            "audio_generation",
            "question_generation",
            "script_audio_evaluation",
            "comfyui_auto_start",
        ],
    }
