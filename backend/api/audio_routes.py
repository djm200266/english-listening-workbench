"""Audio generation, transcription, and evaluation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_mode
from models import TaskStatus

router = APIRouter(prefix="/api/v1/audio", tags=["audio"])


class AudioGenerateRequest(BaseModel):
    task_id: str
    script_version: str | None = None
    speech_rate: str = "normal"
    pause_seconds: float = 0.4


class AudioTranscribeRequest(BaseModel):
    task_id: str
    audio_path: str | None = None


class AudioEvaluateRequest(BaseModel):
    task_id: str


@router.post("/generate")
def generate_audio(req: AudioGenerateRequest):
    """
    Generate dual-voice audio from confirmed script.

    Real mode: calls Piper TTS
    Mock mode: returns mock data
    """
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "音频生成仅在 Real 模式下可用。",
        })

    from api import get_service
    from services.piper_service import generate_audio as piper_generate, build_audio_asset, PiperError
    from services import TaskService
    from repositories import JsonTaskRepository

    try:
        svc = get_service()
    except AssertionError:
        repo = JsonTaskRepository()
        svc = TaskService(repo)
    task = svc.get_task(req.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "TASK_NOT_FOUND",
            "message": f"任务 {req.task_id} 不存在。",
        })
    if task.script is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "SCRIPT_NOT_FOUND",
            "message": f"任务 {req.task_id} 尚未生成脚本。",
        })
    if task.script.status != "confirmed":
        raise HTTPException(status_code=409, detail={
            "error_code": "SCRIPT_NOT_CONFIRMED",
            "message": "脚本未确认，无法生成音频。请先确认脚本。",
        })

    try:
        result = piper_generate(
            task.script,
            req.task_id,
            speech_rate=req.speech_rate,
            pause_seconds=req.pause_seconds,
        )
    except PiperError as e:
        raise HTTPException(status_code=503 if "不存在" in str(e) else 500, detail={
            "error_code": "PIPER_ERROR",
            "message": f"音频生成失败: {e}",
        })

    audio_asset = build_audio_asset(result, req.task_id)
    task.audio = audio_asset
    svc.save_task(task)

    return {
        "task_id": req.task_id,
        "audio": audio_asset.model_dump(),
        "meta": {
            "duration_sec": result.duration_sec,
            "segment_count": result.segment_count,
            "output_path": result.output_path,
            "voice_a": result.voice_a,
            "voice_b": result.voice_b,
        },
    }


@router.post("/transcribe")
def transcribe_audio(req: AudioTranscribeRequest):
    """Transcribe audio with Whisper."""
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "语音转写仅在 Real 模式下可用。",
        })

    from api import get_service
    from services.whisper_service import transcribe, WhisperError
    from services import TaskService
    from repositories import JsonTaskRepository

    try:
        svc = get_service()
    except AssertionError:
        repo = JsonTaskRepository()
        svc = TaskService(repo)
    task = svc.get_task(req.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})
    if task.audio is None:
        raise HTTPException(status_code=404, detail={"error_code": "AUDIO_NOT_FOUND"})

    # Resolve absolute path from audio_url
    from pathlib import Path
    from config import get_config
    assets_root = get_config().get("assets", {}).get("rootDir", "storage")
    # audio_url is like "/media/G7_DIR_.../audio/dialogue_v1_0.wav"
    audio_path = ""
    if task.audio and task.audio.audio_url:
        url_path = task.audio.audio_url.replace("/media/", "").replace("/assets/", "")
        candidate = Path(assets_root) / url_path
        if candidate.exists():
            audio_path = str(candidate)

    # Fallback: find the WAV file in new audio/ subdirectory or old task root
    if not audio_path or not Path(audio_path).exists():
        assets_dir = Path(assets_root) / req.task_id
        # New location: audio/ subdirectory
        wavs = list((assets_dir / "audio").glob("dialogue_*.wav"))
        if not wavs:
            # Old location: task root directory (backward compat)
            wavs = list(assets_dir.glob("dialogue_*.wav"))
        if wavs:
            audio_path = str(wavs[0])

    if not audio_path or not Path(audio_path).exists():
        raise HTTPException(status_code=404, detail={
            "error_code": "AUDIO_FILE_MISSING",
            "message": f"音频文件不存在。请先生成音频。",
        })

    try:
        result = transcribe(audio_path, req.task_id)
    except WhisperError as e:
        raise HTTPException(status_code=503 if "not installed" in str(e).lower() or "找不到" in str(e) else 500, detail={
            "error_code": "WHISPER_ERROR",
            "message": f"转写失败: {e}",
        })

    return {
        "task_id": req.task_id,
        "text": result.text,
        "segments": result.segments[:20],
        "language": result.language,
        "asr_model": result.asr_model,
        "latency_sec": result.latency_sec,
        "transcript_path": result.transcript_path,
    }


@router.post("/evaluate")
def evaluate_audio(req: AudioEvaluateRequest):
    """
    Evaluate script-audio consistency.

    Compares normalized script text with ASR transcript.
    S3 severity on direction/location keyword conflicts.
    """
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "音频评测仅在 Real 模式下可用。",
        })

    from api import get_service
    from services.whisper_service import transcribe, WhisperError
    from services.audio_eval_service import evaluate_consistency
    from pathlib import Path
    from config import get_config
    from services import TaskService
    from repositories import JsonTaskRepository

    try:
        svc = get_service()
    except AssertionError:
        repo = JsonTaskRepository()
        svc = TaskService(repo)
    task = svc.get_task(req.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})
    if task.script is None:
        raise HTTPException(status_code=404, detail={"error_code": "SCRIPT_NOT_FOUND"})
    if task.audio is None:
        raise HTTPException(status_code=404, detail={"error_code": "AUDIO_NOT_FOUND"})

    # Get audio path (check new audio/ subdirectory first, then old location)
    assets_root = get_config().get("assets", {}).get("rootDir", "storage")
    assets_dir = Path(assets_root) / req.task_id
    wavs = list((assets_dir / "audio").glob("dialogue_*.wav"))
    if not wavs:
        wavs = list(assets_dir.glob("dialogue_*.wav"))
    if not wavs:
        raise HTTPException(status_code=404, detail={
            "error_code": "AUDIO_FILE_MISSING",
            "message": "音频文件不存在。",
        })
    audio_path = str(wavs[0])

    # Transcribe
    try:
        asr_result = transcribe(audio_path, req.task_id)
    except WhisperError as e:
        raise HTTPException(status_code=503, detail={
            "error_code": "WHISPER_ERROR",
            "message": f"转写失败: {e}",
        })

    # Build script text
    script_text = " ".join(t.text for t in task.script.dialogue)

    # Evaluate
    eval_result = evaluate_consistency(
        script_text=script_text,
        asr_text=asr_result.text,
        task_id=req.task_id,
        audio_path=audio_path,
        source_script_version=task.script.script_version,
    )

    return {
        "task_id": req.task_id,
        "normalized_script": eval_result.normalized_script[:500],
        "normalized_transcript": eval_result.normalized_transcript[:500],
        "keyword_checks": eval_result.keyword_checks,
        "missing_keywords": eval_result.missing_keywords,
        "conflicting_keywords": eval_result.conflicting_keywords,
        "script_audio_match_pass": eval_result.script_audio_match_pass,
        "severity": eval_result.severity,
        "evidence": eval_result.evidence,
    }
