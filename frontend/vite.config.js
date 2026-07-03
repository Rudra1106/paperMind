import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy all /api traffic to the FastAPI backend in dev.
    // In production, configure your reverse proxy (nginx, etc.) instead.
    proxy: {
      '/upload-paper': 'http://127.0.0.1:8000',
      '/job-status':   'http://127.0.0.1:8000',
      '/roadmap':      'http://127.0.0.1:8000',
      '/chat':         'http://127.0.0.1:8000',
      '/concept':      'http://127.0.0.1:8000',
      '/knowledge-graph': 'http://127.0.0.1:8000',
      '/health':       'http://127.0.0.1:8000',
    },
  },
})
