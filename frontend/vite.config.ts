import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/playfast': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/playbest': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/playstable': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/playoptimized': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
