/**
 * Unified Mock Repository backed by localStorage.
 *
 * Keys:
 *   english_workbench_tasks  -> JSON array of Task
 *   english_workbench_scripts -> JSON object { [taskId]: DialogueScript }
 *
 * All read/write goes through these functions — pages never touch localStorage directly.
 */

import type { Task, TaskListItem, TaskConfig, DialogueScript } from '../types';

const TASKS_KEY = 'english_workbench_tasks';
const SCRIPTS_KEY = 'english_workbench_scripts';

/* ── Internal helpers ── */

function loadTasks(): Task[] {
  try {
    const raw = localStorage.getItem(TASKS_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as Task[];
  } catch {
    return [];
  }
}

function saveTasks(tasks: Task[]): void {
  localStorage.setItem(TASKS_KEY, JSON.stringify(tasks));
}

function loadScripts(): Record<string, DialogueScript> {
  try {
    const raw = localStorage.getItem(SCRIPTS_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, DialogueScript>;
  } catch {
    return {};
  }
}

function saveScripts(scripts: Record<string, DialogueScript>): void {
  localStorage.setItem(SCRIPTS_KEY, JSON.stringify(scripts));
}

/* ── Seed initial data ── */

let _seeded = false;

function seedIfEmpty(): void {
  if (_seeded) return;
  const tasks = loadTasks();
  if (tasks.length > 0) {
    _seeded = true;
    return;
  }
  // Create 5 seed tasks with scripts
  const seeds: Array<{ task: Task; script: DialogueScript }> = [];
  const configs = [
    { name: '七年级问路听说课', scenario: '学生询问图书馆位置' },
    { name: '社区指路练习', scenario: '在社区中为陌生人指路' },
    { name: '校园问路场景', scenario: '新生问路到各个教室' },
    { name: '购物中心指路', scenario: '商场内指引店铺位置' },
    { name: '地铁站周边', scenario: '地铁站附近建筑指引' },
  ];
  const statuses: Task['status'][] = ['draft', 'generating', 'needs_fix', 'approved', 'exported'];

  for (let i = 0; i < 5; i++) {
    const taskId = `G7_DIR_${String(i + 1).padStart(3, '0')}`;
    const script = makeMockScript(taskId, configs[i].name, configs[i].scenario, i === 2 ? 'draft' : 'confirmed');
    const task = makeMockTask(taskId, configs[i].name, configs[i].scenario, statuses[i], script, i);
    seeds.push({ task, script });
  }

  const taskMap = seeds.map(s => s.task);
  const scriptMap: Record<string, DialogueScript> = {};
  for (const s of seeds) {
    scriptMap[s.task.task_id] = s.script;
  }
  saveTasks(taskMap);
  saveScripts(scriptMap);
  _seeded = true;
}

function makeMockTask(
  taskId: string, name: string, scenario: string,
  status: Task['status'], script: DialogueScript, idx: number,
): Task {
  const now = new Date().toISOString();
  const config: TaskConfig = {
    task_id: taskId,
    task_name: name,
    grade: 'grade_7',
    lesson_type: 'listening_speaking',
    topic: 'Asking for Directions',
    scenario,
    required_vocabulary: ['library', 'turn left', 'go along'],
    optional_vocabulary: ['bank', 'hospital'],
    target_patterns: ['Where is...?', 'Go along...'],
    effective_vocabulary: ['library', 'turn left', 'go along'],
    effective_target_patterns: ['Where is...?', 'Go along...'],
    vocabulary_constraint_source: 'user',
    target_pattern_source: 'user',
    dialogue_turns: 8,
    speaker_count: 'auto',
    audio_duration_target_sec: 50,
    speech_rate: 'normal',
    image_style: 'textbook_cartoon',
    image_goal: 'auto', image_prompt_input: '', image_prompt_enhanced: '',
    question_type: 'single_choice',
    question_count: 3,
    additional_instruction: '避免超纲词汇',
    created_by: 'user',
    created_at: now,
  };
  const ev = status === 'needs_fix' ? makeMockEvalFail() : (status === 'approved' || status === 'exported' ? makeMockEvalPass() : null);
  return {
    task_id: taskId,
    task_name: name,
    status,
    config,
    script: script.status === 'confirmed' ? { ...script } : (status === 'draft' ? null : script),
    image: status === 'approved' || status === 'exported' || status === 'needs_fix' ? makeMockImage() : null,
    audio: status === 'approved' || status === 'exported' || status === 'needs_fix' ? makeMockAudio() : null,
    questions: status === 'approved' || status === 'exported' || status === 'needs_fix' ? makeMockQuestions() : null,
    evaluation: ev,
    updated_at: now,
    exported_at: status === 'exported' ? now : null,
  };
}

/* ── Public API ── */

export function listMockTasks(): TaskListItem[] {
  seedIfEmpty();
  const tasks = loadTasks();
  return tasks
    .map(t => ({
      task_id: t.task_id,
      task_name: t.task_name,
      topic: t.config.topic,
      status: t.status,
      overall_score: t.evaluation?.overall_score ?? 0,
      s3s4_count: t.evaluation?.s3s4_count ?? 0,
      updated_at: t.updated_at,
      created_at: t.config.created_at,
    }))
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}

export function getMockTask(taskId: string): Task {
  seedIfEmpty();
  const tasks = loadTasks();
  const task = tasks.find(t => t.task_id === taskId);
  if (!task) throw new Error(`Task ${taskId} not found`);
  return task;
}

export function getMockScript(taskId: string): DialogueScript {
  seedIfEmpty();
  const scripts = loadScripts();
  const script = scripts[taskId];
  if (!script) throw new Error(`Script for task ${taskId} not found`);
  return script;
}

export function createMockTask(config: TaskConfig): { task: Task; script: DialogueScript } {
  seedIfEmpty();
  const tasks = loadTasks();
  const scripts = loadScripts();

  const id = `G7_DIR_${String(tasks.length + 1).padStart(3, '0')}`;
  const now = new Date().toISOString();
  config.task_id = id;
  config.created_at = now;

  // Generate mock 8-turn script from config
  const script = makeMockScript(id, config.task_name, config.scenario, 'draft');

  const task: Task = {
    task_id: id,
    task_name: config.task_name,
    status: 'draft',
    config,
    script,
    image: null,
    audio: null,
    questions: null,
    evaluation: null,
    updated_at: now,
    exported_at: null,
  };

  tasks.push(task);
  scripts[id] = script;
  saveTasks(tasks);
  saveScripts(scripts);

  return { task, script };
}

export function updateMockTask(taskId: string, config: TaskConfig): Task {
  seedIfEmpty();
  const tasks = loadTasks();
  const idx = tasks.findIndex(t => t.task_id === taskId);
  if (idx < 0) throw new Error(`Task ${taskId} not found`);
  tasks[idx].config = config;
  tasks[idx].updated_at = new Date().toISOString();
  saveTasks(tasks);
  return tasks[idx];
}

export function saveMockTask(task: Task): void {
  seedIfEmpty();
  const tasks = loadTasks();
  const idx = tasks.findIndex(t => t.task_id === task.task_id);
  if (idx >= 0) {
    tasks[idx] = task;
  } else {
    tasks.push(task);
  }
  saveTasks(tasks);
  // Also save script if present
  if (task.script) {
    const scripts = loadScripts();
    scripts[task.task_id] = task.script;
    saveScripts(scripts);
  }
}

export function deleteMockTask(taskId: string): void {
  const tasks = loadTasks().filter(t => t.task_id !== taskId);
  saveTasks(tasks);
  const scripts = loadScripts();
  delete scripts[taskId];
  saveScripts(scripts);
}

export function clearMockData(): void {
  localStorage.removeItem(TASKS_KEY);
  localStorage.removeItem(SCRIPTS_KEY);
  _seeded = false;
}

/* ── Shared mock data builders ── */

export function makeMockScript(taskId: string, _name: string, scenario: string, status: string): DialogueScript {
  const now = new Date().toISOString();
  // Build a contextual 8-turn dialogue based on the scenario
  const dialogue = buildDialogue(scenario);
  return {
    task_id: taskId,
    script_id: `SCRIPT_${taskId}`,
    script_version: 'v1.0',
    status,
    source_task_config_version: 'v1.0',
    speakers: [
      { speaker_id: 'A', role: 'Student', voice_id: 'en_US-lessac-medium' },
      { speaker_id: 'B', role: 'Passer-by', voice_id: 'en_US-ryan-medium' },
    ],
    dialogue,
    used_vocabulary: ['library', 'turn left', 'go along', 'bank', 'hospital', 'across from'],
    used_patterns: ['Where is...?', 'Go along...', 'Excuse me...'],
    total_words: dialogue.reduce((sum, t) => sum + t.text.split(/\s+/).length, 0),
    created_at: now,
    confirmed_at: status === 'confirmed' ? now : null,
  };
}

function buildDialogue(_scenario: string) {
  // Fixed 8-turn dialogue for Mock mode
  return [
    { turn_id: 1, speaker_id: 'A', text: 'Excuse me, where is the library?' },
    { turn_id: 2, speaker_id: 'B', text: 'Go along this street and turn left at the bank.' },
    { turn_id: 3, speaker_id: 'A', text: 'Is it far from here?' },
    { turn_id: 4, speaker_id: 'B', text: 'No, it\'s about a five-minute walk.' },
    { turn_id: 5, speaker_id: 'A', text: 'Thank you! And is there a hospital nearby?' },
    { turn_id: 6, speaker_id: 'B', text: 'Yes, the hospital is across from the library.' },
    { turn_id: 7, speaker_id: 'A', text: 'Got it. Thanks for your help!' },
    { turn_id: 8, speaker_id: 'B', text: 'You\'re welcome. Have a nice day!' },
  ];
}

function makeMockImage() {
  return {
    image_id: 'IMG_001',
    image_url: '',
    image_source_script_version: 'v1.0',
    generation_status: 'success' as const,
    is_outdated: false,
    model_name: 'SDXL Base 1.0',
    model_version: '1.0',
    prompt_version: 'v1.0',
    generation_latency_ms: 8500,
    estimated_cost: 0.0,
  };
}

function makeMockAudio() {
  return {
    audio_id: 'AUD_001',
    audio_url: '',
    audio_duration_actual_sec: 48.5,
    audio_source_script_version: 'v1.0',
    speaker_profiles: { A: 'en_US-lessac-medium', B: 'en_US-ryan-medium' },
    generation_status: 'success' as const,
    is_outdated: false,
    model_name: 'Piper TTS',
    model_version: '1.0',
    prompt_version: 'v1.0',
    generation_latency_ms: 3200,
    estimated_cost: 0.0,
  };
}

function makeMockQuestions() {
  return {
    question_set_id: 'QSET_001',
    questions: [
      { index: 1, stem: 'Where is the library?', options: ['Next to the bank', 'Go along and turn left at the bank', 'Across from the hospital', 'Behind the school'], answer: 'Go along and turn left at the bank', explanation: '路人说 Go along this street and turn left at the bank' },
      { index: 2, stem: 'How long does it take to walk to the library?', options: ['About 3 minutes', 'About 5 minutes', 'About 10 minutes', 'About 15 minutes'], answer: 'About 5 minutes', explanation: '路人说 it\'s about a five-minute walk' },
      { index: 3, stem: 'Where is the hospital?', options: ['Next to the bank', 'Across from the library', 'Behind the school', 'On the left'], answer: 'Across from the library', explanation: '路人说 the hospital is across from the library' },
    ],
    question_source_script_version: 'v1.0',
    generation_status: 'success' as const,
    is_outdated: false,
    model_name: 'qwen3:4b-instruct',
    model_version: '4b',
    prompt_version: 'v1.0',
    generation_latency_ms: 4200,
    estimated_cost: 0.0,
  };
}

function makeMockEvalPass() {
  return {
    task_id: '',
    evaluation_version: 'v1.0',
    overall_score: 92,
    pass_status: 'pass' as const,
    dimension_scores: { textQuality: 90, audioQuality: 88, imageQuality: 85, questionQuality: 95, crossModal: 95 },
    items: [],
    s3s4_count: 0,
    generated_at: new Date().toISOString(),
    combined_score: 92,
    rule_score: 90,
    semantic_score: 88,
    visual_score: 0,
    semantic_data: null,
    visual_data: null,
    asset_fingerprint: '',
    evaluation_status: 'generated_rule_only',
    semantic_prompt_version: '',
    visual_prompt_version: '',
    model: 'rule_only',
  };
}

function makeMockEvalFail() {
  return {
    task_id: '',
    evaluation_version: 'v1.0',
    overall_score: 68,
    pass_status: 'fail' as const,
    dimension_scores: { textQuality: 70, audioQuality: 75, imageQuality: 80, questionQuality: 55, crossModal: 60 },
    items: [{
      evaluation_id: 'EVAL_BC_001',
      evaluation_version: 'v1.0',
      target_type: 'question' as const,
      target_id: 'QSET_001',
      overall_score: 0,
      dimension_scores: { answerCorrectness: 0 },
      pass_status: 'fail' as const,
      error_type: 'answer_error',
      severity: 'S3' as const,
      error_location: '第3题',
      evidence: '音频中说 "the hospital is across from the library"，需确认答案选项唯一正确。',
      suspected_cause: '干扰项设计不够清晰',
      repair_suggestion: '重新生成第3题，确保唯一正确答案与音频内容严格一致。',
      evaluator_type: 'llm' as const,
      evaluator_model: 'qwen3:4b-instruct',
      teacher_feedback: null,
      teacher_correction: '',
      evaluated_at: new Date().toISOString(),
    }],
    s3s4_count: 1,
    generated_at: new Date().toISOString(),
    combined_score: 68,
    rule_score: 70,
    semantic_score: 55,
    visual_score: 0,
    semantic_data: null,
    visual_data: null,
    asset_fingerprint: '',
    evaluation_status: 'generated_rule_only',
    semantic_prompt_version: '',
    visual_prompt_version: '',
    model: 'rule_only',
  };
}
