/* ── TypeScript types matching PRD data fields ── */

/* ── Enums ── */

export type TaskStatus =
  | 'draft' | 'generating' | 'partial_success' | 'evaluating'
  | 'failed' | 'needs_fix' | 'outdated'
  | 'pending_review' | 'approved' | 'exported';

export type ScriptStatus = 'draft' | 'confirmed';

export type EvalStatus = 'not_evaluated' | 'evaluating' | 'evaluated' | 'has_issues';

export type Severity = 'S0' | 'S1' | 'S2' | 'S3' | 'S4';

export type PassStatus = 'pass' | 'fail' | 'manual_review';

export type AssetStatus = 'generating' | 'success' | 'failed' | 'outdated';

export type TeacherFeedback = 'agree' | 'false_positive' | 'fixed' | 'missed';

export type EvaluatorType = 'rule' | 'llm' | 'asr' | 'multimodal' | 'human';

export type SpeechRate = 'slow' | 'normal';

export type GradeLevel = 'grade_7' | 'grade_8' | 'grade_9';

export const GRADE_LABELS: Record<GradeLevel, string> = {
  grade_7: '七年级',
  grade_8: '八年级',
  grade_9: '九年级',
};

export type ImageStyle = 'structured_schematic' | 'textbook_cartoon' | 'watercolor' | 'photorealistic' | 'flat_vector' | 'hand_drawn' | 'comic' | 'colored_pencil' | 'three_d_cartoon' | 'cartoon' | 'children_book' | 'flat' | 'realistic';

export type AppMode = 'mock' | 'real';

/* ── Status display labels ── */

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  draft: '草稿',
  generating: '生成中',
  partial_success: '部分成功',
  evaluating: '评测中',
  failed: '失败',
  needs_fix: '存在问题',
  outdated: '已过期',
  pending_review: '待审核',
  approved: '已审核',
  exported: '已导出',
};

export const SCRIPT_STATUS_LABELS: Record<ScriptStatus, string> = {
  draft: '脚本草稿',
  confirmed: '脚本已确认',
};

export const EVAL_STATUS_LABELS: Record<EvalStatus, string> = {
  not_evaluated: '尚未评测',
  evaluating: '评测中',
  evaluated: '已评测',
  has_issues: '存在问题',
};

/** @deprecated Use TASK_STATUS_LABELS */
export const STATUS_LABELS = TASK_STATUS_LABELS;

export const SEVERITY_LABELS: Record<Severity, string> = {
  S0: '无问题',
  S1: '轻微',
  S2: '需修改',
  S3: '不可直接使用',
  S4: '安全高风险',
};

export const IMAGE_STYLE_LABELS: Record<ImageStyle, string> = {
  structured_schematic: '结构化示意图',
  textbook_cartoon: '教材卡通',
  watercolor: '水彩插画',
  photorealistic: '写实风格',
  flat_vector: '扁平矢量',
  hand_drawn: '手绘风格',
  comic: '漫画风格',
  colored_pencil: '彩色铅笔',
  three_d_cartoon: '3D卡通',
  cartoon: '卡通(旧)',
  children_book: '儿童绘本(旧)',
  flat: '扁平(旧)',
  realistic: '写实(旧)',
};

/* ── Data models ── */

export interface Speaker {
  speaker_id: string;
  role: string;
  voice_id: string;
}

export interface DialogueTurn {
  turn_id: number;
  speaker_id: string;
  text: string;
}

export interface DialogueScript {
  task_id: string;
  script_id: string;
  script_version: string;
  status: string;
  source_task_config_version: string;
  speakers: Speaker[];
  dialogue: DialogueTurn[];
  used_vocabulary: string[];
  used_patterns: string[];
  total_words: number;
  created_at: string;
  confirmed_at: string | null;
}

export type ConstraintSource = 'user' | 'auto';

export interface TaskConfig {
  task_id: string;
  task_name: string;
  grade: GradeLevel;
  lesson_type: string;
  topic: string;
  scenario: string;
  required_vocabulary: string[];
  optional_vocabulary: string[];
  target_patterns: string[];
  effective_vocabulary: string[];
  effective_target_patterns: string[];
  vocabulary_constraint_source: ConstraintSource;
  target_pattern_source: ConstraintSource;
  dialogue_turns: number;
  speaker_count: number | 'auto';
  audio_duration_target_sec: number;
  speech_rate: SpeechRate;
  image_style: ImageStyle;
  image_goal: string;
  image_prompt_input: string;
  image_prompt_enhanced: string;
  question_type: string;
  question_count: number;
  additional_instruction: string;
  created_by: string;
  created_at: string;
}

export interface ImageAsset {
  image_id: string;
  image_url: string;
  image_source_script_version: string;
  generation_status: AssetStatus;
  is_outdated: boolean;
  model_name: string;
  model_version: string;
  prompt_version: string;
  generation_latency_ms: number;
  estimated_cost: number;
  topic_type?: string;
  image_type?: string;
  style_preset?: string;
  render_mode?: string;
}

export interface AudioAsset {
  audio_id: string;
  audio_url: string;
  audio_duration_actual_sec: number;
  audio_source_script_version: string;
  speaker_profiles: Record<string, unknown>;
  generation_status: AssetStatus;
  is_outdated: boolean;
  model_name: string;
  model_version: string;
  prompt_version: string;
  generation_latency_ms: number;
  estimated_cost: number;
}

export interface Question {
  index: number;
  stem: string;
  options: string[];
  answer: string;
  explanation: string;
}

export interface QuestionSet {
  question_set_id: string;
  questions: Question[];
  question_source_script_version: string;
  generation_status: AssetStatus;
  is_outdated: boolean;
  model_name: string;
  model_version: string;
  prompt_version: string;
  generation_latency_ms: number;
  estimated_cost: number;
}

export interface EvaluationItem {
  evaluation_id: string;
  evaluation_version: string;
  target_type: string;
  target_id: string;
  overall_score: number;
  dimension_scores: Record<string, number>;
  pass_status: PassStatus;
  error_type: string;
  severity: Severity;
  error_location: string;
  evidence: string;
  suspected_cause: string;
  repair_suggestion: string;
  evaluator_type: EvaluatorType;
  evaluator_model: string;
  teacher_feedback: TeacherFeedback | null;
  teacher_correction: string;
  evaluated_at: string;
}

export interface EvalReport {
  task_id: string;
  evaluation_version: string;
  overall_score: number;
  pass_status: PassStatus;
  dimension_scores: Record<string, number>;
  items: EvaluationItem[];
  s3s4_count: number;
  generated_at: string;
  // Combined evaluation fields
  combined_score: number;
  rule_score: number;
  semantic_score: number;
  visual_score: number | null;
  semantic_data: Record<string, any> | null;
  visual_data: Record<string, any> | null;
  asset_fingerprint: string;
  evaluation_status: string;
  semantic_prompt_version: string;
  visual_prompt_version: string;
  model: string;
}

// Visual evaluation sub-types
export interface VisualDetectedObject {
  label: string;
  category: string;
  confidence: number;
  bbox_hint: string;
}

export interface VisualDetectedText {
  text: string;
  confidence: number;
  location: string;
  language: string;
}

export interface VisualSpatialRelation {
  relation: string;
  subject: string;
  object: string;
  confidence: number;
}

export interface VisualQualityIssue {
  issue_type: string;
  description: string;
  severity: string;
  location: string;
}

export interface VisualEvaluationDimension {
  key: string;
  label: string;
  score: number;
  max_score: number;
  status: string;
  confidence: number;
  evidence: string[];
  issues: string[];
  suggestions: string[];
}

export interface VisualHardFailure {
  code: string;
  severity: string;
  evidence: string;
  recommendation: string;
}

export interface VisualBadCase {
  id: string;
  modality: string;
  severity: string;
  category: string;
  title: string;
  description: string;
  visual_evidence: string;
  expected: string;
  observed: string;
  recommendation: string;
  score: number;
  source: string;
}

export interface VisualEvaluationResult {
  status: string;
  model: string;
  visual_content_checked: boolean;
  visual_consistency_score: number;
  image_caption: string;
  detected_objects: VisualDetectedObject[];
  detected_text: VisualDetectedText[];
  spatial_relations: VisualSpatialRelation[];
  detected_style: string;
  detected_layout_type: string;
  quality_issues: VisualQualityIssue[];
  dimensions: VisualEvaluationDimension[];
  hard_failures: VisualHardFailure[];
  bad_cases: VisualBadCase[];
  recommendations: string[];
  confidence: number;
  image_sha256: string;
  original_image_size: { width: number; height: number };
  evaluated_image_size: { width: number; height: number };
  model_load_ms: number;
  queue_ms: number;
  generation_ms: number;
  total_ms: number;
  retry_count: number;
  error_code: string;
  error_message: string;
}

export interface Task {
  task_id: string;
  task_name: string;
  status: TaskStatus;
  config: TaskConfig;
  script: DialogueScript | null;
  image: ImageAsset | null;
  audio: AudioAsset | null;
  questions: QuestionSet | null;
  evaluation: EvalReport | null;
  updated_at: string;
  exported_at: string | null;
}

export interface TaskListItem {
  task_id: string;
  task_name: string;
  topic: string;
  status: TaskStatus;
  overall_score: number;
  s3s4_count: number;
  updated_at: string;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  mode: string;
  ollama: { available: boolean; model: string; model_present: boolean; last_error: string | null };
  comfyui: { available: boolean; state: string; base_url: string; workflow_available: boolean; checkpoint_available: boolean; generation_ready: boolean; checkpoint: string; last_error: string | null; error_code: string | null; owned: boolean; pid: number | null; health_endpoint: string | null };
  piper: { available: boolean; voice_a: boolean; voice_b: boolean };
  whisper: { available: boolean; model: string };
  ffmpeg: { available: boolean };
}
