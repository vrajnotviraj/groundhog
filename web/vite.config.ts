import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  // keep the browser's Host so the API's same-origin check sees the dev server as the origin
  server: { proxy: { '/api': { target: 'http://localhost:8000' } } },
  test: { environment: 'jsdom', globals: true, setupFiles: './src/test-setup.ts', css: { modules: { classNameStrategy: 'non-scoped' } } },
})
