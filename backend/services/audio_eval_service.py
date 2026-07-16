"""
Script-audio consistency evaluation.

Compares normalized script text with ASR transcript.
Flags missing/conflicting keywords, especially direction and location words.
S3 severity on direction or key location conflicts.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field

# Keywords that must match exactly between script and audio
DIRECTION_KEYWORDS = {
    "left", "right", "straight", "turn left", "turn right",
    "go along", "go straight",
}

LOCATION_KEYWORDS = {
    "across from", "next to", "between", "behind", "in front of",
    "near", "on the left", "on the right",
}

POSITION_KEYWORDS = {
    "first", "second", "third", "second floor", "first floor",
}


def _normalize(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    # Remove punctuation except preserve meaningful chars
    text = re.sub(rf"[{re.escape(string.punctuation)}]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokenize(text: str) -> set[str]:
    """Return set of words from normalized text."""
    return set(text.split())


def _check_phrase(phrase: str, norm_text: str) -> bool:
    """Check if a multi-word phrase appears in normalized text."""
    return _normalize(phrase) in norm_text


@dataclass
class AudioEvalResult:
    task_id: str
    audio_path: str
    source_script_version: str
    normalized_script: str = ""
    normalized_transcript: str = ""
    keyword_checks: list[dict] = field(default_factory=list)
    missing_keywords: list[str] = field(default_factory=list)
    conflicting_keywords: list[str] = field(default_factory=list)
    script_audio_match_pass: bool = False
    evidence: str = ""
    severity: str = "S0"


def evaluate_consistency(
    script_text: str,
    asr_text: str,
    task_id: str,
    audio_path: str,
    source_script_version: str,
) -> AudioEvalResult:
    """
    Compare script and ASR transcript for consistency.

    Returns AudioEvalResult with normalized texts, keyword checks, and pass/fail.
    """
    norm_script = _normalize(script_text)
    norm_asr = _normalize(asr_text)

    result = AudioEvalResult(
        task_id=task_id,
        audio_path=audio_path,
        source_script_version=source_script_version,
        normalized_script=norm_script,
        normalized_transcript=norm_asr,
    )

    script_tokens = _tokenize(norm_script)
    asr_tokens = _tokenize(norm_asr)

    missing: list[str] = []
    conflicts: list[str] = []
    checks: list[dict] = []
    s3_triggered = False

    # Check direction keywords
    for kw in DIRECTION_KEYWORDS:
        in_script = _check_phrase(kw, norm_script)
        in_asr = _check_phrase(kw, norm_asr)
        checks.append({
            "keyword": kw,
            "category": "direction",
            "in_script": in_script,
            "in_asr": in_asr,
        })
        if in_script and not in_asr:
            missing.append(kw)
            s3_triggered = True  # Direction missing = S3
        elif not in_script and in_asr:
            conflicts.append(kw)

    # Check location keywords
    for kw in LOCATION_KEYWORDS:
        in_script = _check_phrase(kw, norm_script)
        in_asr = _check_phrase(kw, norm_asr)
        checks.append({
            "keyword": kw,
            "category": "location",
            "in_script": in_script,
            "in_asr": in_asr,
        })
        if in_script and not in_asr:
            missing.append(kw)
        elif not in_script and in_asr:
            conflicts.append(kw)

    # Check position keywords (first, second, etc.)
    for kw in POSITION_KEYWORDS:
        in_script = _check_phrase(kw, norm_script)
        in_asr = _check_phrase(kw, norm_asr)
        checks.append({
            "keyword": kw,
            "category": "position",
            "in_script": in_script,
            "in_asr": in_asr,
        })
        if in_script and not in_asr:
            missing.append(kw)

    result.keyword_checks = checks
    result.missing_keywords = missing
    result.conflicting_keywords = conflicts
    result.severity = "S3" if s3_triggered else "S0"

    if s3_triggered:
        result.script_audio_match_pass = False
        result.evidence = (
            f"方向/关键地点词在音频中缺失或冲突: {', '.join(missing)}。"
            f"脚本: {norm_script[:200]}; ASR: {norm_asr[:200]}"
        )
    elif missing or conflicts:
        result.script_audio_match_pass = True  # S2-level issues, not blocking
        result.severity = "S2"
        result.evidence = (
            f"次要词汇差异。缺失: {missing}; 额外出现: {conflicts}。"
            f"脚本: {norm_script[:200]}; ASR: {norm_asr[:200]}"
        )
    else:
        result.script_audio_match_pass = True
        result.evidence = "脚本文本与ASR转写方向词和关键地点一致。"

    return result
