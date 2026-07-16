"""Pydantic models matching PRD data field definitions."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Union, Literal, Any

from pydantic import BaseModel, Field, field_validator


# ── Enums ──────────────────────────────────────────────

class TaskStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    PARTIAL_SUCCESS = "partial_success"
    EVALUATING = "evaluating"
    FAILED = "failed"
    NEEDS_FIX = "needs_fix"
    OUTDATED = "outdated"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    EXPORTED = "exported"


class GradeLevel(str, Enum):
    GRADE_7 = "grade_7"
    GRADE_8 = "grade_8"
    GRADE_9 = "grade_9"


GRADE_LABELS: dict[GradeLevel, str] = {
    GradeLevel.GRADE_7: "七年级",
    GradeLevel.GRADE_8: "八年级",
    GradeLevel.GRADE_9: "九年级",
}


def _normalize_grade(raw: str | None) -> GradeLevel:
    """Compat: normalize legacy grade strings to GradeLevel enum."""
    if raw is None:
        return GradeLevel.GRADE_7
    raw_lower = raw.strip().lower()
    if raw_lower in ("grade_7", "grade 7", "seventh grade", "七年级"):
        return GradeLevel.GRADE_7
    if raw_lower in ("grade_8", "grade 8", "eighth grade", "八年级"):
        return GradeLevel.GRADE_8
    if raw_lower in ("grade_9", "grade 9", "ninth grade", "九年级"):
        return GradeLevel.GRADE_9
    return GradeLevel.GRADE_7


class Severity(str, Enum):
    S0 = "S0"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"


class PassStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    MANUAL_REVIEW = "manual_review"


class AssetStatus(str, Enum):
    GENERATING = "generating"
    SUCCESS = "success"
    FAILED = "failed"
    OUTDATED = "outdated"


class TeacherFeedback(str, Enum):
    AGREE = "agree"
    FALSE_POSITIVE = "false_positive"
    FIXED = "fixed"
    MISSED = "missed"


class EvaluatorType(str, Enum):
    RULE = "rule"
    LLM = "llm"
    ASR = "asr"
    MULTIMODAL = "multimodal"
    HUMAN = "human"


class UserAction(str, Enum):
    CREATE = "create"
    EDIT = "edit"
    CONFIRM = "confirm"
    REGENERATE = "regenerate"
    REVIEW = "review"
    EXPORT = "export"


class SpeechRate(str, Enum):
    SLOW = "slow"
    NORMAL = "normal"


class ImageStyle(str, Enum):
    STRUCTURED_SCHEMATIC = "structured_schematic"
    TEXTBOOK_CARTOON = "textbook_cartoon"
    WATERCOLOR = "watercolor"
    PHOTOREALISTIC = "photorealistic"
    FLAT_VECTOR = "flat_vector"
    HAND_DRAWN = "hand_drawn"
    COMIC = "comic"
    COLORED_PENCIL = "colored_pencil"
    THREE_D_CARTOON = "three_d_cartoon"
    # Legacy
    CARTOON = "cartoon"
    CHILDREN_BOOK = "children_book"
    FLAT = "flat"
    REALISTIC = "realistic"


# ── Speaker ────────────────────────────────────────────

class Speaker(BaseModel):
    speaker_id: str
    role: str
    voice_id: str


# ── Dialogue Turn ──────────────────────────────────────

class DialogueTurn(BaseModel):
    turn_id: int
    speaker_id: str
    text: str


# ── Narrow model for Ollama structured output ──────────

class DialogueScriptContent(BaseModel):
    """Only the fields the LLM must generate. System fields are filled by code."""
    speakers: list[Speaker]
    dialogue: list[DialogueTurn]
    used_vocabulary: list[str] = []
    used_patterns: list[str] = []


# ── Dialogue Script (full) ─────────────────────────────
# ── Script ─────────────────────────────────────────────

class DialogueScript(BaseModel):
    task_id: str
    script_id: str
    script_version: str
    status: str = "draft"
    source_task_config_version: str = "v1.0"
    speakers: list[Speaker]
    dialogue: list[DialogueTurn]
    used_vocabulary: list[str] = []
    used_patterns: list[str] = []
    total_words: int = 0
    created_at: str = ""
    confirmed_at: Optional[str] = None


# ── Task Config ────────────────────────────────────────

class TaskConfig(BaseModel):
    task_id: str = ""
    task_name: str
    grade: GradeLevel = GradeLevel.GRADE_7
    lesson_type: str = "listening_speaking"
    topic: str = "Asking for Directions"
    scenario: str = ""
    required_vocabulary: list[str] = []
    optional_vocabulary: list[str] = []
    target_patterns: list[str] = []
    effective_vocabulary: list[str] = []
    effective_target_patterns: list[str] = []
    vocabulary_constraint_source: str = "user"  # "user" | "auto"
    target_pattern_source: str = "user"  # "user" | "auto"
    dialogue_turns: int = 8
    speaker_count: Union[int, str] = "auto"  # "auto" | 1 | 2 | 3 | 4
    audio_duration_target_sec: int = 50
    speech_rate: SpeechRate = SpeechRate.NORMAL
    image_style: ImageStyle = ImageStyle.TEXTBOOK_CARTOON
    image_goal: str = "auto"
    image_prompt_input: str = ""
    image_prompt_enhanced: str = ""
    question_type: str = "single_choice"
    question_count: int = 3
    additional_instruction: str = ""
    created_by: str = "user"
    created_at: str = ""

    @field_validator("speaker_count", mode="before")
    @classmethod
    def validate_speaker_count(cls, v: Any) -> Union[int, str]:
        """Accept 'auto', 1, 2, 3, or 4. Reject everything else."""
        if v is None or v == "auto":
            return "auto"
        if isinstance(v, str) and v.strip().isdigit():
            v = int(v.strip())
        if isinstance(v, int):
            if 1 <= v <= 4:
                return v
        raise ValueError(f"speaker_count must be 'auto' or a number 1-4, got: {v!r}")


# ── Asset references ───────────────────────────────────

class ImageAsset(BaseModel):
    image_id: str = ""
    image_url: str = ""
    image_source_script_version: str = ""
    generation_status: AssetStatus = AssetStatus.GENERATING
    is_outdated: bool = False
    model_name: str = ""
    model_version: str = ""
    prompt_version: str = "v1.0"
    generation_latency_ms: int = 0
    estimated_cost: float = 0.0
    topic_type: str = ""
    image_type: str = ""
    style_preset: str = ""
    render_mode: str = ""


class AudioAsset(BaseModel):
    audio_id: str = ""
    audio_url: str = ""
    audio_duration_actual_sec: float = 0.0
    audio_source_script_version: str = ""
    speaker_profiles: dict = {}
    generation_status: AssetStatus = AssetStatus.GENERATING
    is_outdated: bool = False
    model_name: str = ""
    model_version: str = ""
    prompt_version: str = "v1.0"
    generation_latency_ms: int = 0
    estimated_cost: float = 0.0


class Question(BaseModel):
    index: int
    stem: str
    options: list[str] = []
    answer: str = ""
    explanation: str = ""


class QuestionSet(BaseModel):
    question_set_id: str = ""
    questions: list[Question] = []
    question_source_script_version: str = ""
    generation_status: AssetStatus = AssetStatus.GENERATING
    is_outdated: bool = False
    model_name: str = ""
    model_version: str = ""
    prompt_version: str = "v1.0"
    generation_latency_ms: int = 0
    estimated_cost: float = 0.0


# ── Evaluation ─────────────────────────────────────────

class EvaluationItem(BaseModel):
    evaluation_id: str = ""
    evaluation_version: str = "v1.0"
    target_type: str = ""  # script/image/audio/question/cross_modal
    target_id: str = ""
    overall_score: float = 0.0
    dimension_scores: dict = {}
    pass_status: PassStatus = PassStatus.PASS
    error_type: str = ""
    severity: Severity = Severity.S0
    error_location: str = ""
    evidence: str = ""
    suspected_cause: str = ""
    repair_suggestion: str = ""
    evaluator_type: EvaluatorType = EvaluatorType.RULE
    evaluator_model: str = ""
    teacher_feedback: Optional[TeacherFeedback] = None
    teacher_correction: str = ""
    evaluated_at: str = ""


class EvalReport(BaseModel):
    task_id: str
    evaluation_version: str = "v1.0"
    overall_score: float = 0.0
    pass_status: PassStatus = PassStatus.PASS
    dimension_scores: dict = {}
    items: list[EvaluationItem] = []
    s3s4_count: int = 0
    generated_at: str = ""
    # Combined evaluation fields
    combined_score: float = 0.0
    rule_score: float = 0.0
    semantic_score: float = 0.0
    visual_score: Optional[float] = None  # None=not run, 0=ran with score 0
    semantic_data: Optional[dict] = None
    visual_data: Optional[dict] = None
    asset_fingerprint: str = ""
    evaluation_status: str = ""
    semantic_prompt_version: str = ""
    visual_prompt_version: str = ""
    model: str = ""


# ── Visual Evaluation Models ────────────────────────────

class VisualDetectedObject(BaseModel):
    label: str = ""
    category: str = ""  # location, building, person, weather, road, arrow, icon, story_object
    confidence: float = 0.0
    bbox_hint: str = ""  # e.g. "center-left", "top-right"


class VisualDetectedText(BaseModel):
    text: str = ""
    confidence: float = 0.0
    location: str = ""
    language: str = ""


class VisualSpatialRelation(BaseModel):
    relation: str = ""  # left_of, right_of, above, below, next_to, across_from, between, connected_to, route_direction
    subject: str = ""
    object: str = ""
    confidence: float = 0.0


class VisualQualityIssue(BaseModel):
    issue_type: str = ""  # distorted_object, unreadable_text, incorrect_arrow, etc.
    description: str = ""
    severity: str = ""  # minor, moderate, major
    location: str = ""


class VisualEvaluationDimension(BaseModel):
    key: str = ""
    label: str = ""
    score: float = 0.0
    max_score: float = 100.0
    status: str = "evaluated"  # evaluated, not_applicable, skipped
    confidence: float = 0.0
    evidence: list[str] = []
    issues: list[str] = []
    suggestions: list[str] = []


class VisualHardFailure(BaseModel):
    code: str = ""
    severity: str = ""  # critical, major
    evidence: str = ""
    recommendation: str = ""


class VisualBadCase(BaseModel):
    id: str = ""
    modality: str = "image"
    severity: str = ""
    category: str = ""
    title: str = ""
    description: str = ""
    visual_evidence: str = ""
    expected: str = ""
    observed: str = ""
    recommendation: str = ""
    score: float = 0.0
    source: str = "qwen3-vl"


class VisualEvaluationResult(BaseModel):
    status: str = ""  # success, unavailable, parse_failed, image_not_found
    model: str = ""
    visual_content_checked: bool = False
    visual_consistency_score: float = 0.0
    image_caption: str = ""
    detected_objects: list[VisualDetectedObject] = []
    detected_text: list[VisualDetectedText] = []
    spatial_relations: list[VisualSpatialRelation] = []
    detected_style: str = "unknown"
    detected_layout_type: str = "unknown"
    quality_issues: list[VisualQualityIssue] = []
    dimensions: list[VisualEvaluationDimension] = []
    hard_failures: list[VisualHardFailure] = []
    bad_cases: list[VisualBadCase] = []
    recommendations: list[str] = []
    confidence: float = 0.0
    image_sha256: str = ""
    original_image_size: dict = {}
    evaluated_image_size: dict = {}
    model_load_ms: int = 0
    queue_ms: int = 0
    generation_ms: int = 0
    total_ms: int = 0
    retry_count: int = 0
    error_code: str = ""
    error_message: str = ""


# ── Task ───────────────────────────────────────────────

class Task(BaseModel):
    task_id: str
    task_name: str
    status: TaskStatus = TaskStatus.DRAFT
    config: TaskConfig
    script: Optional[DialogueScript] = None
    image: Optional[ImageAsset] = None
    audio: Optional[AudioAsset] = None
    questions: Optional[QuestionSet] = None
    evaluation: Optional[EvalReport] = None
    updated_at: str = ""
    exported_at: Optional[str] = None


# ── API types ──────────────────────────────────────────

class TaskListItem(BaseModel):
    task_id: str
    task_name: str
    topic: str
    status: TaskStatus
    overall_score: float = 0.0
    s3s4_count: int = 0
    updated_at: str = ""
    created_at: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    mode: str = "mock"
    ollama: dict = {}
    comfyui: dict = {}
    piper: dict = {}
    whisper: dict = {}
    ffmpeg: dict = {}
