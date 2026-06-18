import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/notifications/ws': {
        target: 'ws://localhost:8770',
        ws: true,
      },
      '/api': 'http://localhost:8770',
      '/ws': {
        target: 'ws://localhost:8770',
        ws: true,
      },
      '/screenshots': 'http://localhost:8770',
    },
  },
})
