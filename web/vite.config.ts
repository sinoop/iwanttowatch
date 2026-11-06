import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// During development the API runs separately (`uv run cinematch serve`) on port 8080.
const api = process.env.CINEMATCH_API_URL ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { '/api': api, '/healthz': api },
  },
})
