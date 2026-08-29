import { chromium } from '@playwright/test'

const appUrl = process.env.THERMAGUARD_DEMO_URL || 'https://thermaguard-1060372410958.us-central1.run.app'
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

try {
  await page.goto(appUrl, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  const runtimeConfig = await page.evaluate(() => fetch('/runtime-config.js').then((response) => response.text()))
  if (/api.?key|secret|token|AIza[0-9A-Za-z_-]{20,}/i.test(runtimeConfig)) {
    throw new Error('The production browser runtime configuration contains a credential-like value.')
  }
  await page.getByRole('button', { name: /Enter judge demo/ }).click()
  await page.getByRole('heading', { name: /Describe the facility/ }).waitFor({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Decisions' }).click()
  const completed = page.locator('.history-list > button').filter({ hasText: 'COMPLETED' }).first()
  await completed.waitFor({ timeout: 30_000 })
  await completed.click()
  await page.getByRole('heading', { name: /fits best\./ }).waitFor({ timeout: 30_000 })
  await page.locator('.leaflet-tile-loaded').first().waitFor({ timeout: 30_000 })
  await page.getByText(/USGS The National Map/).waitFor({ timeout: 30_000 })
  if (await page.locator('script[src*="maps.googleapis.com"]').count()) {
    throw new Error('The production page loaded a browser-keyed Google Maps script.')
  }
  process.stdout.write('LIVE_DEMO_OK keyless-runtime usgs-aerial persisted-screening\n')
} finally {
  await browser.close()
}
