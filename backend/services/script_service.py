"""
Script generation via Ollama with JSON Schema structured output.

Strategy:
- Pass DialogueScriptContent.model_json_schema() as Ollama `format`
- temperature=0, num_predict=4096
- On failure: distinguish syntax/truncation/schema and retry appropriately
- Emergency regex repair handles common typos (_digit, trailing commas)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import TaskConfig, DialogueScript, DialogueScriptContent
from services.json_parser import (
    JsonParseError,
    SchemaValidationError,
    extract_json_object,
    emergency_regex_repair,
    parse_and_validate_script,
)
from services.ollama_client import OllamaClient, OllamaError

# ── Logging ────────────────────────────────────────────

LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "script_gen"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_log(filename: str, content: str) -> None:
    (LOGS_DIR / filename).write_text(content, encoding="utf-8")


def _log_call(call_id: str, raw: str, cleaned: str, repaired: str | None,
              errors: list[str] | None, prompt_version: str, model_name: str,
              latency_sec: float, retry_count: int, outcome: str) -> None:
    ts = _now_iso().replace(":", "-")
    prefix = f"{ts}_{call_id}"
    _write_log(f"{prefix}_raw_response.txt", raw)
    _write_log(f"{prefix}_cleaned_response.txt", cleaned)
    if repaired is not None:
        _write_log(f"{prefix}_repaired_response.txt", repaired)
    if errors:
        _write_log(f"{prefix}_parse_errors.json", json.dumps(errors, indent=2, ensure_ascii=False))
    meta = {
        "call_id": call_id,
        "prompt_version": prompt_version,
        "model_name": model_name,
        "latency_sec": round(latency_sec, 3),
        "retry_count": retry_count,
        "outcome": outcome,
        "timestamp": _now_iso(),
    }
    _write_log(f"{prefix}_meta.json", json.dumps(meta, indent=2, ensure_ascii=False))


# ── Topic Classification ──────────────────────────────────

def _classify_topic(config: TaskConfig) -> str:
    """Classify the task into a script type based on topic, scenario, and additional_instruction.
    NEVER use task_id for classification — only real task fields."""
    text = f"{config.topic} {config.scenario} {config.additional_instruction} {config.task_name}".lower()

    # Story detection (must come before directions — "mountain" alone should not trigger directions)
    story_keywords = [
        "故事", "story", "讲述", "tell", "tale", "fable", "寓言", "神话", "legend",
        "narrator", "narrate", "happened", "once upon", "long ago", "愚公", "移山",
        "嫦娥", "后羿", "西游记", "journey to the west", "mulan", "木兰",
        "猴子", "monkey king", "孙悟空",
    ]
    if any(kw in text for kw in story_keywords):
        return "story"

    # Directions detection
    directions_keywords = [
        "问路", "direction", "location", "where is", "how to get to",
        "turn left", "turn right", "go straight", "across from", "next to",
        "library", "hospital", "bank", "post office", "supermarket",
        "地图", "map", "路线", "route",
    ]
    if any(kw in text for kw in directions_keywords):
        return "directions"

    # Weather detection
    weather_keywords = [
        "天气", "weather", "sunny", "rainy", "cloudy", "snowy",
        "temperature", "forecast", "气候", "预报",
    ]
    if any(kw in text for kw in weather_keywords):
        return "weather"

    # Shopping / daily dialogue
    daily_keywords = [
        "购物", "shopping", "点餐", "order", "restaurant", "商店", "store",
        "buy", "买", "卖", "sell", "日常", "daily", "conversation",
        "打电话", "phone", "邀请", "invite",
    ]
    if any(kw in text for kw in daily_keywords):
        return "daily_dialogue"

    # Discussion
    discussion_keywords = [
        "讨论", "discussion", "debate", "辩论", "观点", "opinion",
        "话题", "topic discussion",
    ]
    if any(kw in text for kw in discussion_keywords):
        return "discussion"

    # Interview
    interview_keywords = [
        "采访", "interview", "访问", "专访",
    ]
    if any(kw in text for kw in interview_keywords):
        return "interview"

    return "general"


def _get_speaker_roles(topic_type: str, role_count: int) -> list[dict[str, str]]:
    """Suggest speaker roles based on topic type and role count. Model may override."""
    if topic_type == "story":
        if role_count == 1:
            return [{"id": "A", "role": "Narrator"}]
        elif role_count == 2:
            return [{"id": "A", "role": "Narrator"}, {"id": "B", "role": "Main Character"}]
        elif role_count == 3:
            return [{"id": "A", "role": "Narrator"}, {"id": "B", "role": "Main Character"}, {"id": "C", "role": "Supporting Character"}]
        else:
            return [{"id": "A", "role": "Narrator"}, {"id": "B", "role": "Character 1"}, {"id": "C", "role": "Character 2"}, {"id": "D", "role": "Character 3"}]
    elif topic_type == "directions":
        if role_count == 1:
            return [{"id": "A", "role": "Speaker"}]
        elif role_count == 2:
            return [{"id": "A", "role": "Student"}, {"id": "B", "role": "Passer-by"}]
        else:
            roles = [{"id": "A", "role": "Student"}, {"id": "B", "role": "Passer-by"}]
            for i in range(2, role_count):
                roles.append({"id": chr(ord("A") + i), "role": f"Person {i + 1}"})
            return roles
    elif topic_type == "weather":
        if role_count == 1:
            return [{"id": "A", "role": "Weather Reporter"}]
        else:
            roles = [{"id": "A", "role": "Student 1"}, {"id": "B", "role": "Student 2"}]
            for i in range(2, role_count):
                roles.append({"id": chr(ord("A") + i), "role": f"Student {i + 1}"})
            return roles
    else:
        # General — generate generic roles
        roles = []
        for i in range(role_count):
            rid = chr(ord("A") + i)
            roles.append({"id": rid, "role": f"Speaker {rid}"})
        return roles


# ── Prompts ─────────────────────────────────────────────

def _load_prompt() -> dict[str, Any]:
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "P-SCRIPT.json"
    if not prompt_path.exists():
        raise RuntimeError(f"Prompt file not found: {prompt_path}")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_user_prompt(config: TaskConfig) -> str:
    grade_val = getattr(config.grade, "value", str(config.grade)) if hasattr(config.grade, "value") else str(config.grade)
    grade_map = {"grade_7": "七年级 (grade_7)", "grade_8": "八年级 (grade_8)", "grade_9": "九年级 (grade_9)"}
    grade_display = grade_map.get(grade_val, "七年级 (grade_7)")

    # Classify topic type
    topic_type = _classify_topic(config)

    # Resolve role count
    raw_rc = getattr(config, "speaker_count", 2)
    if raw_rc == "auto" or raw_rc is None:
        role_count_mode = "auto"
        # Suggest based on topic type
        if topic_type == "story":
            suggested_count = 3
        elif topic_type == "discussion":
            suggested_count = 3
        elif topic_type == "interview":
            suggested_count = 3
        elif topic_type == "directions":
            suggested_count = 2
        else:
            suggested_count = 2
        role_count = suggested_count
    else:
        role_count_mode = "fixed"
        role_count = int(raw_rc)

    suggested_roles = _get_speaker_roles(topic_type, role_count)
    roles_desc = ", ".join(f"{r['id']}={r['role']}" for r in suggested_roles)

    parts = [
        f"SCRIPT TYPE: {topic_type}",
        f"Grade: {grade_display}",
        f"Topic: {config.topic}",
        f"Scenario: {config.scenario}",
    ]

    if role_count_mode == "auto":
        parts.append(f"Role count: auto (system suggests {role_count} speaker(s): {roles_desc}. You may adjust based on the scenario.)")
    else:
        parts.append(f"Role count: EXACTLY {role_count} speaker(s). Suggested roles: {roles_desc}. You MUST use exactly {role_count} speakers — no more, no fewer. Adjust role names to match the scenario if needed.")

    # Topic-specific guidance
    if topic_type == "story":
        parts.append("This is a STORY task. Generate a narrative script (can be a single Narrator telling the story, or Narrator + characters with dialogue). Include: background setup, key events, conflict, and resolution/moral. Use past tense and story-telling language appropriate for the grade level. Do NOT turn this into a directions dialogue or any other script type.")
    elif topic_type == "directions":
        parts.append("This is a DIRECTIONS task. Generate a dialogue where someone asks for and receives directions to a location.")
    elif topic_type == "weather":
        parts.append("This is a WEATHER task. Generate content about weather conditions and discussion.")
    elif topic_type == "daily_dialogue":
        parts.append("This is a DAILY DIALOGUE task. Generate a natural everyday conversation appropriate for the scenario.")
    elif topic_type == "discussion":
        parts.append("This is a DISCUSSION task. Generate a multi-perspective discussion on the topic.")

    # Vocabulary
    if config.required_vocabulary:
        parts.append(f"Required vocabulary (MUST appear naturally in the script): {', '.join(config.required_vocabulary)}")
    else:
        parts.append("Required vocabulary: (system will auto-select appropriate words based on grade/topic/scenario)")
    if config.optional_vocabulary:
        parts.append(f"Optional vocabulary: {', '.join(config.optional_vocabulary)}")

    # Patterns
    if config.target_patterns:
        parts.append(f"Target sentence patterns (MUST appear naturally): {', '.join(config.target_patterns)}")
    else:
        parts.append("Target sentence patterns: (system will auto-design 2-4 core patterns appropriate for the script type and grade)")

    parts.append(f"Dialogue turns: {config.dialogue_turns}")
    parts.append(f"Audio target: ~{config.audio_duration_target_sec}s")
    if config.additional_instruction:
        parts.append(f"Additional instructions: {config.additional_instruction}")

    return "\n".join(parts)


REPAIR_SYSTEM_PROMPT = """You are a JSON repair tool. Fix ONLY syntax errors in the malformed JSON below.

RULES:
1. Fix syntax only — do NOT add, remove, or change any dialogue content, speaker names, vocabulary, or facts.
2. Ensure: first char is {, last char is }, no trailing commas, all strings/keys in double quotes.
3. Output ONLY the repaired JSON object — no markdown, no ```json, no explanation.
4. The dialogue MUST have exactly the same number of turns as the original."""


def _build_repair_prompt(raw_output: str, expected_turns: int, errors: list[str]) -> str:
    error_text = "\n".join(f"- {e}" for e in errors)
    return (
        f"VALIDATION ERRORS:\n{error_text}\n\n"
        f"Expected turns: {expected_turns}\n\n"
        f"MALFORMED JSON:\n```\n{raw_output[:4000]}\n```\n\n"
        f"Output ONLY the repaired JSON."
    )


# ── Schema ──────────────────────────────────────────────

# Get JSON Schema once at module load
CONTENT_SCHEMA = DialogueScriptContent.model_json_schema()


# ── Detection helpers ───────────────────────────────────

def _is_truncated(raw_text: str, json_str: str) -> bool:
    """Heuristic: check if model output appears cut off."""
    # If extract_json_object failed with "unclosed braces"
    depth = 0
    in_string = False
    escape = False
    for ch in json_str or raw_text:
        if escape:
            escape = False; continue
        if ch == "\\": escape = True; continue
        if ch == '"': in_string = not in_string; continue
        if in_string: continue
        if ch == "{": depth += 1
        elif ch == "}": depth -= 1
    if depth > 0:
        return True
    # Raw text ends with non-whitespace that isn't }
    stripped = raw_text.rstrip()
    if stripped and not stripped.endswith("}"):
        return True
    return False


# ── Post-generation validation ───────────────────────────

def _validate_speaker_ids(script: DialogueScript, call_id: str) -> None:
    """Ensure every dialogue turn's speaker_id exists in the declared speakers list."""
    valid_ids = {s.speaker_id for s in script.speakers}
    for turn in script.dialogue:
        if turn.speaker_id not in valid_ids:
            raise ValueError(
                f"Script validation failed: Turn {turn.turn_id} uses speaker_id='{turn.speaker_id}' "
                f"which is not in the declared speaker list. Valid IDs: {sorted(valid_ids)}"
            )
    # Also check all declared speakers have at least one line
    used_ids = {t.speaker_id for t in script.dialogue}
    unused = valid_ids - used_ids
    if unused:
        # Log warning but don't fail — some roles may be silent in certain scripts
        import logging
        logging.getLogger(__name__).warning(
            f"[{call_id}] Declared speakers without dialogue: {sorted(unused)}"
        )


# ── Results ────────────────────────────────────────────

class ScriptGenerationResult:
    def __init__(self, script: DialogueScript, model_name: str, model_version: str,
                 prompt_version: str, generation_latency_ms: int, retry_count: int,
                 raw_output: str) -> None:
        self.script = script
        self.model_name = model_name
        self.model_version = model_version
        self.prompt_version = prompt_version
        self.generation_latency_ms = generation_latency_ms
        self.retry_count = retry_count
        self.raw_output = raw_output


# ── Main ────────────────────────────────────────────────

def generate_script(config: TaskConfig, task_id: str) -> ScriptGenerationResult:
    prompt_data = _load_prompt()
    system_prompt = prompt_data["system_prompt"]
    prompt_version = prompt_data["version"]
    user_prompt = _build_user_prompt(config)
    expected_turns = config.dialogue_turns

    client = OllamaClient()
    call_id = task_id
    retry_count = 0
    raw_content = ""
    all_errors: list[str] = []
    last_repaired: str | None = None

    # ── Attempt 1: Schema-constrained generation ──
    start = time.perf_counter()
    result1 = client.chat(
        system_prompt, user_prompt,
        temperature=0.0,
        num_predict=4096,
    )
    raw_content = result1["content"]
    model_name = result1["model"]

    # Try parsing first attempt
    try:
        script = parse_and_validate_script(raw_content, expected_turns)
        _validate_speaker_ids(script, call_id)
        latency = int((time.perf_counter() - start) * 1000)
        _log_call(call_id, raw_content, raw_content, None, None, prompt_version,
                  model_name, latency / 1000, 0, "first_attempt_success")
        return ScriptGenerationResult(script, model_name, model_name,
                                       prompt_version, latency, 0, raw_content)
    except (JsonParseError, SchemaValidationError) as e:
        all_errors.append(f"First attempt: {e}")

    # ── Determine failure type ──
    extracted = ""
    try:
        extracted = extract_json_object(raw_content)
    except JsonParseError:
        pass

    is_truncated = _is_truncated(raw_content, extracted)

    # ── Attempt 2: Strategy depends on failure type ──
    retry_count = 1

    if is_truncated:
        # OUTPUT_TRUNCATED: re-generate with higher num_predict
        try:
            result2 = client.chat(
                system_prompt, user_prompt,
                temperature=0.0,
                num_predict=8192,
            )
            raw2 = result2["content"]
            try:
                script = parse_and_validate_script(raw2, expected_turns)
                _validate_speaker_ids(script, call_id)
                latency = int((time.perf_counter() - start) * 1000)
                _log_call(call_id, raw_content, raw_content, raw2, all_errors, prompt_version,
                          result2["model"], latency / 1000, 1, "regenerate_success_after_truncation")
                return ScriptGenerationResult(script, result2["model"], result2["model"],
                                               prompt_version, latency, 1, raw2)
            except (JsonParseError, SchemaValidationError) as e:
                all_errors.append(f"Re-generate (truncation fix): {e}")
        except OllamaError as e:
            all_errors.append(f"Re-generate failed: {e}")
    else:
        # JSON syntax or schema error: try repair
        # First apply emergency regex repair
        if extracted:
            regex_fixed = emergency_regex_repair(extracted)
            if regex_fixed != extracted:
                try:
                    script = parse_and_validate_script(regex_fixed, expected_turns)
                    _validate_speaker_ids(script, call_id)
                    latency = int((time.perf_counter() - start) * 1000)
                    _log_call(call_id, raw_content, extracted, regex_fixed, all_errors, prompt_version,
                              model_name, latency / 1000, 1, "regex_repair_success")
                    return ScriptGenerationResult(script, model_name, model_name,
                                                   prompt_version, latency, 1, regex_fixed)
                except (JsonParseError, SchemaValidationError) as e:
                    all_errors.append(f"Regex repair: {e}")

        # Regex didn't help — try Ollama repair
        repair_prompt = _build_repair_prompt(raw_content, expected_turns, all_errors)
        try:
            repair_result = client.chat(
                REPAIR_SYSTEM_PROMPT, repair_prompt,
                temperature=0.0,
                format_json=True,
                num_predict=4096,
            )
            last_repaired = repair_result["content"]
            try:
                script = parse_and_validate_script(last_repaired, expected_turns)
                _validate_speaker_ids(script, call_id)
                latency = int((time.perf_counter() - start) * 1000)
                _log_call(call_id, raw_content, raw_content, last_repaired, all_errors, prompt_version,
                          repair_result["model"], latency / 1000, 1, "repair_success")
                return ScriptGenerationResult(script, repair_result["model"], repair_result["model"],
                                               prompt_version, latency, 1, last_repaired)
            except (JsonParseError, SchemaValidationError) as e:
                all_errors.append(f"Repair: {e}")
        except OllamaError as e:
            all_errors.append(f"Repair call failed: {e}")

    # ── All attempts exhausted ──
    latency = int((time.perf_counter() - start) * 1000)
    _log_call(call_id, raw_content, raw_content, last_repaired, all_errors, prompt_version,
              model_name, latency / 1000, retry_count,
              "failed" if is_truncated else "failed")

    raise ValueError(
        f"模型返回格式不符合要求，系统自动修复后仍失败，请重试。\n"
        f"错误详情: {'; '.join(all_errors[-3:])}"
    )
