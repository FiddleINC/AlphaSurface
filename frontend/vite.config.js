import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const proxy = {
  '/ws': {
    target: 'ws://localhost:8000',
    ws: true,
  },
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react()],
  // host: true lets a tablet on the same network open the dev server.
  server: { host: true, proxy },
  preview: { host: true, proxy },
})
