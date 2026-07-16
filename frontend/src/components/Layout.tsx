import { ReactNode, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAppContext } from '../App';

export default function Layout({ children }: { children: ReactNode }) {
  const { health } = useAppContext();
  const loc = useLocation();
  const isActive = (path: string) => loc.pathname === path;
  const backendOnline = health?.status === 'ok';

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
      <header className="bg-brand-600 text-white px-6 py-3 flex items-center justify-between shadow">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-lg font-bold tracking-wide">
            英语听说课工作台
          </Link>
          <nav className="hidden md:flex gap-3 text-sm">
            <Link to="/" className={`px-2 py-1 rounded ${isActive('/') ? 'bg-brand-700' : 'hover:bg-brand-500'}`}>
              任务中心
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="px-3 py-1 rounded-full font-medium bg-green-400 text-green-900 select-none">
            🔌 Real 模式
          </span>
          <ServiceTag
            label="后端"
            state={backendOnline ? 'on' : 'off'}
            tooltip={backendOnline ? '后端在线' : '后端离线 — 请运行 start-real.ps1'}
          />
          <ServiceTag
            label="Ollama"
            state={!backendOnline ? 'unknown' : (health?.ollama?.available ? 'on' : 'off')}
            tooltip={!backendOnline ? '后端离线，状态未知'
              : health?.ollama?.model_present ? 'Ollama 在线，模型就绪'
              : health?.ollama?.available ? 'Ollama 在线，模型缺失'
              : 'Ollama 离线'}
          />
          <PiperTag backendOnline={backendOnline} health={health} />
          <ServiceTag
            label="Whisper"
            state={!backendOnline ? 'unknown' : (health?.whisper?.available ? 'on' : 'off')}
            tooltip={!backendOnline ? '后端离线，状态未知' : (health?.whisper?.available ? 'Whisper 就绪' : 'Whisper 不可用')}
          />
          <ComfyUITag backendOnline={backendOnline} health={health} />
        </div>
      </header>

      <main className="flex-1 p-6 max-w-7xl mx-auto w-full">
        {children}
      </main>

      <footer className="text-center text-xs text-gray-400 py-3 border-t">
        AI生成内容需经教师审核后使用 · V0.1 MVP
      </footer>
    </div>
  );
}

/* ── Piper Status Tag ── */

function PiperTag({ backendOnline, health }: { backendOnline: boolean; health: any }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const piper = health?.piper;

  if (!backendOnline) {
    return <ServiceTag label="Piper" state="unknown" tooltip="后端离线，状态未知" />;
  }

  const status: string = piper?.status || 'stopped';
  const stateMap: Record<string, 'on' | 'off' | 'starting' | 'degraded' | 'failed'> = {
    ready: 'on',
    degraded: 'degraded',
    stopped: 'off',
    failed: 'failed',
    starting: 'starting',
  };
  const state = stateMap[status] || 'off';

  const buildTooltip = () => {
    const lines: string[] = [];
    lines.push(`状态: ${statusLabel(status)}`);
    if (piper?.executable_available !== undefined) {
      lines.push(`可执行文件: ${piper.executable_available ? '✓' : '✗'} ${piper.executable_path || ''}`);
    }
    if (piper?.voice_a !== undefined) {
      lines.push(`Voice A (lessac): ${piper.voice_a ? '✓' : '✗'}`);
    }
    if (piper?.voice_b !== undefined) {
      lines.push(`Voice B (ryan): ${piper.voice_b ? '✓' : '✗'}`);
    }
    if (piper?.test_synthesis !== undefined) {
      lines.push(`测试合成: ${piper.test_synthesis ? '✓' : '✗'}`);
    }
    if (piper?.missing_voices?.length > 0) {
      lines.push(`缺失音色: ${piper.missing_voices.join(', ')}`);
    }
    if (piper?.last_error) {
      lines.push(`错误: ${piper.last_error}`);
    }
    if (status !== 'ready') {
      lines.push('');
      lines.push('💡 点击运行修复脚本:');
      lines.push('  bash deploy/cloudstudio/repair-ai-services.sh');
    }
    return lines.join('\n');
  };

  return (
    <div className="relative" onMouseEnter={() => setShowTooltip(true)} onMouseLeave={() => setShowTooltip(false)}>
      <span
        className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs cursor-pointer ${
          state === 'on' ? 'bg-green-500 text-white' :
          state === 'degraded' ? 'bg-orange-400 text-white' :
          state === 'starting' ? 'bg-yellow-400 text-yellow-900 animate-pulse' :
          state === 'failed' ? 'bg-red-600 text-white' :
          'bg-red-400 text-white'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${
          state === 'on' ? 'bg-white' :
          state === 'degraded' ? 'bg-orange-200' :
          state === 'off' || state === 'failed' ? 'bg-red-200' :
          'bg-gray-400'
        }`} />
        Piper
      </span>
      {showTooltip && (
        <div className="absolute top-full right-0 mt-1 z-50 w-80 p-3 bg-gray-900 text-white text-xs rounded-lg shadow-xl whitespace-pre-line leading-relaxed">
          {buildTooltip()}
        </div>
      )}
    </div>
  );
}

/* ── ComfyUI Status Tag ── */

function ComfyUITag({ backendOnline, health }: { backendOnline: boolean; health: any }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const comfyui = health?.comfyui;

  if (!backendOnline) {
    return <ServiceTag label="ComfyUI" state="unknown" tooltip="后端离线，状态未知" />;
  }

  // Prefer 'status' field (new API), fall back to 'state' (legacy)
  const status: string = comfyui?.status || comfyui?.state || 'stopped';
  const stateMap: Record<string, 'on' | 'off' | 'starting' | 'degraded' | 'failed'> = {
    ready: 'on',
    degraded: 'degraded',
    stopped: 'off',
    failed: 'failed',
    starting: 'starting',
  };
  const state = stateMap[status] || 'off';

  const buildTooltip = () => {
    const lines: string[] = [];
    lines.push(`状态: ${statusLabel(status)}`);
    if (comfyui?.api_available !== undefined) {
      lines.push(`API: ${comfyui.api_available ? '可达 ✓' : '不可达 ✗'}`);
    }
    if (comfyui?.pid) {
      lines.push(`PID: ${comfyui.pid}`);
    }
    if (comfyui?.checkpoint) {
      lines.push(`模型: ${comfyui.checkpoint} ${comfyui.checkpoint_available ? '✓' : '✗'}`);
    }
    if (comfyui?.workflow_available !== undefined) {
      lines.push(`Workflow: ${comfyui.workflow_available ? '✓' : '✗'}`);
    }
    if (comfyui?.generation_ready !== undefined) {
      lines.push(`可生成: ${comfyui.generation_ready ? '✓' : '✗'}`);
    }
    if (comfyui?.missing_models?.length > 0) {
      lines.push(`缺失模型: ${comfyui.missing_models.join(', ')}`);
    }
    if (comfyui?.missing_nodes?.length > 0) {
      lines.push(`缺失节点: ${comfyui.missing_nodes.join(', ')}`);
    }
    if (comfyui?.last_error) {
      lines.push(`错误: ${comfyui.last_error}`);
    }
    if (status !== 'ready') {
      lines.push('');
      lines.push('💡 点击运行修复脚本:');
      lines.push('  bash deploy/cloudstudio/repair-ai-services.sh');
    }
    return lines.join('\n');
  };

  return (
    <div className="relative" onMouseEnter={() => setShowTooltip(true)} onMouseLeave={() => setShowTooltip(false)}>
      <span
        className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs cursor-pointer ${
          state === 'on' ? 'bg-green-500 text-white' :
          state === 'degraded' ? 'bg-orange-400 text-white' :
          state === 'starting' ? 'bg-yellow-400 text-yellow-900 animate-pulse' :
          state === 'failed' ? 'bg-red-600 text-white' :
          'bg-red-400 text-white'
        }`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${
          state === 'on' ? 'bg-white' :
          state === 'degraded' ? 'bg-orange-200' :
          state === 'off' || state === 'failed' ? 'bg-red-200' :
          'bg-gray-400'
        }`} />
        ComfyUI
      </span>
      {showTooltip && (
        <div className="absolute top-full right-0 mt-1 z-50 w-80 p-3 bg-gray-900 text-white text-xs rounded-lg shadow-xl whitespace-pre-line leading-relaxed">
          {buildTooltip()}
        </div>
      )}
    </div>
  );
}

/* ── Status label helper ── */

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    ready: '就绪 ✓',
    degraded: '部分可用',
    stopped: '未运行',
    failed: '失败',
    starting: '启动中...',
  };
  return map[status] || status;
}

/* ── Generic Service Tag ── */

function ServiceTag({ label, state, tooltip }: {
  label: string;
  state: 'on' | 'off' | 'unknown' | 'starting' | 'degraded' | 'failed';
  tooltip: string;
}) {
  const colors: Record<string, string> = {
    on: 'bg-green-500 text-white',
    off: 'bg-red-400 text-white',
    unknown: 'bg-gray-300 text-gray-500',
    starting: 'bg-yellow-400 text-yellow-900 animate-pulse',
    degraded: 'bg-orange-400 text-white',
    failed: 'bg-red-600 text-white',
  };
  return (
    <span
      className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-xs ${colors[state]}`}
      title={tooltip}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${
        state === 'on' ? 'bg-white' :
        state === 'off' || state === 'failed' ? 'bg-red-200' :
        state === 'degraded' ? 'bg-orange-200' :
        'bg-gray-400'
      }`} />
      {label}
    </span>
  );
}
