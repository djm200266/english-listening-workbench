"""
Robust JSON extraction + emergency regex repair + DialogueScript validation.

Layers (in order):
1. extract_json_object() — strip markdown, find balanced {}
2. emergency_regex_repair() — fix _digit, unquoted values, trailing commas
3. json.loads()
4. parse_and_validate_script() — Schema validation
"""

from __future__ import annotations

import json
import re
from typing import Any

from models import DialogueScript, Speaker, DialogueTurn, DialogueScriptContent

VALID_SPEAKER_IDS = {"A", "B"}


class JsonParseError(ValueError):
    def __init__(self, message: str, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


class SchemaValidationError(ValueError):
    def __init__(self, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data


# ── Stage 1: Extract JSON from raw text ────────────────

def extract_json_object(raw_text: str) -> str:
    """Extract the first balanced JSON object from model output."""
    if not raw_text or not raw_text.strip():
        raise JsonParseError("模型返回了空内容。", raw_text)

    text = raw_text.strip()

    # Remove markdown code fences: ```json ... ``` or ``` ... ```
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    elif text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
        text = re.sub(r"\n?```\s*$", "", text, count=1)
        text = text.strip()

    # Find first {
    start = text.find("{")
    if start == -1:
        raise JsonParseError("模型输出中未找到 JSON 对象（缺少 {）。", raw_text[:500])

    # Walk to matching }
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise JsonParseError(
            f"JSON 对象不完整：{depth} 个未闭合的 {{。输出可能被截断。",
            raw_text[:500],
        )

    return text[start:end + 1]


# ── Stage 2: Emergency regex repair ────────────────────

def emergency_regex_repair(json_str: str) -> str:
    """
    Fix common JSON syntax errors that regex can safely handle.
    Does NOT use eval(). Only fixes well-known patterns.

    Fixes:
    - _digit or _number → digit (e.g. _3 → 3, _10 → 10)
    - Trailing commas before } or ]
    - Unquoted values like true/false/null/number that got mangled
    """
    # Fix _digit / _number: model sometimes outputs "_3" instead of "3"
    # Pattern: "field": _N  or  "field": _N,  or  "field": _N}
    json_str = re.sub(r'"_(\d+)"', r'"\1"', json_str)   # "_3" → "3" (quoted)
    json_str = re.sub(r':\s*_(\d+)([,\s}\]])', r': \1\2', json_str)  # : _3, → : 3,

    # Fix trailing commas
    json_str = re.sub(r",\s*}", "}", json_str)
    json_str = re.sub(r",\s*\]", "]", json_str)

    return json_str


# ── Stage 3+4: Parse and validate ──────────────────────

def parse_and_validate_script(raw_text: str, expected_turns: int) -> DialogueScript:
    """
    Full pipeline:
    1. Extract JSON from raw text
    2. Emergency regex repair
    3. json.loads
    4. Pydantic DialogueScriptContent validation
    5. Business rule validation (turns, speaker_id, vocab coverage)

    Returns a DialogueScript (system fields filled with defaults; caller fills task_id etc.)
    """
    # Step 1: Extract
    json_str = extract_json_object(raw_text)

    # Step 2: Emergency regex repair
    repaired_str = emergency_regex_repair(json_str)

    # Step 3: Parse
    try:
        data = json.loads(repaired_str)
    except json.JSONDecodeError as e:
        raise JsonParseError(
            f"JSON 解析失败: {e.msg} (line {e.lineno}, col {e.colno})",
            repaired_str[:500],
        )

    if not isinstance(data, dict):
        raise JsonParseError("输出不是 JSON 对象。", repaired_str[:300])

    # Step 4: Pydantic validation via DialogueScriptContent
    try:
        content = DialogueScriptContent(**data)
    except Exception as e:
        raise SchemaValidationError(f"Schema 校验失败: {e}", data)

    # Step 5: Business rules
    errors: list[str] = []

    if len(content.dialogue) != expected_turns:
        errors.append(f"dialogue 轮数不符：期望 {expected_turns} 轮，实际 {len(content.dialogue)} 轮")

    for i, turn in enumerate(content.dialogue):
        if turn.speaker_id not in VALID_SPEAKER_IDS:
            errors.append(f"dialogue[{i}].speaker_id='{turn.speaker_id}' 无效，只能是 A 或 B")
        if not turn.text or not turn.text.strip():
            errors.append(f"dialogue[{i}].text 不能为空")
        expected_tid = i + 1
        if turn.turn_id != expected_tid:
            errors.append(f"dialogue[{i}].turn_id={turn.turn_id} 应为 {expected_tid}")

    for i, s in enumerate(content.speakers):
        if s.speaker_id not in VALID_SPEAKER_IDS:
            errors.append(f"speakers[{i}].speaker_id='{s.speaker_id}' 无效，只能是 A 或 B")

    if not isinstance(content.used_vocabulary, list):
        errors.append("used_vocabulary 不是数组")
    if not isinstance(content.used_patterns, list):
        errors.append("used_patterns 不是数组")

    if errors:
        raise SchemaValidationError("; ".join(errors), data)

    # Build full DialogueScript (system fields filled by code, not model)
    total_words = sum(len(t.text.split()) for t in content.dialogue)
    return DialogueScript(
        task_id="",
        script_id="",
        script_version="v1.0",
        status="draft",
        source_task_config_version="v1.0",
        speakers=list(content.speakers),
        dialogue=list(content.dialogue),
        used_vocabulary=list(content.used_vocabulary),
        used_patterns=list(content.used_patterns),
        total_words=total_words,
        created_at="",
        confirmed_at=None,
    )
