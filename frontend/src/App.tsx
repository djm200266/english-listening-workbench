import { useState, useEffect, useRef, createContext, useContext } from 'react';
import { Routes, Route } from 'react-router-dom';
import type { HealthResponse } from './types';
import { healthCheck } from './services/api';
import Layout from './components/Layout';
import TaskCenter from './pages/TaskCenter';
import TaskNew from './pages/TaskNew';
import ScriptReview from './pages/ScriptReview';
import MultiModalAssets from './pages/MultiModalAssets';
import EvaluationReport from './pages/EvaluationReport';
import BadCaseDetail from './pages/BadCaseDetail';
import ExportReview from './pages/ExportReview';

/* ── App context ── */

interface AppContextValue {
  health: HealthResponse | null;
}

export const AppContext = createContext<AppContextValue>({ health: null });

export function useAppContext() {
  return useContext(AppContext);
}

/* ── App ── */

const HEALTH_INTERVAL_MS = 5_000;

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkingRef = useRef(false);

  const checkHealth = async () => {
    if (checkingRef.current) return; // prevent overlapping requests
    checkingRef.current = true;
    try {
      const h = await healthCheck();
      setHealth(h);
    } catch {
      setHealth({
        status: 'error', mode: 'real',
        ollama: { available: false, model: '', model_present: false, last_error: null }, comfyui: { available: false, state: 'unavailable', base_url: '', workflow_available: false, checkpoint_available: false, generation_ready: false, checkpoint: '', last_error: null, error_code: null, owned: false, pid: null, health_endpoint: null },
        piper: { available: false, voice_a: false, voice_b: false },
        whisper: { available: false, model: '' },
        ffmpeg: { available: false },
      });
    } finally {
      checkingRef.current = false;
    }
  };

  useEffect(() => {
    checkHealth();
    timerRef.current = setInterval(checkHealth, HEALTH_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return (
    <AppContext.Provider value={{ health }}>
      <Layout>
        <Routes>
          <Route path="/" element={<TaskCenter />} />
          <Route path="/task/new" element={<TaskNew />} />
          <Route path="/task/:taskId/script" element={<ScriptReview />} />
          <Route path="/task/:taskId/assets" element={<MultiModalAssets />} />
          <Route path="/task/:taskId/report" element={<EvaluationReport />} />
          <Route path="/task/:taskId/badcase/:bcId" element={<BadCaseDetail />} />
          <Route path="/task/:taskId/export" element={<ExportReview />} />
        </Routes>
      </Layout>
    </AppContext.Provider>
  );
}
