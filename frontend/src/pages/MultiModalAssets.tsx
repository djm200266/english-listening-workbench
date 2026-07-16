import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Task, ImageStyle } from '../types';
import { getTask, generateAudio, transcribeAudio, evaluateAudio, generateImage, getQuestionStatus, generateQuestions, startComfyUI, ApiError } from '../services/api';
import type { AudioEvalResult, QuestionStatus } from '../services/api';
import { API_BASE_URL } from '../config/api';
import { IMAGE_STYLE_LABELS } from '../types';
import { AssetStatusBadge, TaskStatusBadge } from '../components/StatusBadge';
import { useAppContext } from '../App';

const TOPIC_LABEL: Record<string, string> = {
  directions: '问路/指路', weather: '天气', story: '故事', fallback: '综合',
};
const TYPE_LABEL: Record<string, string> = {
  location_reference_map: '位置参考图', weather_reference_scene: '天气参考图',
  story_reference_illustration: '故事参考图', topic_scene_illustration: '主题插图',
};

function assetUrl(imageUrl: string | undefined): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) return imageUrl;
  return `${API_BASE_URL}${imageUrl.startsWith('/') ? '' : '/'}${imageUrl}`;
}

export default function MultiModalAssets() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    if (!taskId) return;
    setLoading(true);
    try { setTask(await getTask(taskId)); } catch { /* keep stale */ }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [taskId]);

  if (loading) return <div className="text-center py-16"><div className="inline-block w-8 h-8 border-4 border-brand-300 border-t-brand-600 rounded-full animate-spin mb-4" /><p className="text-gray-400">加载中...</p></div>;
  if (!task) return <div className="text-center py-16 text-gray-400">任务不存在</div>;

  const scriptConfirmed = task.script?.status === 'confirmed';

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-800">{task.task_name} · 多模态结果</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
            <span className="font-mono">{task.task_id}</span>
            <TaskStatusBadge status={task.status} />
          </div>
        </div>
        <button onClick={() => navigate(`/task/${taskId}/report`)}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-medium">
          查看评测报告 →
        </button>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <ImageCard task={task} taskId={taskId!} onRefresh={load} scriptConfirmed={scriptConfirmed} />
        <AudioCard task={task} taskId={taskId!} onRefresh={load} scriptConfirmed={scriptConfirmed} />
        <QuestionsCard task={task} scriptConfirmed={scriptConfirmed} />
      </div>

      <div className="flex gap-3 mt-6">
        <button onClick={() => navigate(`/task/${taskId}/script`)} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50">
          ← 返回脚本审核
        </button>
        <button onClick={() => navigate(`/task/${taskId}/export`)} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50">
          审核导出 →
        </button>
      </div>
    </div>
  );
}

/* ── ImageCard ── */

function ImageCard({ task, taskId, onRefresh, scriptConfirmed }: { task: Task; taskId: string; onRefresh: () => void; scriptConfirmed: boolean }) {
  const [generating, setGenerating] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [selectedStyle, setSelectedStyle] = useState<ImageStyle>((task.config.image_style as ImageStyle) || 'cartoon');
  const [startingComfyUI, setStartingComfyUI] = useState(false);
  const { health } = useAppContext();
  const backendOnline = health?.status === 'ok';
  const comfyState = health?.comfyui?.state || 'stopped';
  const comfyuiReady = health?.comfyui?.generation_ready === true;

  // Auto-clear stale connection errors when backend recovers
  useEffect(() => {
    if (backendOnline && error) {
      if (error.includes('无法连接后端') || error.includes('NETWORK_ERROR')) {
        setError(null);
      }
    }
  }, [backendOnline, error]);

  const handleStartComfyUI = async () => {
    setStartingComfyUI(true);
    setError(null);
    try {
      const result = await startComfyUI();
      if (result.ok && result.state === 'ready') {
        setStatusText('ComfyUI 已就绪，可以生成图片');
        setTimeout(() => setStatusText(''), 3000);
      } else if (result.state === 'starting') {
        setStatusText('ComfyUI 正在启动，请等待约30-60秒后刷新页面...');
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setError('启动 ComfyUI 失败: ' + (err.message || '未知错误'));
      } else {
        setError(err instanceof Error ? err.message : '启动 ComfyUI 失败');
      }
    } finally {
      setStartingComfyUI(false);
    }
  };

  const handleGenerate = async () => {
    if (!taskId) return;
    setGenerating(true); setError(null);
    try {
      if (!backendOnline) {
        setError('后端未启动，无法生成图片。');
        return;
      }
      setStatusText('正在提交图片生成任务...');
      await generateImage(taskId, selectedStyle);
      setStatusText(''); onRefresh();
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        const msg = err.message || '';
        if (err.code === 'NETWORK_ERROR') {
          setError('无法连接后端，请确认后端已启动。');
        } else if (err.code === 'TIMEOUT') {
          setError('图片生成超时（5分钟），请稍后重试。');
        } else if (err.code === 'SERVICE_UNAVAILABLE') {
          setError('ComfyUI 不可用：' + msg);
        } else if (err.code === 'NOT_FOUND') {
          setError('图片生成接口未找到（404），请重启后端。');
        } else if (err.code === 'SERVER_ERROR') {
          setError('后端异常：' + msg);
        } else {
          setError(msg || '图片生成失败');
        }
      } else {
        setError(err instanceof Error ? err.message : '图片生成失败');
      }
    } finally { setGenerating(false); setStatusText(''); }
  };

  const hasImage = task.image?.generation_status === 'success';
  const imgUrl = assetUrl(task.image?.image_url);

  // Determine card state
  let emptyState: string | null = null;
  let generateDisabled = false;
  let generateTitle = '生成教学参考图';

  if (!scriptConfirmed) {
    emptyState = '请先确认脚本，再生成教学参考图。';
    generateDisabled = true;
  } else if (!backendOnline) {
    emptyState = '后端未启动，暂无法生成图片。';
    generateDisabled = true;
  } else if (comfyState === 'starting') {
    emptyState = 'ComfyUI 正在启动中，请耐心等待约30-60秒...';
    generateDisabled = true;
    generateTitle = 'ComfyUI 启动中...';
  } else if (comfyState === 'failed') {
    emptyState = `ComfyUI 启动失败${health?.comfyui?.last_error ? ': ' + health.comfyui.last_error : ''}`;
    generateDisabled = true;
    generateTitle = 'ComfyUI 启动失败，点击下方按钮重试';
  } else if (comfyState === 'degraded') {
    emptyState = 'ComfyUI 在线但未完全就绪：' + (
      !health?.comfyui?.checkpoint_available ? '模型文件缺失' :
      !health?.comfyui?.workflow_available ? '工作流文件缺失' : '请检查 ComfyUI 状态');
    generateDisabled = true;
    generateTitle = 'ComfyUI 部分就绪，无法生成';
  } else if (!comfyuiReady) {
    emptyState = 'ComfyUI 未就绪：服务离线';
    generateDisabled = true;
    generateTitle = '请先启动 ComfyUI';
  } else if (!hasImage && !generating) {
    emptyState = '尚未生成教学参考图。';
  }

  return (
    <div className="bg-white rounded-lg p-4 shadow-sm border">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700">🖼️ 教学参考图</h3>
        {task.image && <AssetStatusBadge status={task.image.generation_status} />}
      </div>

      {task.image?.is_outdated && (
        <div className="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2 text-xs text-yellow-700">基于旧脚本版本，需重新生成</div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">
          {error}
          <button onClick={handleGenerate} className="ml-2 underline">重试</button>
        </div>
      )}

      {startingComfyUI && (
        <div className="text-center py-4 text-yellow-600 text-sm animate-pulse">正在启动 ComfyUI...</div>
      )}

      {generating && (
        <div className="text-center py-4 text-blue-500 text-sm animate-pulse">{statusText || '生成中...'}</div>
      )}

      {statusText && !generating && !startingComfyUI && (
        <div className="text-center py-2 text-green-600 text-xs">{statusText}</div>
      )}

      {hasImage && !generating ? (
        <div className="space-y-2">
          {imgUrl && (
            <div className="bg-gray-100 rounded overflow-hidden">
              <img src={imgUrl} alt="教学参考图" className="w-full h-auto object-cover"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />
            </div>
          )}
          <div className="text-xs text-gray-500 space-y-0.5">
            <div>类型: {TYPE_LABEL[task.image?.image_type as string] || task.image?.image_type || '参考图'}</div>
            <div>主题: {TOPIC_LABEL[task.image?.topic_type as string] || task.image?.topic_type || '-'}</div>
            <div>方式: {task.image?.render_mode === 'structured_map' ? '结构化示意图' : task.image?.render_mode === 'comfyui_styled_map' ? '风格化地图' : task.image?.render_mode || '-'}</div>
            <div>风格: {IMAGE_STYLE_LABELS[task.config?.image_style as ImageStyle] || task.config?.image_style || '-'}</div>
            <div>版本: {task.image!.image_source_script_version}</div>
            {task.image!.generation_latency_ms > 0 && <div>耗时: {(task.image!.generation_latency_ms / 1000).toFixed(1)}s</div>}
          </div>
          <button onClick={handleGenerate} disabled={generating} className="w-full py-1 text-sm border border-brand-300 text-brand-600 rounded hover:bg-brand-50 disabled:opacity-50">重新生成图片</button>
        </div>
      ) : task.image?.generation_status === 'generating' ? (
        <div className="text-center py-12 text-blue-500 animate-pulse">生成中...</div>
      ) : task.image?.generation_status === 'failed' ? (
        <div className="text-center py-8 text-red-500"><p>生成失败</p><button onClick={handleGenerate} className="mt-2 text-sm text-brand-600 hover:underline">重试</button></div>
      ) : (
        <div className="text-center py-4">
          {emptyState && <p className="text-sm text-gray-400 mb-3">{emptyState}</p>}
          {/* Start ComfyUI button — shown when ComfyUI is stopped or failed */}
          {scriptConfirmed && !hasImage && !comfyuiReady && comfyState !== 'starting' && (
            <button
              onClick={handleStartComfyUI}
              disabled={startingComfyUI}
              className={`px-4 py-2 rounded-lg text-sm font-medium w-full mb-2 ${
                startingComfyUI ? 'bg-yellow-100 text-yellow-600 cursor-wait' :
                comfyState === 'failed' ? 'bg-red-500 text-white hover:bg-red-600' :
                'bg-orange-500 text-white hover:bg-orange-600'
              }`}
              title={comfyState === 'failed' ? '重试启动 ComfyUI' : '启动 ComfyUI 服务'}>
              {startingComfyUI ? '正在启动 ComfyUI...' :
               comfyState === 'failed' ? '🔄 重试启动 ComfyUI' :
               '🚀 启动 ComfyUI'}
            </button>
          )}
          {scriptConfirmed && !hasImage && (
            <button onClick={handleGenerate} disabled={generateDisabled || generating}
              className={`px-4 py-2 rounded-lg text-sm font-medium w-full ${generateDisabled ? 'bg-gray-200 text-gray-400 cursor-not-allowed' : 'bg-brand-600 text-white hover:bg-brand-700'} disabled:opacity-50`}
              title={generateTitle}>
              {comfyState === 'starting' ? 'ComfyUI 启动中...' : '生成图片'}
            </button>
          )}
          {!scriptConfirmed && (
            <button onClick={() => window.location.href = `/task/${taskId}/script`}
              className="mt-2 text-xs text-brand-600 hover:underline block w-full">返回脚本审核</button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── AudioCard ── */

function AudioCard({ task, taskId, onRefresh, scriptConfirmed }: { task: Task; taskId: string; onRefresh: () => void; scriptConfirmed: boolean }) {
  const [generating, setGenerating] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<AudioEvalResult | null>(null);

  const handleGenerate = async () => {
    if (!taskId) return;
    setGenerating(true); setError(null); setEvalResult(null);
    try {
      setStatusText('正在生成分句音频...');
      await generateAudio(taskId, 'normal', 0.4);
      setStatusText('正在使用 Whisper 转写...');
      const asr = await transcribeAudio(taskId);
      setStatusText(`转写完成: ${asr.text.substring(0, 50)}...`);
      setEvaluating(true);
      const ev = await evaluateAudio(taskId);
      setEvalResult(ev); setStatusText(''); setEvaluating(false);
      onRefresh();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : '音频生成失败'); setStatusText(''); }
    finally { setGenerating(false); }
  };

  const hasAudio = task.audio?.generation_status === 'success';
  const audioUrl = assetUrl(task.audio?.audio_url);

  return (
    <div className="bg-white rounded-lg p-4 shadow-sm border">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700">🎧 音频</h3>
        {task.audio && <AssetStatusBadge status={task.audio.generation_status} />}
      </div>
      {task.audio?.is_outdated && (<div className="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2 text-xs text-yellow-700">⚠️ 基于旧脚本版本，需重新生成</div>)}
      {error && (<div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">{error}</div>)}
      {generating && (<div className="text-center py-4 text-blue-500 text-sm animate-pulse">{statusText || '生成中...'}</div>)}

      {hasAudio && !generating ? (
        <div className="space-y-2">
          {audioUrl && (<audio controls className="w-full h-10"><source src={audioUrl} type="audio/wav" /></audio>)}
          <div className="text-xs text-gray-500 space-y-0.5">
            <div>时长: {task.audio!.audio_duration_actual_sec.toFixed(1)}s</div>
            <div>音色A: {String((task.audio!.speaker_profiles as any)?.A || '-')}</div>
            <div>音色B: {String((task.audio!.speaker_profiles as any)?.B || '-')}</div>
            <div>版本: {task.audio!.audio_source_script_version}</div>
          </div>
          {evalResult && (
            <div className={`border rounded p-2 text-xs ${evalResult.script_audio_match_pass ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
              <div className={`font-medium ${evalResult.severity === 'S3' ? 'text-red-700' : 'text-green-700'}`}>文音一致性: {evalResult.script_audio_match_pass ? '✓ 通过' : '✗ 不通过'} ({evalResult.severity})</div>
              <div className="text-gray-500 mt-1">{evalResult.evidence}</div>
              {evalResult.missing_keywords.length > 0 && <div className="text-red-600 mt-1">缺失: {evalResult.missing_keywords.join(', ')}</div>}
            </div>
          )}
          {evaluating && (<div className="text-xs text-purple-500 animate-pulse">正在评测文音一致性...</div>)}
          <button onClick={handleGenerate} disabled={generating} className="w-full py-1 text-sm border border-brand-300 text-brand-600 rounded hover:bg-brand-50 disabled:opacity-50">重新生成音频</button>
        </div>
      ) : task.audio?.generation_status === 'failed' ? (
        <div className="text-center py-8 text-red-500"><p>生成失败</p><button onClick={handleGenerate} className="mt-2 text-sm text-brand-600 hover:underline">重试</button></div>
      ) : !generating ? (
        <div className="text-center py-4">
          {scriptConfirmed ? (
            <button onClick={handleGenerate} disabled={generating} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50">生成音频</button>
          ) : (
            <div className="text-gray-400 text-sm">请先确认脚本</div>
          )}
        </div>
      ) : null}
    </div>
  );
}

/* ── QuestionsCard ── */

function QuestionsCard({ task, scriptConfirmed }: { task: Task; scriptConfirmed: boolean }) {
  const [qError, setQError] = useState<string | null>(null);
  const [waitSec, setWaitSec] = useState(0);
  const [triggering, setTriggering] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const triggeredRef = useRef<string>('');
  const requestIdRef = useRef(0);
  const taskId = task.task_id;

  // Determine current question state
  const qsGenStatus = task.questions?.generation_status;
  const hasQuestions = qsGenStatus === 'success';
  const isGenerating = qsGenStatus === 'generating';
  const isFailed = qsGenStatus === 'failed';
  const autoTriggerKey = `${taskId}:${task.script?.script_version || ''}`;

  // Poll while generating
  useEffect(() => {
    if (isGenerating && taskId) {
      setWaitSec(0);
      pollRef.current = setInterval(() => {
        setWaitSec(s => s + 2);
        getTask(taskId).then(t => {
          const gs = t.questions?.generation_status;
          if (gs === 'success' || gs === 'failed') {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            window.location.reload();
          }
        }).catch(() => {});
      }, 2000);
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [isGenerating, taskId]);

  // Auto-trigger: script confirmed + not yet triggered for this version
  useEffect(() => {
    if (scriptConfirmed && !hasQuestions && !isGenerating && !isFailed && !triggering &&
        taskId && triggeredRef.current !== autoTriggerKey) {
      triggeredRef.current = autoTriggerKey;
      setTriggering(true);
      const reqId = ++requestIdRef.current;
      generateQuestions(taskId).then(() => {
        if (reqId !== requestIdRef.current) return; // stale request
        getTask(taskId).then(() => {}).catch(() => {});
      }).catch((e: any) => {
        if (reqId !== requestIdRef.current) return;
        const msg = e?.message || '';
        setQError(msg || '题目生成失败（点击重试）');
      }).finally(() => {
        if (reqId === requestIdRef.current) setTriggering(false);
      });
    }
  }, [scriptConfirmed, hasQuestions, isGenerating, isFailed, taskId, autoTriggerKey, triggering]);

  const handleRetry = async () => {
    if (!taskId) return;
    setQError(null); setTriggering(true);
    const reqId = ++requestIdRef.current;
    try {
      await generateQuestions(taskId);
      if (reqId === requestIdRef.current) getTask(taskId).then(() => {}).catch(() => {});
    } catch (e: any) {
      if (reqId !== requestIdRef.current) return;
      setQError(e?.message || '重试失败');
    } finally {
      if (reqId === requestIdRef.current) setTriggering(false);
    }
  };

  // Derive error message from model_name (stores error_code on failure)
  const failureReason = isFailed && task.questions?.model_name ? task.questions.model_name : null;

  return (
    <div className="bg-white rounded-lg p-4 shadow-sm border">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700">� 题目</h3>
        {task.questions && <AssetStatusBadge status={task.questions.generation_status} />}
      </div>
      {task.questions?.is_outdated && (<div className="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2 text-xs text-yellow-700">基于旧脚本版本，需重新生成</div>)}
      {qError && (<div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">{qError}<button onClick={handleRetry} className="ml-2 underline">重试</button></div>)}

      {triggering && (<div className="text-center py-4 text-blue-500 text-sm animate-pulse">正在启动题目生成...</div>)}

      {isGenerating && (
        <div className="text-center py-4">
          <div className="text-blue-500 text-sm animate-pulse mb-1">正在调用 Qwen 生成题目，已等待 {waitSec} 秒...</div>
          <div className="w-full bg-gray-200 rounded-full h-1"><div className="bg-blue-500 h-1 rounded-full animate-pulse" style={{width:'60%'}} /></div>
        </div>
      )}

      {hasQuestions && !triggering ? (
        <div className="space-y-2">
          {task.questions!.questions.map(q => (
            <div key={q.index} className="border rounded p-2 text-xs">
              <div className="font-medium text-gray-800">{q.index}. {q.stem}</div>
              <div className="mt-1 space-y-0.5 text-gray-500">
                {q.options.map((o, i) => (<div key={i} className={o.startsWith(q.answer + '.') ? 'text-green-600 font-medium' : ''}>{o}{o.startsWith(q.answer + '.') ? ' ✓' : ''}</div>))}
              </div>
            </div>
          ))}
          <button onClick={handleRetry} disabled={triggering} className="w-full py-1 text-sm border border-brand-300 text-brand-600 rounded hover:bg-brand-50 disabled:opacity-50">重新生成题目</button>
        </div>
      ) : isFailed && !triggering ? (
        <div className="text-center py-4 text-red-500">
          <p>题目生成失败</p>
          {failureReason && <p className="text-xs mt-1 text-red-400">错误码: {failureReason}</p>}
          <button onClick={handleRetry} className="mt-2 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700">重新生成</button>
        </div>
      ) : !triggering && !isGenerating && !hasQuestions ? (
        <div className="text-center py-8 text-gray-400 text-sm">
          {scriptConfirmed ? '点击 "重新生成" 生成题目' : '等待脚本确认后自动生成题目'}
          {scriptConfirmed && <button onClick={handleRetry} className="mt-2 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 block mx-auto">生成题目</button>}
        </div>
      ) : null}
    </div>
  );
}
