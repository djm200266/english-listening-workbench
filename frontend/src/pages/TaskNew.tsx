import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { TaskConfig, ImageStyle, SpeechRate, GradeLevel } from '../types';
import { IMAGE_STYLE_LABELS, GRADE_LABELS } from '../types';
import { createTask, updateTask, generateScript, getTask, ApiError, enhanceImagePrompt } from '../services/api';

const EMPTY_CONFIG: TaskConfig = {
  task_id: '', task_name: '', grade: 'grade_7', lesson_type: 'listening_speaking',
  topic: 'Asking for Directions', scenario: '',
  required_vocabulary: [], optional_vocabulary: [], target_patterns: [],
  effective_vocabulary: [], effective_target_patterns: [],
  vocabulary_constraint_source: 'user', target_pattern_source: 'user',
  dialogue_turns: 8, speaker_count: 'auto' as number | 'auto', audio_duration_target_sec: 50,
  speech_rate: 'normal' as SpeechRate, image_style: 'textbook_cartoon' as ImageStyle,
  image_goal: 'auto', image_prompt_input: '', image_prompt_enhanced: '',
  question_type: 'single_choice', question_count: 3,
  additional_instruction: '', created_by: 'user', created_at: '',
};

export default function TaskNew() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const editId = params.get('edit');
  const retryTaskId = params.get('retryTaskId');
  const [config, setConfig] = useState<TaskConfig>({ ...EMPTY_CONFIG });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [stage, setStage] = useState('');
  const [elapsedSec, setElapsedSec] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const savedTaskIdRef = useRef<string>('');

  // Cleanup timer on unmount
  useEffect(() => {
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  // Load task if editing
  useEffect(() => {
    if (editId) {
      getTask(editId).then(t => setConfig({ ...t.config })).catch(() => {});
    }
  }, [editId]);

  // getTask already imported from '../services/api' at top

  const startTimer = useCallback(() => {
    setElapsedSec(0);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => setElapsedSec(s => s + 1), 1000);
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  }, []);

  const set = (key: keyof TaskConfig, value: unknown) => {
    setConfig(prev => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors(prev => { const n = { ...prev }; delete n[key]; return n; });
  };

  const validateWith = (cfg: TaskConfig): boolean => {
    const e: Record<string, string> = {};
    if (!cfg.task_name.trim()) e.task_name = '请输入任务名称';
    if (!cfg.scenario.trim()) e.scenario = '请输入场景描述';
    if (cfg.dialogue_turns < 6 || cfg.dialogue_turns > 12) e.dialogue_turns = '轮次需在6-12之间';
    if (cfg.audio_duration_target_sec < 30 || cfg.audio_duration_target_sec > 90) e.audio_duration_target_sec = '时长需在30-90秒之间';
    if (cfg.question_count < 2 || cfg.question_count > 5) e.question_count = '题数需在2-5之间';
    if (cfg.dialogue_turns >= 8 && cfg.audio_duration_target_sec < 40) {
      e.conflict = `对话${cfg.dialogue_turns}轮但音频仅${cfg.audio_duration_target_sec}秒，建议增加音频时长或减少轮次`;
    }
    // required_vocabulary and target_patterns are now optional — system auto-fills when empty
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const normalize = (cfg: TaskConfig): TaskConfig => {
    // Filter empty strings, pure whitespace, and duplicates before submit
    const clean = (arr: string[]) => [...new Set(arr.map(s => s.trim()).filter(s => s.length > 0))];
    return {
      ...cfg,
      required_vocabulary: clean(cfg.required_vocabulary),
      optional_vocabulary: clean(cfg.optional_vocabulary),
      target_patterns: clean(cfg.target_patterns),
      // Set constraint sources: 'user' if user provided values, 'auto' if empty
      vocabulary_constraint_source: clean(cfg.required_vocabulary).length > 0 ? 'user' : 'auto',
      target_pattern_source: clean(cfg.target_patterns).length > 0 ? 'user' : 'auto',
    };
  };

  const handleSubmit = async (draft: boolean) => {
    const normalized = normalize(config);
    // Sync state so UI reflects cleaned values
    setConfig(normalized);
    // Use normalized for validation
    if (!validateWith(normalized)) return;
    setSaving(true);
    setErrors({});
    stopTimer();

    try {
      if (draft) {
        setStage('保存草稿...');
        if (editId) await updateTask(editId, normalized);
        else await createTask(normalized);
        navigate('/');
        return;
      }

      // ── Phase 1: Create task ──
      setStage('正在保存任务...');
      startTimer();
      let taskId = retryTaskId || savedTaskIdRef.current || '';

      if (!taskId) {
        // Create new task
        const task = await createTask(normalized);
        taskId = task.task_id;
        savedTaskIdRef.current = taskId;
      }

      // ── Phase 2: Generate script ──
      setStage('任务已保存，正在调用 Qwen 生成脚本...');
      const result = await generateScript(normalized);

      // Success
      stopTimer();
      setStage('生成成功，正在进入脚本审核页...');
      const actualTaskId = result.task.task_id;
      setTimeout(() => navigate(`/task/${actualTaskId}/script`), 500);
    } catch (err: unknown) {
      stopTimer();
      const isApiErr = err instanceof ApiError;
      let msg: string;
      if (isApiErr) {
        const codeMap: Record<string, string> = {
          NETWORK_ERROR: '后端未启动，无法保存任务',
          OLLAMA_OFFLINE: '任务已保存，但 Ollama 未启动，无法生成脚本',
          MODEL_NOT_FOUND: '任务已保存，但未找到模型 qwen3:4b-instruct',
          OLLAMA_TIMEOUT: '任务已保存，但模型生成超时，请重试',
          MODEL_OUTPUT_VALIDATION_FAILED: '任务已保存，但脚本格式校验失败，请重试',
          SERVICE_UNAVAILABLE: '任务已保存，但依赖服务不可用',
        };
        msg = codeMap[err.code] || `任务已保存，但脚本生成失败：${err.message}`;
      } else {
        msg = err instanceof Error ? err.message : '操作失败';
      }

      setErrors({ submit: msg });
      if (savedTaskIdRef.current && !retryTaskId) {
        // Navigate so user can retry with same task_id
        const tid = savedTaskIdRef.current;
        // Store retry info in URL
        setStage('');
        // Provide retry button inline
      }
    } finally {
      setSaving(false);
      stopTimer();
    }
  };

  const handleRetry = async () => {
    const tid = savedTaskIdRef.current;
    if (!tid) return;
    setSaving(true);
    setErrors({});
    stopTimer();
    setStage('正在重新调用 Qwen 生成脚本...');
    startTimer();
    const retryConfig = normalize(config);
    try {
      const result = await generateScript(retryConfig);
      stopTimer();
      const actualTaskId = result.task.task_id;
      setTimeout(() => navigate(`/task/${actualTaskId}/script`), 500);
    } catch (err: unknown) {
      stopTimer();
      const msg = err instanceof Error ? err.message : '重试失败';
      setErrors({ submit: `重新生成失败：${msg}` });
    } finally {
      setSaving(false);
    }
  };

  const tagInput = (
    label: string, field: 'required_vocabulary' | 'optional_vocabulary' | 'target_patterns',
    values: string[], placeholder: string
  ) => (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      <div className="flex flex-wrap gap-1 mb-1">
        {values.map((v, i) => (
          <span key={i} className="inline-flex items-center gap-1 px-2 py-0.5 bg-brand-50 text-brand-700 text-xs rounded">
            {v}
            <button onClick={() => set(field, values.filter((_, j) => j !== i))} className="hover:text-red-500">&times;</button>
          </span>
        ))}
      </div>
      <input type="text" placeholder={placeholder}
        className={`w-full px-3 py-1.5 border rounded text-sm ${errors[field] ? 'border-red-400' : ''}`}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            const val = (e.target as HTMLInputElement).value.trim();
            if (val && !values.includes(val)) { set(field, [...values, val]); (e.target as HTMLInputElement).value = ''; }
            e.preventDefault();
          }
        }} />
      {errors[field] && <p className="text-red-500 text-xs mt-1">{errors[field]}</p>}
    </div>
  );

  const hasRetryTask = !!(retryTaskId || savedTaskIdRef.current);

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-800 mb-6">{editId ? '编辑任务' : '新建任务'}</h1>

      {/* Progress indicator */}
      {saving && (
        <div className="bg-blue-50 border border-blue-300 rounded-lg p-4 mb-4 flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          <div>
            <p className="text-sm font-medium text-blue-800">{stage || '处理中...'}</p>
            {elapsedSec > 0 && (
              <p className="text-xs text-blue-500">已等待 {elapsedSec} 秒{elapsedSec > 5 ? '，Qwen 正在生成脚本，请耐心等待...' : ''}</p>
            )}
          </div>
        </div>
      )}

      {/* Error with retry */}
      {errors.submit && (
        <div className="bg-red-50 border border-red-300 rounded-lg p-4 mb-4 text-sm">
          <p className="text-red-700 mb-2">{errors.submit}</p>
          <div className="flex gap-2">
            {hasRetryTask && (
              <button onClick={handleRetry} disabled={saving}
                className="px-4 py-1.5 bg-brand-600 text-white rounded text-sm hover:bg-brand-700 disabled:opacity-50">
                重新生成脚本
              </button>
            )}
            {savedTaskIdRef.current && (
              <button onClick={() => navigate(`/task/${savedTaskIdRef.current}/script`)}
                className="px-4 py-1.5 border rounded text-sm text-gray-600 hover:bg-gray-50">
                查看已保存的任务
              </button>
            )}
          </div>
        </div>
      )}

      {/* Basic Info */}
      <section className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">基础信息</h2>
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">任务名称 *</label>
            <input type="text" value={config.task_name} onChange={e => set('task_name', e.target.value)}
              className={`w-full px-3 py-1.5 border rounded ${errors.task_name ? 'border-red-400' : ''}`} />
            {errors.task_name && <p className="text-red-500 text-xs mt-1">{errors.task_name}</p>}
          </div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">年级 *</label>
            <select value={config.grade} onChange={e => set('grade', e.target.value as GradeLevel)} className="w-full px-3 py-1.5 border rounded text-sm">
              {(Object.entries(GRADE_LABELS) as [GradeLevel, string][]).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}
            </select></div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">课型</label>
            <input type="text" value="听说课 (listening_speaking)" disabled className="w-full px-3 py-1.5 border rounded bg-gray-50 text-gray-500 text-sm" /></div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">主题</label>
            <input type="text" value={config.topic} onChange={e => set('topic', e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm" /></div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">场景 *</label>
            <input type="text" value={config.scenario} onChange={e => set('scenario', e.target.value)} placeholder="如：学生询问图书馆位置"
              className={`w-full px-3 py-1.5 border rounded text-sm ${errors.scenario ? 'border-red-400' : ''}`} />
            {errors.scenario && <p className="text-red-500 text-xs mt-1">{errors.scenario}</p>}</div>
        </div>
      </section>

      {/* Language */}
      <section className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">语言约束</h2>
        <div className="space-y-3">
          {tagInput('必选词汇（可选）', 'required_vocabulary', config.required_vocabulary, '如 mountain、weather、library，输入后按回车添加')}
          <p className="text-xs text-gray-400 -mt-2">未指定时，系统将根据年级、主题和场景自动选择合适词汇。</p>
          {tagInput('可选词汇', 'optional_vocabulary', config.optional_vocabulary, '输入后按回车添加')}
          {tagInput('目标句型（可选）', 'target_patterns', config.target_patterns, '如 Where is...?、How\'s the weather?，输入后按回车添加')}
          <p className="text-xs text-gray-400 -mt-2">未指定时，系统将自动设计符合当前课题的核心句型。</p>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">对话轮次 * (6-12)</label>
            <input type="number" min={6} max={12} value={config.dialogue_turns} onChange={e => set('dialogue_turns', Number(e.target.value))}
              className={`w-24 px-3 py-1.5 border rounded text-sm ${errors.dialogue_turns ? 'border-red-400' : ''}`} />
            {errors.dialogue_turns && <p className="text-red-500 text-xs mt-1">{errors.dialogue_turns}</p>}</div>
        </div>
      </section>

      {/* Audio */}
      <section className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">音频设置</h2>
        <div className="grid grid-cols-3 gap-4">
          <div><label className="block text-sm font-medium text-gray-700 mb-1">角色数</label>
            <select value={String(config.speaker_count)} onChange={e => {
              const v = e.target.value;
              set('speaker_count', v === 'auto' ? 'auto' : Number(v));
            }} className="w-full px-3 py-1.5 border rounded text-sm">
              <option value="auto">自动</option>
              <option value="1">1人</option>
              <option value="2">2人</option>
              <option value="3">3人</option>
              <option value="4">4人</option>
            </select></div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">语速</label>
            <select value={config.speech_rate} onChange={e => set('speech_rate', e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm">
              <option value="normal">正常</option><option value="slow">慢速</option></select></div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">目标时长(秒) *</label>
            <input type="number" min={30} max={90} value={config.audio_duration_target_sec} onChange={e => set('audio_duration_target_sec', Number(e.target.value))}
              className={`w-full px-3 py-1.5 border rounded text-sm ${errors.audio_duration_target_sec ? 'border-red-400' : ''}`} />
            {errors.audio_duration_target_sec && <p className="text-red-500 text-xs mt-1">{errors.audio_duration_target_sec}</p>}</div>
        </div>
      </section>

      {/* Questions */}
      <section className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">题目设置</h2>
        <div className="grid grid-cols-3 gap-4">
          <div><label className="block text-sm font-medium text-gray-700 mb-1">题型</label>
            <input type="text" value="单选题 (single_choice)" disabled className="w-full px-3 py-1.5 border rounded bg-gray-50 text-gray-500 text-sm" /></div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">题数 * (2-5)</label>
            <input type="number" min={2} max={5} value={config.question_count} onChange={e => set('question_count', Number(e.target.value))}
              className={`w-full px-3 py-1.5 border rounded text-sm ${errors.question_count ? 'border-red-400' : ''}`} />
            {errors.question_count && <p className="text-red-500 text-xs mt-1">{errors.question_count}</p>}</div>
          <div><label className="block text-sm font-medium text-gray-700 mb-1">图片风格</label>
            <select value={config.image_style} onChange={e => set('image_style', e.target.value)} className="w-full px-3 py-1.5 border rounded text-sm">
              {(Object.entries(IMAGE_STYLE_LABELS) as [ImageStyle, string][]).map(([k, v]) => (<option key={k} value={k}>{v}</option>))}</select></div>
        </div>
      </section>

      {/* Image Generation Settings */}
      <section className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">图片生成设置</h2>
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">图片生成意图</label>
            <select value={config.image_goal} onChange={e => set('image_goal', e.target.value)}
              className="w-full px-3 py-1.5 border rounded text-sm">
              <option value="auto">自动判断</option>
              <option value="reference_map">位置参考图</option>
              <option value="weather_visual">天气图</option>
              <option value="story_panel">故事分镜图</option>
              <option value="scene">情境图</option>
              <option value="vocab_visual">词汇图</option>
              <option value="classroom_poster">教学插图/海报</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">用户图片提示词（可选）</label>
            <textarea value={config.image_prompt_input} onChange={e => set('image_prompt_input', e.target.value)}
              placeholder={'例如：\n- 画一张清晰的街道参考位置图，标出 library, bank, hospital, park\n- 生成天气教学图，展示 sunny / cloudy / rainy\n- 生成 4 格故事图，表现愚公移山主要情节'}
              className="w-full px-3 py-1.5 border rounded text-sm h-20 resize-none" />
            <div className="flex items-center gap-2 mt-2">
              <PromptEnhancer config={config} onEnhanced={(enhanced: string) => set('image_prompt_enhanced', enhanced)} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">增强后的图片 Prompt（可编辑）</label>
            <textarea value={config.image_prompt_enhanced} onChange={e => set('image_prompt_enhanced', e.target.value)}
              placeholder="点击「完善图片Prompt」自动生成，或手动输入完整prompt..."
              className="w-full px-3 py-1.5 border rounded text-sm h-20 resize-none bg-blue-50" />
            <p className="text-xs text-gray-400 mt-1">此 Prompt 将优先生效；为空时由系统自动生成。</p>
          </div>
          <p className="text-xs text-gray-400">系统会根据所选年级和教材的卡通教学插图风格，生成适合对应年级英语课堂使用的图片。</p>
        </div>
      </section>

      {/* Additional */}
      <section className="bg-white rounded-lg p-5 shadow-sm border mb-6">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">补充说明</h2>
        <textarea value={config.additional_instruction} onChange={e => set('additional_instruction', e.target.value)}
          placeholder="补充教学要求，如：避免超纲词汇、注重礼貌用语..." className="w-full px-3 py-1.5 border rounded text-sm h-20 resize-none" />
      </section>

      {errors.conflict && (
        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-3 mb-4 text-sm text-yellow-800">⚠️ 约束冲突：{errors.conflict}</div>
      )}

      <div className="flex gap-3 justify-end">
        <button onClick={() => navigate('/')} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50">取消</button>
        <button onClick={() => handleSubmit(true)} disabled={saving} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50 disabled:opacity-50">保存草稿</button>
        <button onClick={() => handleSubmit(false)} disabled={saving}
          className="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50 font-medium">
          {saving ? (elapsedSec > 0 ? `生成中 ${elapsedSec}s...` : '提交中...') : '提交并生成脚本'}
        </button>
      </div>
    </div>
  );
}

/* ── PromptEnhancer sub-component ── */

function PromptEnhancer({ config, onEnhanced }: { config: TaskConfig; onEnhanced: (enhanced: string) => void }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [waitSec, setWaitSec] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const handleEnhance = async () => {
    if (loading) return;
    setLoading(true); setError(null); setWaitSec(0);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => setWaitSec(s => s + 1), 1000);
    try {
      const result = await enhanceImagePrompt({
        topic: config.topic, scene: config.scenario, grade: config.grade,
        image_style: config.image_style, image_goal: config.image_goal,
        image_prompt_input: config.image_prompt_input,
      });
      if (result.enhanced_prompt) {
        onEnhanced(result.enhanced_prompt);
      }
    } catch (e: any) {
      const msg = e?.message || '';
      const code = e?.code || '';
      if (code === 'TIMEOUT' || msg.includes('超时')) {
        setError('Prompt 助手等待超过180秒，请检查 Ollama 负载后重试。');
      } else if (code === 'NOT_FOUND' || msg.includes('Not Found')) {
        setError('Prompt助手接口未注册，请重启后端并检查路由。');
      } else if (code === 'NETWORK_ERROR') {
        setError('后端未启动，无法使用Prompt助手。');
      } else if (msg.includes('Ollama') || msg.includes('OLLAMA')) {
        setError(msg);
      } else {
        setError(msg || 'Prompt 增强失败');
      }
    } finally {
      setLoading(false);
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button onClick={handleEnhance} disabled={loading}
        className="px-3 py-1 text-sm bg-purple-100 text-purple-700 rounded hover:bg-purple-200 disabled:opacity-50 whitespace-nowrap">
        {loading ? `完善中 ${waitSec}s...` : '完善图片Prompt'}
      </button>
      {loading && waitSec > 5 && (
        <span className="text-xs text-gray-400">首次运行可能需要较长时间...</span>
      )}
      {error && <span className="text-xs text-red-500">{error}</span>}
    </div>
  );
}
