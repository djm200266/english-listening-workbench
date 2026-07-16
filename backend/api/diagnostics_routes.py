"""Diagnostics endpoints — full inference checks on demand."""

from __future__ import annotations

from fastapi import APIRouter

from config import get_mode
from models import HealthResponse

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/ollama")
def diagnostics_ollama():
    """Full Ollama diagnostic: tags check + quick inference test."""
    if get_mode() != "real":
        return {"error_code": "NOT_REAL_MODE", "message": "Real mode only."}
    from services.ollama_client import OllamaClient
    return OllamaClient().diagnostic_inference()
