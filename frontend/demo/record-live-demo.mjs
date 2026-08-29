import { chromium } from '@playwright/test'
import { copyFile, mkdir, rm } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const APP_URL = process.env.THERMAGUARD_DEMO_URL || 'https://thermaguard-1060372410958.us-central1.run.app'
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const outputDirectory = path.resolve(scriptDirectory, '../../demo-assets')
const rawDirectory = path.join(outputDirectory, 'raw')
const finalVideo = path.join(outputDirectory, 'thermaguard-continuous-demo.webm')

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))

async function focus(locator) {
  await locator.scrollIntoViewIfNeeded()
  const box = await locator.boundingBox()
  if (box) {
    await locator.page().mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 })
  }
}

async function polishedClick(locator) {
  await focus(locator)
  await pause(350)
  await locator.click()
}

async function show(locator, hold = 5000) {
  await locator.scrollIntoViewIfNeeded()
  await pause(hold)
}

await mkdir(rawDirectory, { recursive: true })
await rm(finalVideo, { force: true })

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  colorScheme: 'dark',
  recordVideo: { dir: rawDirectory, size: { width: 1920, height: 1080 } },
})

await context.addInitScript(() => {
  const installCursor = () => {
    if (document.querySelector('[data-demo-cursor]')) return
    const cursor = document.createElement('div')
    cursor.dataset.demoCursor = 'true'
    Object.assign(cursor.style, {
      position: 'fixed', left: '0', top: '0', width: '18px', height: '18px',
      border: '2px solid #ff6a2a', borderRadius: '50%', background: 'rgba(255,106,42,.18)',
      boxShadow: '0 0 0 4px rgba(255,106,42,.08)', pointerEvents: 'none', zIndex: '2147483647',
      transform: 'translate(-50%, -50%)', transition: 'width 120ms ease, height 120ms ease',
    })
    document.documentElement.appendChild(cursor)
    document.addEventListener('mousemove', (event) => {
      cursor.style.left = `${event.clientX}px`
      cursor.style.top = `${event.clientY}px`
    }, { passive: true })
    document.addEventListener('mousedown', () => { cursor.style.width = '12px'; cursor.style.height = '12px' })
    document.addEventListener('mouseup', () => { cursor.style.width = '18px'; cursor.style.height = '18px' })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', installCursor)
  else installCursor()
})

const page = await context.newPage()
const video = page.video()

try {
  await page.goto(APP_URL, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await page.getByRole('heading', { name: 'Welcome back.' }).waitFor({ timeout: 30_000 })
  await pause(4000)

  await polishedClick(page.getByRole('button', { name: /Enter judge demo/ }))
  await page.getByRole('heading', { name: /Describe the facility/ }).waitFor({ timeout: 30_000 })
  await pause(4000)

  const acreage = page.getByLabel('Campus footprint, acres')
  await focus(acreage)
  await acreage.fill('60')
  await pause(2200)
  await page.getByLabel('IT design density').selectOption('2')
  await pause(1800)
  await page.getByLabel('Cooling architecture').selectOption('dry')
  await pause(1800)
  await page.getByLabel('Expected utilization, percent').fill('75')
  await pause(2400)

  await acreage.fill('40')
  await page.getByLabel('IT design density').selectOption('1.25')
  await page.getByLabel('Cooling architecture').selectOption('hybrid')
  await page.getByLabel('Expected utilization, percent').fill('85')
  await pause(3500)

  await polishedClick(page.getByRole('button', { name: 'Decisions' }))
  await page.getByRole('heading', { name: 'Previous screenings.' }).waitFor({ timeout: 30_000 })
  await pause(3500)

  const completedRun = page.locator('.history-list > button').filter({ hasText: 'COMPLETED' }).first()
  await completedRun.waitFor({ timeout: 30_000 })
  await polishedClick(completedRun)
  await page.getByRole('heading', { name: /fits best\./ }).waitFor({ timeout: 30_000 })
  await page.locator('.screening-map img').first().waitFor({ timeout: 30_000 })
  if (await page.locator('.map-fallback').count()) throw new Error('The live map fell back during recording.')
  await pause(5000)

  await show(page.locator('.workspace'), 6500)
  const secondRank = page.locator('.rank-card').nth(1)
  await polishedClick(secondRank)
  await pause(5500)
  const thirdRank = page.locator('.rank-card').nth(2)
  await polishedClick(thirdRank)
  await pause(5000)
  await polishedClick(page.locator('.rank-card').first())
  await pause(4500)

  await show(page.locator('#impact'), 8500)
  await page.locator('.impact-metrics').waitFor({ timeout: 20_000 })

  await show(page.locator('.decision-section'), 8000)

  await show(page.locator('.tuning-section'), 6000)
  const powerWeight = page.locator('.weight-editor input[type="range"]').nth(1)
  await focus(powerWeight)
  await powerWeight.fill('40')
  await pause(2000)
  await polishedClick(page.getByRole('button', { name: /Apply weights/ }))
  await page.getByRole('button', { name: /Apply weights/ }).waitFor({ state: 'visible', timeout: 30_000 })
  await pause(5500)

  await polishedClick(page.getByRole('button', { name: /Evidence & memo/ }))
  const drawer = page.getByRole('dialog', { name: 'Evidence & exports' })
  await drawer.waitFor({ timeout: 20_000 })
  await pause(6500)
  await drawer.evaluate((element) => element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' }))
  await pause(6000)
  await drawer.evaluate((element) => element.scrollTo({ top: 0, behavior: 'smooth' }))
  await pause(3500)
  await polishedClick(drawer.getByRole('button', { name: 'Close evidence' }))

  await page.getByRole('heading', { name: /fits best\./ }).scrollIntoViewIfNeeded()
  await pause(5000)
} finally {
  await context.close()
  await browser.close()
}

if (!video) throw new Error('Playwright did not initialize video capture.')
const rawVideo = await video.path()
await copyFile(rawVideo, finalVideo)
process.stdout.write(`${finalVideo}\n`)
