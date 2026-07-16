"""Question generation and retrieval endpoints with async job tracking."""

from __future__ import annotations

import threading, time
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException

from config import get_mode, get_config
from models import TaskStatus, AssetStatus

router = APIRouter(prefix="/api/v1/tasks", tags=["questions"])

# ── In-memory job tracker ──
# { task_id: { "status": "generating"|"generated"|"failed",
#              "started_at": str, "elapsed_seconds": int,
#              "model": str, "last_error": str|null, "retry_count": int } }
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# Generation lock per task_id to prevent duplicate runs
_gen_locks: dict[str, threading.Lock] = {}
_gen_lock_mutex = threading.Lock()

MAX_GENERATION_SEC = 120


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_lock(task_id: str) -> threading.Lock:
    with _gen_lock_mutex:
        if task_id not in _gen_locks:
            _gen_locks[task_id] = threading.Lock()
        return _gen_locks[task_id]


def _update_job(task_id: str, **kwargs):
    with _jobs_lock:
        if task_id not in _jobs:
            _jobs[task_id] = {}
        _jobs[task_id].update(kwargs)


# ── GET existing questions ──

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


# ── GET question generation status ──

@router.get("/{task_id}/questions/status")
def get_question_status(task_id: str):
    """Get question generation status with job tracking info."""
    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})

    qs = task.questions

    # Check in-memory job tracker for active generation
    with _jobs_lock:
        job = _jobs.get(task_id)

    if job and job.get("status") == "generating":
        started = job.get("started_at", "")
        elapsed = 0
        if started:
            try:
                elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())
            except Exception:
                pass
        # If exceeded max time, mark as failed
        if elapsed > MAX_GENERATION_SEC:
            job["status"] = "failed"
            job["last_error"] = f"题目生成超时（>{MAX_GENERATION_SEC}秒）"
            return {
                "task_id": task_id,
                "status": "failed",
                "elapsed_seconds": elapsed,
                "model": job.get("model", ""),
                "last_error": job["last_error"],
            }
        return {
            "task_id": task_id,
            "status": "generating",
            "elapsed_seconds": elapsed,
            "model": job.get("model", ""),
            "last_error": None,
        }

    if job and job.get("status") == "failed":
        return {
            "task_id": task_id,
            "status": "failed",
            "elapsed_seconds": job.get("elapsed_seconds", 0),
            "model": job.get("model", ""),
            "last_error": job.get("last_error", ""),
        }

    if qs is None:
        return {"task_id": task_id, "status": "not_generated", "elapsed_seconds": 0, "model": "", "last_error": None}

    return {
        "task_id": task_id,
        "status": qs.generation_status.value if qs.generation_status else "unknown",
        "question_count": len(qs.questions) if qs.questions else 0,
        "script_version": qs.question_source_script_version,
        "model": qs.model_name or "",
        "elapsed_seconds": qs.generation_latency_ms // 1000 if qs.generation_latency_ms else 0,
        "last_error": None,
    }


# ── POST generate questions ──

@router.post("/{task_id}/questions/generate")
def generate_questions_endpoint(task_id: str):
    """Generate listening comprehension questions for a confirmed script.

    Returns 202 if generation is started in background (async pattern).
    Returns 200 with questions if already generated for current script version.
    Returns 409 if generation is already running.
    Returns 503 if Ollama is offline.
    """
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={"error_code": "NOT_REAL_MODE"})

    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    from services.question_service import generate_questions
    from services.ollama_client import OllamaClient, OllamaError, OllamaErrorCode

    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "TASK_NOT_FOUND",
            "message": f"任务 {task_id} 不存在。",
        })
    if task.script is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "SCRIPT_NOT_FOUND",
            "message": "该任务尚未生成脚本。",
        })
    if task.script.status != "confirmed":
        raise HTTPException(status_code=409, detail={
            "error_code": "SCRIPT_NOT_CONFIRMED",
            "message": "脚本未确认，无法生成题目。",
        })

    # ── Pre-check: Ollama available? ──
    try:
        ollama_client = OllamaClient()
        health = ollama_client.health_check()
    except Exception as e:
        raise HTTPException(status_code=503, detail={
            "error_code": "OLLAMA_OFFLINE",
            "message": f"Ollama 服务不可用: {e}",
        })

    if not health.get("available"):
        raise HTTPException(status_code=503, detail={
            "error_code": "OLLAMA_OFFLINE",
            "message": f"Ollama 服务离线。请先启动 Ollama: ollama serve",
        })

    if not health.get("model_present"):
        model_name = health.get("model", "unknown")
        raise HTTPException(status_code=503, detail={
            "error_code": "MODEL_NOT_FOUND",
            "message": f"模型 {model_name} 未安装。请先运行: ollama pull {model_name}",
        })

    # ── Already generated for this script version? ──
    if task.questions and task.questions.question_source_script_version == task.script.script_version and \
       task.questions.generation_status == AssetStatus.SUCCESS:
        return {
            "task_id": task_id,
            "question_status": "generated",
            "questions": task.questions.model_dump(),
        }

    # ── Already running? ──
    lock = _get_lock(task_id)
    if not lock.acquire(blocking=False):
        # Check how long it's been running
        with _jobs_lock:
            job = _jobs.get(task_id, {})
        started = job.get("started_at", "")
        elapsed = 0
        if started:
            try:
                elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds())
            except Exception:
                pass
        if elapsed > MAX_GENERATION_SEC:
            # Stale job — force release and allow retry
            lock.release()  # It was never actually acquired, need to recreate
            with _gen_lock_mutex:
                _gen_locks[task_id] = threading.Lock()
            new_lock = _gen_locks[task_id]
            if not new_lock.acquire(blocking=False):
                raise HTTPException(status_code=409, detail={
                    "error_code": "GENERATION_IN_PROGRESS",
                    "message": f"题目生成正在运行中（已等待{elapsed}秒）。请稍后再试。",
                })
            lock = new_lock
        else:
            raise HTTPException(status_code=409, detail={
                "error_code": "GENERATION_IN_PROGRESS",
                "message": f"题目生成正在运行中（已等待{elapsed}秒）。请稍后再试。",
            })

    # ── Start generation ──
    job_model = health.get("model", "unknown")
    _update_job(task_id,
        status="generating",
        started_at=_now_iso(),
        elapsed_seconds=0,
        model=job_model,
        last_error=None,
        retry_count=0,
    )

    try:
        # Double-check after acquiring lock
        task2 = svc.get_task(task_id)
        if task2 and task2.questions and task2.questions.question_source_script_version == task2.script.script_version and \
           task2.questions.generation_status == AssetStatus.SUCCESS:
            _update_job(task_id, status="generated")
            return {
                "task_id": task_id,
                "question_status": "generated",
                "questions": task2.questions.model_dump(),
            }

        # Mark as generating
        ver = task2.script.script_version if task2 and task2.script else "v1.0"
        empty_qs = __import__('models').QuestionSet(
            question_set_id=f"QSET_{task_id}",
            generation_status=AssetStatus.GENERATING,
            question_source_script_version=ver,
        )
        task2.questions = empty_qs
        svc.save_task(task2)

        _update_job(task_id,
            status="generating",
            started_at=_now_iso(),
            model=job_model,
        )

        # Generate with timeout
        t0 = time.perf_counter()

        # Use a thread to enforce timeout
        result_container: list = []
        error_container: list = []

        def _run_generation():
            try:
                qset = generate_questions(task2.config, task2.script, task_id)
                result_container.append(qset)
            except Exception as e:
                error_container.append(e)

        gen_thread = threading.Thread(target=_run_generation, daemon=True)
        gen_thread.start()
        gen_thread.join(timeout=MAX_GENERATION_SEC)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)

        if gen_thread.is_alive():
            # Timeout — mark as failed, thread continues but we return error
            _mark_failed(svc, task_id, "QUESTION_GENERATION_TIMEOUT",
                        f"题目生成超时（>{MAX_GENERATION_SEC}秒）")
            _update_job(task_id, status="failed",
                       elapsed_seconds=MAX_GENERATION_SEC,
                       last_error=f"题目生成超时（>{MAX_GENERATION_SEC}秒）")
            raise HTTPException(status_code=504, detail={
                "error_code": "QUESTION_GENERATION_TIMEOUT",
                "message": f"题目生成超时（>{MAX_GENERATION_SEC}秒）。请重试或减少题目数量。",
            })

        if error_container:
            e = error_container[0]
            if isinstance(e, OllamaError):
                err_msg = str(e)[:300]
                _mark_failed(svc, task_id, getattr(e, 'error_code', 'OLLAMA_ERROR'), err_msg)
                _update_job(task_id, status="failed", elapsed_seconds=elapsed_ms // 1000, last_error=err_msg)
                raise HTTPException(status_code=503, detail={
                    "error_code": getattr(e, 'error_code', 'OLLAMA_ERROR'),
                    "message": err_msg,
                })
            elif isinstance(e, ValueError):
                err_msg = str(e)[:300]
                _mark_failed(svc, task_id, "INVALID_MODEL_JSON", err_msg)
                _update_job(task_id, status="failed", elapsed_seconds=elapsed_ms // 1000, last_error=err_msg)
                raise HTTPException(status_code=422, detail={
                    "error_code": "INVALID_MODEL_JSON",
                    "message": err_msg,
                })
            else:
                err_msg = str(e)[:300]
                _mark_failed(svc, task_id, "QUESTION_GENERATION_FAILED", err_msg)
                _update_job(task_id, status="failed", elapsed_seconds=elapsed_ms // 1000, last_error=err_msg)
                raise HTTPException(status_code=500, detail={
                    "error_code": "QUESTION_GENERATION_FAILED",
                    "message": err_msg,
                })

        # Success
        qset = result_container[0]
        task2.questions = qset
        svc.save_task(task2)

        _update_job(task_id, status="generated",
                   elapsed_seconds=elapsed_ms // 1000,
                   last_error=None)

        # Save to assets (non-fatal)
        try:
            _save_questions_asset(task_id, qset)
        except Exception as asset_err:
            import traceback
            traceback.print_exc()

        return {
            "task_id": task_id,
            "question_status": "generated",
            "questions": qset.model_dump(),
        }

    except HTTPException:
        raise
    except OllamaError as e:
        err_msg = str(e)[:300]
        _mark_failed(svc, task_id, getattr(e, 'error_code', 'OLLAMA_ERROR'), err_msg)
        _update_job(task_id, status="failed", elapsed_seconds=0, last_error=err_msg)
        raise HTTPException(status_code=503, detail={
            "error_code": getattr(e, 'error_code', 'OLLAMA_ERROR'),
            "message": err_msg,
        })
    except ValueError as e:
        err_msg = str(e)[:300]
        _mark_failed(svc, task_id, "INVALID_MODEL_JSON", err_msg)
        _update_job(task_id, status="failed", elapsed_seconds=0, last_error=err_msg)
        raise HTTPException(status_code=422, detail={
            "error_code": "INVALID_MODEL_JSON",
            "message": err_msg,
        })
    except Exception as e:
        import traceback, sys
        err_msg = str(e)[:300]
        tb = traceback.format_exc()
        from pathlib import Path as _Path
        err_log = _Path(__file__).parent.parent.parent / "logs" / "runtime" / "question-api-error.log"
        err_log.parent.mkdir(parents=True, exist_ok=True)
        with open(err_log, "a", encoding="utf-8") as ef:
            ef.write(f"\n=== {datetime.now().isoformat()} task={task_id} ===\n{tb}\n")
        _mark_failed(svc, task_id, "QUESTION_GENERATION_FAILED", err_msg)
        _update_job(task_id, status="failed", elapsed_seconds=0, last_error=err_msg)
        raise HTTPException(status_code=500, detail={
            "error_code": "QUESTION_GENERATION_FAILED",
            "message": err_msg,
        })
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
