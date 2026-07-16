/**
 * API client — Real mode only.
 * Base URL from ../config/api.ts (overridable via VITE_API_BASE_URL).
 * No Mock fallback. Structured ApiError with error_code on failures.
 */

import type { HealthResponse, Task, TaskConfig, TaskListItem, AIServicesStatus, RepairStatus } from '../types';
import { API_BASE_URL } from '../config/api';

/* ── Error types ── */

export type ApiErrorCode =
  | 'NETWORK_ERROR'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'VALIDATION_ERROR'
  | 'SERVER_ERROR'
  | 'SERVICE_UNAVAILABLE'
  | 'TIMEOUT'
  | 'UNKNOWN';

export class ApiError extends Error {
  code: ApiErrorCode;
  status: number | null;
  constructor(message: string, code: ApiErrorCode, status: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

function codeFromStatus(status: number): ApiErrorCode {
  if (status === 404) return 'NOT_FOUND';
  if (status === 409) return 'CONFLICT';
  if (status === 422) return 'VALIDATION_ERROR';
  if (status === 503) return 'SERVICE_UNAVAILABLE';
  if (status === 504) return 'TIMEOUT';
  if (status >= 500) return 'SERVER_ERROR';
  return 'UNKNOWN';
}

async function _fetch<T>(url: string, init?: RequestInit, timeoutMs: number = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal: controller.signal });
  } catch (e: any) {
    if (e.name === 'AbortError') {
      throw new ApiError(`请求超时 (${timeoutMs/1000}s): ${url}`, 'TIMEOUT');
    }
    throw new ApiError(
      `无法连接后端 (${API_BASE_URL})。请确认后端已启动。`,
      'NETWORK_ERROR',
    );
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    const d = await res.json().catch(() => ({ detail: res.statusText }));
    const raw = typeof d.detail === 'object'
      ? d.detail.message || JSON.stringify(d.detail)
      : d.detail || res.statusText;
    const code = codeFromStatus(res.status);
    const messages: Record<ApiErrorCode, string> = {
      NETWORK_ERROR: '无法连接后端',
      NOT_FOUND: raw || '资源不存在',
      CONFLICT: raw || '状态冲突，操作不允许',
      VALIDATION_ERROR: raw || '请求参数错误',
      SERVER_ERROR: raw || '后端执行异常',
      SERVICE_UNAVAILABLE: raw || '依赖服务不可用',
      TIMEOUT: raw || '请求超时',
      UNKNOWN: raw || '未知错误',
    };
    throw new ApiError(messages[code], code, res.status);
  }
  return res.json();
}

/* ── Health ── */

export async function healthCheck(): Promise<HealthResponse> {
  try {
    return await _fetch<HealthResponse>(`${API_BASE_URL}/api/health`);
  } catch (e) {
    if (e instanceof ApiError && e.code === 'NETWORK_ERROR') {
      return {
        status: 'error', mode: 'real',
        ollama: { available: false, model: '', model_present: false, last_error: null },
        comfyui: { available: false, status: 'unavailable', state: 'unavailable', base_url: '', api_available: false, workflow_available: false, workflow_path: '', checkpoint_available: false, checkpoint: '', checkpoint_path: '', checkpoint_size: null, generation_ready: false, test_generation: false, missing_models: [], missing_nodes: [], last_error: null, error_code: null, owned: false, pid: null, health_endpoint: null },
        piper: { available: false, status: 'stopped', executable_available: false, executable_path: '', voice_a: false, voice_b: false, voice_a_path: '', voice_b_path: '', voice_a_json_exists: false, voice_b_json_exists: false, test_synthesis: false, missing_voices: [], last_error: null },
        whisper: { available: false, model: '' },
        ffmpeg: { available: false },
      };
    }
    throw e;
  }
}

/* ── Tasks ── */

export function listTasks(): Promise<TaskListItem[]> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks`);
}

export function getTask(taskId: string): Promise<Task> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}`);
}

export function createTask(config: TaskConfig): Promise<Task> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function updateTask(taskId: string, config: TaskConfig): Promise<Task> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

export function deleteTask(taskId: string): Promise<{ ok: boolean }> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}`, { method: 'DELETE' });
}

/* ── Script ── */

export interface ScriptGenerateResult {
  task: Task;
  meta: { model_name: string; model_version: string; prompt_version: string; generation_latency_ms: number; retry_count: number; };
}

export function generateScript(config: TaskConfig): Promise<ScriptGenerateResult> {
  return _fetch(`${API_BASE_URL}/api/v1/script/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  }, 180_000);
}

export function confirmScript(taskId: string): Promise<{ task_id: string; script_version: string; status: string; confirmed_at: string }> {
  return _fetch(`${API_BASE_URL}/api/v1/script/confirm`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  });
}

/* ── Audio ── */

export interface AudioGenerateMeta { duration_sec: number; segment_count: number; output_path: string; voice_a: string; voice_b: string; }

export async function generateAudio(taskId: string, speechRate: string = 'normal', pauseSeconds: number = 0.4): Promise<{ task: Task; meta: AudioGenerateMeta }> {
  const data: any = await _fetch(`${API_BASE_URL}/api/v1/audio/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId, speech_rate: speechRate, pause_seconds: pauseSeconds }),
  }, 120_000);
  const task = await getTask(taskId);
  return { task, meta: data.meta };
}

export interface TranscribeResult { task_id: string; text: string; segments: Array<{ start: number; end: number; text: string }>; language: string; asr_model: string; latency_sec: number; }

export function transcribeAudio(taskId: string): Promise<TranscribeResult> {
  return _fetch(`${API_BASE_URL}/api/v1/audio/transcribe`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  }, 60_000);
}

export interface AudioEvalResult { task_id: string; script_audio_match_pass: boolean; severity: string; missing_keywords: string[]; evidence: string; }

export function evaluateAudio(taskId: string): Promise<AudioEvalResult> {
  return _fetch(`${API_BASE_URL}/api/v1/audio/evaluate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task_id: taskId }),
  }, 60_000);
}

/* ── Questions ── */

export interface QuestionStatus { task_id: string; question_status: string; question_count: number; script_version: string; }

export function getQuestionStatus(taskId: string): Promise<QuestionStatus> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}/questions/status`);
}

export function generateQuestions(taskId: string): Promise<any> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}/questions/generate`, { method: 'POST' }, 180_000);
}

/* ── Asset Validation ── */

export interface AssetValidationResult {
  task_id: string;
  all_valid: boolean;
  image: {
    status: string;
    file_exists: boolean;
    file_path: string;
    file_size: number;
    image_url: string;
    can_open: boolean;
    last_error: string | null;
    stored_status?: string;
  };
  audio: {
    status: string;
    file_exists: boolean;
    file_path: string;
    file_size: number;
    audio_url: string;
    duration_sec: number;
    mime_type: string;
    wav_valid: boolean;
    last_error: string | null;
    stored_status?: string;
  };
  questions: {
    status: string;
    json_file_exists: boolean;
    question_count: number;
    has_options: boolean;
    has_answers: boolean;
    last_error: string | null;
  };
}

export function validateTaskAssets(taskId: string): Promise<AssetValidationResult> {
  return _fetch(`${API_BASE_URL}/api/v1/tasks/${encodeURIComponent(taskId)}/assets/validate`);
}

/* ── Prompt Assistant ── */

export interface PromptAssistResult { success: boolean; raw_input: string; enhanced_prompt: string; model?: string; timing?: { queue_ms: number; generation_ms: number; total_ms: number; retry_count: number; }; }

export async function enhanceImagePrompt(req: { topic: string; scene: string; grade: string; image_style: string; image_goal: string; image_prompt_input: string }): Promise<PromptAssistResult> {
  return _fetch(`${API_BASE_URL}/api/v1/prompt-assistant/image`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(req),
  }, 180_000);
}

/* ── Image ── */

export interface ImageGenerateResult { task: Task; meta: { image_url: string; style: string; width: number; height: number; latency_ms: number; topic_type: string; image_type: string; style_preset: string; render_mode: string; comfyui_used: boolean; }; }

/* ── Export ── */

export interface ExportResult {
  blob: Blob;
  filename: string;
  size: number;
}

export async function exportPackage(taskId: string, filename?: string): Promise<ExportResult> {
  const params = new URLSearchParams();
  if (filename) params.set('filename', filename);
  const url = `${API_BASE_URL}/api/v1/export/tasks/${encodeURIComponent(taskId)}?${params.toString()}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120_000);

  let res: Response;
  try {
    res = await fetch(url, { method: 'POST', signal: controller.signal });
  } catch (e: any) {
    clearTimeout(timer);
    if (e.name === 'AbortError') throw new ApiError('导出超时 (120s)', 'TIMEOUT');
    throw new ApiError('无法连接后端', 'NETWORK_ERROR');
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    const d = await res.json().catch(() => ({ detail: res.statusText }));
    const raw = typeof d.detail === 'object' ? d.detail.message || JSON.stringify(d.detail) : d.detail || res.statusText;
    throw new ApiError(raw || '导出失败', codeFromStatus(res.status), res.status);
  }

  const blob = await res.blob();
  const exportFilename = res.headers.get('X-Export-Filename') || 'export.zip';
  const exportSize = parseInt(res.headers.get('X-Export-Size') || '0', 10);

  return { blob, filename: exportFilename, size: exportSize };
}

export async function generateImage(taskId: string, style?: string): Promise<ImageGenerateResult> {
  const data: any = await _fetch(`${API_BASE_URL}/api/v1/images/tasks/${encodeURIComponent(taskId)}/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(style ? { style } : {}),
  }, 300_000);
  const task = await getTask(taskId);
  return { task, meta: data.meta };
}

/* ── ComfyUI Service ── */

export interface ComfyUIStatus { ok: boolean; launched: boolean; message: string; state: string; pid: number | null; comfyui: HealthResponse['comfyui']; }

export function getComfyUIStatus(): Promise<ComfyUIStatus> {
  return _fetch(`${API_BASE_URL}/api/v1/services/comfyui/status`);
}

export function startComfyUI(): Promise<ComfyUIStatus> {
  return _fetch(`${API_BASE_URL}/api/v1/services/comfyui/start`, { method: 'POST' }, 300_000);
}

/* ── AI Services (repair) ── */

export function getAIServicesStatus(): Promise<AIServicesStatus> {
  return _fetch(`${API_BASE_URL}/api/v1/services/ai/status`);
}

export function triggerAIRepair(): Promise<{ ok: boolean; message: string; job_id: string; log_file: string }> {
  return _fetch(`${API_BASE_URL}/api/v1/services/ai/repair`, { method: 'POST' }, 10000);
}

export function getAIRepairStatus(): Promise<RepairStatus> {
  return _fetch(`${API_BASE_URL}/api/v1/services/ai/repair/status`);
}
