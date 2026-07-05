import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  envPrefix: ['VITE_', 'SUPABASE_'],
  server: {
    port: 5173,
    // Proxy all /api traffic to the FastAPI backend in dev.
    // In production, configure your reverse proxy (nginx, etc.) instead.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    },
  },
})
