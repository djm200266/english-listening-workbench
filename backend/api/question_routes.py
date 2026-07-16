"""Question generation and retrieval endpoints."""

from __future__ import annotations

import threading
from fastapi import APIRouter, HTTPException

from config import get_mode
from models import TaskStatus, AssetStatus

router = APIRouter(prefix="/api/v1/tasks", tags=["questions"])

# Simple in-memory lock per task_id to prevent duplicate generation
_gen_locks: dict[str, threading.Lock] = {}
_gen_lock_mutex = threading.Lock()


def _get_lock(task_id: str) -> threading.Lock:
    with _gen_lock_mutex:
        if task_id not in _gen_locks:
            _gen_locks[task_id] = threading.Lock()
        return _gen_locks[task_id]


@router.get("/{task_id}/questions")
def get_questions(task_id: str):
    """Get existing questions for a task."""
    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "message": f"Task {task_id} not found."})
    if task.questions is None:
        raise HTTPException(status_code=404, detail={"error_code": "QUESTION_NOT_GENERATED", "message": "题目尚未生成。"})
    return task.questions.model_dump()


@router.get("/{task_id}/questions/status")
def get_question_status(task_id: str):
    """Get question generation status."""
    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})
    qs = task.questions
    if qs is None:
        return {"task_id": task_id, "question_status": "not_generated"}
    return {
        "task_id": task_id, "question_status": qs.generation_status.value,
        "question_count": len(qs.questions) if qs.questions else 0,
        "script_version": qs.question_source_script_version,
    }


@router.post("/{task_id}/questions/generate")
def generate_questions_endpoint(task_id: str):
    """Generate listening comprehension questions for a confirmed script."""
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={"error_code": "NOT_REAL_MODE"})

    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    from services.question_service import generate_questions
    from services.ollama_client import OllamaError

    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "message": f"任务 {task_id} 不存在。"})
    if task.script is None:
        raise HTTPException(status_code=404, detail={"error_code": "SCRIPT_NOT_FOUND", "message": "该任务尚未生成脚本。"})
    if task.script.status != "confirmed":
        raise HTTPException(status_code=409, detail={"error_code": "SCRIPT_NOT_CONFIRMED", "message": "脚本未确认，无法生成题目。"})

    # Check if already successfully generated for this script version
    if task.questions and task.questions.question_source_script_version == task.script.script_version and \
       task.questions.generation_status == AssetStatus.SUCCESS:
        return {"task_id": task_id, "question_status": "generated", "questions": task.questions.model_dump()}

    lock = _get_lock(task_id)
    if not lock.acquire(blocking=False):
        return {"task_id": task_id, "question_status": "generating"}

    try:
        # Double-check after acquiring lock
        task2 = svc.get_task(task_id)
        if task2 and task2.questions and task2.questions.generation_status == AssetStatus.SUCCESS:
            return {"task_id": task_id, "question_status": "generated", "questions": task2.questions.model_dump()}

        # Mark as generating with current script version
        ver = task2.script.script_version if task2 and task2.script else "v1.0"
        empty_qs = __import__('models').QuestionSet(
            question_set_id=f"QSET_{task_id}",
            generation_status=AssetStatus.GENERATING,
            question_source_script_version=ver,
        )
        task2.questions = empty_qs
        svc.save_task(task2)

        # Generate
        qset = generate_questions(task2.config, task2.script, task_id)
        task2.questions = qset
        svc.save_task(task2)

        # Save to assets (non-fatal)
        try:
            _save_questions_asset(task_id, qset)
        except Exception as asset_err:
            import traceback
            traceback.print_exc()

        return {"task_id": task_id, "question_status": "generated", "questions": qset.model_dump()}
    except OllamaError as e:
        err_msg = str(e)[:300]
        _mark_failed(svc, task_id, getattr(e, 'error_code', 'OLLAMA_ERROR'), err_msg)
        raise HTTPException(status_code=503, detail={"error_code": getattr(e, 'error_code', 'OLLAMA_ERROR'), "message": err_msg})
    except ValueError as e:
        err_msg = str(e)[:300]
        _mark_failed(svc, task_id, "QUESTION_SCHEMA_VALIDATION_FAILED", err_msg)
        raise HTTPException(status_code=422, detail={"error_code": "QUESTION_SCHEMA_VALIDATION_FAILED", "message": err_msg})
    except Exception as e:
        import traceback, sys
        err_msg = str(e)[:300]
        tb = traceback.format_exc()
        # Write to a dedicated error log
        err_log = __import__('pathlib').Path(__file__).parent.parent.parent / "logs" / "runtime" / "question-api-error.log"
        err_log.parent.mkdir(parents=True, exist_ok=True)
        with open(err_log, "a", encoding="utf-8") as ef:
            ef.write(f"\n=== {__import__('datetime').datetime.now().isoformat()} task={task_id} ===\n{tb}\n")
        _mark_failed(svc, task_id, "QUESTION_GENERATION_FAILED", err_msg)
        raise HTTPException(status_code=500, detail={"error_code": "QUESTION_GENERATION_FAILED", "message": err_msg})
    finally:
        lock.release()


def _mark_failed(svc, task_id: str, code: str, msg: str):
    task = svc.get_task(task_id)
    if task:
        task.questions = __import__('models').QuestionSet(
            question_set_id=f"QSET_{task_id}",
            generation_status=AssetStatus.FAILED,
            question_source_script_version=task.script.script_version if task.script else "v1.0",
            model_name=code,  # store error_code in model_name for diagnostics
            generation_latency_ms=0,
        )
        svc.save_task(task)


def _save_questions_asset(task_id: str, qset):
    from pathlib import Path
    from config import get_config
    from datetime import datetime, timezone
    root = get_config().get("assets", {}).get("rootDir", "storage")
    qdir = Path(root) / task_id / "questions"
    qdir.mkdir(parents=True, exist_ok=True)
    import json
    (qdir / "questions_v1.json").write_text(qset.model_dump_json(indent=2), encoding="utf-8")
    meta = {"task_id": task_id, "count": len(qset.questions), "generated_at": datetime.now(timezone.utc).isoformat()}
    (qdir / "questions_v1_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
