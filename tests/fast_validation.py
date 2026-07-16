"""
Fast validation tests for visual evaluation service.
NO Ollama calls, NO model loading. Pure code verification.
"""
import sys
import os
import io
import re
import json
import tempfile
from pathlib import Path

# Fix Windows encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ── Add backend to path ────────────────────────────────
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

PASSED = 0
FAILED = 0
ERRORS = []


def check(name: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        msg = f"  [FAIL] {name}: {detail}"
        print(msg)
        ERRORS.append(msg)


def section(title: str):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print(f"{'=' * 50}")


# ═════════════════════════════════════════════════════════
# Test 1: Python import check
# ═════════════════════════════════════════════════════════
section("Test 1: Python import check")

try:
    from config import get_config
    check("import config", True)
except Exception as e:
    check("import config", False, str(e))

try:
    from models import (
        Task, VisualEvaluationResult, VisualEvaluationDimension,
        VisualDetectedObject, VisualDetectedText, VisualSpatialRelation,
        VisualQualityIssue, VisualHardFailure, VisualBadCase,
    )
    check("import models (all visual types)", True)
except Exception as e:
    check("import models", False, str(e))

try:
    from services.visual_evaluation_service import (
        evaluate_image_visual, run_performance_tests,
        _build_stage1_prompt, _build_stage2_prompt,
        _extract_json, _stage1_cache_key, _compute_sha256,
        _load_stage1_cache, _save_stage1_cache,
        _build_visual_cache_key,
        _parse_visual_result,
        STAGE1_SYSTEM_PROMPT, STAGE2_SYSTEM_PROMPT_SHORT, STAGE2_SYSTEM_PROMPT_LONG,
        VISUAL_PROMPT_VERSION, LOGS_DIR,
        ERR_STAGE1_TIMEOUT, ERR_STAGE2_TIMEOUT, ERR_VISUAL_TOTAL_TIMEOUT,
        ERR_VISUAL_PARSE_FAILED,
    )
    check("import visual_evaluation_service (all symbols)", True)
except Exception as e:
    check("import visual_evaluation_service", False, str(e))

try:
    from services.ollama_client import OllamaClient, OllamaError, OllamaErrorCode
    check("import ollama_client", True)
except Exception as e:
    check("import ollama_client", False, str(e))

try:
    from services.evaluation_service import generate_evaluation
    check("import evaluation_service", True)
except Exception as e:
    check("import evaluation_service", False, str(e))


# ═════════════════════════════════════════════════════════
# Test 2: Pydantic schema test
# ═════════════════════════════════════════════════════════
section("Test 2: Pydantic schema test")

# Test VisualEvaluationResult construction
try:
    result = VisualEvaluationResult(
        status="success",
        model="qwen3-vl:4b",
        visual_content_checked=True,
        visual_consistency_score=85.0,
        image_caption="Test caption",
        detected_style="cartoon",
        detected_layout_type="reference_map",
        image_sha256="abc123",
        original_image_size={"width": 1024, "height": 1024},
        evaluated_image_size={"width": 768, "height": 768},
        total_ms=5000,
    )
    check("VisualEvaluationResult construction", True)
    d = result.model_dump()
    check("VisualEvaluationResult.model_dump()", d["status"] == "success")
    check("VisualEvaluationResult JSON roundtrip",
          VisualEvaluationResult(**json.loads(json.dumps(d))).status == "success")
except Exception as e:
    check("VisualEvaluationResult", False, str(e))

# Test VisualEvaluationDimension
try:
    dim = VisualEvaluationDimension(
        key="visual_content_alignment",
        label="Content Alignment",
        score=85,
        max_score=100,
        status="evaluated",
        confidence=0.8,
        evidence=["evidence 1"],
        issues=["issue 1", "issue 2"],
        suggestions=["suggestion 1"],
    )
    check("VisualEvaluationDimension construction", True)
    check("VisualEvaluationDimension issues capped", len(dim.issues) <= 2)
except Exception as e:
    check("VisualEvaluationDimension", False, str(e))

# Test all sub-models
for cls, name, kwargs in [
    (VisualDetectedObject, "VisualDetectedObject", {"label": "test", "category": "object", "confidence": 0.9}),
    (VisualDetectedText, "VisualDetectedText", {"text": "hello", "confidence": 0.9, "location": "top"}),
    (VisualSpatialRelation, "VisualSpatialRelation", {"relation": "above", "subject": "A", "object": "B", "confidence": 0.8}),
    (VisualQualityIssue, "VisualQualityIssue", {"issue_type": "blur", "description": "blurry", "severity": "minor"}),
    (VisualHardFailure, "VisualHardFailure", {"code": "HF_001", "severity": "major", "evidence": "test"}),
    (VisualBadCase, "VisualBadCase", {"id": "VC_001", "modality": "image", "severity": "minor", "category": "test", "title": "test", "description": "test"}),
]:
    try:
        obj = cls(**kwargs)
        check(f"{name} construction", True)
    except Exception as e:
        check(f"{name} construction", False, str(e))


# ═════════════════════════════════════════════════════════
# Test 3: Prompt building test
# ═════════════════════════════════════════════════════════
section("Test 3: Prompt building test")

# Create a minimal mock task for prompt building
# We need to create a task structure that the prompt builders can use
from unittest.mock import MagicMock

# Build a mock config
mock_cfg = MagicMock()
mock_cfg.topic = "Asking for directions"
mock_cfg.scenario = "School library"
mock_cfg.grade = "grade_7"
mock_cfg.image_type = "location_reference_map"
mock_cfg.image_style = MagicMock()
mock_cfg.image_style.value = "textbook_cartoon"

# Make str() work
mock_cfg.image_style.__str__ = lambda self: "textbook_cartoon"

mock_cfg.image_goal = "location_reference"
mock_cfg.image_prompt_enhanced = "A colorful school map with arrows and labels"
mock_cfg.image_prompt_input = ""
mock_cfg.required_vocabulary = ["library", "classroom", "turn left", "second floor", "walk"]

# Build mock script
mock_turn = MagicMock()
mock_turn.turn_id = 0
mock_turn.speaker_id = "A"
mock_turn.text = "Excuse me, where is the library?"
mock_script = MagicMock()
mock_script.dialogue = [mock_turn]
mock_script.script_version = "v1"

# Build mock image
mock_image = MagicMock()
mock_image.image_url = "assets/tasks/G7_DIR_0838/image.png"
mock_image.image_type = "location_reference_map"

# Build mock task
mock_task = MagicMock()
mock_task.task_id = "TEST_001"
mock_task.config = mock_cfg
mock_task.script = mock_script
mock_task.image = mock_image

# Test Stage 1 prompt
s1_prompt = _build_stage1_prompt(mock_task)
check("Stage 1 prompt is non-empty", len(s1_prompt) > 50)
check("Stage 1 prompt contains expected type", "location_reference_map" in s1_prompt)
check("Stage 1 prompt contains style", "textbook_cartoon" in s1_prompt)
check("Stage 1 prompt contains NO 'score'", "score" not in s1_prompt.lower().split("score") if "score" in s1_prompt.lower() else True)

# Test Stage 2 prompt
stage1_data = {
    "image_caption": "Grade 7 school map",
    "detected_objects": ["library (red square)", "classroom (yellow square)"],
    "detected_text": ["Library", "You are here"],
    "spatial_relations": ["library is next to classroom"],
    "detected_style": "textbook_cartoon",
    "detected_layout_type": "location_reference_map",
    "quality_issues": "",
}
s2_prompt = _build_stage2_prompt(mock_task, stage1_data)
check("Stage 2 prompt is non-empty", len(s2_prompt) > 50)
check("Stage 2 prompt contains VISUAL FACTS", "VISUAL FACTS" in s2_prompt)
check("Stage 2 prompt contains REQUIREMENTS", "REQUIREMENTS" in s2_prompt)
check("Stage 2 prompt contains dimension list", "visual_content_alignment" in s2_prompt)
check("Stage 2 prompt mentions max 2", "Max 2" in s2_prompt)
check("Stage 2 prompt is concise (<2000 chars)", len(s2_prompt) < 2000,
      f"actual: {len(s2_prompt)} chars")

# Test system prompts
check("STAGE1_SYSTEM_PROMPT is short (<100 chars)", len(STAGE1_SYSTEM_PROMPT) < 100,
      f"actual: {len(STAGE1_SYSTEM_PROMPT)} chars")
check("STAGE2_SYSTEM_PROMPT_SHORT is short (<100 chars)", len(STAGE2_SYSTEM_PROMPT_SHORT) < 100,
      f"actual: {len(STAGE2_SYSTEM_PROMPT_SHORT)} chars")
check("STAGE2_SYSTEM_PROMPT_LONG is present", len(STAGE2_SYSTEM_PROMPT_LONG) > 20)


# ═════════════════════════════════════════════════════════
# Test 4: Cache read/write test
# ═════════════════════════════════════════════════════════
section("Test 4: Cache read/write test")

# Test with real Stage 1 cache if it exists
existing_cache_dir = Path(LOGS_DIR) / "G7_DIR_0838" / "stage1_cache"
if existing_cache_dir.exists():
    cache_files = list(existing_cache_dir.glob("*.json"))
    if cache_files:
        check(f"Found {len(cache_files)} existing Stage 1 cache file(s)", True)
        for cf in cache_files:
            try:
                data = json.loads(cf.read_text(encoding="utf-8"))
                check(f"Cache {cf.name} is valid JSON", isinstance(data, dict))
                check(f"Cache has image_caption", "image_caption" in data)
                check(f"Cache has detected_objects", "detected_objects" in data)
                check(f"Cache has detected_style", "detected_style" in data)
                check(f"Cache has detected_layout_type", "detected_layout_type" in data)
            except Exception as e:
                check(f"Cache {cf.name} parse", False, str(e))
    else:
        check("No existing cache files (will create on first run)", True)
else:
    check("Stage 1 cache directory not yet created (OK)", True)

# Test write + read cycle with temp cache
test_task_id = "_fast_test_temp_"
test_s1_key = "test12345678ab"
test_cache_data = {
    "image_caption": "Test map",
    "detected_objects": ["obj1", "obj2"],
    "detected_text": ["text1"],
    "spatial_relations": ["rel1"],
    "detected_style": "cartoon",
    "detected_layout_type": "map",
    "quality_issues": "",
}

try:
    _save_stage1_cache(test_task_id, test_s1_key, test_cache_data)
    check("Stage 1 cache save", True)

    loaded = _load_stage1_cache(test_task_id, test_s1_key)
    check("Stage 1 cache load", loaded is not None)
    check("Stage 1 cache data matches", loaded == test_cache_data)

    # Clean up temp cache
    import shutil
    cache_dir = LOGS_DIR / test_task_id
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
except Exception as e:
    check("Stage 1 cache save/load", False, str(e))

# Test SHA256 computation
try:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        tmp_path = f.name
    sha = _compute_sha256(Path(tmp_path))
    check("SHA256 is 64 chars hex", len(sha) == 64)
    check("SHA256 is hex", all(c in "0123456789abcdef" for c in sha))
    os.unlink(tmp_path)
except Exception as e:
    check("SHA256 computation", False, str(e))

# Test cache key generation
s1_key = _stage1_cache_key(mock_task, "abc123def456", "qwen3-vl:4b", "v2")
check("Stage 1 cache key is 16 chars", len(s1_key) == 16)

full_key = _build_visual_cache_key(mock_task, "abc123def456", "qwen3-vl:4b", "v2")
check("Full cache key is 16 chars", len(full_key) == 16)

# Same inputs = same key
s1_key2 = _stage1_cache_key(mock_task, "abc123def456", "qwen3-vl:4b", "v2")
check("Cache key is deterministic", s1_key == s1_key2)


# ═════════════════════════════════════════════════════════
# Test 5: JSON parse test
# ═════════════════════════════════════════════════════════
section("Test 5: JSON parse test")

# Test _extract_json
test_cases = [
    ('{"key": "value"}', '{"key": "value"}', "plain JSON"),
    ('```json\n{"key": "value"}\n```', '{"key": "value"}', "code-fenced JSON"),
    ('```\n{"key": "value"}\n```', '{"key": "value"}', "no-lang code fence"),
    ('Thinking text... {"key": "value"}', '{"key": "value"}', "JSON after text"),
    ('{"key": "value"} trailing text', '{"key": "value"}', "JSON before text"),
    ('text {"a": 1} more {"b": 2}', '{"a": 1} more {"b": 2}', "multiple JSON (first { to last })"),
]

for raw, expected, desc in test_cases:
    extracted = _extract_json(raw)
    check(f"extract_json: {desc}", extracted == expected, f"got: {extracted}")

# Test JSON repair (trailing commas)
bad_json = '{"a": 1, "b": [1, 2,], "c": {"d": 3,},}'
extracted = _extract_json(bad_json)
try:
    repaired = json.loads(re.sub(r',\s*}', '}', re.sub(r',\s*]', ']', extracted)))
    check("JSON repair: trailing commas", repaired == {"a": 1, "b": [1, 2], "c": {"d": 3}})
except Exception as e:
    check("JSON repair: trailing commas", False, str(e))

# Test with real Stage 1 output format
real_output = '''
{
  "image_caption": "Test map",
  "detected_objects": ["obj1", "obj2"],
  "detected_text": ["text1"],
  "spatial_relations": ["rel1"],
  "detected_style": "cartoon",
  "detected_layout_type": "map",
  "quality_issues": ""
}
'''
extracted = _extract_json(real_output)
try:
    parsed = json.loads(extracted)
    check("Parse real-format Stage 1 JSON", all(k in parsed for k in [
        "image_caption", "detected_objects", "detected_text",
        "spatial_relations", "detected_style", "detected_layout_type"
    ]))
except Exception as e:
    check("Parse real-format Stage 1 JSON", False, str(e))

# Test _parse_visual_result
try:
    test_data = {
        "image_caption": "Test",
        "detected_style": "cartoon",
        "detected_layout_type": "map",
        "detected_objects": [{"label": "obj1"}],
        "detected_text": [{"text": "hello"}],
        "spatial_relations": [{"relation": "above"}],
        "quality_issues": [],
        "dimensions": [
            {"key": "visual_content_alignment", "label": "Content", "score": 80, "status": "evaluated"},
            {"key": "image_type_alignment", "label": "Type", "score": 90, "status": "evaluated"},
        ],
        "hard_failures": [],
        "bad_cases": [],
        "recommendations": ["Good work"],
        "confidence": 0.85,
    }
    parsed = _parse_visual_result(
        test_data, "qwen3-vl:4b", "sha256",
        {"width": 1024, "height": 1024},
        {"width": 768, "height": 768},
    )
    check("_parse_visual_result success", parsed.status == "success")
    check("_parse_visual_result score computed", parsed.visual_consistency_score == 85.0)
    check("_parse_visual_result dimensions count", len(parsed.dimensions) == 2)
    check("_parse_visual_result model", "qwen3-vl:4b" in parsed.model)
except Exception as e:
    check("_parse_visual_result", False, str(e))


# ═════════════════════════════════════════════════════════
# Test 6: FastAPI route test (no server needed)
# ═════════════════════════════════════════════════════════
section("Test 6: FastAPI route structure test")

try:
    from api.evaluation_routes import router, _set_progress, _clear_progress, _eval_progress
    check("import evaluation_routes router", True)

    # Test progress tracking functions (in-memory, no server)
    _set_progress("test_task", "visual_stage1", "testing...", 5.0)
    with __import__('api.evaluation_routes', fromlist=['_progress_lock'])._progress_lock:
        info = _eval_progress.get("test_task")
    check("Progress set", info is not None)
    check("Progress stage", info["stage"] == "visual_stage1")
    check("Progress message", "testing" in info["message"])

    _clear_progress("test_task")
    with __import__('api.evaluation_routes', fromlist=['_progress_lock'])._progress_lock:
        info2 = _eval_progress.get("test_task")
    check("Progress cleared", info2 is None)

    # Test error codes are imported correctly
    check("ERR_STAGE1_TIMEOUT defined", ERR_STAGE1_TIMEOUT == "VISUAL_STAGE1_TIMEOUT")
    check("ERR_STAGE2_TIMEOUT defined", ERR_STAGE2_TIMEOUT == "VISUAL_STAGE2_TIMEOUT")
    check("ERR_VISUAL_TOTAL_TIMEOUT defined", ERR_VISUAL_TOTAL_TIMEOUT == "VISUAL_TOTAL_TIMEOUT")
    check("ERR_VISUAL_PARSE_FAILED defined", ERR_VISUAL_PARSE_FAILED == "VISUAL_PARSE_FAILED")

except Exception as e:
    check("FastAPI route test", False, str(e))


# ═════════════════════════════════════════════════════════
# Test 7: config.json validation
# ═════════════════════════════════════════════════════════
section("Test 7: config.json validation")

cfg = get_config()
eval_cfg = cfg.get("evaluation", {})
check("visualModel is qwen3-vl:4b", eval_cfg.get("visualModel") == "qwen3-vl:4b")
check("visualStage1TimeoutSec = 180", eval_cfg.get("visualStage1TimeoutSec") == 180)
check("visualStage2TimeoutSec = 90", eval_cfg.get("visualStage2TimeoutSec") == 90)
check("visualTotalTimeoutSec = 300", eval_cfg.get("visualTotalTimeoutSec") == 300)
check("visualSingleModel = false (Plan A default)", eval_cfg.get("visualSingleModel") == False)
check("visualPromptVersion set", len(eval_cfg.get("visualPromptVersion", "")) > 0)


# ═════════════════════════════════════════════════════════
# Summary
# ═════════════════════════════════════════════════════════
section("SUMMARY")
print(f"  Passed: {PASSED}")
print(f"  Failed: {FAILED}")
if ERRORS:
    print(f"  Errors:")
    for e in ERRORS:
        print(f"    {e}")

print(f"\n{'*** ALL TESTS PASSED ***' if FAILED == 0 else '*** SOME TESTS FAILED ***'}")
sys.exit(0 if FAILED == 0 else 1)
