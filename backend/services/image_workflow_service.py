"""
Image workflow service: topic-aware prompt construction + ComfyUI generation.
Supports: directions (deterministic map), weather (scene panel), story (illustration board).
"""

from __future__ import annotations

import json, os, random, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import get_config
from models import TaskConfig, DialogueScript, ImageAsset, AssetStatus
from services.comfyui_client import ComfyUIClient, ComfyUIError
from services.topic_classifier import classify_topic, get_image_spec
from services.deterministic_map import generate_directions_map
from services.image_style_presets import get_style_preset, get_style_label


def _now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def _assets_dir(task_id: str) -> Path:
    root = get_config().get("assets", {}).get("rootDir", "storage")
    d = Path(root) / task_id / "images"; d.mkdir(parents=True, exist_ok=True); return d


# ---- Grade helper ----

def _grade_label(config: TaskConfig) -> str:
    """Return Chinese grade label for use in image prompts."""
    raw = getattr(config.grade, "value", str(config.grade)) if hasattr(config.grade, "value") else str(config.grade)
    mapping = {"grade_7": "七年级", "grade_8": "八年级", "grade_9": "九年级"}
    return mapping.get(raw, "七年级")


# ---- Topic-specific prompt builders ----

def _prompt_directions(script: DialogueScript | None, config: TaskConfig) -> str:
    entities = _extract_entities(script, config)
    landmarks = ", ".join(entities[:6]) if entities else "library, bank, hospital, school"
    return (
        f"textbook style location reference map, top-down street map view, bright cartoon style for {_grade_label(config)} English textbook, "
        f"clear street layout with buildings: {landmarks}, "
        f"road arrows showing directions, simple labels, clean white background, "
        f"educational illustration, children's textbook map, colorful landmarks, "
        f"NO human characters, NO portraits, NO indoor scenes, NO dialogue bubbles"
    )

def _prompt_weather(script: DialogueScript | None, config: TaskConfig) -> str:
    cities = _extract_cities(script, config)
    weathers = _extract_weather_states(script)
    if not cities:
        cities = ["Beijing", "Shanghai", "Moscow"]
    if not weathers:
        weathers = ["sunny", "rainy", "cloudy"]
    panels = min(len(cities), 4)
    desc = " | ".join(f"{c}: {w}" for c, w in zip(cities[:panels], weathers[:panels] * panels))
    return (
        f"textbook style weather reference panel, {panels} weather comparison panels, "
        f"{desc}, "
        f"cartoon educational illustration for {_grade_label(config)} English, children's textbook weather map, "
        f"each panel showing distinct weather with city landmark silhouette, bright colors, clean layout, "
        f"NO portrait photos, NO human faces dominating, weather icons visible"
    )

def _prompt_story(script: DialogueScript | None, config: TaskConfig) -> str:
    chars = _extract_characters(script)
    events = _extract_events(script)
    char_desc = ", ".join(chars[:3]) if chars else "story characters"
    event_desc = ", ".join(events[:3]) if events else "key story moment"
    panels = 3 if len(events) >= 3 else (2 if len(events) >= 2 else 1)
    return (
        f"textbook style story illustration, {panels} comic panels showing: {event_desc}, "
        f"characters: {char_desc}, "
        f"cartoon children's book style for {_grade_label(config)} English textbook, bright colors, simple bold lines, "
        f"clear story sequence, educational illustration, action scenes, "
        f"kid-friendly, warm tones, suitable for classroom"
    )

def _prompt_fallback(script: DialogueScript | None, config: TaskConfig) -> str:
    scenario = config.scenario or config.topic
    return (
        f"English teaching illustration for {_grade_label(config)} classroom, clear and simple, suitable for children, "
        f"scene of {scenario}, cartoon style, bright colors, simple lines"
    )

PROMPT_BUILDERS = {
    "directions": _prompt_directions,
    "weather": _prompt_weather,
    "story": _prompt_story,
    "fallback": _prompt_fallback,
}

NEGATIVE_BY_TOPIC = {
    "directions": "human faces, portraits, people, indoor, dialogue, speech bubbles, dark, realistic photo",
    "weather": "portrait, human faces closeup, dark, realistic photo, single panel only, text heavy",
    "story": "photorealistic, dark horror, abstract, map style, weather chart",
    "fallback": "blurry, low quality, ugly, text, watermark, dark, scary, nsfw",
}

STYLE_MAP = {"textbook_directions_map": "cartoon", "textbook_weather_panel": "children_book", "textbook_story_board": "children_book", "default_teaching_style": "cartoon"}


# ---- Entity extractors ----

def _extract_entities(script, config) -> list[str]:
    entities = set()
    if script:
        for t in script.dialogue:
            for w in ["library","bank","hospital","school","post office","supermarket","hotel","restaurant","museum","park","station","airport","bookstore","pharmacy","bridge","corner","street","road","bus stop"]:
                if w in t.text.lower(): entities.add(w.title())
        for v in script.used_vocabulary: entities.add(v)
    if config.required_vocabulary:
        for v in config.required_vocabulary: entities.add(v)
    return list(entities)[:8]

def _extract_cities(script, config) -> list[str]:
    city_names = {"beijing","shanghai","moscow","london","new york","tokyo","sydney","paris","toronto","boston","chicago","seoul","bangkok","singapore","hong kong","berlin","rome"}
    found = set()
    if script:
        for t in script.dialogue:
            for city in city_names:
                if city in t.text.lower(): found.add(city.title())
    return list(found)

def _extract_weather_states(script) -> list[str]:
    states = {"sunny","rainy","cloudy","windy","snowy","stormy","hot","cold","warm","cool","foggy","raining","snowing"}
    found = set()
    if script:
        for t in script.dialogue:
            for s in states:
                if s in t.text.lower(): found.add(s)
    return list(found)

def _extract_characters(script) -> list[str]:
    if not script: return []
    roles = list({s.role for s in script.speakers if s.role})
    return roles if roles else ["main character"]

def _goal_to_image_type(goal: str) -> str:
    mapping = {
        "reference_map": "location_reference_map",
        "weather_visual": "weather_reference_scene",
        "story_panel": "story_reference_illustration",
        "scene": "topic_scene_illustration",
        "vocab_visual": "vocab_visual",
        "classroom_poster": "classroom_poster",
        "auto": "",
    }
    return mapping.get(goal, "topic_scene_illustration")

def _build_prompt_from_user_input(user_input: str, config: TaskConfig, script) -> str:
    goal = getattr(config, "image_goal", "auto") or "auto"
    style = str(getattr(config, "image_style", "cartoon"))
    gl = _grade_label(config)
    guidance = {
        "reference_map": "top-down street map view, clear layout with labeled buildings, road arrows, no human figures dominant",
        "weather_visual": "weather comparison panels, distinct weather icons, city silhouettes, no close-up human portraits",
        "story_panel": "comic panel layout, clear story sequence, key action scenes, cartoon style",
        "scene": "scene with two characters, clear location background, educational illustration",
        "vocab_visual": "grid of vocabulary items with clear visual representations, labeled, educational",
        "classroom_poster": "classroom poster design, colorful, informative, large clear visuals, teaching aid style",
        "auto": f"educational illustration for {gl} classroom, clear and simple",
    }.get(goal, f"educational illustration for {gl} classroom")
    return (
        f"Educational illustration for {gl} English, {guidance}, "
        f"{style} style, textbook quality, bright colors, clean lines. "
        f"Scene: {user_input}"
    )

def _extract_events(script) -> list[str]:
    if not script: return []
    texts = [t.text for t in script.dialogue if len(t.text) > 20]
    return texts[:4]


# ---- Main ----

class ImageGenerationResult:
    def __init__(self, image_id: str, image_path: str, image_url: str,
                 prompt: str, negative_prompt: str, seed: int, style: str,
                 width: int, height: int, source_script_version: str,
                 generation_latency_ms: int, model_name: str,
                 topic_type: str = "fallback", image_type: str = "",
                 style_preset: str = "", render_mode: str = "comfyui_direct",
                 comfyui_used: bool = True, prompt_source: str = "auto",
                 image_goal: str = "auto") -> None:
        self.image_id = image_id; self.image_path = image_path; self.image_url = image_url
        self.prompt = prompt; self.negative_prompt = negative_prompt; self.seed = seed
        self.style = style; self.width = width; self.height = height
        self.source_script_version = source_script_version
        self.generation_latency_ms = generation_latency_ms; self.model_name = model_name
        self.topic_type = topic_type; self.image_type = image_type
        self.style_preset = style_preset; self.render_mode = render_mode
        self.comfyui_used = comfyui_used
        self.prompt_source = prompt_source; self.image_goal = image_goal


def generate_image(task_id: str, config: TaskConfig, script: DialogueScript | None) -> ImageGenerationResult:
    """
    Priority-based image generation:
    1. image_prompt_enhanced (user-edited enhanced prompt) - highest priority
    2. image_prompt_input (user rough prompt, auto-enhance first)
    3. Auto topic classification (directions/weather/story/fallback)
    """
    src_ver = script.script_version if script else "v1.0"
    cfg = get_config().get("comfyui", {})
    width = int(cfg.get("width", 1024))
    height = int(cfg.get("height", 1024))
    prompt_source = "auto"

    # Determine image_goal
    image_goal = getattr(config, "image_goal", "auto") or "auto"
    user_enhanced = getattr(config, "image_prompt_enhanced", "") or ""
    user_input = getattr(config, "image_prompt_input", "") or ""

    # Determine topic_type and image_type from goal or classification
    if image_goal != "auto":
        topic_type = image_goal
        image_type = _goal_to_image_type(image_goal)
    elif script:
        topic_type = classify_topic(script)
        spec = get_image_spec(topic_type)
        image_type = spec["image_type"]
    else:
        topic_type = "fallback"
        image_type = "topic_scene_illustration"

    # ---- reference_map: deterministic only for structured_schematic ----
    raw_style = str(getattr(config, "image_style", "textbook_cartoon") or "textbook_cartoon")
    # Normalize legacy style values
    legacy_map = {"cartoon": "textbook_cartoon", "children_book": "textbook_cartoon",
                  "flat": "flat_vector", "realistic": "photorealistic"}
    raw_style = legacy_map.get(raw_style, raw_style)
    structured_only = {"structured_schematic", "structured", "diagram", "deterministic_map"}
    is_reference = (image_goal == "reference_map" or image_type == "location_reference_map")

    if is_reference and raw_style in structured_only:
        render_mode = "structured_map"
    elif is_reference:
        render_mode = "comfyui_styled_map"
    else:
        spec = get_image_spec(topic_type)
        render_mode = spec["render_mode"]
        size = spec["default_size"]
        width, height = size["width"], size["height"]

    # Build prompt based on priority
    if user_enhanced.strip():
        positive = user_enhanced.strip()
        prompt_source = "enhanced"
    elif user_input.strip():
        positive = _build_prompt_from_user_input(user_input, config, script)
        prompt_source = "input"
    else:
        positive = ""
        prompt_source = "auto"

    style_preset = "textbook_directions_map" if render_mode == "structured_map" else "default_teaching_style"

    # ---- Structured map (PIL deterministic) ----
    if render_mode == "structured_map":
        entities = _extract_entities(script, config)
        route = _build_route_from_script(script) if script else []
        t0 = time.perf_counter()
        output_path = generate_directions_map(task_id, entities, route, grade_label=_grade_label(config))
        latency = int((time.perf_counter() - t0) * 1000)
        assets_root = get_config().get("assets", {}).get("rootDir", "storage")
        rel = os.path.relpath(output_path, assets_root).replace("\\", "/")
        img_url = f"/assets/{rel}"
        return ImageGenerationResult(
            image_id=f"IMG_{task_id}", image_path=output_path, image_url=img_url,
            prompt="deterministic_map", negative_prompt="", seed=0,
            style="cartoon", width=width, height=height,
            source_script_version=src_ver, generation_latency_ms=latency,
            model_name="PIL_deterministic", topic_type=topic_type,
            image_type=image_type, style_preset=style_preset,
            render_mode=render_mode, comfyui_used=False,
            prompt_source=prompt_source, image_goal=image_goal,
        )

    # ---- Ensure ComfyUI is running ----
    from services.comfyui_process_manager import get_comfyui_manager
    mgr = get_comfyui_manager()
    if not mgr.is_running():
        result = mgr.ensure_running()
        if not result["ok"]:
            raise ComfyUIError(
                f"ComfyUI 后台启动失败: {result.get('message', 'unknown')}\n"
                f"日志: {result.get('log_path', '')}"
            )

    # ---- ComfyUI generation (styled reference maps / weather / story / fallback) ----
    raw_style = str(getattr(config, "image_style", "textbook_cartoon") or "textbook_cartoon")
    style_data = get_style_preset(raw_style)

    if render_mode == "comfyui_styled_map":
        # Build styled reference map prompt
        entities = _extract_entities(script, config)
        landmarks = ", ".join(entities[:6]) if entities else "library, bank, hospital, park"
        relations = _extract_relations(script) if script else "next to, across from"
        final_positive = (
            f"Educational location reference map for {_grade_label(config)} English, "
            f"top-down or isometric street layout showing labeled landmarks: {landmarks}. "
            f"Clear roads with directional arrows showing spatial relationships ({relations}). "
            f"Clean map composition with clear visual structure. "
            f"{style_data['positive']}. "
            f"NO classroom interior, NO indoor scene, NO character portraits, NO photorealistic faces."
        )
        if positive and positive.strip():
            final_positive = f"{positive}, {style_data['positive']}"
    else:
        # Build prompt from topic builder
        prompt_builder = PROMPT_BUILDERS.get(topic_type, _prompt_fallback)
        base_prompt = prompt_builder(script, config)
        if positive and positive != base_prompt:
            final_positive = f"{positive}, {style_data['positive']}"
        else:
            final_positive = base_prompt

    # Build negative
    base_negative = NEGATIVE_BY_TOPIC.get(topic_type, NEGATIVE_BY_TOPIC["fallback"])
    if render_mode == "comfyui_styled_map":
        base_negative = "classroom interior, school classroom, indoor room, portrait, close-up characters, conversation scene, photorealistic faces, dark, scary"
    final_negative = f"{base_negative}, {style_data['negative']}"

    seed = random.randint(0, 2**63 - 1)

    client = ComfyUIClient()
    workflow = _load_workflow_template()
    prefix = f"{task_id}_{topic_type}_{raw_style}"
    wf = _substitute_workflow(workflow, final_positive, final_negative, seed, width, height, prefix)

    # Save debug files
    _save_debug(task_id, final_positive, final_negative, wf)

    t0 = time.perf_counter()
    prompt_id = client.submit_workflow(wf)
    history = client.wait_for_result(prompt_id)
    images = client.get_image_info(history)
    if not images: raise ComfyUIError("ComfyUI did not return any images.")
    img_info = images[0]
    assets = _assets_dir(task_id)
    filename = img_info["filename"]
    output_path = str(assets / filename)
    client.download_image(filename=filename, subfolder=img_info.get("subfolder",""), output_path=output_path)
    latency = int((time.perf_counter() - t0) * 1000)
    assets_root = get_config().get("assets", {}).get("rootDir", "storage")
    rel = os.path.relpath(output_path, assets_root).replace("\\", "/")

    # Save metadata
    meta = {"task_id": task_id, "topic_type": topic_type, "image_type": image_type,
            "style_preset": style_preset, "render_mode": render_mode,
            "prompt_summary": positive[:200], "width": width, "height": height,
            "generated_at": _now_iso(), "generation_duration_ms": latency,
            "comfyui_used": True, "source_script_status": script.status if script else "none"}
    meta_path = str(assets / "image_v1_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return ImageGenerationResult(
        image_id=f"IMG_{task_id}", image_path=output_path, image_url=f"/assets/{rel}",
        prompt=final_positive, negative_prompt=final_negative, seed=seed,
        style=raw_style, width=width, height=height,
        source_script_version=src_ver, generation_latency_ms=latency,
        model_name=cfg.get("checkpoint", "sd_xl_base_1.0.safetensors"),
        topic_type=topic_type, image_type=image_type, style_preset=style_preset,
        render_mode=render_mode, comfyui_used=True,
        prompt_source=prompt_source, image_goal=image_goal,
    )


def _save_debug(task_id: str, positive: str, negative: str, workflow: dict | None = None):
    debug_dir = Path(__file__).parent.parent.parent / "logs" / "image_gen" / task_id
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "final_positive_prompt.txt").write_text(positive, encoding="utf-8")
    (debug_dir / "final_negative_prompt.txt").write_text(negative, encoding="utf-8")
    if workflow:
        (debug_dir / "submitted_workflow.json").write_text(
            json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
        # Save prompt node mapping for debugging
        mapping = {"positive_node": "6", "negative_node": "7", "sampler_node": "10",
                   "checkpoint_node": "4", "latent_node": "5", "output_node": "19"}
        (debug_dir / "prompt_node_mapping.json").write_text(
            json.dumps(mapping, indent=2), encoding="utf-8")

def _extract_relations(script: DialogueScript) -> str:
    rels = set()
    rel_map = {"next to": "next to", "across from": "across from", "between": "between",
               "behind": "behind", "in front of": "in front of", "near": "near",
               "turn left": "turn left at", "turn right": "turn right at"}
    for t in script.dialogue:
        txt = t.text.lower()
        for kw, rel in rel_map.items():
            if kw in txt:
                rels.add(rel)
    return ", ".join(rels) if rels else "next to, across from"

def _build_route_from_script(script: DialogueScript) -> list[str]:
    steps = []
    for t in script.dialogue:
        txt = t.text.lower()
        if "turn left" in txt: steps.append("turn left")
        elif "turn right" in txt: steps.append("turn right")
        elif "go straight" in txt: steps.append("go straight")
        elif "go along" in txt: steps.append("go along")
    return steps

def _load_workflow_template() -> dict[str, Any]:
    cfg = get_config().get("comfyui", {})
    rel = cfg.get("workflowPath", "backend/workflows/sdxl_cartoon_api.fixed.json")
    project_root = Path(__file__).parent.parent.parent
    wf_path = project_root / rel
    if not wf_path.exists():
        fallback = project_root / "backend/workflows/sdxl_cartoon_api.json"
        if fallback.exists(): wf_path = fallback
        else: raise RuntimeError(f"Workflow file not found: {wf_path}")
    with open(wf_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _substitute_workflow(wf, pos, neg, seed, w, h, prefix):
    if seed is None: seed = random.randint(0, 2**63-1)
    wf = json.loads(json.dumps(wf))
    wf["6"]["inputs"]["text"] = pos; wf["7"]["inputs"]["text"] = neg
    wf["10"]["inputs"]["noise_seed"] = seed
    wf["5"]["inputs"]["width"] = w; wf["5"]["inputs"]["height"] = h
    wf["19"]["inputs"]["filename_prefix"] = prefix
    return wf

def build_image_asset(result: ImageGenerationResult, source_script_version: str) -> ImageAsset:
    return ImageAsset(
        image_id=result.image_id, image_url=result.image_url,
        image_source_script_version=source_script_version,
        generation_status=AssetStatus.SUCCESS, is_outdated=False,
        model_name=result.model_name, model_version="1.0",
        prompt_version="v1.0", generation_latency_ms=result.generation_latency_ms,
        estimated_cost=0.0,
        topic_type=result.topic_type, image_type=result.image_type,
        style_preset=result.style_preset, render_mode=result.render_mode,
    )
