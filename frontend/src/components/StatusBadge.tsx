import type { TaskStatus, ScriptStatus, EvalStatus, Severity, AssetStatus } from '../types';
import { TASK_STATUS_LABELS, SCRIPT_STATUS_LABELS, EVAL_STATUS_LABELS, SEVERITY_LABELS } from '../types';

/* ── Task Status ── */

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium status-${status}`}>
      {TASK_STATUS_LABELS[status] || status}
    </span>
  );
}

/* ── Script Status ── */

export function ScriptStatusBadge({ status }: { status: ScriptStatus }) {
  const colors: Record<ScriptStatus, string> = {
    draft: 'bg-yellow-100 text-yellow-700',
    confirmed: 'bg-green-100 text-green-700 font-medium',
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs ${colors[status]}`}>
      {SCRIPT_STATUS_LABELS[status]}
    </span>
  );
}

/* ── Evaluation Status ── */

export function EvalStatusBadge({ status }: { status: EvalStatus }) {
  const colors: Record<EvalStatus, string> = {
    not_evaluated: 'bg-gray-100 text-gray-500',
    evaluating: 'bg-purple-100 text-purple-700 animate-pulse',
    evaluated: 'bg-green-100 text-green-700',
    has_issues: 'bg-orange-100 text-orange-700',
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs ${colors[status]}`}>
      {EVAL_STATUS_LABELS[status]}
    </span>
  );
}

/* ── Severity ── */

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium severity-${severity}`}>
      {SEVERITY_LABELS[severity] || severity}
    </span>
  );
}

/* ── Asset Status ── */

export function AssetStatusBadge({ status }: { status: AssetStatus }) {
  const map: Record<AssetStatus, string> = {
    generating: '生成中',
    success: '成功',
    failed: '失败',
    outdated: '已过期',
  };
  const color: Record<AssetStatus, string> = {
    generating: 'bg-blue-100 text-blue-700',
    success: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    outdated: 'bg-gray-200 text-gray-500',
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${color[status]}`}>
      {map[status]}
    </span>
  );
}

/* ── Confirm Dialog ── */

export function ConfirmDialog({
  open, title, message, onConfirm, onCancel,
}: {
  open: boolean; title: string; message: string;
  onConfirm: () => void; onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 shadow-xl max-w-sm w-full">
        <h3 className="text-lg font-semibold mb-2">{title}</h3>
        <p className="text-gray-600 mb-4">{message}</p>
        <div className="flex justify-end gap-3">
          <button onClick={onCancel} className="px-4 py-2 rounded border text-gray-600 hover:bg-gray-50">取消</button>
          <button onClick={onConfirm} className="px-4 py-2 rounded bg-red-500 text-white hover:bg-red-600">确认</button>
        </div>
      </div>
    </div>
  );
}
