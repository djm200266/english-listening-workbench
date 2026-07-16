"""Visual evaluation service using Qwen3-VL via OllamaClient.

Two-stage architecture:
  Stage 1: qwen3-vl:4b extracts visual facts from the image
  Stage 2: same qwen3-vl:4b (default) or qwen3:4b-instruct scores from facts

Default Plan B (single_model=True):
  qwen3-vl:4b for both stages — no model switching, no VRAM contention

Plan A (single_model=False):
  qwen3-vl:4b Stage 1 → qwen3:4b-instruct Stage 2 — for comparison only

Stage 1 cache is ALWAYS reused when image fingerprint matches.
Force-regenerate only affects the full result cache, never Stage 1 cache.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_config
from models import (
    Task, VisualEvaluationResult, VisualEvaluationDimension,
    VisualDetectedObject, VisualDetectedText, VisualSpatialRelation,
    VisualQualityIssue, VisualHardFailure, VisualBadCase,
)
from services.ollama_client import OllamaClient, OllamaError

LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "visual_eval"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".webp"}

def _grade_label(task) -> str:
    """Return Chinese grade label for use in prompts."""
    raw = getattr(task.config.grade, "value", str(task.config.grade)) if hasattr(task.config.grade, "value") else str(task.config.grade)
    mapping = {"grade_7": "七年级", "grade_8": "八年级", "grade_9": "九年级"}
    return mapping.get(raw, "七年级")

# ── Stage-specific error codes ──────────────────────────
ERR_STAGE1_TIMEOUT = "VISUAL_STAGE1_TIMEOUT"
ERR_STAGE2_TIMEOUT = "VISUAL_STAGE2_TIMEOUT"
ERR_VISUAL_TOTAL_TIMEOUT = "VISUAL_TOTAL_TIMEOUT"
ERR_VISUAL_MODEL_NOT_FOUND = "VISUAL_MODEL_NOT_FOUND"
ERR_VISUAL_MODEL_OFFLINE = "VISUAL_MODEL_OFFLINE"
ERR_VISUAL_IMAGE_NOT_FOUND = "VISUAL_IMAGE_NOT_FOUND"
ERR_VISUAL_PARSE_FAILED = "VISUAL_PARSE_FAILED"

# ── Prompt version for cache invalidation ───────────────
VISUAL_PROMPT_VERSION = "v2"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Stage 1: Vision fact extraction system prompt ────────
# CRITICAL: qwen3-vl has a thinking mode that consumes tokens BEFORE JSON output.
# We MUST tell it to skip thinking and output JSON directly.
# If num_predict is too low, thinking burns all tokens and no JSON is produced.

STAGE1_SYSTEM_PROMPT = (
    "Output ONLY a JSON object describing this English teaching image. "
    "Do NOT think, do NOT reason, do NOT explain. "
    "Skip all analysis. Go straight to JSON output. "
    "First char MUST be {, last char MUST be }. No markdown, no ```json."
)

# ── Stage 2: Scoring system prompts ─────────────────────
# Short version for VL model (format_json compatible)
# Long version for text model (no format_json constraint)

STAGE2_SYSTEM_PROMPT_SHORT = (
    "Reply in JSON only. No markdown, no explanation, no thinking. "
    "First char {, last char }."
)

STAGE2_SYSTEM_PROMPT_LONG = (
    "You are a {_grade_label(task)} English teaching image evaluator. "
    "Based on the extracted visual facts, compare with the requirements and score. "
    "Output ONLY a valid JSON object. First char {, last char }."
    "No markdown, no explanation."
)


# ── Image resolution ────────────────────────────────────

def _max_size_for_task(task: Task) -> int:
    """Determine appropriate max image dimension based on task type."""
    image_type = getattr(task.config, "image_type", "") or ""
    if task.image:
        image_type = image_type or getattr(task.image, "image_type", "")
    if image_type in ("location_reference_map", "reference_map"):
        return 1024
    return 768


def _resolve_image_path(task: Task) -> Path | None:
    """Safely resolve the actual image file path from task image data."""
    if not task.image or not task.image.image_url:
        return None

    cfg = get_config()
    assets_root = Path(cfg.get("assets", {}).get("rootDir", "storage")).resolve()

    rel = task.image.image_url.lstrip("/")
    if rel.startswith("assets/"):
        rel = rel[len("assets/"):]

    candidate = (assets_root / rel).resolve()
    try:
        candidate.relative_to(assets_root)
    except ValueError:
        alt = (assets_root / Path(task.image.image_url).name).resolve()
        try:
            alt.relative_to(assets_root)
            if alt.exists():
                return alt
        except (ValueError, OSError):
            pass
        return None

    return candidate if candidate.exists() else None


def _compute_sha256(filepath: Path) -> str:
    """Compute SHA256 hash of file contents."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _preprocess_image(filepath: Path, task_id: str, max_size: int) -> tuple[bytes, dict, dict]:
    """
    Preprocess image for vision model: resize if needed, convert to JPEG.
    Returns (image_bytes, original_size_info, evaluated_size_info).
    Does NOT modify the original file.
    """
    from PIL import Image
    import io

    img = Image.open(filepath).convert("RGB")
    orig_size = {"width": img.width, "height": img.height}

    if max(img.width, img.height) > max_size:
        ratio = max_size / max(img.width, img.height)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    eval_size = {"width": img.width, "height": img.height}

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    img_bytes = buf.getvalue()

    eval_copy_dir = LOGS_DIR / task_id
    eval_copy_dir.mkdir(parents=True, exist_ok=True)
    (eval_copy_dir / "visual_input.jpg").write_bytes(img_bytes)

    return img_bytes, orig_size, eval_size


# ── JSON extraction and repair ──────────────────────────

def _extract_json(text: str) -> str:
    """Extract JSON from potentially messy model output."""
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
    if text.endswith("```"):
        text = text[:text.rfind("```")].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return text


def _repair_json(json_str: str) -> str:
    """
    Repair common model JSON errors:
    1. Trailing commas before } or ]
    2. Truncated JSON (auto-close unclosed braces/brackets)
    3. Common number typos like 10" → 100
    """
    # Fix trailing commas
    repaired = re.sub(r',\s*}', '}', json_str)
    repaired = re.sub(r',\s*]', ']', repaired)

    # Fix quoted numbers like "max_score": 10" → "max_score": 100
    repaired = re.sub(r'(\d+)"(\s*[,}\]])', r'\1\2', repaired)

    # Auto-close truncated JSON
    open_braces = repaired.count('{') - repaired.count('}')
    open_brackets = repaired.count('[') - repaired.count(']')

    if open_braces > 0 or open_brackets > 0:
        # If last char is a partial string value, close it
        if repaired.rstrip().endswith('"'):
            # Check if it's an unclosed string (odd number of quotes in last line)
            last_line = repaired.rstrip().split('\n')[-1]
            if last_line.count('"') % 2 == 1:
                repaired = repaired.rstrip() + '"'

        # Close any unclosed string (if last non-whitespace is not ,, {, [, :, ")
        last_char = repaired.rstrip()[-1] if repaired.rstrip() else ''
        if last_char not in (',', '{', '[', ':', '"', '}'):
            # Might be a truncated value — add closing quote
            if ':' in repaired.rstrip().split('\n')[-1]:
                repaired = repaired.rstrip() + '"'

        # Add missing closing brackets/braces
        repaired += ']' * open_brackets
        repaired += '}' * open_braces

    return repaired


# ── Stage 1 prompt builder ──────────────────────────────

def _build_stage1_prompt(task: Task) -> str:
    """Build a concise Stage 1 prompt for vision fact extraction only."""
    cfg = task.config
    image_type = getattr(cfg, "image_type", "") or (
        getattr(task.image, "image_type", "") if task.image else ""
    )
    style = cfg.image_style.value if hasattr(cfg.image_style, "value") else str(cfg.image_style)

    return (
        f"Describe this {_grade_label(task)} English teaching image.\n"
        f"Expected type: {image_type or 'N/A'}\n"
        f"Expected style: {style}\n"
        f"Output ONLY a JSON object with these EXACT keys:\n"
        f"- image_caption: string (one sentence)\n"
        f"- detected_objects: array of strings (label names only)\n"
        f"- detected_text: array of strings (any visible text)\n"
        f"- spatial_relations: array of strings (layout descriptions)\n"
        f"- detected_style: string\n"
        f"- detected_layout_type: string\n"
        f"- quality_issues: array of strings (if any, empty array if none)\n"
        f"NO nested objects. Keep arrays simple. No thinking, no markdown."
    )


# ── Stage 2 prompt builder ──────────────────────────────

def _build_stage2_prompt(task: Task, stage1_data: dict) -> str:
    """Build concise Stage 2 scoring prompt from extracted visual facts only."""
    cfg = task.config

    # Script summary (brief)
    script_summary = ""
    if task.script:
        turns = [f"T{t.turn_id}:{t.text[:40]}" for t in task.script.dialogue[:6]]
        script_summary = "; ".join(turns)

    # Core elements
    core = ", ".join(cfg.required_vocabulary[:6]) if cfg.required_vocabulary else "N/A"

    # Final prompt
    final_prompt = (cfg.image_prompt_enhanced or cfg.image_prompt_input or "N/A")[:150]

    return (
        f"Evaluate this {_grade_label(task)} English teaching image quality.\n\n"
        f"=== VISUAL FACTS ===\n"
        f"Caption: {stage1_data.get('image_caption', 'N/A')[:200]}\n"
        f"Style: {stage1_data.get('detected_style', 'unknown')}\n"
        f"Layout: {stage1_data.get('detected_layout_type', 'unknown')}\n"
        f"Objects: {json.dumps(stage1_data.get('detected_objects', []), ensure_ascii=False)[:300]}\n"
        f"Text: {json.dumps(stage1_data.get('detected_text', []), ensure_ascii=False)[:300]}\n"
        f"Relations: {json.dumps(stage1_data.get('spatial_relations', []), ensure_ascii=False)[:200]}\n"
        f"Issues: {json.dumps(stage1_data.get('quality_issues', []), ensure_ascii=False)[:200]}\n\n"
        f"=== REQUIREMENTS ===\n"
        f"Topic: {cfg.topic}\n"
        f"Type: {getattr(cfg, 'image_type', '') or 'N/A'}\n"
        f"Style: {cfg.image_style}\n"
        f"Goal: {getattr(cfg, 'image_goal', 'auto')}\n"
        f"Elements: {core}\n"
        f"Prompt: {final_prompt}\n"
        f"Script: {script_summary[:200]}\n\n"
        f"Score 10 dimensions (0-100, -1 if N/A):\n"
        f"visual_content_alignment, image_type_alignment, style_alignment, "
        f"required_element_coverage, spatial_relation_accuracy, "
        f"instructional_clarity, text_legibility, composition_quality, "
        f"artifact_quality, prompt_visual_consistency.\n\n"
        f"Output JSON with: visual_consistency_score, confidence, dimensions (array of "
        f"{{key, label, score, max_score, status, issues:[], suggestions:[]}}), "
        f"hard_failures, bad_cases, recommendations.\n"
        f"Max 2 issues and 2 suggestions per dimension. No thinking, no markdown."
    )


# ── Stage 1 cache (separate from full result cache) ─────

def _stage1_cache_key(task: Task, image_sha256: str, visual_model: str, prompt_version: str) -> str:
    """Build fingerprint for Stage 1 cache (image content only, no script dependency)."""
    parts = [
        image_sha256,
        visual_model,
        prompt_version,
        getattr(task.config, "image_goal", ""),
        task.config.image_style.value if hasattr(task.config.image_style, "value") else str(task.config.image_style),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:16]


def _stage1_cache_dir(task_id: str) -> Path:
    d = LOGS_DIR / task_id / "stage1_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_stage1_cache(task_id: str, s1_key: str) -> dict | None:
    cache_file = _stage1_cache_dir(task_id) / f"{s1_key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return data
    except Exception:
        return None


def _save_stage1_cache(task_id: str, s1_key: str, data: dict):
    cache_file = _stage1_cache_dir(task_id) / f"{s1_key}.json"
    cache_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Full result cache ───────────────────────────────────

def _build_visual_cache_key(task: Task, image_sha256: str, visual_model: str, prompt_version: str) -> str:
    """Build a cache fingerprint for full visual evaluation result."""
    parts = [
        task.task_id,
        image_sha256,
        visual_model,
        prompt_version,
        getattr(task.config, "image_goal", ""),
        task.config.image_style.value if hasattr(task.config.image_style, "value") else str(task.config.image_style),
        task.script.script_version if task.script else "noscript",
    ]
    if task.image:
        parts.append(getattr(task.image, "image_type", ""))
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:16]


def _full_cache_dir(task_id: str) -> Path:
    d = LOGS_DIR / task_id / "full_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_full_cached_result(task_id: str, cache_key: str) -> VisualEvaluationResult | None:
    cache_file = _full_cache_dir(task_id) / f"{cache_key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return VisualEvaluationResult(**data)
    except Exception:
        return None


def _save_full_cached_result(task_id: str, cache_key: str, result: VisualEvaluationResult):
    cache_file = _full_cache_dir(task_id) / f"{cache_key}.json"
    cache_file.write_text(result.model_dump_json(indent=2), encoding="utf-8")


# ── Progress logger ─────────────────────────────────────

def _start_progress_logger(task_id: str, stage: str, model: str, stage1_cache_hit: bool):
    """Start a background thread that logs progress every 15 seconds."""
    stop_event = threading.Event()
    start_time = time.perf_counter()

    def _log_loop():
        while not stop_event.is_set():
            stop_event.wait(15.0)
            if stop_event.is_set():
                break
            elapsed = int(time.perf_counter() - start_time)
            print(
                f"[Visual Eval] {stage}, elapsed={elapsed}s, model={model}, "
                f"stage1_cache_hit={stage1_cache_hit}, task={task_id}"
            )

    t = threading.Thread(target=_log_loop, daemon=True)
    t.start()
    return stop_event


# ── Parse and validate ───────────────────────────────────

def _parse_visual_result(data: dict, model: str, image_sha256: str,
                         orig_size: dict, eval_size: dict) -> VisualEvaluationResult:
    """Parse raw dict into VisualEvaluationResult with validation.

    Handles common qwen3-vl output issues:
    - spatial_relations as a flat string instead of list[dict]
    - detected_objects as a flat list of strings instead of list[dict]
    - quality_issues as a string instead of list[dict]
    """
    # ── Safely coerce lists ──
    def _ensure_list_of_dicts(val, default=None):
        """Convert model output to list[dict]. Handles string and list-of-strings inputs."""
        if default is None:
            default = []
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return default
            # Single string description → wrap as single-item list with description field
            return [{"description": val}]
        if not isinstance(val, list):
            return default
        # Check if list items are strings → convert to dicts
        result = []
        for item in val:
            if isinstance(item, str):
                if item.strip():
                    result.append({"description": item})
            elif isinstance(item, dict):
                result.append(item)
        return result if result else default

    def _ensure_list_of_strings(val, default=None):
        """Convert model output to list[str]."""
        if default is None:
            default = []
        if isinstance(val, str):
            val = val.strip()
            return [val] if val else default
        if not isinstance(val, list):
            return default
        return [str(v) for v in val if v]

    dimensions = []
    dims_raw = data.get("dimensions", [])
    if isinstance(dims_raw, list):
        for d in dims_raw:
            if not isinstance(d, dict):
                continue
            score = d.get("score", 0)
            if isinstance(score, (int, float)):
                score = max(0, min(100, float(score)))
            dimensions.append(VisualEvaluationDimension(
                key=d.get("key", ""),
                label=d.get("label", ""),
                score=score,
                max_score=float(d.get("max_score", 100)),
                status=d.get("status", "evaluated"),
                confidence=float(d.get("confidence", 0.5)),
                evidence=(d.get("evidence") or [])[:3],
                issues=(d.get("issues") or [])[:2],
                suggestions=(d.get("suggestions") or [])[:2],
            ))

    detected_objects_raw = data.get("detected_objects", [])
    detected_objects_raw = _ensure_list_of_dicts(detected_objects_raw)
    detected_objects = []
    for o in detected_objects_raw:
        if not isinstance(o, dict):
            continue
        detected_objects.append(VisualDetectedObject(
            label=o.get("label", o.get("description", "")),
            category=o.get("category", ""),
            confidence=float(o.get("confidence", 0.5)),
            bbox_hint=o.get("bbox_hint", ""),
        ))

    detected_text_raw = data.get("detected_text", [])
    detected_text_raw = _ensure_list_of_dicts(detected_text_raw)
    detected_text = []
    for t in detected_text_raw:
        if not isinstance(t, dict):
            continue
        detected_text.append(VisualDetectedText(
            text=t.get("text", t.get("description", "")),
            confidence=float(t.get("confidence", 0.5)),
            location=t.get("location", ""),
            language=t.get("language", "en"),
        ))

    spatial_relations_raw = data.get("spatial_relations", [])
    spatial_relations_raw = _ensure_list_of_dicts(spatial_relations_raw)
    spatial_relations = []
    for s in spatial_relations_raw:
        if not isinstance(s, dict):
            continue
        # handle both object format and description-only format
        if s.get("subject") or s.get("relation"):
            spatial_relations.append(VisualSpatialRelation(
                relation=s.get("relation", ""),
                subject=s.get("subject", ""),
                object=s.get("object", ""),
                confidence=float(s.get("confidence", 0.5)),
            ))
        else:
            # Generic description → store as relation
            spatial_relations.append(VisualSpatialRelation(
                relation=s.get("description", ""),
                subject="", object="",
                confidence=float(s.get("confidence", 0.5)),
            ))

    quality_issues_raw = data.get("quality_issues", [])
    quality_issues_raw = _ensure_list_of_dicts(quality_issues_raw)
    quality_issues = []
    for qi in quality_issues_raw:
        if not isinstance(qi, dict):
            continue
        quality_issues.append(VisualQualityIssue(
            issue_type=qi.get("issue_type", ""),
            description=qi.get("description", ""),
            severity=qi.get("severity", "minor"),
            location=qi.get("location", ""),
        ))

    hard_failures = []
    for hf in data.get("hard_failures", []):
        hard_failures.append(VisualHardFailure(
            code=hf.get("code", ""),
            severity=hf.get("severity", "major"),
            evidence=hf.get("evidence", ""),
            recommendation=hf.get("recommendation", ""),
        ))

    bad_cases = []
    for i, bc in enumerate(data.get("bad_cases", [])):
        bad_cases.append(VisualBadCase(
            id=bc.get("id", f"VC_{i + 1:03d}"),
            modality="image",
            severity=bc.get("severity", "minor"),
            category=bc.get("category", ""),
            title=bc.get("title", ""),
            description=bc.get("description", ""),
            visual_evidence=bc.get("visual_evidence", ""),
            expected=bc.get("expected", ""),
            observed=bc.get("observed", ""),
            recommendation=bc.get("recommendation", ""),
            score=float(bc.get("score", 0)),
            source="qwen3-vl",
        ))

    # Compute overall visual consistency score from dimensions
    # Model outputs various statuses: "evaluated", "pass", "fail", "not_applicable"
    evaluable_statuses = {"evaluated", "pass", "fail", "ok", "success"}
    dim_scores = [d.score for d in dimensions
                  if d.status.lower() in evaluable_statuses and d.score >= 0]
    visual_score = round(sum(dim_scores) / len(dim_scores), 1) if dim_scores else 0.0

    return VisualEvaluationResult(
        status="success",
        model=model,
        visual_content_checked=True,
        visual_consistency_score=visual_score,
        image_caption=data.get("image_caption", ""),
        detected_objects=detected_objects,
        detected_text=detected_text,
        spatial_relations=spatial_relations,
        detected_style=data.get("detected_style", "unknown"),
        detected_layout_type=data.get("detected_layout_type", "unknown"),
        quality_issues=quality_issues,
        dimensions=dimensions,
        hard_failures=hard_failures,
        bad_cases=bad_cases,
        recommendations=(data.get("recommendations") or [])[:5],
        confidence=float(data.get("confidence", 0.5)),
        image_sha256=image_sha256,
        original_image_size=orig_size,
        evaluated_image_size=eval_size,
        model_load_ms=0,
        queue_ms=0,
        generation_ms=0,
        total_ms=0,
        retry_count=0,
    )


# ═══════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════

def evaluate_image_visual(
    task: Task,
    force_regenerate: bool = False,
    single_model: bool = False,
) -> VisualEvaluationResult:
    """
    Run visual evaluation on a task's generated image.

    DEFAULT: Plan A (single_model=False) — VL Stage 1 + text model Stage 2.
    This is the ONLY reliable approach:
    - qwen3-vl:4b CANNOT do Stage 2 scoring (thinking consumes ALL tokens)
    - qwen3:4b-instruct text model: no thinking, reliable JSON output
    - Both models briefly coexist in VRAM (~6.7GB total, fits in 8GB)

    Plan B (single_model=True) is DEPRECATED — tested and confirmed non-viable:
    qwen3-vl thinking mode exhausts num_predict budget before any JSON output.

    Stage 1 cache is ALWAYS reused when image fingerprint matches.
    force_regenerate only skips the FULL result cache, never Stage 1.

    Args:
        task: Task with generated image
        force_regenerate: Skip full result cache (Stage 1 cache still respected)
        single_model: DO NOT USE — VL model cannot produce Stage 2 JSON
    """
    cfg = get_config().get("evaluation", {})
    visual_model = cfg.get("visualModel", "qwen3-vl:4b")
    text_model = get_config().get("ollama", {}).get("model", "qwen3:4b-instruct")
    prompt_version = cfg.get("visualPromptVersion", VISUAL_PROMPT_VERSION)

    # Stage timeouts
    stage1_timeout = cfg.get("visualStage1TimeoutSec", 180)
    stage2_timeout = cfg.get("visualStage2TimeoutSec", 90)
    total_timeout = cfg.get("visualTotalTimeoutSec", 300)

    # Token budgets
    # Stage 1: qwen3-vl may think before outputting JSON even with format_json=True
    # 500 tokens is too low (thinking burns ~300-500 tokens, leaving none for JSON)
    # 1200 tokens: ~400 for potential thinking + ~800 for JSON output
    stage1_num_predict = 1200
    # Stage 2: text model needs ~700 tokens for 10-dimension scoring JSON
    stage2_num_predict = 700

    # Track retry for Stage 1 parse failures
    stage1_retry_with_higher = False
    stage1_retry_num_predict = 2000  # fallback if first attempt produces no JSON

    ts = _now_iso().replace(":", "-")
    debug_dir = LOGS_DIR / task.task_id
    debug_dir.mkdir(parents=True, exist_ok=True)

    # ── Resolve image path ──
    img_path = _resolve_image_path(task)
    if img_path is None:
        return VisualEvaluationResult(
            status="image_not_found",
            error_code=ERR_VISUAL_IMAGE_NOT_FOUND,
            error_message=f"无法找到任务 {task.task_id} 的图片文件。",
        )

    suffix = img_path.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        return VisualEvaluationResult(
            status="image_not_found",
            error_code="VISUAL_IMAGE_FORMAT_UNSUPPORTED",
            error_message=f"不支持的图片格式: {suffix}。支持: {', '.join(SUPPORTED_FORMATS)}",
        )

    # ── Compute image hash ──
    try:
        image_sha256 = _compute_sha256(img_path)
    except Exception as e:
        return VisualEvaluationResult(
            status="image_not_found",
            error_code="VISUAL_IMAGE_READ_FAILED",
            error_message=f"无法读取图片文件: {e}",
        )

    # ── Check full result cache (skipped if force_regenerate) ──
    if not force_regenerate:
        full_key = _build_visual_cache_key(task, image_sha256, visual_model, prompt_version)
        cached = _load_full_cached_result(task.task_id, full_key)
        if cached is not None:
            print(f"[Visual Eval] Full cache hit for {task.task_id}, returning instantly")
            return cached

    t0 = time.perf_counter()
    diagnostics: dict[str, Any] = {
        "stage1_cache_hit": False,
        "stage1_elapsed_s": 0,
        "stage2_elapsed_s": 0,
        "stage1_num_predict": stage1_num_predict,
        "stage2_num_predict": stage2_num_predict,
        "single_model": single_model,
        "prompt_version": prompt_version,
    }
    client = OllamaClient()

    # ═══════════════════════════════════════════════════════
    # Stage 1: Vision model extracts facts from image
    # Stage 1 cache is ALWAYS checked and reused if available
    # ═══════════════════════════════════════════════════════

    s1_key = _stage1_cache_key(task, image_sha256, visual_model, prompt_version)
    stage1_data = _load_stage1_cache(task.task_id, s1_key)

    if stage1_data is not None:
        diagnostics["stage1_cache_hit"] = True
        print(f"[Visual Eval] Stage 1 cache HIT for {task.task_id}, skipping image re-read")
        # We still need orig_size and eval_size for the result
        max_size = _max_size_for_task(task)
        try:
            _, orig_size, eval_size = _preprocess_image(img_path, task.task_id, max_size)
        except Exception:
            orig_size = {"width": 0, "height": 0}
            eval_size = {"width": 0, "height": 0}
    else:
        diagnostics["stage1_cache_hit"] = False
        print(f"[Visual Eval] Stage 1 cache MISS for {task.task_id}, running vision extraction...")

        # Preprocess image
        max_size = _max_size_for_task(task)
        try:
            img_bytes, orig_size, eval_size = _preprocess_image(img_path, task.task_id, max_size)
        except Exception as e:
            return VisualEvaluationResult(
                status="image_not_found",
                error_code="VISUAL_IMAGE_READ_FAILED",
                error_message=f"图片预处理失败: {e}",
            )

        stage1_prompt = _build_stage1_prompt(task)
        (debug_dir / f"{ts}_stage1_prompt.txt").write_text(stage1_prompt, encoding="utf-8")

        # Start progress logger
        progress_stop = _start_progress_logger(
            task.task_id, "Stage 1 vision extraction", visual_model, False
        )

        try:
            t_s1 = time.perf_counter()
            client_vl = OllamaClient(model=visual_model, timeout_sec=stage1_timeout)
            result1 = client_vl.chat_with_images(
                STAGE1_SYSTEM_PROMPT, stage1_prompt,
                image_bytes_list=[img_bytes],
                temperature=0.1,
                num_predict=stage1_num_predict,
                keep_alive="30m",  # Keep loaded for Stage 2 reuse
                format_json=True,
                timeout_sec=stage1_timeout,
            )
            progress_stop.set()
            stage1_elapsed = time.perf_counter() - t_s1
            diagnostics["stage1_elapsed_s"] = round(stage1_elapsed, 1)
            diagnostics["model_load_ms"] = int(result1.get("load_duration_ns", 0) / 1_000_000)
            diagnostics["generation_ms"] = int(result1.get("eval_duration_ns", 0) / 1_000_000)

            raw_output = result1["content"]
            print(f"[Visual Eval] Stage 1 complete, elapsed={stage1_elapsed:.1f}s, "
                  f"model={visual_model}, output_len={len(raw_output)}")

        except OllamaError as e:
            progress_stop.set()
            err_code = getattr(e, "error_code", "VISUAL_EVALUATION_FAILED")
            if "not found" in str(e).lower():
                err_code = ERR_VISUAL_MODEL_NOT_FOUND
            elif "timeout" in str(e).lower() or "超时" in str(e):
                err_code = ERR_STAGE1_TIMEOUT
            print(f"[Visual Eval] Stage 1 FAILED: [{err_code}] {str(e)[:200]}")
            return VisualEvaluationResult(
                status="unavailable",
                error_code=err_code,
                error_message=str(e)[:500],
                total_ms=int((time.perf_counter() - t0) * 1000),
            )

        (debug_dir / f"{ts}_stage1_raw.txt").write_text(raw_output, encoding="utf-8")

        # Parse stage 1 JSON — if parse fails and no JSON found, retry with higher num_predict
        json_str = _extract_json(raw_output)
        try:
            stage1_data = json.loads(json_str)
        except json.JSONDecodeError:
            try:
                repaired = _repair_json(json_str)
                stage1_data = json.loads(repaired)
            except json.JSONDecodeError:
                # Check if output has NO '{' at all (pure thinking, no JSON attempted)
                has_json_attempt = '{' in raw_output
                if not has_json_attempt and stage1_num_predict < stage1_retry_num_predict:
                    print(f"[Visual Eval] Stage 1: NO JSON found in output (pure thinking). "
                          f"Retrying with num_predict={stage1_retry_num_predict}...")
                    # Retry with higher budget
                    try:
                        t_s1_retry = time.perf_counter()
                        result1_retry = client_vl.chat_with_images(
                            STAGE1_SYSTEM_PROMPT, stage1_prompt,
                            image_bytes_list=[img_bytes],
                            temperature=0.1,
                            num_predict=stage1_retry_num_predict,
                            keep_alive="30m",
                            format_json=True,
                            timeout_sec=stage1_timeout,
                        )
                        stage1_elapsed = time.perf_counter() - t_s1_retry
                        diagnostics["stage1_elapsed_s"] = round(stage1_elapsed, 1)
                        diagnostics["stage1_retry_num_predict"] = stage1_retry_num_predict
                        raw_output = result1_retry["content"]
                        print(f"[Visual Eval] Stage 1 retry complete, elapsed={stage1_elapsed:.1f}s, "
                              f"output_len={len(raw_output)}")
                        (debug_dir / f"{ts}_stage1_raw_retry.txt").write_text(raw_output, encoding="utf-8")

                        json_str = _extract_json(raw_output)
                        try:
                            stage1_data = json.loads(json_str)
                        except json.JSONDecodeError:
                            try:
                                repaired = _repair_json(json_str)
                                stage1_data = json.loads(repaired)
                            except json.JSONDecodeError:
                                print(f"[Visual Eval] Stage 1 retry JSON parse also FAILED, "
                                      f"raw preview: {raw_output[:300]}")
                                return VisualEvaluationResult(
                                    status="parse_failed",
                                    error_code=ERR_VISUAL_PARSE_FAILED,
                                    error_message=f"Stage 1: 视觉模型重试后仍返回无效JSON。output_len={len(raw_output)}",
                                    total_ms=int((time.perf_counter() - t0) * 1000),
                                    retry_count=1,
                                )
                    except OllamaError as e2:
                        print(f"[Visual Eval] Stage 1 retry FAILED: {str(e2)[:200]}")
                        return VisualEvaluationResult(
                            status="unavailable",
                            error_code=getattr(e2, "error_code", "VISUAL_EVALUATION_FAILED"),
                            error_message=f"Stage 1 retry: {str(e2)[:500]}",
                            total_ms=int((time.perf_counter() - t0) * 1000),
                        )
                else:
                    print(f"[Visual Eval] Stage 1 JSON parse FAILED, raw preview: {raw_output[:300]}")
                    return VisualEvaluationResult(
                        status="parse_failed",
                        error_code=ERR_VISUAL_PARSE_FAILED,
                        error_message=f"Stage 1: 视觉模型事实提取返回无效JSON。output_len={len(raw_output)}",
                        total_ms=int((time.perf_counter() - t0) * 1000),
                    )

        # Save Stage 1 cache
        _save_stage1_cache(task.task_id, s1_key, stage1_data)
        print(f"[Visual Eval] Stage 1 cache SAVED for {task.task_id}")

    # Write stage1_data to debug dir
    (debug_dir / f"{ts}_stage1_data.json").write_text(
        json.dumps(stage1_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ═══════════════════════════════════════════════════════
    # Stage 2: Scoring from extracted facts (no images)
    # ═══════════════════════════════════════════════════════

    # Determine Stage 2 model
    if single_model:
        stage2_model = visual_model  # Plan B: same VL model
        stage2_system_prompt = STAGE2_SYSTEM_PROMPT_SHORT  # short for VL format_json
        stage2_use_format_json = True
    else:
        stage2_model = text_model  # Plan A: text model
        stage2_system_prompt = STAGE2_SYSTEM_PROMPT_LONG
        stage2_use_format_json = True  # text model handles format_json fine

    stage2_prompt = _build_stage2_prompt(task, stage1_data)
    (debug_dir / f"{ts}_stage2_prompt.txt").write_text(stage2_prompt, encoding="utf-8")

    # Check total time budget
    elapsed_total = time.perf_counter() - t0
    remaining_budget = total_timeout - elapsed_total
    if remaining_budget < 15:
        print(f"[Visual Eval] TOTAL TIMEOUT: {elapsed_total:.0f}s elapsed exceeds {total_timeout}s budget")
        return VisualEvaluationResult(
            status="unavailable",
            error_code=ERR_VISUAL_TOTAL_TIMEOUT,
            error_message=f"视觉评测总超时: 已用 {elapsed_total:.0f}s, 超出预算 {total_timeout}s。",
            total_ms=int(elapsed_total * 1000),
        )
    effective_stage2_timeout = min(stage2_timeout, max(15, int(remaining_budget - 5)))

    print(f"[Visual Eval] Stage 2 scoring, model={stage2_model}, "
          f"single_model={single_model}, timeout={effective_stage2_timeout}s, "
          f"stage1_cache_hit={diagnostics['stage1_cache_hit']}")

    # Start progress logger
    progress_stop2 = _start_progress_logger(
        task.task_id, "Stage 2 scoring", stage2_model, diagnostics["stage1_cache_hit"]
    )

    try:
        t_s2 = time.perf_counter()
        # Create client with the right timeout (chat() doesn't accept timeout_sec kwarg)
        stage2_client = OllamaClient(model=stage2_model, timeout_sec=effective_stage2_timeout)
        result2 = stage2_client.chat(
            system_prompt=stage2_system_prompt,
            user_prompt=stage2_prompt,
            model=stage2_model,
            temperature=0.1,
            num_predict=stage2_num_predict,
            keep_alive="30m",
            format_json=stage2_use_format_json,
        )
        progress_stop2.set()
        stage2_elapsed = time.perf_counter() - t_s2
        diagnostics["stage2_elapsed_s"] = round(stage2_elapsed, 1)
        diagnostics["stage2_generation_ms"] = int(result2.get("eval_duration_ns", 0) / 1_000_000)

        scoring_raw = result2["content"]
        print(f"[Visual Eval] Stage 2 complete, elapsed={stage2_elapsed:.1f}s, "
              f"model={stage2_model}, output_len={len(scoring_raw)}")

    except OllamaError as e:
        progress_stop2.set()
        err_code = getattr(e, "error_code", "VISUAL_EVALUATION_FAILED")
        if "timeout" in str(e).lower() or "超时" in str(e):
            err_code = ERR_STAGE2_TIMEOUT
        print(f"[Visual Eval] Stage 2 FAILED: [{err_code}] {str(e)[:200]}")
        return VisualEvaluationResult(
            status="unavailable",
            error_code=err_code,
            error_message=f"Stage 2 评分失败: {e}",
            total_ms=int((time.perf_counter() - t0) * 1000),
        )

    (debug_dir / f"{ts}_stage2_raw.txt").write_text(scoring_raw, encoding="utf-8")

    # Parse stage 2 JSON
    json_str2 = _extract_json(scoring_raw)
    try:
        scoring_data = json.loads(json_str2)
    except json.JSONDecodeError:
        try:
            repaired = _repair_json(json_str2)
            scoring_data = json.loads(repaired)
        except json.JSONDecodeError:
            print(f"[Visual Eval] Stage 2 JSON parse FAILED, raw preview: {scoring_raw[:300]}")
            return VisualEvaluationResult(
                status="parse_failed",
                error_code=ERR_VISUAL_PARSE_FAILED,
                error_message=f"Stage 2: 评分阶段返回无效JSON。output_len={len(scoring_raw)}",
                total_ms=int((time.perf_counter() - t0) * 1000),
            )

    total_ms = int((time.perf_counter() - t0) * 1000)
    diagnostics["total_elapsed_s"] = round(total_ms / 1000, 1)

    # Merge stage 1 + stage 2 data
    merged_data = {**stage1_data, **scoring_data}

    # Build result
    approach_label = "Plan B (VL both stages)" if single_model else "Plan A (VL + text)"
    visual_result = _parse_visual_result(
        merged_data,
        f"{visual_model} [{approach_label}]",
        image_sha256, orig_size, eval_size,
    )
    visual_result.total_ms = total_ms
    visual_result.model_load_ms = diagnostics.get("model_load_ms", 0)
    visual_result.generation_ms = diagnostics.get("generation_ms", 0)

    # Save full result cache
    full_key = _build_visual_cache_key(task, image_sha256, visual_model, prompt_version)
    _save_full_cached_result(task.task_id, full_key, visual_result)

    # Save final result + diagnostics
    final_output = {
        "result": visual_result.model_dump(),
        "diagnostics": diagnostics,
        "approach": approach_label,
    }
    (debug_dir / f"{ts}_result.json").write_text(
        json.dumps(final_output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"[Visual Eval] DONE total={total_ms / 1000:.1f}s, score={visual_result.visual_consistency_score}, "
          f"approach={approach_label}, stage1_cache_hit={diagnostics['stage1_cache_hit']}")

    return visual_result


# ── Performance comparison ──────────────────────────────

def run_performance_tests(task: Task) -> dict:
    """
    Run real comparison:
      Test A: Plan B (single_model=True) — VL for both stages, Stage 1 cache hit
      Test B: Plan A (single_model=False) — VL + text model

    Returns timing comparison and diagnostic data.
    """
    results = {}
    total_start = time.perf_counter()

    print("=" * 60)
    print("VISUAL EVALUATION PERFORMANCE COMPARISON")
    print(f"Task: {task.task_id}")
    print(f"Time: {_now_iso()}")
    print("=" * 60)

    # ── Test A: Plan B (single VL model, both stages) ──
    # Stage 1 cache should be hit since we already have it
    print("\n--- Test A: Plan B (single VL model, both stages) ---")
    print("  Mode: single_model=True, Stage 1 cache should hit")
    t_a_start = time.perf_counter()
    r_a = evaluate_image_visual(task, force_regenerate=True, single_model=True)
    t_a_elapsed = time.perf_counter() - t_a_start
    results["test_a_single_model"] = {
        "elapsed_s": round(t_a_elapsed, 1),
        "status": r_a.status,
        "score": r_a.visual_consistency_score if r_a.status == "success" else None,
        "model": r_a.model,
    }
    print(f"  Test A result: {t_a_elapsed:.1f}s, status={r_a.status}, score={r_a.visual_consistency_score}")

    # ── Test B: Plan A (VL + text model) ──
    # Stage 1 cache should also hit
    print("\n--- Test B: Plan A (VL + text model) ---")
    print("  Mode: single_model=False, Stage 1 cache should hit")
    t_b_start = time.perf_counter()
    r_b = evaluate_image_visual(task, force_regenerate=True, single_model=False)
    t_b_elapsed = time.perf_counter() - t_b_start
    results["test_b_two_model"] = {
        "elapsed_s": round(t_b_elapsed, 1),
        "status": r_b.status,
        "score": r_b.visual_consistency_score if r_b.status == "success" else None,
        "model": r_b.model,
    }
    print(f"  Test B result: {t_b_elapsed:.1f}s, status={r_b.status}, score={r_b.visual_consistency_score}")

    # ── Summary ──
    total_elapsed = time.perf_counter() - total_start
    print(f"\n--- Summary (total test time: {total_elapsed:.1f}s) ---")
    print(f"  Test A (Plan B, VL only):   {results['test_a_single_model']['elapsed_s']}s  status={results['test_a_single_model']['status']}")
    print(f"  Test B (Plan A, VL+text):   {results['test_b_two_model']['elapsed_s']}s  status={results['test_b_two_model']['status']}")

    a_ok = results["test_a_single_model"]["status"] == "success"
    b_ok = results["test_b_two_model"]["status"] == "success"

    if a_ok and b_ok:
        if results["test_a_single_model"]["elapsed_s"] <= results["test_b_two_model"]["elapsed_s"]:
            winner = "Plan B (VL only)"
            margin = results["test_b_two_model"]["elapsed_s"] - results["test_a_single_model"]["elapsed_s"]
        else:
            winner = "Plan A (VL+text)"
            margin = results["test_a_single_model"]["elapsed_s"] - results["test_b_two_model"]["elapsed_s"]
        print(f"  Winner: {winner} — faster by {margin:.1f}s")
    elif a_ok and not b_ok:
        print(f"  Winner: Plan B (VL only) — Plan A failed with status={results['test_b_two_model']['status']}")
    elif b_ok and not a_ok:
        print(f"  Winner: Plan A (VL+text) — Plan B failed with status={results['test_a_single_model']['status']}")
    else:
        print(f"  Both plans failed. A={results['test_a_single_model']['status']}, B={results['test_b_two_model']['status']}")

    results["_total_test_time_s"] = round(total_elapsed, 1)
    return results
