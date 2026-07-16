import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Task, Severity, VisualEvaluationResult } from '../types';
import { getTask } from '../services/api';
import { API_BASE_URL } from '../config/api';
import { SeverityBadge } from '../components/StatusBadge';

const DIMENSIONS: { key: string; label: string; weight: number }[] = [
  { key: 'textQuality', label: '文本质量', weight: 20 },
  { key: 'audioQuality', label: '音频质量', weight: 20 },
  { key: 'imageQuality', label: '图片质量', weight: 15 },
  { key: 'questionQuality', label: '题目质量', weight: 20 },
  { key: 'crossModal', label: '跨模态一致性', weight: 25 },
];

const VISUAL_DIM_LABELS: Record<string, string> = {
  visual_content_alignment: '视觉内容对齐度',
  image_type_alignment: '图片类型匹配度',
  style_alignment: '风格一致性',
  required_element_coverage: '必要元素覆盖度',
  spatial_relation_accuracy: '空间关系准确性',
  instructional_clarity: '教学清晰度',
  text_legibility: '文字可读性',
  composition_quality: '构图质量',
  artifact_quality: '瑕疵程度',
  prompt_visual_consistency: 'Prompt-画面一致性',
};

const STYLE_LABELS: Record<string, string> = {
  textbook_cartoon: '教材卡通', watercolor: '水彩插画', photorealistic: '写实风格',
  flat_vector: '扁平矢量', hand_drawn: '手绘风格', comic: '漫画风格',
  colored_pencil: '彩色铅笔', three_d_cartoon: '3D卡通', structured_map: '结构化地图',
  unknown: '未知',
};

const LAYOUT_LABELS: Record<string, string> = {
  reference_map: '位置参考图', weather_panels: '天气面板', story_panels: '故事分镜',
  scene: '场景图', vocabulary_visual: '词汇图', unknown: '未知',
};

export default function EvaluationReport() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Severity | 'all'>('all');
  const triggeredRef = useRef('');

  const loadTask = async () => {
    if (!taskId) return;
    try { setTask(await getTask(taskId)); } catch { /* keep stale */ }
    finally { setLoading(false); }
  };

  useEffect(() => { loadTask(); }, [taskId]);

  // Check assets ready and auto-trigger evaluation
  const evalReport = task?.evaluation ?? null;
  const scriptOk = task?.script?.status === 'confirmed';
  const imgOk = task?.image?.generation_status === 'success';
  const audOk = task?.audio?.generation_status === 'success';
  const qOk = task?.questions?.generation_status === 'success';
  const allReady = scriptOk && imgOk && audOk && qOk;

  const triggerKey = `${taskId}`;
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const doGenerate = async () => {
    if (!taskId || generating) return;
    setGenerating(true); setError(null);
    try {
      const r = await fetch(`${API_BASE_URL}/api/v1/evaluations/tasks/${encodeURIComponent(taskId)}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ include_semantic: true, include_visual: true, force_regenerate: false }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.detail?.message || '评测生成失败');
      } else {
        await loadTask();
      }
    } catch (e: any) { setError(e?.message || '请求失败'); }
    finally { setGenerating(false); }
  };

  const doVisualOnly = async () => {
    if (!taskId || generating) return;
    setGenerating(true); setError(null);
    try {
      const r = await fetch(`${API_BASE_URL}/api/v1/evaluations/tasks/${encodeURIComponent(taskId)}/visual`, {
        method: 'POST',
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.detail?.message || '视觉评测失败');
      } else {
        await loadTask();
      }
    } catch (e: any) { setError(e?.message || '请求失败'); }
    finally { setGenerating(false); }
  };

  // Auto-trigger once when assets ready and no report
  useEffect(() => {
    if (allReady && !evalReport && !generating && triggeredRef.current !== triggerKey) {
      triggeredRef.current = triggerKey;
      doGenerate();
    }
  }, [allReady, evalReport, triggerKey]);

  // Cleanup
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  if (loading) return <div className="text-center py-16"><div className="inline-block w-8 h-8 border-4 border-brand-300 border-t-brand-600 rounded-full animate-spin mb-4" /><p className="text-gray-400">加载中...</p></div>;
  if (!task) return <div className="text-center py-16 text-gray-400">任务不存在</div>;

  const items = evalReport?.items ?? [];
  const filtered = filter === 'all' ? items : items.filter(i => i.severity === filter);
  const gatePassed = evalReport?.pass_status === 'pass' && !items.some(i => i.severity === 'S3' || i.severity === 'S4');

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div><h1 className="text-xl font-bold text-gray-800">{task.task_name} · 评测报告</h1><div className="text-sm text-gray-500 mt-1">{task.task_id}</div></div>
        <div className="flex gap-2">
          <button onClick={() => navigate(`/task/${taskId}/assets`)} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50">← 返回素材</button>
          <button onClick={() => navigate(`/task/${taskId}/export`)} className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-medium">审核导出 →</button>
        </div>
      </div>

      {/* Generating state */}
      {generating && (
        <div className="text-center py-16">
          <div className="inline-block w-8 h-8 border-4 border-purple-300 border-t-purple-600 rounded-full animate-spin mb-4" />
          <p className="text-gray-600 font-medium">正在生成评测报告...</p>
          <p className="text-sm text-gray-400 mt-1">正在分析脚本、图片、音频和题目...</p>
        </div>
      )}

      {/* Assets NOT ready */}
      {!generating && !allReady && !evalReport && (
        <div className="max-w-lg mx-auto text-center py-16">
          <div className="text-5xl mb-4">📋</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">素材尚未齐全</h2>
          <div className="text-sm text-gray-500 space-y-1 mb-4">
            <div>脚本: {scriptOk ? '✅ 已确认' : '❌ 未确认'}</div>
            <div>图片: {imgOk ? '✅ 已生成' : '❌ 未生成'}</div>
            <div>音频: {audOk ? '✅ 已生成' : '❌ 未生成'}</div>
            <div>题目: {qOk ? '✅ 已生成' : '❌ 未生成'}</div>
          </div>
          <button onClick={() => navigate(`/task/${taskId}/assets`)} className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm">前往生成素材 →</button>
        </div>
      )}

      {/* Assets ready but no report yet (with retry) */}
      {!generating && allReady && !evalReport && (
        <div className="max-w-lg mx-auto text-center py-16">
          <div className="text-5xl mb-4">📊</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">素材已齐全，准备评测</h2>
          <p className="text-sm text-gray-500 mb-1">脚本 ✅ | 图片 ✅ | 音频 ✅ | 题目 ✅</p>
          {error && <p className="text-sm text-red-500 mb-3">{error}</p>}
          <button onClick={doGenerate} disabled={generating} className="px-6 py-2 bg-brand-600 text-white rounded-lg text-sm hover:bg-brand-700 font-medium">
            开始评测
          </button>
        </div>
      )}

      {/* Report */}
      {evalReport && (
        <>
          <div className="grid grid-cols-3 gap-4 mb-6">
            <div className="bg-white rounded-lg p-5 shadow-sm border text-center">
              <div className={`text-3xl font-bold ${(evalReport.combined_score || evalReport.overall_score) >= 80 ? 'text-green-600' : 'text-red-600'}`}>{evalReport.combined_score ?? evalReport.overall_score}</div>
              <div className="text-sm text-gray-500 mt-1">总分 (≥80通过)</div>
            </div>
            <div className="bg-white rounded-lg p-5 shadow-sm border text-center">
              <div className={`text-3xl font-bold ${gatePassed ? 'text-green-600' : 'text-red-600'}`}>{gatePassed ? '通过' : '不通过'}</div>
              <div className="text-sm text-gray-500 mt-1">门禁状态</div>
            </div>
            <div className="bg-white rounded-lg p-5 shadow-sm border text-center">
              <div className={`text-3xl font-bold ${evalReport.s3s4_count > 0 ? 'text-red-600' : 'text-green-600'}`}>{evalReport.s3s4_count}</div>
              <div className="text-sm text-gray-500 mt-1">严重问题(S3/S4)</div>
            </div>
          </div>

          <div className="bg-white rounded-lg p-5 shadow-sm border mb-6">
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-3">分项得分</h3>
            <div className="space-y-2">
              {DIMENSIONS.map(d => {
                const score = evalReport.dimension_scores[d.key] ?? 0;
                return (
                  <div key={d.key} className="flex items-center gap-3">
                    <span className="w-28 text-sm text-gray-600">{d.label} ({d.weight}%)</span>
                    <div className="flex-1 bg-gray-100 rounded-full h-3">
                      <div className={`h-3 rounded-full ${score >= 80 ? 'bg-green-500' : score >= 60 ? 'bg-yellow-400' : 'bg-red-500'}`} style={{width: `${score}%`}} />
                    </div>
                    <span className="w-10 text-sm font-medium text-right">{score}</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="bg-white rounded-lg p-5 shadow-sm border mb-6">
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-3">门禁条件</h3>
            <div className="space-y-1 text-sm">
              <GateItem label="综合得分 ≥ 80" pass={(evalReport.combined_score || evalReport.overall_score) >= 80} />
              <GateItem label="无S3/S4严重错误" pass={evalReport.s3s4_count === 0} />
              <GateItem label="素材完整" pass={allReady} />
              <GateItem label="版本一致" pass={!task.image?.is_outdated && !task.audio?.is_outdated && !task.questions?.is_outdated} />
            </div>
          </div>

          {/* ── Visual Evaluation Section ── */}
          {(() => {
            const vd = evalReport.visual_data as VisualEvaluationResult | null;
            const visOk = vd?.status === 'success';
            const visFailed = vd?.status === 'parse_failed';
            const visUnavailable = !vd || vd.status === 'unavailable' || vd.status === 'image_not_found';

            return (
              <div className="bg-white rounded-lg p-5 shadow-sm border mb-6">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-500 uppercase">
                    🖼️ 视觉图片评测 {visOk ? '✅' : visFailed ? '❌' : '⚠️'}
                  </h3>
                  {!visOk && evalReport && (
                    <button onClick={doVisualOnly} disabled={generating}
                      className="px-3 py-1 text-xs bg-purple-100 text-purple-700 rounded hover:bg-purple-200 disabled:opacity-50">
                      {generating ? '评测中...' : (visFailed ? '重试视觉评测' : '仅重新运行视觉评测')}
                    </button>
                  )}
                </div>

                {/* Visual unavailable */}
                {visUnavailable && (
                  <div className="text-sm text-gray-500 bg-amber-50 border border-amber-200 rounded p-3">
                    {vd?.error_code === 'VISUAL_IMAGE_NOT_FOUND' && '⚠️ 未找到图片文件，无法进行视觉评测。请先生成图片。'}
                    {vd?.error_code === 'VISUAL_MODEL_NOT_FOUND' && '⚠️ 视觉模型 qwen3-vl:4b 未安装。请运行: ollama pull qwen3-vl:4b'}
                    {vd?.error_code === 'VISUAL_MODEL_OFFLINE' && '⚠️ Ollama 服务未启动，视觉评测不可用。'}
                    {(!vd || !vd.error_code) && '⚠️ 视觉评测不可用。当前图片相关结果仅基于Prompt和元数据。'}
                    {vd?.error_message && <div className="text-xs text-gray-400 mt-1">{vd.error_message}</div>}
                  </div>
                )}

                {/* Visual parse failed */}
                {visFailed && vd && (
                  <div className="text-sm bg-red-50 border border-red-200 rounded p-3">
                    <div className="font-medium text-red-700 mb-1">视觉模型返回解析失败</div>
                    <div className="text-xs text-red-600 mb-2">{vd.error_message}</div>
                    {vd.total_ms > 0 && (
                      <div className="text-xs text-gray-500">
                        已耗时 {(vd.total_ms / 1000).toFixed(1)}s · 重试 {vd.retry_count || 0} 次
                      </div>
                    )}
                    <button onClick={doVisualOnly} disabled={generating}
                      className="mt-2 px-3 py-1 text-xs bg-red-100 text-red-700 rounded hover:bg-red-200 disabled:opacity-50">
                      {generating ? '评测中...' : '重试视觉评测'}
                    </button>
                  </div>
                )}

                {/* Visual success */}
                {visOk && vd && (
                  <div className="space-y-4">
                    {/* Score overview */}
                    <div className="grid grid-cols-3 gap-3">
                      <div className="bg-purple-50 rounded p-3 text-center">
                        <div className={`text-2xl font-bold ${vd.visual_consistency_score >= 80 ? 'text-green-600' : vd.visual_consistency_score >= 60 ? 'text-yellow-600' : 'text-red-600'}`}>
                          {vd.visual_consistency_score}
                        </div>
                        <div className="text-xs text-gray-500">视觉一致性总分</div>
                      </div>
                      <div className="bg-purple-50 rounded p-3 text-center">
                        <div className="text-2xl font-bold text-purple-600">{STYLE_LABELS[vd.detected_style] || vd.detected_style}</div>
                        <div className="text-xs text-gray-500">检测风格</div>
                      </div>
                      <div className="bg-purple-50 rounded p-3 text-center">
                        <div className="text-2xl font-bold text-purple-600">{LAYOUT_LABELS[vd.detected_layout_type] || vd.detected_layout_type}</div>
                        <div className="text-xs text-gray-500">检测图片类型</div>
                      </div>
                    </div>

                    {/* Image caption */}
                    {vd.image_caption && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">📝 图片描述</h4>
                        <p className="text-sm text-gray-700 bg-gray-50 rounded p-3">{vd.image_caption}</p>
                      </div>
                    )}

                    {/* Detected objects */}
                    {vd.detected_objects && vd.detected_objects.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">🔍 检测到的对象</h4>
                        <div className="flex flex-wrap gap-1">
                          {vd.detected_objects.map((o, i) => (
                            <span key={i} className="px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded"
                              title={`类别: ${o.category}, 置信度: ${(o.confidence * 100).toFixed(0)}%`}>
                              {o.label} {o.confidence < 0.7 ? '?' : ''}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Detected text */}
                    {vd.detected_text && vd.detected_text.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">🔤 检测到的文字</h4>
                        <div className="space-y-1">
                          {vd.detected_text.map((t, i) => (
                            <div key={i} className="text-xs text-gray-700 flex items-center gap-2">
                              <span className="bg-green-50 text-green-700 px-1.5 py-0.5 rounded">"{t.text}"</span>
                              <span className="text-gray-400">{t.location}</span>
                              <span className="text-gray-400">置信度: {(t.confidence * 100).toFixed(0)}%</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Spatial relations */}
                    {vd.spatial_relations && vd.spatial_relations.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">📍 空间关系</h4>
                        <div className="flex flex-wrap gap-1">
                          {vd.spatial_relations.map((s, i) => (
                            <span key={i} className="px-2 py-0.5 text-xs bg-indigo-50 text-indigo-700 rounded">
                              {s.subject} {s.relation.replace(/_/g, ' ')} {s.object}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Visual dimensions */}
                    {vd.dimensions && vd.dimensions.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">📊 视觉评测维度</h4>
                        <div className="space-y-1.5">
                          {vd.dimensions.filter(d => d.status !== 'not_applicable').map(d => (
                            <div key={d.key} className="flex items-center gap-2">
                              <span className="w-36 text-xs text-gray-600 truncate" title={VISUAL_DIM_LABELS[d.key] || d.label}>
                                {VISUAL_DIM_LABELS[d.key] || d.label}
                              </span>
                              <div className="flex-1 bg-gray-100 rounded-full h-2">
                                <div className={`h-2 rounded-full ${d.score >= 80 ? 'bg-green-500' : d.score >= 60 ? 'bg-yellow-400' : 'bg-red-500'}`}
                                  style={{ width: `${Math.max(0, d.score)}%` }} />
                              </div>
                              <span className="w-8 text-xs font-medium text-right">{d.score}</span>
                              {d.issues && d.issues.length > 0 && (
                                <span className="text-xs text-red-500" title={d.issues.join('; ')}>⚠</span>
                              )}
                            </div>
                          ))}
                        </div>
                        {/* Dimension evidence details */}
                        <details className="mt-2 text-xs text-gray-500">
                          <summary className="cursor-pointer hover:text-gray-700">查看详细证据</summary>
                          <div className="mt-1 space-y-1 max-h-60 overflow-y-auto">
                            {vd.dimensions.filter(d => d.evidence && d.evidence.length > 0 || d.suggestions && d.suggestions.length > 0).map(d => (
                              <div key={d.key} className="border-l-2 border-purple-200 pl-2 py-1">
                                <span className="font-medium text-gray-600">{VISUAL_DIM_LABELS[d.key] || d.label}: </span>
                                {d.evidence && d.evidence.map((e, i) => <div key={i} className="text-gray-500">✓ {e}</div>)}
                                {d.suggestions && d.suggestions.length > 0 && (
                                  <div className="text-amber-600 mt-0.5">
                                    {d.suggestions.map((s, i) => <div key={i}>💡 {s}</div>)}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        </details>
                      </div>
                    )}

                    {/* Hard failures */}
                    {vd.hard_failures && vd.hard_failures.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-red-600 uppercase mb-1">🚨 视觉硬失败</h4>
                        <div className="space-y-2">
                          {vd.hard_failures.map((hf, i) => (
                            <div key={i} className="bg-red-50 border border-red-200 rounded p-2 text-xs">
                              <div className="font-medium text-red-700">{hf.code} ({hf.severity})</div>
                              <div className="text-red-600">{hf.evidence}</div>
                              <div className="text-gray-600 mt-0.5">建议: {hf.recommendation}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Visual bad cases */}
                    {vd.bad_cases && vd.bad_cases.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-amber-600 uppercase mb-1">⚠️ 视觉Bad Case</h4>
                        <div className="space-y-2">
                          {vd.bad_cases.map((bc, i) => (
                            <div key={i} className="bg-amber-50 border border-amber-200 rounded p-2 text-xs">
                              <div className="font-medium text-amber-800">{bc.title} [{bc.severity}]</div>
                              <div className="text-gray-600">{bc.description}</div>
                              <div className="grid grid-cols-2 gap-1 mt-1 text-gray-500">
                                <div>期望: {bc.expected}</div>
                                <div>实际: {bc.observed}</div>
                              </div>
                              <div className="text-gray-600 mt-0.5">建议: {bc.recommendation}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Quality issues */}
                    {vd.quality_issues && vd.quality_issues.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">🔧 质量问题</h4>
                        <div className="flex flex-wrap gap-1">
                          {vd.quality_issues.map((qi, i) => (
                            <span key={i} className={`px-2 py-0.5 text-xs rounded ${qi.severity === 'major' ? 'bg-red-50 text-red-700' : qi.severity === 'moderate' ? 'bg-yellow-50 text-yellow-700' : 'bg-gray-50 text-gray-600'}`}
                              title={qi.description}>
                              {qi.issue_type.replace(/_/g, ' ')} ({qi.severity})
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Recommendations */}
                    {vd.recommendations && vd.recommendations.length > 0 && (
                      <div>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-1">💡 改进建议</h4>
                        <ul className="text-xs text-gray-600 space-y-0.5 list-disc list-inside">
                          {vd.recommendations.map((r, i) => <li key={i}>{r}</li>)}
                        </ul>
                      </div>
                    )}

                    {/* Meta info */}
                    <div className="text-xs text-gray-400 border-t pt-2 flex flex-wrap gap-x-4 gap-y-1">
                      <span>模型: {vd.model}</span>
                      <span>耗时: {(vd.total_ms / 1000).toFixed(1)}s</span>
                      <span>置信度: {(vd.confidence * 100).toFixed(0)}%</span>
                      <span>重试: {vd.retry_count}次</span>
                      {vd.image_sha256 && <span className="font-mono">SHA256: {vd.image_sha256.slice(0, 12)}</span>}
                    </div>
                  </div>
                )}
              </div>
            );
          })()}

          {/* Combined evaluation summary */}
          {evalReport && (evalReport.semantic_data || evalReport.visual_data) && (
            <div className="bg-white rounded-lg p-5 shadow-sm border mb-6">
              <h3 className="text-sm font-semibold text-gray-500 uppercase mb-3">📋 综合评测来源</h3>
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="bg-blue-50 rounded p-3 text-center">
                  <div className="font-bold text-blue-700">{evalReport.rule_score}</div>
                  <div className="text-xs text-gray-500">规则评测 (权重35%)</div>
                </div>
                <div className="bg-green-50 rounded p-3 text-center">
                  <div className="font-bold text-green-700">{evalReport.semantic_score || '—'}</div>
                  <div className="text-xs text-gray-500">Qwen文本语义 (权重35%)</div>
                </div>
                <div className="bg-purple-50 rounded p-3 text-center">
                  <div className="font-bold text-purple-700">{evalReport.visual_score !== null && evalReport.visual_score !== undefined ? evalReport.visual_score : '—'}</div>
                  <div className="text-xs text-gray-500">Qwen3-VL视觉 (权重30%)</div>
                </div>
              </div>
              <div className="mt-2 text-xs text-gray-500 text-center">
                综合得分 = {evalReport.combined_score} | 评测模型: {evalReport.model || 'rule_only'} | 状态: {evalReport.evaluation_status}
              </div>
            </div>
          )}

          {items.length > 0 && (
            <div className="bg-white rounded-lg p-5 shadow-sm border">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-500 uppercase">问题列表</h3>
                <div className="flex gap-1">
                  {(['all','S0','S1','S2','S3','S4'] as const).map(s => (
                    <button key={s} onClick={() => setFilter(s)} className={`px-2 py-0.5 text-xs rounded ${filter===s ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-600'}`}>{s==='all'?'全部':s}</button>
                  ))}
                </div>
              </div>
              {filtered.length === 0 ? <p className="text-sm text-gray-400 py-4 text-center">无匹配问题</p> : (
                <div className="space-y-2">
                  {filtered.map(item => (
                    <div key={item.evaluation_id} className="flex items-center gap-3 p-3 border rounded hover:bg-gray-50 cursor-pointer"
                      onClick={() => navigate(`/task/${taskId}/badcase/${item.evaluation_id}`)}>
                      <SeverityBadge severity={item.severity} />
                      <span className="text-sm text-gray-600">{item.target_type}</span>
                      <span className="text-sm font-medium text-gray-800 flex-1">{item.error_type}</span>
                      <span className="text-xs text-brand-600">查看详情 →</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function GateItem({ label, pass }: { label: string; pass: boolean }) {
  return <div className="flex items-center gap-2"><span className={pass?'text-green-500':'text-red-500'}>{pass?'✓':'✗'}</span><span className={pass?'text-gray-600':'text-red-600 font-medium'}>{label}</span></div>;
}
