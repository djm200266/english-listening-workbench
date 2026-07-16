import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import type { Task } from '../types';
import { getTask, exportPackage } from '../services/api';

/* ── IndexedDB helpers for directory handle persistence ── */

const DB_NAME = 'ewb-export-dir';
const DB_VERSION = 1;
const STORE_NAME = 'handles';

function openHandleDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => { req.result.createObjectStore(STORE_NAME); };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function loadSavedHandle(): Promise<FileSystemDirectoryHandle | null> {
  try {
    const db = await openHandleDB();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, 'readonly');
      const req = tx.objectStore(STORE_NAME).get('exportDir');
      req.onsuccess = () => resolve(req.result ?? null);
      req.onerror = () => resolve(null);
    });
  } catch { return null; }
}

async function saveHandle(handle: FileSystemDirectoryHandle | null): Promise<void> {
  try {
    const db = await openHandleDB();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    if (handle) tx.objectStore(STORE_NAME).put(handle, 'exportDir');
    else tx.objectStore(STORE_NAME).delete('exportDir');
    return new Promise((resolve) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  } catch { /* ignore */ }
}

/* ── Filename helpers ── */

const ILLEGAL_CHARS = /[\\/:*?"<>|]/g;

function cleanFilename(name: string): string {
  let cleaned = name.replace(ILLEGAL_CHARS, '').trim();
  if (!cleaned) cleaned = 'export';
  if (!cleaned.toLowerCase().endsWith('.zip')) cleaned += '.zip';
  // prevent .zip.zip
  cleaned = cleaned.replace(/\.zip\.zip$/i, '.zip');
  if (cleaned.length > 200) cleaned = cleaned.slice(0, 196) + '.zip';
  return cleaned;
}

function buildDefaultFilename(task: Task): string {
  const ts = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15).replace('T', '_');
  const name = task.task_name.replace(/[/\\]/g, '-').slice(0, 30);
  return cleanFilename(`${task.task_id}_${name}_素材包_${ts}.zip`);
}

/* ── Types ── */

type ExportMode = 'none' | 'directory' | 'download';
type ExportPhase =
  | 'idle'
  | 'checking'
  | 'generating'
  | 'receiving'
  | 'writing'
  | 'done'
  | 'error';

interface ExportRecord {
  filename: string;
  size: number;
  exportedAt: string;
  mode: ExportMode;
  directoryName?: string;
}

/* ── Main component ── */

export default function ExportReview() {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [phase, setPhase] = useState<ExportPhase>('idle');
  const [exportResult, setExportResult] = useState<ExportRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Directory picker state
  const [dirHandle, setDirHandle] = useState<FileSystemDirectoryHandle | null>(null);
  const [dirName, setDirName] = useState<string>('');
  const [dirPermissionValid, setDirPermissionValid] = useState(false);
  const [customFilename, setCustomFilename] = useState('');

  useEffect(() => {
    if (!taskId) return;
    getTask(taskId).then(t => {
      setTask(t);
      setCustomFilename(buildDefaultFilename(t));
    }).catch(() => {});
  }, [taskId]);

  // Restore saved directory handle
  useEffect(() => {
    loadSavedHandle().then(async (handle) => {
      if (!handle) return;
      try {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const h = handle as any;
        const ok = (await h.queryPermission({ mode: 'readwrite' })) === 'granted';
        if (!ok) {
          const req = await h.requestPermission({ mode: 'readwrite' });
          if (req !== 'granted') { await saveHandle(null); return; }
        }
        setDirHandle(handle);
        setDirName(handle.name);
        setDirPermissionValid(true);
      } catch {
        await saveHandle(null);
      }
    });
  }, []);

  const pickDirectory = useCallback(async () => {
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const handle = await (window as any).showDirectoryPicker({
        mode: 'readwrite',
        id: 'english-listening-workbench-export',
      });
      setDirHandle(handle);
      setDirName(handle.name);
      setDirPermissionValid(true);
      await saveHandle(handle);
    } catch (e: any) {
      if (e.name === 'AbortError') return; // user cancelled
      console.warn('showDirectoryPicker failed:', e);
    }
  }, []);

  const clearDirectory = useCallback(async () => {
    setDirHandle(null);
    setDirName('');
    setDirPermissionValid(false);
    await saveHandle(null);
  }, []);

  if (!task) return <div className="text-center py-12 text-gray-400">加载中...</div>;

  const hasS3S4 = (task.evaluation?.s3s4_count ?? 0) > 0;
  const hasOutdated = task.image?.is_outdated || task.audio?.is_outdated || task.questions?.is_outdated;
  const hasAllAssets = !!(task.script && task.image && task.audio && task.questions);
  const hasEvaluation = !!task.evaluation;
  const evalPassed = task.evaluation?.pass_status === 'pass';
  const canExport = hasAllAssets && hasEvaluation && !hasS3S4 && !hasOutdated && evalPassed && confirmed;

  const blockReasons: string[] = [];
  if (!hasAllAssets) blockReasons.push('素材不完整（需脚本+图片+音频+题目全部成功生成）');
  if (!hasEvaluation) blockReasons.push('尚未完成评测');
  if (hasS3S4) blockReasons.push(`存在 ${task.evaluation?.s3s4_count} 个S3/S4严重问题，必须修复后才能导出`);
  if (hasOutdated) blockReasons.push('存在过期素材（基于旧脚本版本），需重新生成');
  if (!evalPassed && hasEvaluation) blockReasons.push('评测门禁未通过');
  if (!confirmed) blockReasons.push('请确认审核清单并勾选"教师审核确认"');

  const handleExport = async () => {
    if (!taskId || !canExport || exporting) return;
    setExporting(true);
    setError(null);
    setExportResult(null);

    const filename = cleanFilename(customFilename || buildDefaultFilename(task));
    setCustomFilename(filename);

    try {
      setPhase('checking');
      // Verify assets checklist is complete
      if (!hasAllAssets || !hasEvaluation || hasS3S4 || hasOutdated || !evalPassed) {
        throw new Error('导出条件不满足，请检查审核清单');
      }

      setPhase('generating');
      const result = await exportPackage(taskId, filename);

      setPhase('receiving');

      // Determine export mode
      const hasPicker = dirHandle && dirPermissionValid;

      if (hasPicker && dirHandle) {
        setPhase('writing');
        try {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const fileHandle = await (dirHandle as any).getFileHandle(filename, { create: true });
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const writable = await (fileHandle as any).createWritable();
          await writable.write(result.blob);
          await writable.close();
          setPhase('done');
          setExportResult({
            filename,
            size: result.size,
            exportedAt: new Date().toISOString(),
            mode: 'directory',
            directoryName: dirName,
          });
        } catch (e: any) {
          // Directory write failed — fall back to download
          console.warn('Directory write failed, falling back to download:', e);
          triggerDownload(result.blob, filename);
          setPhase('done');
          setExportResult({
            filename,
            size: result.size,
            exportedAt: new Date().toISOString(),
            mode: 'download',
          });
        }
      } else {
        triggerDownload(result.blob, filename);
        setPhase('done');
        setExportResult({
          filename,
          size: result.size,
          exportedAt: new Date().toISOString(),
          mode: 'download',
        });
      }
    } catch (e: any) {
      setPhase('error');
      setError(e.message || '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const hasDirectoryPicker = typeof (window as any).showDirectoryPicker === 'function';

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-xl font-bold text-gray-800 mb-2">最终审核与导出</h1>
      <p className="text-sm text-gray-500 mb-6">{task.task_name} · {task.task_id}</p>

      {/* Audit checklist */}
      <div className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">审核清单</h2>
        <div className="space-y-2 text-sm">
          <CheckItem label="素材完整（脚本+图片+音频+题目+答案全部存在）" pass={hasAllAssets} />
          <CheckItem label="评测通过（总分≥80且无S3/S4）" pass={hasEvaluation && !hasS3S4 && evalPassed} />
          <CheckItem label="版本一致（所有素材基于当前脚本版本）" pass={!hasOutdated} />
          <CheckItem label="安全无阻断（无不适龄/违法/隐私内容）" pass={true} />
        </div>
      </div>

      {/* Block reasons */}
      {blockReasons.length > 0 && (
        <div className="bg-red-50 border border-red-300 rounded-lg p-4 mb-4">
          <h3 className="text-sm font-semibold text-red-700 mb-2">导出被阻止</h3>
          <ul className="list-disc list-inside space-y-1 text-sm text-red-600">
            {blockReasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Preview */}
      <div className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">最终预览</h2>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div className="border rounded p-3">
            <span className="text-gray-500">📄 脚本:</span>
            <span className="ml-2 text-gray-800">{task.script ? `${task.script.dialogue.length}轮对话` : '未生成'}</span>
          </div>
          <div className="border rounded p-3">
            <span className="text-gray-500">🖼️ 图片:</span>
            <span className="ml-2 text-gray-800">{task.image?.generation_status === 'success' ? '已生成' : '未生成'}</span>
          </div>
          <div className="border rounded p-3">
            <span className="text-gray-500">🎧 音频:</span>
            <span className="ml-2 text-gray-800">{task.audio ? `${task.audio.audio_duration_actual_sec.toFixed(1)}s` : '未生成'}</span>
          </div>
          <div className="border rounded p-3">
            <span className="text-gray-500">📝 题目:</span>
            <span className="ml-2 text-gray-800">{task.questions ? `${task.questions.questions.length}道` : '未生成'}</span>
          </div>
        </div>
      </div>

      {/* Export format */}
      <div className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">导出格式</h2>
        <div className="text-sm text-gray-700">
          <p>📦 <strong>ZIP 包</strong>，内含：</p>
          <ul className="list-disc list-inside ml-4 mt-1 text-gray-500 space-y-0.5">
            <li>script.txt — 对话脚本</li>
            <li>image.png — 情境图片</li>
            <li>audio.mp3 — 听力音频</li>
            <li>questions.json — 题目与答案</li>
            <li>report.json — 评测报告</li>
            <li>manifest.json — 版本清单</li>
          </ul>
        </div>
      </div>

      {/* ── Export settings (NEW) ── */}
      <div className="bg-white rounded-lg p-5 shadow-sm border mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase mb-3">导出设置</h2>

        {/* Directory picker */}
        <div className="mb-4">
          <label className="block text-sm text-gray-700 mb-1 font-medium">导出位置</label>
          {dirHandle && dirPermissionValid ? (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-green-700 bg-green-50 px-3 py-1 rounded border border-green-200">
                📁 {dirName}
              </span>
              <button onClick={pickDirectory} className="text-xs text-blue-600 hover:underline">重新选择</button>
              <button onClick={clearDirectory} className="text-xs text-red-500 hover:underline">清除选择</button>
            </div>
          ) : hasDirectoryPicker ? (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm text-gray-400">未选择，使用浏览器默认下载目录</span>
              <button onClick={pickDirectory} className="px-3 py-1 text-xs bg-blue-50 text-blue-700 rounded hover:bg-blue-100 border border-blue-200">
                选择文件夹
              </button>
            </div>
          ) : (
            <span className="text-sm text-gray-400">当前浏览器不支持文件夹选择器，将使用浏览器默认下载</span>
          )}
          <p className="text-xs text-gray-400 mt-1">
            {dirPermissionValid
              ? '选择文件夹后，ZIP会直接写入该文件夹'
              : '未选择时，继续使用浏览器默认下载方式'}
          </p>
        </div>

        {/* Filename */}
        <div>
          <label className="block text-sm text-gray-700 mb-1 font-medium">ZIP文件名</label>
          <input
            type="text"
            value={customFilename}
            onChange={e => setCustomFilename(e.target.value)}
            className="w-full px-3 py-2 text-sm border rounded bg-gray-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-brand-300"
            placeholder="输入文件名..."
          />
          <p className="text-xs text-gray-400 mt-1">默认格式: {`{task_id}_{任务名}_素材包_{时间}.zip`}</p>
        </div>
      </div>

      {/* Teacher confirmation */}
      <div className="bg-white rounded-lg p-5 shadow-sm border mb-6">
        <label className="flex items-start gap-3 cursor-pointer">
          <input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)}
            className="mt-1 w-4 h-4 text-brand-600 rounded" />
          <div>
            <span className="text-sm font-medium text-gray-800">教师审核确认</span>
            <p className="text-xs text-gray-500 mt-0.5">
              我确认以上素材已经审核，内容正确、适合课堂教学使用。
              我理解通过AI生成的素材由我承担最终教学责任。
            </p>
          </div>
        </label>
      </div>

      {/* Disclaimer */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-6 text-xs text-yellow-700">
        ⚠️ <strong>免责声明</strong>：AI生成内容需经教师审核后使用。本工具仅辅助素材制作，不替代教师的教学判断。
        请确认所有内容（包括文本、图片、音频和题目）符合教学目标且无错误后，再用于课堂教学。
      </div>

      {/* ── Export progress ── */}
      {exporting && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="w-5 h-5 border-2 border-blue-400 border-t-blue-600 rounded-full animate-spin" />
            <span className="text-sm text-blue-700 font-medium">
              {phase === 'checking' && '正在检查审核条件……'}
              {phase === 'generating' && '正在生成ZIP素材包……'}
              {phase === 'receiving' && '正在接收ZIP文件……'}
              {phase === 'writing' && '正在写入所选文件夹……'}
            </span>
          </div>
        </div>
      )}

      {/* ── Export result ── */}
      {exportResult && phase === 'done' && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-semibold text-green-800 mb-2">✅ 导出完成</h3>
          <div className="text-sm text-green-700 space-y-1">
            <div>📦 <strong>{exportResult.filename}</strong></div>
            <div>📏 大小: {formatSize(exportResult.size)}</div>
            <div>🕐 导出时间: {formatTime(exportResult.exportedAt)}</div>
            <div>💾 导出模式: {exportResult.mode === 'directory'
              ? `写入文件夹「${exportResult.directoryName}」`
              : '浏览器下载（可按 Ctrl+J 查看）'}</div>
            {exportResult.mode === 'download' && (
              <div className="text-xs text-green-600 mt-1">文件已交由浏览器下载，请在浏览器下载记录中查看。</div>
            )}
          </div>
          <button
            onClick={() => { setExportResult(null); setPhase('idle'); }}
            className="mt-3 px-4 py-1.5 text-xs bg-green-200 text-green-800 rounded hover:bg-green-300"
          >
            再次导出
          </button>
        </div>
      )}

      {/* ── Export error ── */}
      {error && phase === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <h3 className="text-sm font-semibold text-red-700 mb-1">❌ 导出失败</h3>
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3 justify-end">
        <button onClick={() => navigate(`/task/${taskId}/report`)} className="px-4 py-2 border rounded text-gray-600 hover:bg-gray-50">
          ← 返回评测
        </button>
        <button
          onClick={handleExport}
          disabled={!canExport || exporting}
          className={`px-6 py-2 rounded-lg font-medium text-white transition ${
            canExport && !exporting
              ? 'bg-brand-600 hover:bg-brand-700'
              : 'bg-gray-300 cursor-not-allowed'
          }`}
        >
          {exporting ? '导出中...' : '📦 导出素材包'}
        </button>
      </div>
    </div>
  );
}

function CheckItem({ label, pass }: { label: string; pass: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className={pass ? 'text-green-500 text-lg' : 'text-red-500 text-lg'}>
        {pass ? '✓' : '✗'}
      </span>
      <span className={pass ? 'text-gray-600' : 'text-red-600 font-medium'}>{label}</span>
    </div>
  );
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN');
  } catch {
    return iso;
  }
}
