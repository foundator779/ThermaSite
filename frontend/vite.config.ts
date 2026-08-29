import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  envDir: '..',
  plugins: [react()],
  test: { include: ['src/**/*.test.{ts,tsx}'] },
  server: { port: 5173 },
  build: { chunkSizeWarningLimit: 1100 },
})
