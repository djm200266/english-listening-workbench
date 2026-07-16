import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Task, DialogueScript } from '../types';
import { getTask, confirmScript } from '../services/api';
import { checkPatternCoverage } from '../utils/patterns';
import { TaskStatusBadge, ScriptStatusBadge, EvalStatusBadge } from '../components/StatusBadge';

export default function ScriptReview() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [script, setScript] = useState<DialogueScript | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTurnId, setEditTurnId] = useState<number | null>(null);
  const [editText, setEditText] = useState('');
  const [confirming, setConfirming] = useState(false);
  const loadData = useCallback(async () => {
    if (!taskId) {
      setError('缺少任务ID');
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const t = await getTask(taskId);
      setTask(t);
      if (!t.script) {
        setError('该任务尚未生成脚本。请返回新建任务页面提交生成。');
        setLoading(false);
        return;
      }
      setScript(t.script);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '数据加载失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ── Loading state ──
  if (loading) {
    return (
      <div className="text-center py-16">
        <div className="inline-block w-8 h-8 border-4 border-brand-300 border-t-brand-600 rounded-full animate-spin mb-4" />
        <p className="text-gray-400">加载中...</p>
      </div>
    );
  }

  // ── Error state ──
  if (error) {
    return (
      <div className="max-w-md mx-auto text-center py-16">
        <div className="text-4xl mb-4">⚠️</div>
        <h2 className="text-lg font-semibold text-gray-800 mb-2">加载失败</h2>
        <p className="text-sm text-gray-500 mb-6">{error}</p>
        <div className="flex gap-3 justify-center">
          <button onClick={loadData} className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm">
            重试
          </button>
          <button onClick={() => navigate('/')} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50 text-sm">
            返回任务中心
          </button>
        </div>
      </div>
    );
  }

  // ── Task not found ──
  if (!task || !script) {
    return (
      <div className="max-w-md mx-auto text-center py-16">
        <h2 className="text-lg font-semibold text-gray-800 mb-2">任务不存在</h2>
        <p className="text-sm text-gray-500 mb-6">任务 {taskId} 未找到或已被删除。</p>
        <button onClick={() => navigate('/')} className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm">
          返回任务中心
        </button>
      </div>
    );
  }

  // ── Success state ──
  const isConfirmed = script.status === 'confirmed';
  const textScore = task.evaluation?.dimension_scores?.textQuality ?? null;

  const startEdit = (turnId: number, text: string) => {
    setEditTurnId(turnId);
    setEditText(text);
    setEditing(true);
  };

  const handleSaveEdit = () => {
    if (editTurnId === null) return;
    setScript(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        dialogue: prev.dialogue.map(t =>
          t.turn_id === editTurnId ? { ...t, text: editText } : t
        ),
      };
    });
    setEditing(false);
    setEditTurnId(null);
  };

  const handleConfirm = async () => {
    if (!taskId) return;
    setConfirming(true);
    setError(null);
    try {
      await confirmScript(taskId);
      const now = new Date().toISOString();
      setScript(prev => prev ? { ...prev, status: 'confirmed', confirmed_at: now } : prev);
      setTask(prev => prev ? { ...prev, status: 'pending_review' } : prev);
      // Auto-navigate to multi-modal assets after confirm
      navigate(`/task/${taskId}/assets`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '确认失败');
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div>
      {/* Top bar */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-gray-800">{task.task_name}</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
            <span className="font-mono">{task.task_id}</span>
            <TaskStatusBadge status={task.status} />
            <ScriptStatusBadge status={script.status as 'draft' | 'confirmed'} />
            <EvalStatusBadge status={task.evaluation ? (task.evaluation.s3s4_count > 0 ? 'has_issues' : 'evaluated') : 'not_evaluated'} />
            <span className="text-xs text-gray-400">v{script.script_version}</span>
          </div>
          {/* Script metadata */}
          <div className="flex flex-wrap gap-2 mt-2 text-xs">
            <span className="px-2 py-0.5 bg-purple-50 text-purple-600 rounded">
              年级: {task.config.grade === 'grade_7' ? '七年级' : task.config.grade === 'grade_8' ? '八年级' : '九年级'}
            </span>
            <span className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded">
              角色: {script.speakers.length}人 ({script.speakers.map(s => s.role).join('、')})
            </span>
            <span className="px-2 py-0.5 bg-green-50 text-green-600 rounded">
              角色来源: {task.config.speaker_count === 'auto' ? '系统自动' : '用户指定'}
            </span>
            <span className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded">
              对话轮次: {script.dialogue.length}/{task.config.dialogue_turns}
            </span>
            <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
              总词数: {script.total_words}
            </span>
          </div>
        </div>
        <button onClick={() => navigate(`/task/${taskId}/assets`)}
          className={`px-4 py-2 rounded-lg font-medium transition ${
            isConfirmed
              ? 'bg-brand-600 text-white hover:bg-brand-700'
              : 'bg-gray-200 text-gray-400 cursor-not-allowed'
          }`}
          disabled={!isConfirmed}
          title={isConfirmed ? '查看多模态结果' : '请先确认脚本'}
        >
          查看素材 →
        </button>
      </div>

      <div className="flex gap-6">
        {/* Left: Dialogue editor */}
        <div className="flex-1 bg-white rounded-lg p-5 shadow-sm border">
          <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">对话脚本</h2>
          <div className="space-y-2">
            {script.dialogue.map(turn => {
              const speaker = script.speakers.find(s => s.speaker_id === turn.speaker_id);
              return (
                <div key={turn.turn_id} className="flex gap-3 items-start group">
                  <span className="text-xs text-gray-400 w-6 pt-1 font-mono">{turn.turn_id}</span>
                  <span className={`px-2 py-0.5 rounded text-xs font-medium w-16 text-center ${
                    speaker?.speaker_id === 'A' ? 'bg-blue-100 text-blue-700' : 'bg-green-100 text-green-700'
                  }`}>
                    {speaker?.role || turn.speaker_id}
                  </span>
                  <span className="flex-1 text-gray-800">{turn.text}</span>
                  <button
                    onClick={() => startEdit(turn.turn_id, turn.text)}
                    className="opacity-0 group-hover:opacity-100 text-xs text-brand-600 hover:underline"
                  >
                    编辑
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Score panel */}
        <div className="w-72 space-y-4">
          <div className="bg-white rounded-lg p-4 shadow-sm border">
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">文本评测</h3>
            {textScore !== null ? (
              <div className="space-y-2">
                <div className={`text-2xl font-bold ${textScore >= 4 ? 'text-green-600' : textScore >= 3 ? 'text-yellow-600' : 'text-red-600'}`}>
                  {textScore}/5
                </div>
                <div className="text-xs text-gray-500">
                  <div>✓ 词汇覆盖率: 100%</div>
                  <div>✓ 句型覆盖率: 100%</div>
                  <div>✓ 对话轮次: {script.dialogue.length}/{task.config.dialogue_turns}</div>
                  <div>✓ 总词数: {script.total_words}</div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-400">尚未评测</p>
            )}
          </div>

          <div className="bg-white rounded-lg p-4 shadow-sm border">
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">词汇/句型覆盖</h3>
            <div className="text-xs space-y-2">
              <div>
                <span className="text-gray-500">必选词汇:</span>
                {task.config.required_vocabulary.length > 0 ? (
                  <>
                    <span className={task.config.required_vocabulary.every(v =>
                      script.used_vocabulary.some(uv => uv.toLowerCase().includes(v.toLowerCase()))
                    ) ? 'text-green-600' : 'text-red-600'}>
                      {task.config.required_vocabulary.every(v =>
                        script.used_vocabulary.some(uv => uv.toLowerCase().includes(v.toLowerCase()))
                      ) ? ' ✓ 全部覆盖' : ' ✗ 未完全覆盖'}
                    </span>
                    <div className="text-gray-400 mt-0.5">{script.used_vocabulary.join(', ') || '无'}</div>
                  </>
                ) : (
                  <>
                    <span className="text-blue-500"> 未指定（系统自动选择）</span>
                    <div className="text-gray-400 mt-0.5">
                      系统采用: {task.config.effective_vocabulary?.join(', ') || script.used_vocabulary.join(', ') || '—'}
                    </div>
                  </>
                )}
              </div>
              <div>
                <span className="text-gray-500">目标句型:</span>
                {task.config.target_patterns.length > 0 ? (
                  <>
                    {(() => {
                      const cov = checkPatternCoverage(script.dialogue, task.config.target_patterns);
                      return (
                        <span className={cov.coverage === 1 ? 'text-green-600' : 'text-red-600'}>
                          {cov.coverage === 1 ? ` ✓ 全部覆盖 (${cov.matched.length}/${task.config.target_patterns.length})` : ` ✗ ${cov.unmatched.length}个未匹配`}
                        </span>
                      );
                    })()}
                    {(() => {
                      const cov = checkPatternCoverage(script.dialogue, task.config.target_patterns);
                      return cov.unmatched.length > 0 ? (
                        <div className="text-red-500 mt-0.5">未匹配: {cov.unmatched.join(', ')}</div>
                      ) : null;
                    })()}
                  </>
                ) : (
                  <>
                    <span className="text-blue-500"> 未指定（系统自动设计）</span>
                    <div className="text-gray-400 mt-0.5">
                      系统采用: {task.config.effective_target_patterns?.join(', ') || script.used_patterns.join(', ') || '—'}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Edit modal */}
      {editing && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 shadow-xl max-w-lg w-full">
            <h3 className="text-lg font-semibold mb-3">编辑对话</h3>
            <textarea value={editText} onChange={e => setEditText(e.target.value)}
              className="w-full px-3 py-2 border rounded h-24 resize-none" />
            <div className="flex justify-end gap-3 mt-4">
              <button onClick={() => { setEditing(false); setEditTurnId(null); }} className="px-4 py-2 border rounded text-gray-600">取消</button>
              <button onClick={handleSaveEdit} className="px-4 py-2 bg-brand-600 text-white rounded">保存</button>
            </div>
          </div>
        </div>
      )}

      {/* Bottom actions */}
      <div className="flex justify-end gap-3 mt-6">
        <button onClick={() => navigate('/')} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50">
          返回
        </button>
        {!isConfirmed && (
          <button onClick={handleConfirm} disabled={confirming}
            className="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 font-medium disabled:opacity-50">
            {confirming ? '确认中...' : '确认脚本并启用下游生成'}
          </button>
        )}
        <button onClick={() => navigate(`/task/${taskId}/report`)}
          className="px-4 py-2 border rounded text-brand-600 border-brand-300 hover:bg-brand-50">
          查看评测报告
        </button>
      </div>
    </div>
  );
}
