"""Image generation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_mode

router = APIRouter(prefix="/api/v1/images", tags=["images"])


class GenerateImageRequest(BaseModel):
    style: str | None = None


@router.post("/tasks/{task_id}/generate")
def generate_images(task_id: str, req: GenerateImageRequest | None = None):
    """
    Generate a situational image for a task using ComfyUI.

    Based on task script content, scenario, and selected style.
    Returns the generated image URL and metadata.
    """
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={
            "error_code": "NOT_REAL_MODE",
            "message": "图片生成仅在 Real 模式下可用。",
        })

    from api import get_service
    from services import TaskService
    from repositories import JsonTaskRepository
    from services.image_workflow_service import generate_image, build_image_asset
    from services.comfyui_client import ComfyUIError

    try:
        svc = get_service()
    except AssertionError:
        repo = JsonTaskRepository()
        svc = TaskService(repo)

    task = svc.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={
            "error_code": "TASK_NOT_FOUND",
            "message": f"任务 {task_id} 不存在。",
        })

    # Apply optional style override
    if req and req.style:
        task.config.image_style = req.style  # type: ignore[assignment]

    try:
        result = generate_image(task_id, task.config, task.script)
    except ComfyUIError as e:
        raise HTTPException(status_code=503 if "无法连接" in str(e) else 500, detail={
            "error_code": "COMFYUI_ERROR",
            "message": f"图片生成失败: {e}",
        })

    # Build and save image asset
    source_ver = task.script.script_version if task.script else "v1.0"
    asset = build_image_asset(result, source_ver)
    task.image = asset
    svc.save_task(task)

    return {
        "task_id": task_id,
        "image": asset.model_dump(),
        "meta": {
            "prompt": result.prompt,
            "negative_prompt": result.negative_prompt,
            "seed": result.seed,
            "style": result.style,
            "width": result.width,
            "height": result.height,
            "generation_latency_ms": result.generation_latency_ms,
            "model_name": result.model_name,
            "topic_type": result.topic_type,
            "image_type": result.image_type,
            "style_preset": result.style_preset,
            "render_mode": result.render_mode,
            "comfyui_used": result.comfyui_used,
            "image_goal": result.image_goal,
            "prompt_source": result.prompt_source,
        },
    }


@router.get("/tasks/{task_id}")
def get_task_images(task_id: str):
    """List generated images for a task."""
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
            "error_code": "TASK_NOT_FOUND",
            "message": f"任务 {task_id} 不存在。",
        })

    images = []
    if task.image:
        images.append(task.image.model_dump())

    # Also list files in the images directory
    from pathlib import Path as _Path
    from config import get_config as _get_config
    _assets_root = _get_config().get("assets", {}).get("rootDir", "storage")
    img_dir = _Path(_assets_root) / task_id / "images"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.png")):
            rel = str(f.relative_to(_assets_root)).replace("\\", "/")
            images.append({
                "filename": f.name,
                "url": f"/assets/{rel}",
                "size_bytes": f.stat().st_size,
            })

    return {"task_id": task_id, "images": images}
