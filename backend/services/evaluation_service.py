"""Evaluation service: generate evaluation report from task assets."""

from __future__ import annotations

import json, random, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models import Task, EvalReport, EvaluationItem, Severity, PassStatus, EvaluatorType
from config import get_config

def _now_iso() -> str: return datetime.now(timezone.utc).isoformat()


def _check_all_assets_ready(task: Task) -> bool:
    return bool(
        task.script and task.script.status == "confirmed"
        and task.image and task.image.generation_status.value == "success"
        and task.audio and task.audio.generation_status.value == "success"
        and task.questions and task.questions.generation_status.value == "success"
    )


def generate_evaluation(task: Task) -> EvalReport:
    """Generate evaluation report from task assets."""
    if not _check_all_assets_ready(task):
        raise ValueError("素材尚未齐全，无法生成评测报告。")

    t0 = time.perf_counter()
    items: list[EvaluationItem] = []
    dim_scores: dict[str, float] = {}

    # 1. Text quality (script evaluation)
    vocab_cov, vocab_src = _calc_vocab_coverage(task)
    pattern_cov, pattern_src = _calc_pattern_coverage(task)
    text_score = min(100, int(vocab_cov * 50 + pattern_cov * 50))
    dim_scores["textQuality"] = text_score

    # Build evidence message based on source type
    vocab_evidence = f"词汇覆盖率: {vocab_cov:.0%}（{'用户指定' if vocab_src == 'user' else '系统自动选择'}）"
    pattern_evidence = f"句型覆盖率: {pattern_cov:.0%}（{'用户指定' if pattern_src == 'user' else '系统自动设计'}）"

    # Only flag issues for user-specified constraints that are not fully covered
    has_user_issue = (vocab_src == "user" and vocab_cov < 1.0) or (pattern_src == "user" and pattern_cov < 1.0)
    if has_user_issue or text_score < 80:
        items.append(EvaluationItem(
            evaluation_id=f"EV_{task.task_id}_text",
            evaluation_version="v1.0", target_type="script", target_id=task.script.script_id,
            overall_score=text_score, dimension_scores={"vocab_coverage": vocab_cov, "pattern_coverage": pattern_cov},
            pass_status=PassStatus.PASS if text_score >= 80 else PassStatus.FAIL,
            severity=Severity.S2 if text_score < 80 else Severity.S0,
            evidence=f"{vocab_evidence}, {pattern_evidence}",
            evaluator_type=EvaluatorType.RULE, evaluator_model="rule_engine",
            evaluated_at=_now_iso(),
        ))

    # 2. Audio quality
    audio_score = _eval_audio(task)
    dim_scores["audioQuality"] = audio_score

    # 3. Image quality (basic rule check)
    img_score = 85
    if task.image:
        img_score = 100 if task.image.generation_status.value == "success" else 50
    dim_scores["imageQuality"] = img_score

    # 4. Question quality
    q_score = _eval_questions(task)
    dim_scores["questionQuality"] = q_score

    # 5. Cross-modal
    cross_score = _eval_cross_modal(task)
    dim_scores["crossModal"] = cross_score
    if cross_score < 80:
        items.append(EvaluationItem(
            evaluation_id=f"EV_{task.task_id}_cross",
            evaluation_version="v1.0", target_type="cross_modal",
            target_id=task.task_id, overall_score=cross_score,
            dimension_scores={},
            pass_status=PassStatus.FAIL if cross_score < 60 else PassStatus.PASS,
            severity=Severity.S2 if cross_score < 80 else Severity.S0,
            evidence=f"跨模态一致性: {cross_score}",
            evaluator_type=EvaluatorType.RULE, evaluator_model="rule_engine",
            evaluated_at=_now_iso(),
        ))

    # Weighted score
    weights = get_config().get("evaluation", {}).get("weights", {})
    w = {
        "textQuality": weights.get("textQuality", 0.2),
        "audioQuality": weights.get("audioQuality", 0.2),
        "imageQuality": weights.get("imageQuality", 0.15),
        "questionQuality": weights.get("questionQuality", 0.2),
        "crossModal": weights.get("crossModal", 0.25),
    }
    overall = sum(dim_scores[k] * w.get(k, 0.2) for k in dim_scores)
    s3s4 = sum(1 for i in items if i.severity in (Severity.S3, Severity.S4))
    passed = overall >= get_config().get("evaluation", {}).get("passThreshold", 80)

    return EvalReport(
        task_id=task.task_id,
        evaluation_version="v1.0",
        overall_score=round(overall, 1),
        pass_status=PassStatus.PASS if passed else PassStatus.FAIL,
        dimension_scores=dim_scores,
        items=items,
        s3s4_count=s3s4,
        generated_at=_now_iso(),
    )


def _calc_vocab_coverage(task: Task) -> tuple[float, str]:
    """Returns (coverage_score, source_label). source_label is 'user', 'auto', or 'none'."""
    if not task.script or not task.config:
        return 1.0, "none"
    required = [v.lower() for v in task.config.required_vocabulary]
    if not required:
        # User didn't specify — system auto-selected
        return 1.0, "auto"
    all_text = " ".join(t.text.lower() for t in task.script.dialogue)
    found = sum(1 for v in required if v in all_text)
    return found / len(required), "user"


def _calc_pattern_coverage(task: Task) -> tuple[float, str]:
    """Returns (coverage_score, source_label). source_label is 'user', 'auto', or 'none'."""
    if not task.script or not task.config:
        return 0.0, "none"
    required = [p.lower() for p in task.config.target_patterns]
    if not required:
        # User didn't specify — system auto-designed
        return 1.0, "auto"
    all_text = " ".join(t.text.lower() for t in task.script.dialogue)
    found = sum(1 for p in required if p in all_text)
    return found / len(required), "user"


def _eval_audio(task: Task) -> float:
    if not task.audio: return 0.0
    score = 85  # base
    if task.audio.audio_duration_actual_sec > 0:
        target = task.config.audio_duration_target_sec
        actual = task.audio.audio_duration_actual_sec
        bias = abs(actual - target) / max(target, 1)
        if bias <= 0.2: score = 95
        elif bias <= 0.4: score = 80
        else: score = 60
    return float(score)


def _eval_questions(task: Task) -> float:
    if not task.questions or not task.questions.questions: return 0.0
    total = len(task.questions.questions)
    expected = task.config.question_count or total
    count_ok = total >= expected
    answer_ok = all(q.answer in ("A","B","C","D") for q in task.questions.questions)
    opts_ok = all(len(q.options) == 4 for q in task.questions.questions)
    score = 100.0
    if not count_ok: score -= 20
    if not answer_ok: score -= 30
    if not opts_ok: score -= 10
    return max(0, score)


def _eval_cross_modal(task: Task) -> float:
    """Basic cross-modal consistency check."""
    score = 90.0
    if task.image and task.script:
        if task.image.image_source_script_version != task.script.script_version:
            score -= 20
    if task.audio and task.script:
        if task.audio.audio_source_script_version != task.script.script_version:
            score -= 20
    if task.questions and task.script:
        if task.questions.question_source_script_version != task.script.script_version:
            score -= 10
    return max(0, score)
