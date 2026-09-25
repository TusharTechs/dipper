import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API runs on :8000 (uv run uvicorn dipper_api.main:app). /api/* is proxied to it in dev.
export default defineConfig({
  plugins: [react()],
  // MapLibre v6 loads an ES-module worker relative to its own file; pre-bundling breaks that URL.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  // Its worker is bundled explicitly (see CaseMap.tsx) as an ES module worker.
  worker: { format: 'es' },
  server: {
    port: 3000,
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
