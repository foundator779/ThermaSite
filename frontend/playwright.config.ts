import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
  ],
  outputDir: 'test-results',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:15173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  webServer: [
    {
      command: process.env.E2E_LIVE_RESEARCH ? 'npm run dev:e2e:api:live' : 'npm run dev:e2e:api',
      url: 'http://127.0.0.1:18000/api/v1/healthz',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev:e2e:web',
      url: 'http://127.0.0.1:15173',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
