"""
Question generation service using Ollama + Pydantic validation.
Generates multiple-choice listening comprehension questions based on confirmed script.
"""

from __future__ import annotations

import json, time, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import TaskConfig, DialogueScript, QuestionSet, Question, AssetStatus
from services.ollama_client import OllamaClient, OllamaError

LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "question_gen"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str: return datetime.now(timezone.utc).isoformat()


QUESTION_SYSTEM_PROMPT_BASE = """You are an English listening comprehension test writer.

Given a dialogue script, generate multiple-choice listening comprehension questions.

RULES:
- Output ONLY a JSON object. First char {, last char }. No markdown, no ```json, no explanation.
- All strings in double quotes. No trailing commas.
- Generate exactly the requested number of questions.
- Each question must have exactly 4 options labeled A, B, C, D.
- Only one correct answer per question.
- Questions must be answerable from the dialogue text.
- evidence_turn_ids must reference real turn numbers from the dialogue.
- Do NOT invent facts not present in the script.

JSON structure:
{
  "questions": [
    {
      "stem": "Where is the library?",
      "options": [
        {"label": "A", "text": "Next to the bank"},
        {"label": "B", "text": "Across from the hospital"},
        {"label": "C", "text": "Behind the school"},
        {"label": "D", "text": "On Main Street"}
      ],
      "answer": "D",
      "evidence_turn_ids": [1, 2],
      "explanation": "The passer-by says the library is on Main Street in turn 2."
    }
  ]
}"""

GRADE_QUESTION_GUIDANCE: dict[str, str] = {
    "grade_7": "Language: Grade 7 (CEFR A1-A2), simple vocabulary, short sentences, direct comprehension questions only.",
    "grade_8": "Language: Grade 8 (CEFR A2), medium vocabulary, simple compound sentences, questions may integrate 2 pieces of information.",
    "grade_9": "Language: Grade 9 (CEFR A2-B1), richer vocabulary, compound sentences with connectors, questions may require simple inference.",
}


def _get_question_system_prompt(grade: str) -> str:
    guidance = GRADE_QUESTION_GUIDANCE.get(grade, GRADE_QUESTION_GUIDANCE["grade_7"])
    return QUESTION_SYSTEM_PROMPT_BASE + "\n\n" + guidance


def _build_user_prompt(config: TaskConfig, script: DialogueScript) -> str:
    dialogue_text = "\n".join(
        f"Turn {t.turn_id} [{t.speaker_id}]: {t.text}" for t in script.dialogue
    )
    grade_label = getattr(config.grade, "value", str(config.grade)) if hasattr(config.grade, "value") else str(config.grade)

    # Use effective vocabulary from script when user didn't specify
    eff_vocab = config.effective_vocabulary or script.used_vocabulary
    eff_patterns = config.effective_target_patterns or script.used_patterns

    parts = [
        f"Generate {config.question_count} single-choice listening questions based on this dialogue:",
        "",
        dialogue_text,
        "",
        f"Topic: {config.topic}",
        f"Grade: {grade_label}",
    ]
    if eff_vocab:
        src = "system-selected" if config.vocabulary_constraint_source == "auto" else "user-specified"
        parts.append(f"Key vocabulary ({src}): {', '.join(eff_vocab)}")
    if eff_patterns:
        src = "system-designed" if config.target_pattern_source == "auto" else "user-specified"
        parts.append(f"Key sentence patterns ({src}): {', '.join(eff_patterns)}")
    parts.append(f"Generate exactly {config.question_count} questions. Questions MUST be answerable from the dialogue. Output ONLY the JSON object.")
    return "\n".join(parts)


def _extract_json(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```\s*$", text, re.DOTALL)
    if m: return m.group(1).strip()
    if text.startswith("```"): text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1)
    if text.endswith("```"): text = text[:text.rfind("```")].strip()
    start = text.find("{"); end = text.rfind("}")
    if start >= 0 and end > start: text = text[start:end+1]

    # Fix malformed option dicts like {"label": "D", "-than", "text": "..."}
    # where the model injects stray tokens between label and text keys
    text = re.sub(
        r'\{\s*"label"\s*:\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*"text"\s*:\s*',
        r'{"label": "\1", "text": ',
        text
    )

    return text


def generate_questions(config: TaskConfig, script: DialogueScript, task_id: str) -> QuestionSet:
    """
    Generate listening comprehension questions.

    Returns QuestionSet with status=SUCCESS on success.
    Raises OllamaError on connection issues, ValueError on parse/validation failure.
    """
    count = config.question_count or 3
    user_prompt = _build_user_prompt(config, script)
    grade_val = getattr(config.grade, "value", str(config.grade)) if hasattr(config.grade, "value") else str(config.grade)
    system_prompt = _get_question_system_prompt(grade_val)
    client = OllamaClient()
    t0 = time.perf_counter()

    # Use temperature=0.1 for more reliable structured output, num_predict=800 is enough for 3-5 questions
    result = client.chat(system_prompt, user_prompt, temperature=0.1, num_predict=800, keep_alive="30m")
    raw = result["content"].strip()
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Log raw output
    ts = _now_iso().replace(":", "-")
    (LOGS_DIR / f"{ts}_{task_id}_raw.txt").write_text(raw, encoding="utf-8")

    json_str = _extract_json(raw)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # Try one repair: ask model to fix
        repair_prompt = f"Your previous JSON output was invalid. Fix the JSON and output ONLY the corrected JSON object:\n\n{raw[:500]}"
        try:
            result2 = client.chat(system_prompt, repair_prompt, temperature=0.1, num_predict=800)
            raw2 = result2["content"].strip()
            (LOGS_DIR / f"{ts}_{task_id}_repair_raw.txt").write_text(raw2, encoding="utf-8")
            json_str2 = _extract_json(raw2)
            data = json.loads(json_str2)
        except Exception:
            raise ValueError(f"题目JSON解析失败（含一次修复重试）: {e}")

    questions_raw = data.get("questions", [])
    if not isinstance(questions_raw, list) or len(questions_raw) == 0:
        raise ValueError("QUESTION_JSON_PARSE_FAILED: 模型未返回questions数组")

    # Validate each question with lenient option parsing
    max_turn = len(script.dialogue)
    questions: list[Question] = []
    for i, q in enumerate(questions_raw):
        stem = q.get("stem", "")
        if not stem: raise ValueError(f"QUESTION_SCHEMA_VALIDATION_FAILED: 题目{i+1}缺少stem")
        options = q.get("options", [])
        if len(options) != 4:
            raise ValueError(f"QUESTION_SCHEMA_VALIDATION_FAILED: 题目{i+1}需要4个选项，实际{len(options)}个")

        # Normalize options: handle malformed dicts with extra keys
        clean_options = []
        labels_found = []
        for o in options:
            label = o.get("label", "")
            text = o.get("text", "")
            if not text:
                # Try to find text from other keys
                for k, v in o.items():
                    if k not in ("label", "text") and isinstance(v, str) and v:
                        text = v
                        break
            if label and text:
                clean_options.append(f"{label}. {text}")
                labels_found.append(label)

        if len(clean_options) != 4:
            raise ValueError(f"QUESTION_SCHEMA_VALIDATION_FAILED: 题目{i+1}无法提取4个有效选项（得到{len(clean_options)}个）")
        if set(labels_found) != {"A", "B", "C", "D"}:
            raise ValueError(f"QUESTION_SCHEMA_VALIDATION_FAILED: 题目{i+1}选项标签应为A/B/C/D，实际{labels_found}")

        answer = q.get("answer", "").strip().upper()
        if answer not in ("A", "B", "C", "D"):
            raise ValueError(f"QUESTION_SCHEMA_VALIDATION_FAILED: 题目{i+1}的answer='{answer}'无效，必须为A/B/C/D")

        # Evidence is optional now - just warn if invalid
        evidence = q.get("evidence_turn_ids", [])
        bad = [t for t in evidence if not isinstance(t, int) or t < 1 or t > max_turn]
        if bad:
            evidence = []  # Drop invalid evidence instead of failing

        questions.append(Question(
            index=i+1, stem=stem,
            options=clean_options,
            answer=answer,
            explanation=q.get("explanation", "")[:300],
        ))

    # Truncate to requested count
    questions = questions[:count]

    now = _now_iso()
    return QuestionSet(
        question_set_id=f"QSET_{task_id}",
        questions=questions,
        question_source_script_version=script.script_version,
        generation_status=AssetStatus.SUCCESS,
        is_outdated=False,
        model_name=result["model"],
        model_version=result["model"],
        prompt_version="v1.0",
        generation_latency_ms=latency_ms,
        estimated_cost=0.0,
    )
