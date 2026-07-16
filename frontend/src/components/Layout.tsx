import { ReactNode } from 'react';
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
          <ServiceTag
            label="Piper"
            state={!backendOnline ? 'unknown' : (health?.piper?.available ? 'on' : 'off')}
            tooltip={!backendOnline ? '后端离线，状态未知' : (health?.piper?.available ? 'Piper 音色就绪' : 'Piper 不可用')}
          />
          <ServiceTag
            label="Whisper"
            state={!backendOnline ? 'unknown' : (health?.whisper?.available ? 'on' : 'off')}
            tooltip={!backendOnline ? '后端离线，状态未知' : (health?.whisper?.available ? 'Whisper 就绪' : 'Whisper 不可用')}
          />
          <ServiceTag
            label="ComfyUI"
            state={!backendOnline ? 'unknown'
              : health?.comfyui?.state === 'starting' ? 'starting'
              : health?.comfyui?.state === 'ready' ? 'on'
              : health?.comfyui?.state === 'degraded' ? 'degraded'
              : health?.comfyui?.state === 'failed' ? 'failed'
              : health?.comfyui?.available ? 'starting'
              : 'off'}
            tooltip={!backendOnline ? '后端离线，状态未知'
              : health?.comfyui?.state === 'starting' ? 'ComfyUI 正在启动中...请耐心等待'
              : health?.comfyui?.state === 'ready' ? 'ComfyUI 就绪，可生成图片'
              : health?.comfyui?.state === 'degraded' ? (
                !health?.comfyui?.checkpoint_available ? 'ComfyUI 在线但模型缺失' :
                !health?.comfyui?.workflow_available ? 'ComfyUI 在线但工作流缺失' :
                'ComfyUI 在线但部分就绪')
              : health?.comfyui?.state === 'failed' ? `ComfyUI 启动失败: ${health?.comfyui?.last_error || '未知错误'}`
              : health?.comfyui?.available ? 'ComfyUI 在线但未完全就绪'
              : `ComfyUI 离线 — 点击生成图片按钮将自动启动${health?.comfyui?.last_error ? ': ' + health.comfyui.last_error : ''}`}
          />
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

function ServiceTag({ label, state, tooltip }: { label: string; state: 'on' | 'off' | 'unknown' | 'starting' | 'degraded' | 'failed'; tooltip: string }) {
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
