import { useState, useEffect, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import type { TaskListItem, TaskStatus } from '../types';
import { listTasks, deleteTask, ApiError } from '../services/api';
import { API_BASE_URL } from '../config/api';
import { useAppContext } from '../App';
import { TaskStatusBadge } from '../components/StatusBadge';
import { ConfirmDialog } from '../components/StatusBadge';

type PageState = 'loading' | 'backend_offline' | 'request_error' | 'empty' | 'success';

const FILTER_OPTIONS: { label: string; value: TaskStatus | 'all' }[] = [
  { label: '全部', value: 'all' },
  { label: '草稿', value: 'draft' },
  { label: '生成中', value: 'generating' },
  { label: '待评测', value: 'evaluating' },
  { label: '存在问题', value: 'needs_fix' },
  { label: '待审核', value: 'pending_review' },
  { label: '已导出', value: 'exported' },
  { label: '失败', value: 'failed' },
];

export default function TaskCenter() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [filter, setFilter] = useState<TaskStatus | 'all'>('all');
  const [search, setSearch] = useState('');
  const [delId, setDelId] = useState<string | null>(null);
  const [pageState, setPageState] = useState<PageState>('loading');
  const [errorMsg, setErrorMsg] = useState('');
  const navigate = useNavigate();
  const { health } = useAppContext();

  const backendOnline = health?.status === 'ok';

  const load = useCallback(async () => {
    setPageState('loading');
    setErrorMsg('');
    try {
      const data = await listTasks();
      setTasks(data);
      setPageState(data.length === 0 ? 'empty' : 'success');
    } catch (e: unknown) {
      if (e instanceof ApiError && (e.code === 'NETWORK_ERROR' || e.code === 'TIMEOUT')) {
        setPageState('backend_offline');
        setErrorMsg(e.message);
      } else {
        setPageState('request_error');
        setErrorMsg(e instanceof Error ? e.message : '任务列表读取失败');
      }
      setTasks([]);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh when backend comes online
  useEffect(() => {
    if (backendOnline && pageState === 'backend_offline') {
      load();
    }
  }, [backendOnline, pageState, load]);

  const handleDelete = async () => {
    if (!delId) return;
    await deleteTask(delId);
    setDelId(null);
    load();
  };

  const hasS3S4 = (t: TaskListItem) => t.s3s4_count > 0;

  // ── ALL hooks above this line; render branches below ──

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-800">任务中心</h1>
        <Link
          to={backendOnline ? '/task/new' : '#'}
          className={`px-4 py-2 rounded-lg transition font-medium text-white ${
            backendOnline
              ? 'bg-brand-600 hover:bg-brand-700'
              : 'bg-gray-300 cursor-not-allowed'
          }`}
          title={backendOnline ? '新建任务' : '后端未启动，无法创建真实任务'}
          onClick={e => { if (!backendOnline) e.preventDefault(); }}
        >
          ＋ 新建任务
        </Link>
      </div>

      {/* ── LOADING ── */}
      {pageState === 'loading' && (
        <div className="text-center py-16">
          <div className="inline-block w-8 h-8 border-4 border-brand-300 border-t-brand-600 rounded-full animate-spin mb-4" />
          <p className="text-gray-400">正在连接后端并读取任务...</p>
        </div>
      )}

      {/* ── BACKEND OFFLINE ── */}
      {pageState === 'backend_offline' && (
        <div className="max-w-lg mx-auto text-center py-16">
          <div className="text-5xl mb-4">🔌</div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">后端未启动</h2>
          <p className="text-gray-500 mb-1">暂时无法读取真实任务。</p>
          <p className="text-xs text-gray-400 mb-6">
            后端地址：{API_BASE_URL}
          </p>
          <p className="text-xs text-gray-400 mb-6">
            请在项目根目录右键运行 <code className="bg-gray-100 px-1 rounded">start-real.ps1</code>
          </p>
          <div className="flex gap-3 justify-center">
            <button onClick={load} className="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm font-medium">
              重试连接
            </button>
          </div>
        </div>
      )}

      {/* ── REQUEST ERROR ── */}
      {pageState === 'request_error' && (
        <div className="max-w-lg mx-auto text-center py-16">
          <div className="text-5xl mb-4">⚠️</div>
          <h2 className="text-xl font-bold text-gray-800 mb-2">任务列表读取失败</h2>
          <p className="text-sm text-gray-500 mb-6">{errorMsg}</p>
          <button onClick={load} className="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm font-medium">
            重试
          </button>
        </div>
      )}

      {/* ── EMPTY ── */}
      {pageState === 'empty' && (
        <div className="text-center py-16">
          <div className="text-5xl mb-4">📋</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">暂无任务</h2>
          <p className="text-gray-400 mb-6">点击"新建任务"开始创建</p>
          {backendOnline && (
            <Link to="/task/new" className="px-6 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 text-sm font-medium inline-block">
              ＋ 新建任务
            </Link>
          )}
        </div>
      )}

      {/* ── SUCCESS ── */}
      {pageState === 'success' && (
        <>
          {/* Filter bar */}
          <div className="flex flex-wrap items-center gap-2 mb-4">
            {FILTER_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setFilter(opt.value)}
                className={`px-3 py-1 rounded-full text-sm transition ${
                  filter === opt.value
                    ? 'bg-brand-600 text-white'
                    : 'bg-white text-gray-600 border hover:border-brand-400'
                }`}
              >
                {opt.label}
              </button>
            ))}
            <input
              type="text"
              placeholder="搜索任务..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="ml-auto px-3 py-1 border rounded text-sm w-48"
            />
          </div>

          {/* Task cards */}
          <div className="grid gap-3">
            {tasks.filter(t => {
              if (filter !== 'all' && t.status !== filter) return false;
              if (search && !t.task_name.includes(search) && !t.topic.includes(search)) return false;
              return true;
            }).map(t => (
              <div
                key={t.task_id}
                className={`bg-white rounded-lg p-4 shadow-sm border hover:shadow-md transition cursor-pointer ${
                  hasS3S4(t) ? 'border-l-4 border-l-red-500' : ''
                }`}
                onClick={() => {
                  if (t.status === 'draft') navigate(`/task/new?edit=${t.task_id}`);
                  else navigate(`/task/${t.task_id}/script`);
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 font-mono">{t.task_id}</span>
                    <span className="font-semibold text-gray-800">{t.task_name}</span>
                    <TaskStatusBadge status={t.status} />
                    {hasS3S4(t) && (
                      <span className="text-xs text-red-600 font-medium">⚠ {t.s3s4_count}个严重问题</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-sm text-gray-500">
                    {t.overall_score > 0 && (
                      <span className={t.overall_score >= 80 ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
                        {t.overall_score}分
                      </span>
                    )}
                    <span>{t.updated_at ? new Date(t.updated_at).toLocaleDateString('zh-CN') : ''}</span>
                    <div className="flex gap-1" onClick={e => e.stopPropagation()}>
                      {(t.status === 'needs_fix' || t.status === 'partial_success') && (
                        <Link to={`/task/${t.task_id}/report`} className="px-2 py-1 text-xs bg-orange-100 text-orange-700 rounded hover:bg-orange-200">
                          修复
                        </Link>
                      )}
                      {t.status === 'pending_review' && (
                        <Link to={`/task/${t.task_id}/export`} className="px-2 py-1 text-xs bg-blue-100 text-blue-700 rounded hover:bg-blue-200">
                          审核
                        </Link>
                      )}
                      {t.status === 'approved' && (
                        <Link to={`/task/${t.task_id}/export`} className="px-2 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200">
                          导出
                        </Link>
                      )}
                      <button
                        onClick={() => setDelId(t.task_id)}
                        className="px-2 py-1 text-xs text-gray-400 hover:text-red-600 rounded hover:bg-red-50"
                      >
                        删除
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
            {tasks.filter(t => {
              if (filter !== 'all' && t.status !== filter) return false;
              if (search && !t.task_name.includes(search) && !t.topic.includes(search)) return false;
              return true;
            }).length === 0 && (
              <div className="text-center py-8 text-gray-400 text-sm">无匹配结果</div>
            )}
          </div>
        </>
      )}

      <ConfirmDialog
        open={!!delId}
        title="确认删除"
        message={`确定要删除任务 ${delId} 吗？已导出的任务将保留版本记录。`}
        onConfirm={handleDelete}
        onCancel={() => setDelId(null)}
      />
    </div>
  );
}
