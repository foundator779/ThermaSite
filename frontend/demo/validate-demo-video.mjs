import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { pathToFileURL, fileURLToPath } from 'node:url'
import path from 'node:path'

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const assetDirectory = path.resolve(scriptDirectory, '../../demo-assets')
const videoPath = path.join(assetDirectory, 'thermasite-continuous-demo.webm')
const frameDirectory = path.join(assetDirectory, 'qa-frames')
await mkdir(frameDirectory, { recursive: true })

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
await page.goto(pathToFileURL(videoPath).href, { waitUntil: 'domcontentloaded' })
await page.addStyleTag({ content: '*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:#090909;overflow:hidden}video{width:100%;height:100%;object-fit:contain}' })
const videoElement = page.locator('video')

const metadata = await videoElement.evaluate((video) => new Promise((resolve, reject) => {
  const ready = () => resolve({ duration: video.duration, width: video.videoWidth, height: video.videoHeight })
  if (video.readyState >= 1) return ready()
  video.addEventListener('loadedmetadata', ready, { once: true })
  video.addEventListener('error', () => reject(new Error('The recorded WebM could not be decoded.')), { once: true })
}))

for (const [index, fraction] of [0.04, 0.34, 0.50, 0.66, 0.93].entries()) {
  await videoElement.evaluate((video, time) => new Promise((resolve) => {
    video.addEventListener('seeked', resolve, { once: true })
    video.currentTime = time
  }), metadata.duration * fraction)
  await page.screenshot({ path: path.join(frameDirectory, `frame-${index + 1}.png`) })
}

await browser.close()
process.stdout.write(JSON.stringify(metadata))
