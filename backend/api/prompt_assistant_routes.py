"""Prompt assistant endpoint — optimized for speed."""

from __future__ import annotations

import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import get_mode

router = APIRouter(prefix="/api/v1/prompt-assistant", tags=["prompt-assistant"])


class PromptAssistRequest(BaseModel):
    topic: str = ""
    scene: str = ""
    grade: str = "grade_7"  # receives GradeLevel value from frontend
    image_style: str = "textbook_cartoon"
    image_goal: str = "auto"
    image_prompt_input: str = ""


ASSIST_SYSTEM = (
    "You are an image prompt writer. Given a user's rough idea, output ONLY the final English image-generation prompt "
    "suitable for a text-to-image model (ComfyUI/SDXL). "
    "Do NOT output markdown, JSON, explanations, reasoning, or multiple options. "
    "Output ONLY the prompt text, 100-180 English words, one paragraph. "
    "No thinking aloud. No prefixes or suffixes."
)

GOAL_GUIDANCE = {
    "reference_map": "street/location reference map, top-down or isometric, landmarks, roads, directional arrows, spatial relationships",
    "weather_visual": "weather comparison, multi-panel, sunny/rainy/cloudy/snowy, distinct weather visuals",
    "story_panel": "storyboard/comic panels, 2-4 panels, key story events, clear sequence",
    "scene": "scene illustration with characters and location background",
    "vocab_visual": "vocabulary learning image, grid/card layout, clear visual-word pairs",
    "classroom_poster": "classroom poster/teaching aid, clear and informative",
    "auto": "educational illustration appropriate for the lesson",
}


@router.post("/image")
def enhance_prompt(req: PromptAssistRequest):
    """Enhance a user's rough image prompt. Returns timing metadata."""
    if get_mode() != "real":
        raise HTTPException(status_code=400, detail={"error_code": "NOT_REAL_MODE"})

    from services.ollama_client import OllamaClient, OllamaError
    from services.image_style_presets import get_style_preset

    t_total_start = time.perf_counter()

    guidance = GOAL_GUIDANCE.get(req.image_goal, GOAL_GUIDANCE["auto"])
    user_input = req.image_prompt_input.strip() if req.image_prompt_input else (
        f"topic={req.topic}, scene={req.scene}, goal={req.image_goal}"
    )
    style_data = get_style_preset(req.image_style)

    # Streamlined user prompt — only essential fields
    user_msg = (
        f"Grade: {req.grade}\n"
        f"Topic: {req.topic}\n"
        f"Goal: {guidance}\n"
        f"Style: {req.image_style} — {style_data['positive'][:120]}\n"
        f"User input: {user_input}\n"
        f"Output ONLY the final English prompt, 100-180 words."
    )

    t_queue_start = time.perf_counter()
    queue_ms = int((t_queue_start - t_total_start) * 1000)

    retry_count = 0
    try:
        client = OllamaClient()
        result = client.chat(
            ASSIST_SYSTEM, user_msg,
            temperature=0.2, num_predict=384,
            keep_alive="30m", format_json=False,
        )
        retry_count = 0
    except OllamaError:
        retry_count = 1
        try:
            client = OllamaClient()
            result = client.chat(
                ASSIST_SYSTEM, user_msg,
                temperature=0.2, num_predict=256,
                keep_alive="30m", format_json=False,
            )
        except OllamaError as e:
            raise HTTPException(status_code=503, detail={
                "error_code": getattr(e, 'error_code', 'OLLAMA_ERROR'),
                "message": str(e)[:300],
            })

    t_total_end = time.perf_counter()

    enhanced = result["content"].strip()
    # Clean artifacts
    if enhanced.startswith('"') and enhanced.endswith('"'):
        enhanced = enhanced[1:-1]
    if enhanced.startswith("```"):
        enhanced = "\n".join(enhanced.split("\n")[1:-1] if enhanced.count("\n") >= 2 else [enhanced.replace("```", "")])

    total_ms = int((t_total_end - t_total_start) * 1000)
    generation_ms = int(result.get("total_duration_ns", 0) / 1_000_000) if result.get("total_duration_ns") else total_ms - queue_ms

    return {
        "success": True,
        "raw_input": req.image_prompt_input,
        "enhanced_prompt": enhanced,
        "model": result["model"],
        "timing": {
            "queue_ms": queue_ms,
            "generation_ms": generation_ms,
            "total_ms": total_ms,
            "retry_count": retry_count,
        },
    }
