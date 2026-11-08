import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The browser always calls relative `/api/...`; Vite proxies it to the backend,
// so the backend does not need CORS. VITE_API_URL is read from the repo-root .env.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, '..'), '')
  const apiUrl = process.env.VITE_API_URL ?? env.VITE_API_URL ?? 'http://localhost:8000'

  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
    server: {
      host: true,
      port: 5173,
      proxy: { '/api': { target: apiUrl, changeOrigin: true } },
    },
  }
})
