"""Unit tests for JSON parser and script validation."""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.json_parser import (
    extract_json_object,
    parse_and_validate_script,
    JsonParseError,
    SchemaValidationError,
)

passed = 0
failed = 0


def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  [PASS] {name}")
    except AssertionError as e:
        failed += 1
        print(f"  [FAIL] {name}: {e}")
    except Exception as e:
        failed += 1
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")


def make_valid_json(turns=1):
    """Build a minimal valid DialogueScript JSON string."""
    speakers = [
        {"speaker_id": "A", "role": "Student", "voice_id": "en_US-lessac-medium"},
        {"speaker_id": "B", "role": "Passer-by", "voice_id": "en_US-ryan-medium"},
    ]
    dialogue = []
    for i in range(turns):
        speaker_id = "A" if i % 2 == 0 else "B"
        dialogue.append({"turn_id": i + 1, "speaker_id": speaker_id, "text": f"Turn {i+1} text."})
    obj = {
        "speakers": speakers,
        "dialogue": dialogue,
        "used_vocabulary": ["test"],
        "used_patterns": ["test pattern"],
        "total_words": turns * 3,
    }
    return json.dumps(obj, ensure_ascii=False)


# ── Test 1: Pure JSON ──
def t1():
    raw = make_valid_json(turns=2)
    script = parse_and_validate_script(raw, expected_turns=2)
    assert len(script.dialogue) == 2
    assert script.total_words == 6

test("Pure JSON parses correctly", t1)


# ── Test 2: Markdown code fence ──
def t2():
    inner = make_valid_json(turns=2)
    raw = f"Here is a dialogue:\n\n```json\n{inner}\n```\n\nThat's it."
    script = parse_and_validate_script(raw, expected_turns=2)
    assert len(script.dialogue) == 2
    assert len(script.speakers) == 2

test("Markdown code fence parses correctly", t2)


# ── Test 3: Leading/trailing text ──
def t3():
    inner = make_valid_json(turns=3)
    raw = f"Okay, here is your JSON:\n\n{inner}\n\nI hope this helps!"
    script = parse_and_validate_script(raw, expected_turns=3)
    assert len(script.dialogue) == 3

test("Leading/trailing text extracts correctly", t3)


# ── Test 4: Trailing comma auto-fixed ──
def t4():
    # _remove_trailing_commas should fix this
    raw = '{"speakers":[{"speaker_id":"A","role":"Student","voice_id":"en_US-lessac-medium"},{"speaker_id":"B","role":"Passer-by","voice_id":"en_US-ryan-medium"},],"dialogue":[{"turn_id":1,"speaker_id":"A","text":"Hello"},{"turn_id":2,"speaker_id":"B","text":"Hi"},],"used_vocabulary":["hello"],"used_patterns":[],"total_words":2}'
    script = parse_and_validate_script(raw, expected_turns=2)
    assert len(script.dialogue) == 2
    # This is a feature: trailing commas are auto-cleaned

test("Trailing comma auto-fixed by extract_json_object", t4)


# ── Test 5: Truncated output ──
def t5():
    raw = '{"speakers":[{"speaker_id":"A","role":"Student"'
    try:
        parse_and_validate_script(raw, expected_turns=1)
        assert False, "Should have raised"
    except JsonParseError as e:
        assert "不完整" in str(e) or "未闭合" in str(e) or "{" in str(e)

test("Truncated output raises JsonParseError", t5)


# ── Test 6: Wrong turn count ──
def t6():
    raw = make_valid_json(turns=2)
    try:
        parse_and_validate_script(raw, expected_turns=8)
        assert False, "Should have raised"
    except SchemaValidationError as e:
        assert "轮数不符" in str(e) or "期望" in str(e)

test("Wrong turn count fails schema validation", t6)


# ── Test 7: Invalid speaker_id ──
def t7():
    raw = '{"speakers":[{"speaker_id":"A","role":"Student","voice_id":"en_US-lessac-medium"}],"dialogue":[{"turn_id":1,"speaker_id":"C","text":"Hello"}],"used_vocabulary":[],"used_patterns":[],"total_words":1}'
    try:
        parse_and_validate_script(raw, expected_turns=1)
        assert False, "Should have raised"
    except SchemaValidationError as e:
        assert "C" in str(e)

test("Invalid speaker_id fails schema validation", t7)


# ── Test 8: Empty text ──
def t8():
    raw = '{"speakers":[{"speaker_id":"A","role":"Student","voice_id":"en_US-lessac-medium"}],"dialogue":[{"turn_id":1,"speaker_id":"A","text":""}],"used_vocabulary":[],"used_patterns":[],"total_words":0}'
    try:
        parse_and_validate_script(raw, expected_turns=1)
        assert False, "Should have raised"
    except SchemaValidationError as e:
        assert "不能为空" in str(e) or "empty" in str(e).lower()

test("Empty text fails schema validation", t8)


# ── Test 9: Non-consecutive turn_id ──
def t9():
    raw = make_valid_json(turns=2)
    # Modify to non-consecutive
    obj = json.loads(raw)
    obj["dialogue"][1]["turn_id"] = 5
    raw = json.dumps(obj)
    try:
        parse_and_validate_script(raw, expected_turns=2)
        assert False, "Should have raised"
    except SchemaValidationError as e:
        assert "turn_id" in str(e)

test("Non-consecutive turn_id fails validation", t9)


# ── Test 10: Empty content ──
def t10():
    for empty in ["", "   \n  ", None]:
        try:
            extract_json_object(empty or "")
            assert False, f"Should have raised for {repr(empty)}"
        except JsonParseError:
            pass

test("Empty content raises JsonParseError", t10)


# ── Summary ──
print(f"\nResults: {passed} passed, {failed} failed out of {passed + failed}")
if failed > 0:
    sys.exit(1)
