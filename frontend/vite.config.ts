import { defineConfig, loadEnv, type ProxyOptions } from 'vite';
import react from '@vitejs/plugin-react';

// The browser always talks to the API under /api. In dev (and `vite preview`) this proxy
// forwards /api/* to the FastAPI backend and strips the prefix; in docker nginx does the same.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_API_TARGET || 'http://localhost:8000';
  const proxy: Record<string, ProxyOptions> = {
    '/api': {
      target,
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, '') || '/',
    },
  };
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { port: 4173, proxy },
    // The only chunks above the default 500 kB are mermaid's own lazy chunks (cytoscape, ELK layout),
    // fetched on demand by the /about page — the main bundle stays small.
    build: { sourcemap: false, chunkSizeWarningLimit: 1500 },
  };
});
