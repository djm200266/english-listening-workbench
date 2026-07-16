"""Script generation and confirmation endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from config import get_mode
from models import TaskConfig, TaskStatus
from services.ollama_client import OllamaError, OllamaErrorCode

router = APIRouter(prefix="/api/v1/script", tags=["script"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Map Ollama error codes to HTTP status + user messages
OLLAMA_ERROR_MAP = {
    OllamaErrorCode.OFFLINE: (503, "Ollama 服务未启动，无法生成脚本。"),
    OllamaErrorCode.MODEL_NOT_FOUND: (503, "未找到模型 qwen3:4b-instruct。"),
    OllamaErrorCode.TIMEOUT: (504, "模型生成超时，请稍后重试或检查模型负载。"),
    OllamaErrorCode.HTTP_ERROR: (502, "Ollama 接口返回异常。"),
    OllamaErrorCode.INVALID_RESPONSE: (502, "Ollama 返回异常响应。"),
    OllamaErrorCode.EMPTY_RESPONSE: (502, "Ollama 返回空内容。"),
}


@router.post("/generate")
def generate_script_endpoint(config: TaskConfig):
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "脚本生成仅在 Real 模式下可用。",
        })

    from services.script_service import generate_script
    from services import TaskService
    from repositories import JsonTaskRepository
    from api import get_service

    try:
        svc = get_service()
    except AssertionError:
        repo = JsonTaskRepository()
        svc = TaskService(repo)

    task = svc.create_task(config)

    try:
        result = generate_script(config, task.task_id)
    except OllamaError as e:
        task.status = TaskStatus.FAILED
        svc.save_task(task)
        status, msg = OLLAMA_ERROR_MAP.get(e.error_code, (502, "Ollama 调用失败。"))
        raise HTTPException(status_code=status, detail={
            "error_code": e.error_code,
            "message": msg,
            "detail": str(e)[:300],
        })
    except ValueError as e:
        task.status = TaskStatus.FAILED
        svc.save_task(task)
        raise HTTPException(status_code=502, detail={
            "error_code": "MODEL_OUTPUT_VALIDATION_FAILED",
            "message": "模型已正常生成内容，但输出格式不符合脚本 Schema，系统修复失败。",
            "detail": str(e)[:300],
            "retry_count": 1,
        })

    task.script = result.script
    task.status = TaskStatus.DRAFT

    # Populate effective vocabulary/patterns from model output
    task.config.effective_vocabulary = result.script.used_vocabulary
    task.config.effective_target_patterns = result.script.used_patterns

    # Track constraint source: user-provided vs system auto-selected
    if not config.required_vocabulary:
        task.config.vocabulary_constraint_source = "auto"
    if not config.target_patterns:
        task.config.target_pattern_source = "auto"

    svc.save_task(task)

    return {
        "task": task.model_dump(),
        "meta": {
            "model_name": result.model_name, "model_version": result.model_version,
            "prompt_version": result.prompt_version,
            "generation_latency_ms": result.generation_latency_ms,
            "retry_count": result.retry_count,
        },
    }


from pydantic import BaseModel


class ConfirmRequest(BaseModel):
    task_id: str


@router.post("/confirm")
def confirm_script_endpoint(req: ConfirmRequest):
    task_id = req.task_id
    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository

    try:
        svc = get_service()
    except AssertionError:
        repo = JsonTaskRepository()
        svc = TaskService(repo)
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "TASK_NOT_FOUND", "message": f"任务 {task_id} 不存在。",
        })
    if task.script is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "SCRIPT_NOT_FOUND", "message": "该任务尚未生成脚本。",
        })

    now = _now_iso()
    task.script.status = "confirmed"
    task.script.confirmed_at = now

    if task.image and task.image.image_source_script_version != task.script.script_version:
        task.image.is_outdated = True
    if task.audio and task.audio.audio_source_script_version != task.script.script_version:
        task.audio.is_outdated = True
        task.audio.generation_status = "outdated"  # type: ignore
    if task.questions and task.questions.question_source_script_version != task.script.script_version:
        task.questions.is_outdated = True
        task.questions.generation_status = "outdated"  # type: ignore

    svc.save_task(task)

    # Auto-trigger question generation in background
    import threading, traceback
    def _gen_questions():
        try:
            from services.question_service import generate_questions
            from models import AssetStatus
            qset = generate_questions(task.config, task.script, task_id)
            t2 = svc.get_task(task_id)
            if t2:
                t2.questions = qset
                svc.save_task(t2)
        except Exception as e:
            # Log the real error and mark failed
            try:
                import sys
                tb = traceback.format_exc()
                error_log = Path(__file__).parent.parent.parent / "logs" / "runtime" / "question-daemon-error.log"
                error_log.parent.mkdir(parents=True, exist_ok=True)
                with open(error_log, "a", encoding="utf-8") as ef:
                    ef.write(f"\n=== {datetime.now(timezone.utc).isoformat()} task={task_id} ===\n")
                    ef.write(f"ERROR: {e}\n{tb}\n")
                # Mark question as failed so frontend can show error
                t3 = svc.get_task(task_id)
                if t3:
                    t3.questions = models.QuestionSet(
                        question_set_id=f"QSET_{task_id}",
                        generation_status=models.AssetStatus.FAILED,
                        question_source_script_version=task.script.script_version,
                    )
                    svc.save_task(t3)
            except Exception:
                pass
    from pathlib import Path
    from datetime import datetime, timezone
    import models
    t = threading.Thread(target=_gen_questions, daemon=True)
    t.start()

    return {
        "task_id": task_id, "script_version": task.script.script_version,
        "status": task.script.status, "confirmed_at": now,
    }
