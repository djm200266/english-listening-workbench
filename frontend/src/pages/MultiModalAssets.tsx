import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Task, ImageStyle } from '../types';
import { getTask, generateAudio, transcribeAudio, evaluateAudio, generateImage, getQuestionStatus, generateQuestions, startComfyUI, validateTaskAssets, ApiError } from '../services/api';
import type { AudioEvalResult, QuestionStatus, AssetValidationResult } from '../services/api';
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

/** Build full URL from image_url or audio_url. Handles /media/ and /assets/ prefixes. */
function assetUrl(assetUrlStr: string | undefined): string | null {
  if (!assetUrlStr) return null;
  if (assetUrlStr.startsWith('http://') || assetUrlStr.startsWith('https://')) return assetUrlStr;
  // Remove leading slash for clean join
  const clean = assetUrlStr.startsWith('/') ? assetUrlStr.slice(1) : assetUrlStr;
  return `${API_BASE_URL}/${clean}`;
}

export default function MultiModalAssets() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [validation, setValidation] = useState<AssetValidationResult | null>(null);

  const load = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const t = await getTask(taskId);
      setTask(t);
      // Also validate assets
      try {
        const v = await validateTaskAssets(taskId);
        setValidation(v);
      } catch { /* validation is optional */ }
    } catch { /* keep stale */ }
    finally { setLoading(false); }
  }, [taskId]);

  useEffect(() => { load(); }, [load]);

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
        <div className="flex gap-2">
          <button onClick={load} className="px-3 py-2 border rounded text-gray-500 hover:bg-gray-50 text-sm" title="刷新页面和文件验证">
            🔄 刷新验证
          </button>
          <button onClick={() => navigate(`/task/${taskId}/report`)}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-medium">
            查看评测报告 →
          </button>
        </div>
      </div>

      {/* Validation warnings */}
      {validation && !validation.all_valid && (
        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-3 mb-4 text-sm text-yellow-800">
          <strong>⚠️ 文件状态异常：</strong>
          {validation.image.status !== 'ok' && validation.image.status !== 'no_image' && (
            <span className="ml-2">图片: {validation.image.last_error || validation.image.status}</span>
          )}
          {validation.audio.status !== 'ok' && validation.audio.status !== 'no_audio' && (
            <span className="ml-2">音频: {validation.audio.last_error || validation.audio.status}</span>
          )}
          {validation.questions.status !== 'ok' && validation.questions.status !== 'no_questions' && (
            <span className="ml-2">题目: {validation.questions.last_error || validation.questions.status}</span>
          )}
          <button onClick={load} className="ml-3 underline text-yellow-900 font-medium">重新检测</button>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        <ImageCard task={task} taskId={taskId!} onRefresh={load} scriptConfirmed={scriptConfirmed} validation={validation} />
        <AudioCard task={task} taskId={taskId!} onRefresh={load} scriptConfirmed={scriptConfirmed} validation={validation} />
        <QuestionsCard task={task} scriptConfirmed={scriptConfirmed} onRefresh={load} />
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

function ImageCard({ task, taskId, onRefresh, scriptConfirmed, validation }: {
  task: Task; taskId: string; onRefresh: () => void; scriptConfirmed: boolean; validation: AssetValidationResult | null;
}) {
  const [generating, setGenerating] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [selectedStyle, setSelectedStyle] = useState<ImageStyle>((task.config.image_style as ImageStyle) || 'textbook_cartoon');
  const [startingComfyUI, setStartingComfyUI] = useState(false);
  const [imgLoadError, setImgLoadError] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const { health } = useAppContext();
  const backendOnline = health?.status === 'ok';
  const comfyStatus = health?.comfyui?.status || health?.comfyui?.state || 'stopped';
  const comfyuiReady = health?.comfyui?.generation_ready === true;

  // Auto-clear stale errors when backend recovers
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
    setGenerating(true); setError(null); setImgLoadError(false);
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

  const storedSuccess = task.image?.generation_status === 'success';
  // Validate with file check: stored success must also pass file validation
  const imgValid = validation?.image;
  const fileActuallyExists = imgValid?.file_exists === true && imgValid?.file_size > 0;
  const isStale = storedSuccess && !fileActuallyExists && imgValid !== undefined;
  const hasImage = storedSuccess && fileActuallyExists;

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
  } else if (comfyStatus === 'starting') {
    emptyState = 'ComfyUI 正在启动中，请耐心等待约30-60秒...';
    generateDisabled = true;
    generateTitle = 'ComfyUI 启动中...';
  } else if (comfyStatus === 'failed') {
    emptyState = `ComfyUI 启动失败${health?.comfyui?.last_error ? ': ' + health.comfyui.last_error : ''}`;
    generateDisabled = true;
    generateTitle = 'ComfyUI 启动失败，点击下方按钮重试';
  } else if (comfyStatus === 'degraded') {
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
        <div className="flex items-center gap-1">
          {task.image && <AssetStatusBadge status={isStale ? 'outdated' : task.image.generation_status} />}
          {isStale && <span className="text-xs text-red-500 font-medium">文件丢失</span>}
        </div>
      </div>

      {task.image?.is_outdated && (
        <div className="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2 text-xs text-yellow-700">基于旧脚本版本，需重新生成</div>
      )}

      {/* Stale success warning */}
      {isStale && (
        <div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">
          ⚠️ 状态显示"成功"但图片文件不存在
          {imgValid?.last_error && <div className="mt-1">原因: {imgValid.last_error}</div>}
          {imgValid?.image_url && <div className="mt-1 text-gray-500 break-all">URL: {imgUrl}</div>}
          <button onClick={onRefresh} className="ml-2 underline">重新检测</button>
          <button onClick={handleGenerate} className="ml-2 underline text-brand-600">重新生成</button>
        </div>
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
          {imgUrl && !imgLoadError ? (
            <div className="bg-gray-100 rounded overflow-hidden relative">
              <img src={imgUrl} alt="教学参考图" className="w-full h-auto object-cover"
                onError={() => setImgLoadError(true)} />
            </div>
          ) : imgLoadError ? (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-center">
              <p className="text-sm text-red-600 mb-1">❌ 图片加载失败</p>
              <p className="text-xs text-red-400 break-all mb-2">URL: {imgUrl}</p>
              <button onClick={() => { setImgLoadError(false); onRefresh(); }}
                className="text-xs text-brand-600 underline">重新检测</button>
            </div>
          ) : null}
          <div className="text-xs text-gray-500 space-y-0.5">
            <div>类型: {TYPE_LABEL[task.image?.image_type as string] || task.image?.image_type || '参考图'}</div>
            <div>主题: {TOPIC_LABEL[task.image?.topic_type as string] || task.image?.topic_type || '-'}</div>
            <div>方式: {task.image?.render_mode === 'structured_map' ? '结构化示意图' : task.image?.render_mode === 'comfyui_styled_map' ? '风格化地图' : task.image?.render_mode || '-'}</div>
            <div>风格: {IMAGE_STYLE_LABELS[task.config?.image_style as ImageStyle] || task.config?.image_style || '-'}</div>
            <div>版本: {task.image!.image_source_script_version}</div>
            {task.image!.generation_latency_ms > 0 && <div>耗时: {(task.image!.generation_latency_ms / 1000).toFixed(1)}s</div>}
            {/* File validation info */}
            {imgValid && (
              <div className="mt-1 pt-1 border-t border-gray-200">
                <div className="text-gray-400">
                  文件: {imgValid.file_exists ? `✓ ${(imgValid.file_size / 1024).toFixed(0)} KB` : '✗ 不存在'}
                  {imgValid.can_open ? ' · 可打开' : ''}
                </div>
              </div>
            )}
            <button onClick={() => setShowDebug(!showDebug)}
              className="text-gray-400 hover:text-gray-600 text-xs underline">调试信息</button>
            {showDebug && (
              <div className="bg-gray-100 rounded p-2 text-xs text-gray-500 break-all space-y-0.5">
                <div>URL: {imgUrl || '(空)'}</div>
                <div>文件路径: {imgValid?.file_path || '(未知)'}</div>
                <div>文件大小: {imgValid?.file_size ? `${(imgValid.file_size / 1024).toFixed(0)} KB` : '0'}</div>
                <div>Status Code: {imgLoadError ? '加载失败' : 'OK'}</div>
              </div>
            )}
          </div>
          <button onClick={handleGenerate} disabled={generating} className="w-full py-1 text-sm border border-brand-300 text-brand-600 rounded hover:bg-brand-50 disabled:opacity-50">重新生成图片</button>
        </div>
      ) : task.image?.generation_status === 'generating' ? (
        <div className="text-center py-12 text-blue-500 animate-pulse">生成中...</div>
      ) : task.image?.generation_status === 'failed' ? (
        <div className="text-center py-8 text-red-500">
          <p>生成失败</p>
          {task.image?.model_name && task.image.model_name.startsWith('OLLAMA') && (
            <p className="text-xs mt-1">错误码: {task.image.model_name}</p>
          )}
          <button onClick={handleGenerate} className="mt-2 text-sm text-brand-600 hover:underline">重试</button>
        </div>
      ) : (
        <div className="text-center py-4">
          {emptyState && <p className="text-sm text-gray-400 mb-3">{emptyState}</p>}
          {/* Start ComfyUI button */}
          {scriptConfirmed && !hasImage && !comfyuiReady && comfyStatus !== 'starting' && (
            <button
              onClick={handleStartComfyUI}
              disabled={startingComfyUI}
              className={`px-4 py-2 rounded-lg text-sm font-medium w-full mb-2 ${
                startingComfyUI ? 'bg-yellow-100 text-yellow-600 cursor-wait' :
                comfyStatus === 'failed' ? 'bg-red-500 text-white hover:bg-red-600' :
                'bg-orange-500 text-white hover:bg-orange-600'
              }`}
              title={comfyStatus === 'failed' ? '重试启动 ComfyUI' : '启动 ComfyUI 服务'}>
              {startingComfyUI ? '正在启动 ComfyUI...' :
               comfyStatus === 'failed' ? '🔄 重试启动 ComfyUI' :
               '🚀 启动 ComfyUI'}
            </button>
          )}
          {scriptConfirmed && !hasImage && (
            <button onClick={handleGenerate} disabled={generateDisabled || generating}
              className={`px-4 py-2 rounded-lg text-sm font-medium w-full ${generateDisabled ? 'bg-gray-200 text-gray-400 cursor-not-allowed' : 'bg-brand-600 text-white hover:bg-brand-700'} disabled:opacity-50`}
              title={generateTitle}>
              {comfyStatus === 'starting' ? 'ComfyUI 启动中...' : '生成图片'}
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

function AudioCard({ task, taskId, onRefresh, scriptConfirmed, validation }: {
  task: Task; taskId: string; onRefresh: () => void; scriptConfirmed: boolean; validation: AssetValidationResult | null;
}) {
  const [generating, setGenerating] = useState(false);
  const [statusText, setStatusText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<AudioEvalResult | null>(null);
  const [audioError, setAudioError] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  const handleGenerate = async () => {
    if (!taskId) return;
    setGenerating(true); setError(null); setEvalResult(null); setAudioError(false);
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

  const storedSuccess = task.audio?.generation_status === 'success';
  const audValid = validation?.audio;
  const fileActuallyExists = audValid?.file_exists === true && audValid?.file_size > 0;
  const isStale = storedSuccess && !fileActuallyExists && audValid !== undefined;
  const hasAudio = storedSuccess && fileActuallyExists;

  const audioUrl = assetUrl(task.audio?.audio_url);
  // Prefer validated duration, fall back to stored
  const displayDuration = audValid?.duration_sec || task.audio?.audio_duration_actual_sec || 0;

  return (
    <div className="bg-white rounded-lg p-4 shadow-sm border">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700">🎧 音频</h3>
        <div className="flex items-center gap-1">
          {task.audio && <AssetStatusBadge status={isStale ? 'outdated' : task.audio.generation_status} />}
          {isStale && <span className="text-xs text-red-500 font-medium">文件丢失</span>}
        </div>
      </div>
      {task.audio?.is_outdated && (<div className="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2 text-xs text-yellow-700">⚠️ 基于旧脚本版本，需重新生成</div>)}

      {/* Stale success warning */}
      {isStale && (
        <div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">
          ⚠️ 状态显示"成功"但音频文件不存在
          {audValid?.last_error && <div className="mt-1">原因: {audValid.last_error}</div>}
          <button onClick={onRefresh} className="ml-2 underline">重新检测</button>
          <button onClick={handleGenerate} className="ml-2 underline text-brand-600">重新生成</button>
        </div>
      )}

      {error && (<div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">{error}</div>)}
      {generating && (<div className="text-center py-4 text-blue-500 text-sm animate-pulse">{statusText || '生成中...'}</div>)}

      {hasAudio && !generating ? (
        <div className="space-y-2">
          {audioUrl && !audioError ? (
            <div>
              <audio ref={audioRef} controls className="w-full h-10"
                onError={() => setAudioError(true)}
                onLoadedMetadata={(e) => {
                  // Update duration from actual audio metadata
                  const dur = (e.target as HTMLAudioElement).duration;
                  if (dur && isFinite(dur) && dur > 0 && (!displayDuration || displayDuration < 0.1)) {
                    // Force re-render would be needed here, but at minimum the native player shows correct time
                  }
                }}>
                <source src={audioUrl} type={audValid?.mime_type || 'audio/wav'} />
              </audio>
            </div>
          ) : audioError ? (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-center">
              <p className="text-sm text-red-600 mb-1">❌ 音频无法播放</p>
              <p className="text-xs text-red-400 break-all mb-2">URL: {audioUrl}</p>
              <p className="text-xs text-gray-500">可能原因：文件缺失、格式损坏、或服务器不支持 Range 请求</p>
              <button onClick={() => { setAudioError(false); onRefresh(); }}
                className="mt-1 text-xs text-brand-600 underline">重新检测</button>
            </div>
          ) : null}
          <div className="text-xs text-gray-500 space-y-0.5">
            <div>时长: {displayDuration > 0 ? `${displayDuration.toFixed(1)}s` : '⚠️ 0:00 — 文件可能损坏'}</div>
            <div>音色A: {String((task.audio!.speaker_profiles as any)?.A || '-')}</div>
            <div>音色B: {String((task.audio!.speaker_profiles as any)?.B || '-')}</div>
            <div>版本: {task.audio!.audio_source_script_version}</div>
            {/* File validation info */}
            {audValid && (
              <div className="mt-1 pt-1 border-t border-gray-200">
                <div className="text-gray-400">
                  文件: {audValid.file_exists ? `✓ ${(audValid.file_size / 1024).toFixed(0)} KB` : '✗ 不存在'}
                  {audValid.wav_valid ? ' · WAV有效' : ''}
                  {audValid.duration_sec > 0 ? ` · ${audValid.duration_sec.toFixed(1)}s` : ''}
                </div>
              </div>
            )}
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
        <div className="text-center py-8 text-red-500">
          <p>生成失败</p>
          {task.audio?.model_name && <p className="text-xs mt-1">错误: {task.audio.model_name}</p>}
          <button onClick={handleGenerate} className="mt-2 text-sm text-brand-600 hover:underline">重试</button>
        </div>
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

function QuestionsCard({ task, scriptConfirmed, onRefresh }: { task: Task; scriptConfirmed: boolean; onRefresh: () => void }) {
  const [qError, setQError] = useState<string | null>(null);
  const [waitSec, setWaitSec] = useState(0);
  const [triggering, setTriggering] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const triggeredRef = useRef<string>('');
  const requestIdRef = useRef(0);
  const taskId = task.task_id;
  const MAX_POLL_SEC = 120;

  // Determine current question state
  const qsGenStatus = task.questions?.generation_status;
  const hasQuestions = qsGenStatus === 'success';
  const isGenerating = qsGenStatus === 'generating';
  const isFailed = qsGenStatus === 'failed';
  const autoTriggerKey = `${taskId}:${task.script?.script_version || ''}`;

  // Poll while generating — with max timeout
  useEffect(() => {
    if (isGenerating && taskId) {
      setWaitSec(0);
      setTimedOut(false);
      pollRef.current = setInterval(() => {
        setWaitSec(s => {
          const next = s + 2;
          if (next >= MAX_POLL_SEC) {
            // Timeout — stop polling and show failure
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setTimedOut(true);
            return next;
          }
          return next;
        });
        getTask(taskId).then(t => {
          const gs = t.questions?.generation_status;
          if (gs === 'success' || gs === 'failed') {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            onRefresh();
          }
        }).catch(() => {});
      }, 2000);
    }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [isGenerating, taskId, onRefresh]);

  // Auto-trigger: script confirmed + not yet triggered for this version
  useEffect(() => {
    if (scriptConfirmed && !hasQuestions && !isGenerating && !isFailed && !triggering &&
        !timedOut && taskId && triggeredRef.current !== autoTriggerKey) {
      triggeredRef.current = autoTriggerKey;
      setTriggering(true);
      const reqId = ++requestIdRef.current;
      setTimedOut(false);
      setQError(null);
      generateQuestions(taskId).then((result) => {
        if (reqId !== requestIdRef.current) return;
        // Check if already running
        if (result?.question_status === 'generating') {
          setTriggering(false);
          onRefresh(); // Will start polling
        } else {
          onRefresh();
          setTriggering(false);
        }
      }).catch((e: any) => {
        if (reqId !== requestIdRef.current) return;
        const msg = e?.message || '';
        if (e?.code === 'GENERATION_IN_PROGRESS') {
          setQError('题目生成正在进行中，请等待...');
          setTriggering(false);
          onRefresh();
        } else {
          setQError(msg || '题目生成失败（点击重试）');
          setTriggering(false);
        }
      });
    }
  }, [scriptConfirmed, hasQuestions, isGenerating, isFailed, taskId, autoTriggerKey, triggering, timedOut, onRefresh]);

  const handleRetry = async () => {
    if (!taskId) return;
    setQError(null); setTriggering(true); setTimedOut(false);
    const reqId = ++requestIdRef.current;
    try {
      await generateQuestions(taskId);
      if (reqId === requestIdRef.current) onRefresh();
    } catch (e: any) {
      if (reqId !== requestIdRef.current) return;
      if (e?.code === 'GENERATION_IN_PROGRESS') {
        setQError('题目生成正在进行中，请等待...');
        onRefresh();
      } else {
        setQError(e?.message || '重试失败');
      }
    } finally {
      if (reqId === requestIdRef.current) setTriggering(false);
    }
  };

  // Derive error message from model_name (stores error_code on failure)
  const failureReason = isFailed && task.questions?.model_name ? task.questions.model_name : null;
  const errorLabel = (code: string): string => {
    const map: Record<string, string> = {
      'OLLAMA_OFFLINE': 'Ollama 离线',
      'MODEL_NOT_FOUND': '模型未安装',
      'OLLAMA_TIMEOUT': 'Ollama 超时',
      'QUESTION_GENERATION_TIMEOUT': '生成超时',
      'INVALID_MODEL_JSON': '模型返回格式错误',
      'QUESTION_GENERATION_FAILED': '生成失败',
      'QUESTION_SCHEMA_VALIDATION_FAILED': '题目格式校验失败',
      'OLLAMA_ERROR': 'Ollama 错误',
    };
    return map[code] || code;
  };

  return (
    <div className="bg-white rounded-lg p-4 shadow-sm border">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-700">📝 题目</h3>
        {task.questions && <AssetStatusBadge status={task.questions.generation_status} />}
      </div>
      {task.questions?.is_outdated && (<div className="bg-yellow-50 border border-yellow-300 rounded p-2 mb-2 text-xs text-yellow-700">基于旧脚本版本，需重新生成</div>)}
      {qError && (
        <div className="bg-red-50 border border-red-300 rounded p-2 mb-2 text-xs text-red-700">
          {qError}
          <button onClick={handleRetry} className="ml-2 underline">重试</button>
        </div>
      )}

      {triggering && (<div className="text-center py-4 text-blue-500 text-sm animate-pulse">正在启动题目生成...</div>)}

      {isGenerating && !timedOut && (
        <div className="text-center py-4">
          <div className="text-blue-500 text-sm animate-pulse mb-1">正在调用模型生成题目，已等待 {waitSec} 秒...</div>
          <div className="w-full bg-gray-200 rounded-full h-1">
            <div className="bg-blue-500 h-1 rounded-full transition-all" style={{width: `${Math.min((waitSec / MAX_POLL_SEC) * 100, 100)}%`}} />
          </div>
          {waitSec > 30 && (
            <p className="text-xs text-gray-400 mt-1">模型响应较慢，最长等待{MAX_POLL_SEC}秒</p>
          )}
        </div>
      )}

      {timedOut && (
        <div className="text-center py-4">
          <div className="text-red-500 text-sm mb-2">⏰ 题目生成超时（{MAX_POLL_SEC}秒）</div>
          <p className="text-xs text-gray-500 mb-2">模型响应时间过长，可能因 Ollama 负载过高或模型未预热</p>
          <button onClick={handleRetry} disabled={triggering}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700">
            重新生成
          </button>
        </div>
      )}

      {hasQuestions && !triggering ? (
        <div className="space-y-2">
          {task.questions!.questions.map(q => (
            <div key={q.index} className="border rounded p-2 text-xs">
              <div className="font-medium text-gray-800">{q.index}. {q.stem}</div>
              <div className="mt-1 space-y-0.5 text-gray-500">
                {q.options.map((o, i) => {
                  const optLabel = String.fromCharCode(65 + i);
                  const isCorrect = optLabel === q.answer;
                  return (
                    <div key={i} className={isCorrect ? 'text-green-600 font-medium' : ''}>
                      {o} {isCorrect ? ' ✓' : ''}
                    </div>
                  );
                })}
              </div>
              {q.explanation && (
                <div className="mt-1 text-gray-400 italic">{q.explanation}</div>
              )}
            </div>
          ))}
          <button onClick={handleRetry} disabled={triggering} className="w-full py-1 text-sm border border-brand-300 text-brand-600 rounded hover:bg-brand-50 disabled:opacity-50">重新生成题目</button>
        </div>
      ) : isFailed && !triggering ? (
        <div className="text-center py-4 text-red-500">
          <p>题目生成失败</p>
          {failureReason && <p className="text-xs mt-1 text-red-400">错误: {errorLabel(failureReason)} ({failureReason})</p>}
          <button onClick={handleRetry} className="mt-2 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700">重新生成</button>
        </div>
      ) : !triggering && !isGenerating && !hasQuestions && !timedOut ? (
        <div className="text-center py-8 text-gray-400 text-sm">
          {scriptConfirmed ? '点击按钮生成题目' : '等待脚本确认后自动生成题目'}
          {scriptConfirmed && (
            <button onClick={handleRetry} className="mt-2 px-4 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 block mx-auto">生成题目</button>
          )}
        </div>
      ) : null}
    </div>
  );
}
