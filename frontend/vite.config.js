import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build straight into the FastAPI package so `autopilot web` serves the SPA.
// In dev, proxy /api to the backend on :8000.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../job_hunt/web/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
