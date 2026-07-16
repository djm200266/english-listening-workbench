"""Evaluation endpoints: rule + semantic + visual combined evaluation."""

from __future__ import annotations

import hashlib
import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_mode

router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])

# ── In-flight progress tracking ─────────────────────────
_eval_progress: dict[str, dict] = {}
_progress_lock = threading.Lock()


class GenerateRequest(BaseModel):
    include_semantic: bool = True
    include_visual: bool = True
    force_regenerate: bool = False


def _fingerprint(task) -> str:
    """Build a fingerprint from asset versions to detect changes."""
    parts = [
        task.task_id,
        task.script.script_version if task.script else "noscript",
        task.image.image_url if task.image else "noimg",
        task.audio.audio_url if task.audio else "noaudio",
        str(len(task.questions.questions)) if task.questions and task.questions.questions else "noq",
    ]
    # Include visual-specific fields if present
    if task.evaluation and task.evaluation.visual_data:
        vd = task.evaluation.visual_data
        parts.append(vd.get("image_sha256", ""))
        parts.append(vd.get("model", ""))
        parts.append(vd.get("visual_prompt_version", ""))
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


def _check_assets(task) -> tuple[bool, list[str]]:
    missing = []
    if not (task.script and task.script.status == "confirmed"):
        missing.append("脚本(未确认)")
    if not (task.image and task.image.generation_status.value == "success"):
        missing.append("图片")
    if not (task.audio and task.audio.generation_status.value == "success"):
        missing.append("音频")
    if not (task.questions and task.questions.generation_status.value == "success"):
        missing.append("题目")
    return len(missing) == 0, missing


@router.get("/tasks/{task_id}/progress")
def get_evaluation_progress(task_id: str):
    """Get current evaluation progress stage and timing."""
    with _progress_lock:
        info = _eval_progress.get(task_id)
    if info is None:
        return {"task_id": task_id, "stage": "idle", "message": "没有正在进行的评测"}
    return info


# ── Progress helpers ────────────────────────────────────

def _set_progress(task_id: str, stage: str, message: str, elapsed_s: float = 0):
    with _progress_lock:
        _eval_progress[task_id] = {
            "task_id": task_id,
            "stage": stage,
            "message": message,
            "elapsed_s": round(elapsed_s, 1),
            "updated_at": time.time(),
        }


def _clear_progress(task_id: str):
    with _progress_lock:
        _eval_progress.pop(task_id, None)


@router.get("/tasks/{task_id}")
def get_evaluation(task_id: str):
    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})
    if task.evaluation is None:
        raise HTTPException(status_code=404, detail={"error_code": "EVALUATION_NOT_GENERATED", "message": "评测尚未生成"})
    return task.evaluation.model_dump()


@router.get("/tasks/{task_id}/status")
def get_evaluation_status(task_id: str):
    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})

    ready, missing = _check_assets(task)
    fp_current = _fingerprint(task) if ready else ""
    fp_stored = task.evaluation.asset_fingerprint if task.evaluation and hasattr(task.evaluation, "asset_fingerprint") else ""
    is_stale = bool(fp_current and fp_stored and fp_current != fp_stored)

    return {
        "task_id": task_id,
        "assets_ready": ready,
        "assets_detail": {
            "script_confirmed": bool(task.script and task.script.status == "confirmed"),
            "image_ready": bool(task.image and task.image.generation_status.value == "success"),
            "audio_ready": bool(task.audio and task.audio.generation_status.value == "success"),
            "questions_ready": bool(task.questions and task.questions.generation_status.value == "success"),
        },
        "missing": missing,
        "evaluation_status": "stale" if is_stale else ("generated" if task.evaluation else "not_generated"),
        "has_semantic": bool(task.evaluation and task.evaluation.semantic_data),
    }


@router.post("/tasks/{task_id}/generate")
def generate_evaluation(task_id: str, req: GenerateRequest = GenerateRequest()):
    """Generate evaluation: rule first, optionally semantic via Qwen."""
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={"error_code": "NOT_REAL_MODE"})

    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    from services.evaluation_service import generate_evaluation as do_rule_eval

    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})

    ready, missing = _check_assets(task)
    if not ready:
        raise HTTPException(status_code=400, detail={
            "error_code": "ASSETS_NOT_READY",
            "message": f"缺少: {', '.join(missing)}",
            "missing": missing,
        })

    fp = _fingerprint(task)
    if not req.force_regenerate and task.evaluation and not hasattr(task.evaluation, "asset_fingerprint"):
        # Check if fingerprint matches stored
        fp_stored = getattr(task.evaluation, "asset_fingerprint", "")
        if fp_stored and fp == fp_stored:
            return task.evaluation.model_dump()

    # 1. Rule evaluation
    try:
        report = do_rule_eval(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error_code": "EVAL_FAILED", "message": str(e)})

    rule_score = report.overall_score

    # 2. Semantic + Visual evaluation in PARALLEL (different models, no VRAM contention)
    import concurrent.futures
    semantic_data = None
    visual_data = None

    def _run_semantic():
        if not req.include_semantic:
            return None
        try:
            from services.semantic_evaluation_service import run_semantic_evaluation
            return run_semantic_evaluation(task)
        except Exception:
            return {"status": "unavailable", "error_code": "SEMANTIC_FAILED"}

    def _run_visual():
        if not req.include_visual:
            return None
        try:
            from services.visual_evaluation_service import evaluate_image_visual
            _set_progress(task_id, "visual_stage1", "正在分析实际图片...", 0)
            result = evaluate_image_visual(task, force_regenerate=req.force_regenerate)
            _set_progress(task_id, "visual_done", "视觉评测完成", 0)
            return result.model_dump()
        except Exception as e:
            _set_progress(task_id, "visual_failed", f"视觉评测失败: {str(e)[:100]}", 0)
            return {"status": "unavailable", "error_code": "VISUAL_FAILED", "message": str(e)[:300]}

    if req.include_semantic or req.include_visual:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_sem = executor.submit(_run_semantic)
            future_vis = executor.submit(_run_visual)
            try:
                semantic_data = future_sem.result(timeout=300)
            except Exception:
                semantic_data = {"status": "unavailable", "error_code": "SEMANTIC_TIMEOUT"}
            try:
                visual_data = future_vis.result(timeout=300)
            except Exception:
                visual_data = {"status": "unavailable", "error_code": "VISUAL_TIMEOUT"}
        _clear_progress(task_id)

    # 4. Build combined report
    eval_cfg = __import__('config').get_config().get("evaluation", {})
    rule_w = eval_cfg.get("ruleWeight", 0.35)
    sem_w = eval_cfg.get("semanticWeight", 0.35)
    vis_w = eval_cfg.get("visualWeight", 0.30)

    sem_ok = semantic_data and semantic_data.get("status") == "success"
    vis_ok = visual_data and visual_data.get("status") == "success"

    # Calculate weights, normalizing based on what's available
    active_weights = []
    scores_parts = []

    # Rule always available
    active_weights.append(rule_w)
    scores_parts.append(rule_score)

    sem_score = 0
    if sem_ok:
        sem_score = semantic_data.get("overall_score", 0)
        active_weights.append(sem_w)
        scores_parts.append(sem_score)
    else:
        semantic_data = semantic_data or {"status": "unavailable", "error_code": "OLLAMA_OFFLINE", "rule_only": True}

    vis_score = 0
    if vis_ok:
        vis_score = visual_data.get("visual_consistency_score", 0)
        active_weights.append(vis_w)
        scores_parts.append(vis_score)
    else:
        visual_data = visual_data or {"status": "unavailable", "error_code": "VISUAL_MODEL_OFFLINE"}

    # Normalize weights
    total_w = sum(active_weights)
    if total_w > 0:
        normalized = [w / total_w for w in active_weights]
        combined = round(sum(s * nw for s, nw in zip(scores_parts, normalized)), 1)
    else:
        combined = rule_score

    # Determine status
    if vis_ok and sem_ok:
        status = "generated"
    elif vis_ok and not sem_ok:
        status = "generated_without_semantic"
    elif sem_ok and not vis_ok:
        status = "generated_without_visual"
    elif not sem_ok and not vis_ok:
        status = "generated_rule_only"
    else:
        status = "generated"

    report.semantic_data = semantic_data
    report.visual_data = visual_data
    report.combined_score = combined
    report.rule_score = rule_score
    report.semantic_score = sem_score if sem_ok else 0
    report.visual_score = vis_score if vis_ok else None
    report.evaluation_status = status
    report.asset_fingerprint = fp
    report.semantic_prompt_version = eval_cfg.get("semanticPromptVersion", "v1")
    report.visual_prompt_version = eval_cfg.get("visualPromptVersion", "v1")

    # Build model string
    models = ["rule"]
    if sem_ok: models.append("qwen3:4b-instruct")
    if vis_ok: models.append(visual_data.get("model", "qwen3-vl:4b"))
    report.model = " + ".join(models)

    task.evaluation = report
    svc.save_task(task)
    return report.model_dump()


@router.post("/tasks/{task_id}/semantic")
def run_semantic_only(task_id: str):
    """Re-run only semantic evaluation, preserving rule results."""
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={"error_code": "NOT_REAL_MODE"})

    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})
    if task.evaluation is None:
        raise HTTPException(status_code=400, detail={"error_code": "EVALUATION_NOT_GENERATED", "message": "请先生成规则评测。"})

    try:
        from services.semantic_evaluation_service import run_semantic_evaluation
        sd = run_semantic_evaluation(task)
    except Exception as e:
        raise HTTPException(status_code=503, detail={"error_code": "SEMANTIC_FAILED", "message": str(e)[:300]})

    eval_cfg = __import__('config').get_config().get("evaluation", {})
    rw = eval_cfg.get("ruleWeight", 0.5)
    sw = eval_cfg.get("semanticWeight", 0.5)
    rs = task.evaluation.overall_score

    if sd.get("status") == "success":
        ss = sd.get("overall_score", 0)
        combined = round(rs * rw + ss * sw, 1)
        task.evaluation.semantic_data = sd
        task.evaluation.combined_score = combined
        task.evaluation.semantic_score = ss
        task.evaluation.evaluation_status = "generated"
        task.evaluation.model = "qwen3:4b-instruct"
    else:
        task.evaluation.semantic_data = sd

    svc.save_task(task)
    return task.evaluation.model_dump()


@router.post("/tasks/{task_id}/visual")
def run_visual_only(task_id: str, force_regenerate: bool = False):
    """Re-run only visual evaluation, preserving rule + semantic results."""
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={"error_code": "NOT_REAL_MODE"})

    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    try: svc = get_service()
    except AssertionError: svc = TaskService(JsonTaskRepository())
    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND"})
    if task.evaluation is None:
        raise HTTPException(status_code=400, detail={"error_code": "EVALUATION_NOT_GENERATED", "message": "请先生成规则评测。"})

    # Run visual evaluation
    t_v0 = time.time()
    try:
        from services.visual_evaluation_service import evaluate_image_visual
        _set_progress(task_id, "visual_stage1", "正在分析实际图片...", 0)
        visual_result = evaluate_image_visual(task, force_regenerate=force_regenerate)
        _set_progress(task_id, "visual_done", "视觉评测完成", time.time() - t_v0)
        visual_data = visual_result.model_dump()
    except Exception as e:
        _set_progress(task_id, "visual_failed", f"视觉评测失败", time.time() - t_v0)
        raise HTTPException(status_code=503, detail={"error_code": "VISUAL_FAILED", "message": str(e)[:300]})
    finally:
        _clear_progress(task_id)

    eval_cfg = __import__('config').get_config().get("evaluation", {})
    rw = eval_cfg.get("ruleWeight", 0.35)
    sw = eval_cfg.get("semanticWeight", 0.35)
    vw = eval_cfg.get("visualWeight", 0.30)

    rs = task.evaluation.overall_score
    ss = task.evaluation.semantic_score if hasattr(task.evaluation, "semantic_score") else 0

    sem_ok = task.evaluation.semantic_data and task.evaluation.semantic_data.get("status") == "success"
    vis_ok = visual_data.get("status") == "success"

    # Recalculate combined score
    active_weights = [rw]
    scores = [rs]
    if sem_ok:
        active_weights.append(sw)
        scores.append(ss)
    if vis_ok:
        active_weights.append(vw)
        vs = visual_data.get("visual_consistency_score", 0)
        scores.append(vs)
        task.evaluation.visual_score = vs
    else:
        # Visual eval failed or didn't run — set to None to distinguish from 0
        task.evaluation.visual_score = None

    total_w = sum(active_weights)
    if total_w > 0:
        normalized = [w / total_w for w in active_weights]
        combined = round(sum(s * nw for s, nw in zip(scores, normalized)), 1)
    else:
        combined = rs

    task.evaluation.visual_data = visual_data
    task.evaluation.combined_score = combined
    task.evaluation.visual_prompt_version = eval_cfg.get("visualPromptVersion", "v1")

    # Update status
    if vis_ok and sem_ok:
        task.evaluation.evaluation_status = "generated"
    elif vis_ok:
        task.evaluation.evaluation_status = "generated_without_semantic"
    elif sem_ok:
        task.evaluation.evaluation_status = "generated_without_visual"
    else:
        task.evaluation.evaluation_status = "generated_rule_only"

    # Update model string
    models = ["rule"]
    if sem_ok: models.append("qwen3:4b-instruct")
    if vis_ok: models.append(visual_data.get("model", "qwen3-vl:4b"))
    task.evaluation.model = " + ".join(models)

    # Update fingerprint
    task.evaluation.asset_fingerprint = _fingerprint(task)

    svc.save_task(task)
    return task.evaluation.model_dump()
