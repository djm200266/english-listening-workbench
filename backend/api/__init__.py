"""API routes for tasks."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import get_mode
from models import Task, TaskConfig, TaskListItem
from services import TaskService
from repositories import JsonTaskRepository

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])

# Singleton: injected by main.py
_task_service: TaskService | None = None


def set_task_service(svc: TaskService) -> None:
    global _task_service
    _task_service = svc


def get_service() -> TaskService:
    global _task_service
    if _task_service is None:
        repo = JsonTaskRepository()
        _task_service = TaskService(repo)
    return _task_service


@router.get("", response_model=list[TaskListItem])
def list_tasks():
    return get_service().list_tasks()


@router.post("", response_model=Task, status_code=201)
def create_task(config: TaskConfig):
    try:
        return get_service().create_task(config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str):
    task = get_service().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.put("/{task_id}", response_model=Task)
def update_task(task_id: str, config: TaskConfig):
    task = get_service().update_config(task_id, config)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


@router.delete("/{task_id}")
def delete_task(task_id: str):
    ok = get_service().delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {"ok": True}


# ── Asset validation ──

@router.get("/{task_id}/assets/validate")
def validate_task_assets(task_id: str):
    """Validate that image and audio files for a task actually exist on disk.

    Returns detailed file status — does NOT trust stored generation_status alone.
    """
    from pathlib import Path as _Path
    from config import get_config

    task = get_service().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "message": f"任务 {task_id} 不存在。"})

    assets_root = get_config().get("assets", {}).get("rootDir", "storage")
    result = {
        "task_id": task_id,
        "image": _validate_image(task, assets_root),
        "audio": _validate_audio(task, assets_root),
        "questions": _validate_questions(task, assets_root),
    }

    # Overall status
    img_ok = result["image"]["status"] == "ok"
    aud_ok = result["audio"]["status"] == "ok"
    q_ok = result["questions"]["status"] == "ok"

    if task.image and not img_ok:
        result["image"]["stored_status"] = task.image.generation_status.value if task.image.generation_status else "unknown"
    if task.audio and not aud_ok:
        result["audio"]["stored_status"] = task.audio.generation_status.value if task.audio.generation_status else "unknown"

    result["all_valid"] = (not task.image or img_ok) and (not task.audio or aud_ok) and (not task.questions or q_ok)
    return result


def _validate_image(task, assets_root: str) -> dict:
    from pathlib import Path as _Path
    result = {
        "status": "no_image",
        "file_exists": False,
        "file_path": "",
        "file_size": 0,
        "image_url": "",
        "can_open": False,
        "last_error": None,
    }

    if not task.image:
        return result

    result["image_url"] = task.image.image_url or ""

    # Resolve file path from URL
    url = task.image.image_url or ""
    for prefix in ("/media/", "/assets/"):
        if url.startswith(prefix):
            rel = url[len(prefix):]
            fp = _Path(assets_root) / rel
            if fp.exists():
                result["file_path"] = str(fp)
                result["file_exists"] = True
                result["file_size"] = fp.stat().st_size
                break

    # Also check in common locations
    if not result["file_exists"]:
        img_dir = _Path(assets_root) / task.task_id / "images"
        if img_dir.exists():
            pngs = sorted(img_dir.glob("*.png"))
            if pngs:
                fp = pngs[0]
                result["file_path"] = str(fp)
                result["file_exists"] = True
                result["file_size"] = fp.stat().st_size

    if result["file_exists"] and result["file_size"] > 0:
        # Try to open with Pillow
        try:
            from PIL import Image
            img = Image.open(result["file_path"])
            img.verify()
            result["can_open"] = True
            result["status"] = "ok"
        except Exception as e:
            result["last_error"] = f"图片无法打开: {str(e)[:200]}"
            result["status"] = "corrupted"
    elif result["file_exists"] and result["file_size"] == 0:
        result["last_error"] = "文件大小为0字节"
        result["status"] = "empty_file"
    else:
        result["last_error"] = "图片文件不存在"
        result["status"] = "file_missing"

    return result


def _validate_audio(task, assets_root: str) -> dict:
    from pathlib import Path as _Path
    result = {
        "status": "no_audio",
        "file_exists": False,
        "file_path": "",
        "file_size": 0,
        "audio_url": "",
        "duration_sec": 0,
        "mime_type": "",
        "wav_valid": False,
        "last_error": None,
    }

    if not task.audio:
        return result

    result["audio_url"] = task.audio.audio_url or ""

    # Resolve file path from URL
    url = task.audio.audio_url or ""
    for prefix in ("/media/", "/assets/"):
        if url.startswith(prefix):
            rel = url[len(prefix):]
            fp = _Path(assets_root) / rel
            if fp.exists():
                result["file_path"] = str(fp)
                result["file_exists"] = True
                result["file_size"] = fp.stat().st_size
                break

    # Also check common locations
    if not result["file_exists"]:
        assets_dir = _Path(assets_root) / task.task_id
        # New location: audio/ subdirectory
        wavs = list((assets_dir / "audio").glob("dialogue_*.wav"))
        if not wavs:
            # Old location
            wavs = list(assets_dir.glob("dialogue_*.wav"))
        if wavs:
            fp = wavs[0]
            result["file_path"] = str(fp)
            result["file_exists"] = True
            result["file_size"] = fp.stat().st_size

    if result["file_exists"] and result["file_size"] > 0:
        # Try to read WAV header
        try:
            import wave
            with wave.open(result["file_path"], "rb") as wf:
                result["duration_sec"] = round(wf.getnframes() / wf.getframerate(), 2)
                result["wav_valid"] = True
                result["mime_type"] = "audio/wav"
            if result["duration_sec"] > 0:
                result["status"] = "ok"
            else:
                result["last_error"] = "音频时长为0"
                result["status"] = "zero_duration"
        except Exception as e:
            result["last_error"] = f"WAV文件无效: {str(e)[:200]}"
            result["status"] = "corrupted"
    elif result["file_exists"] and result["file_size"] == 0:
        result["last_error"] = "文件大小为0字节"
        result["status"] = "empty_file"
    else:
        result["last_error"] = "音频文件不存在"
        result["status"] = "file_missing"

    return result


def _validate_questions(task, assets_root: str) -> dict:
    from pathlib import Path as _Path
    result = {
        "status": "no_questions",
        "json_file_exists": False,
        "question_count": 0,
        "has_options": False,
        "has_answers": False,
        "last_error": None,
    }

    if not task.questions:
        return result

    qs = task.questions
    if qs.questions and len(qs.questions) > 0:
        result["question_count"] = len(qs.questions)
        result["has_options"] = all(len(q.options) >= 4 for q in qs.questions)
        result["has_answers"] = all(q.answer in ("A", "B", "C", "D") for q in qs.questions)
        result["status"] = "ok"
    else:
        result["last_error"] = "题目列表为空"
        result["status"] = "empty"

    # Also check JSON file
    qdir = _Path(assets_root) / task.task_id / "questions"
    qfile = qdir / "questions_v1.json"
    if qfile.exists():
        result["json_file_exists"] = True
        try:
            import json
            data = json.loads(qfile.read_text(encoding="utf-8"))
            if data.get("questions"):
                result["question_count"] = max(result["question_count"], len(data["questions"]))
        except Exception:
            pass

    return result
