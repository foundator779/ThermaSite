import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const sites = [
  ['phoenix-west-valley', 33.4435, -112.5870],
  ['new-albany-business-park', 40.1120, -82.7490],
  ['north-hillsboro-industrial', 45.5700, -122.9680],
  ['council-bluffs-south', 41.1980, -95.7890],
  ['loudoun-gateway', 38.9580, -77.5115],
  ['dfw-south', 32.5670, -96.7790],
  ['atlanta-factory-shoals', 33.7140, -84.6250],
  ['tahoe-reno-industrial', 39.5870, -119.4370],
]

const output = path.resolve('demo-assets/site-aerials')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
for (const [name, latitude, longitude] of sites) {
  const url = `https://www.google.com/maps/@${latitude},${longitude},16z/data=!3m1!1e3`
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await page.waitForTimeout(3500)
  await page.screenshot({ path: path.join(output, `${name}.png`) })
}
await browser.close()
