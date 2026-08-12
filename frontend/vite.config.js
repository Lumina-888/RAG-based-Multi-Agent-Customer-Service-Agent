import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// SP-FE 开发期：Vite dev server 代理 /api/v1 → 后端 8000（生产由 FastAPI 托管 dist）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
