import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Task, EvaluationItem } from '../types';
import { getTask } from '../services/api';
import { SeverityBadge } from '../components/StatusBadge';

export default function BadCaseDetail() {
  const { taskId, bcId } = useParams<{ taskId: string; bcId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [item, setItem] = useState<EvaluationItem | null>(null);
  const [feedback, setFeedback] = useState<string>('');

  useEffect(() => {
    if (!taskId) return;
    getTask(taskId).then(t => {
      setTask(t);
      const found = t.evaluation?.items.find(i => i.evaluation_id === bcId);
      setItem(found ?? null);
    }).catch(() => {});
  }, [taskId, bcId]);

  if (!task || !item) return <div className="text-center py-12 text-gray-400">加载中...</div>;

  const jumpToEditor = () => {
    if (item.target_type === 'question') navigate(`/task/${taskId}/assets`);
    else navigate(`/task/${taskId}/script`);
  };

  return (
    <div className="max-w-3xl mx-auto">
      <button onClick={() => navigate(-1)} className="text-sm text-brand-600 hover:underline mb-4 inline-block">
        ← 返回评测报告
      </button>

      <div className="bg-white rounded-lg p-6 shadow-sm border">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4">
          <SeverityBadge severity={item.severity} />
          <span className="text-sm text-gray-500">{item.target_type}</span>
          <h1 className="text-lg font-bold text-gray-800">{item.error_type}</h1>
        </div>

        <div className="text-xs text-gray-400 mb-6">
          评测ID: {item.evaluation_id} · 评测器: {item.evaluator_type} · 模型: {item.evaluator_model || '规则引擎'}
        </div>

        {/* Detail grid */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          <div>
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-1">发生位置</h3>
            <p className="text-sm text-gray-800">{item.error_location}</p>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-500 uppercase mb-1">评测版本</h3>
            <p className="text-sm text-gray-800">{item.evaluation_version}</p>
          </div>
        </div>

        {/* Evidence */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">证据</h3>
          <div className="bg-gray-50 rounded p-4 text-sm text-gray-700 whitespace-pre-wrap">
            {item.evidence || '（无证据）'}
          </div>
        </div>

        {/* Suspected cause */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">疑似根因</h3>
          <p className="text-sm text-gray-800">{item.suspected_cause || '待分析'}</p>
        </div>

        {/* Repair suggestion */}
        <div className="mb-6">
          <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">修复建议</h3>
          <div className="bg-brand-50 rounded p-4 text-sm text-brand-800">
            {item.repair_suggestion || '无'}
          </div>
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-3 mb-6 pt-4 border-t">
          <button onClick={jumpToEditor}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm font-medium">
            跳转到编辑位置
          </button>
          <button className="px-4 py-2 border border-brand-300 text-brand-600 rounded-lg hover:bg-brand-50 text-sm">
            局部重生成
          </button>
          <button className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50 text-sm">
            人工修改
          </button>
        </div>

        {/* Teacher feedback */}
        <div className="border-t pt-4">
          <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">教师反馈</h3>
          {item.teacher_feedback ? (
            <div className="text-sm text-gray-700">
              标记: <span className="font-medium">{item.teacher_feedback}</span>
              {item.teacher_correction && <p className="mt-1 text-gray-500">{item.teacher_correction}</p>}
            </div>
          ) : (
            <div className="flex gap-2 flex-wrap">
              {(['agree', 'false_positive', 'fixed'] as const).map(fb => (
                <button key={fb} onClick={() => {
                  setItem(prev => prev ? { ...prev, teacher_feedback: fb } : prev);
                }}
                  className={`px-3 py-1 text-xs rounded ${
                    item.teacher_feedback === fb
                      ? 'bg-brand-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {{ agree: '✓ 认可', false_positive: '✗ 误报', fixed: '🔧 已修复' }[fb]}
                </button>
              ))}
            </div>
          )}
          {item.teacher_feedback && (
            <div className="mt-3">
              <textarea value={feedback} onChange={e => setFeedback(e.target.value)}
                placeholder="补充说明（可选）..."
                className="w-full px-3 py-1.5 border rounded text-sm h-16 resize-none" />
              <button onClick={() => {
                setItem(prev => prev ? { ...prev, teacher_correction: feedback } : prev);
                setFeedback('');
              }}
                className="mt-2 px-3 py-1 bg-gray-100 text-gray-600 rounded text-xs hover:bg-gray-200">
                保存说明
              </button>
            </div>
          )}
        </div>
      </div>

      {/* History placeholder */}
      <div className="bg-white rounded-lg p-4 shadow-sm border mt-4">
        <h3 className="text-sm font-semibold text-gray-500 uppercase mb-2">修复历史</h3>
        <p className="text-xs text-gray-400">（功能开发中：V0.2将展示完整修复与回归记录）</p>
      </div>
    </div>
  );
}
