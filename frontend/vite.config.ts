import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // Production: absolute paths from root (served by FastAPI).
  // Dev: Vite dev server on port 5173.
  base: '/',
  define: {
    __API_BASE_URL__: JSON.stringify(mode === 'production' ? '' : 'http://127.0.0.1:8000'),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/storage': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}));
