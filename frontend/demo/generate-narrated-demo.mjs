import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { access, mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const require = createRequire(import.meta.url)
const ffmpegPath = require('ffmpeg-static')
const ffprobePath = require('ffprobe-static').path
const scriptDirectory = path.dirname(fileURLToPath(import.meta.url))
const workspace = path.resolve(scriptDirectory, '../..')
const inputVideo = path.join(workspace, 'demo-assets/thermasite-continuous-demo.webm')
const outputDirectory = path.join(workspace, 'demo-assets/narration')
const narrationTrack = path.join(outputDirectory, 'thermasite-narration.wav')
const finalVideo = path.join(workspace, 'demo-assets/thermasite-final-demo-narrated.mp4')
const timingFile = path.join(outputDirectory, 'timing-report.json')
let videoDuration = 132

const voice = {
  id: 'hpp4J3VqNfWAUOO0d1Us',
  name: 'Bella - Professional, Bright, Warm',
  model: 'eleven_multilingual_v2',
}

const segments = [
  { start: 0.5, end: 4.5, text: 'Where should your next AI data center actually go?' },
  { start: 5.0, end: 21.0, text: 'Set acreage, density, cooling, and utilization. A sixty-acre dense concept reaches one hundred twenty megawatts. Reset to forty acres at one point two five megawatts per acre for the saved fifty-megawatt profile.' },
  { start: 22.0, end: 31.0, text: 'Every screening, source, estimate, and rescore is saved in the judge workspace.' },
  { start: 32.0, end: 47.0, text: 'The agent pre-screens eight sourced industrial markets, submits equal forty-acre footprints to FortyGuard, and keeps five complete finalists.' },
  { start: 47.5, end: 64.0, text: "Each overlay shows the same facility on an industrial-edge search zone. The concepts sit on open land, not city centers, and never claim that a parcel is available or buildable." },
  { start: 65.0, end: 82.0, text: 'FortyGuard measures ambient heat. Transparent PUE and WUE assumptions turn that evidence into comparable power, water, and July operating-cost scenarios for the exact same facility.' },
  { start: 83.0, end: 95.0, text: 'The investment case is measurable: cost advantage, energy avoided, direct water avoided, and recommendation durability across five buyer strategies.' },
  { start: 96.0, end: 107.0, text: 'Every factor stays visible. Change the investment weights, and ThermaSite rescores stored evidence without another paid provider call.' },
  { start: 108.0, end: 121.0, text: 'The recommendation and operating advantage update together. Here, emphasizing thermal resilience moves Hillsboro to first and exposes a more sensitive decision.' },
  { start: 122.0, end: 137.0, text: 'An independent audit reproduces the ranking, projections, and impact claims. Judges can inspect official sources, FortyGuard activity IDs, and download the memo and evidence bundle.' },
  { start: 137.5, end: 142.3, text: 'ThermaSite finds the five places worth investigating next.' },
]

const regenerateSegments = new Set(
  (process.env.REGENERATE_SEGMENTS || '')
    .split(',')
    .map((value) => Number(value.trim()))
    .filter(Number.isInteger),
)

async function fileExists(file) {
  try {
    await access(file)
    return true
  } catch {
    return false
  }
}

function loadEnv(source) {
  return Object.fromEntries(source.split(/\r?\n/).flatMap((line) => {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/)
    if (!match || match[1].startsWith('#')) return []
    return [[match[1], match[2].replace(/^(['"])(.*)\1$/, '$2')]]
  }))
}

function run(binary, args) {
  const result = spawnSync(binary, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  if (result.status !== 0) throw new Error(result.stderr || `${binary} exited with ${result.status}`)
  return result.stdout
}

function duration(file) {
  return Number(run(ffprobePath, [
    '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', file,
  ]).trim())
}

videoDuration = duration(inputVideo)

await mkdir(outputDirectory, { recursive: true })
const env = loadEnv(await readFile(path.join(workspace, '.env'), 'utf8'))
const apiKey = env.ELEVEN_LAB || env.ELEVENLABS_API_KEY
if (!apiKey) throw new Error('ELEVEN_LAB or ELEVENLABS_API_KEY is required in .env')

const report = []
for (const [index, segment] of segments.entries()) {
  const file = path.join(outputDirectory, `segment-${String(index + 1).padStart(2, '0')}.mp3`)
  const segmentNumber = index + 1
  if (regenerateSegments.has(segmentNumber) || !(await fileExists(file))) {
    const response = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voice.id}?output_format=mp3_44100_128`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'xi-api-key': apiKey },
      body: JSON.stringify({
        text: segment.text,
        model_id: voice.model,
        voice_settings: {
          stability: 0.46,
          similarity_boost: 0.8,
          style: 0.18,
          use_speaker_boost: true,
          speed: 1.03,
        },
      }),
    })
    if (!response.ok) {
      const detail = await response.text()
      throw new Error(`ElevenLabs segment ${segmentNumber} failed (${response.status}): ${detail.slice(0, 500)}`)
    }
    await writeFile(file, Buffer.from(await response.arrayBuffer()))
  }
  const originalDuration = duration(file)
  const slotDuration = segment.end - segment.start
  const tempo = originalDuration > slotDuration ? Math.min(2, originalDuration / slotDuration) : 1
  report.push({ ...segment, file, original_duration: originalDuration, slot_duration: slotDuration, tempo })
}

const mixInputs = report.flatMap((item) => ['-i', item.file])
const filters = report.map((item, index) => {
  const delay = Math.round(item.start * 1000)
  return `[${index}:a]aresample=48000,atempo=${item.tempo.toFixed(6)},volume=1,adelay=${delay}:all=1[s${index}]`
})
filters.push(`${report.map((_, index) => `[s${index}]`).join('')}amix=inputs=${report.length}:duration=longest:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=8,apad,atrim=duration=${videoDuration}[aout]`)
run(ffmpegPath, [
  '-y', ...mixInputs,
  '-filter_complex', filters.join(';'),
  '-map', '[aout]', '-c:a', 'pcm_s16le', narrationTrack,
])

run(ffmpegPath, [
  '-y', '-i', inputVideo, '-i', narrationTrack,
  '-map', '0:v:0', '-map', '1:a:0',
  '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
  '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
  '-movflags', '+faststart', '-t', String(videoDuration), finalVideo,
])

await writeFile(timingFile, JSON.stringify({ voice, video_duration: videoDuration, segments: report }, null, 2))
process.stdout.write(`${finalVideo}\n`)
