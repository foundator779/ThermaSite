import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  const mapsApiKey = env.VITE_GOOGLE_MAPS_API_KEY || env.GOOGLE_MAPS_API_KEY || ''

  return {
    envDir: '..',
    // Only the browser-safe Maps key is injected. GOOGLE_API_KEY remains backend-only.
    define: {
      'import.meta.env.VITE_GOOGLE_MAPS_API_KEY': JSON.stringify(mapsApiKey),
    },
    plugins: [react()],
    test: { include: ['src/**/*.test.{ts,tsx}'] },
    server: { port: 5173 },
    build: { chunkSizeWarningLimit: 1100 },
  }
})
