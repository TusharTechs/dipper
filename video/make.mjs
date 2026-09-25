// Makes the demo video end to end, on this Mac:
//   1. films the live app (capture.mjs)          4. renders the film frame by frame in headless Chrome (film.html)
//   2. voices the script with macOS speech       5. composes the music and mixes the sound (audio.py)
//   3. times every scene to its narration        6. muxes video/out/dipper-demo.mp4 and writes subtitles (.srt)
//
//   node video/make.mjs                          everything, filming https://dipper-8fe5.onrender.com
//   node video/make.mjs --reuse                  keep the last capture; redo voice, timing, picture and sound
//   node video/make.mjs --reuse --stills 12,95   render only these moments (seconds) to video/out/stills/
//   Options: --base URL, --workers N (parallel renderers, default 4), --fps N (default 30), --no-subs
import { spawn, execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import { existsSync, readFileSync } from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { SCENES, VOICE } from './story.mjs'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const puppeteer = require('puppeteer-core')
const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.dirname(HERE), OUT = path.join(HERE, 'out')
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const argv = process.argv.slice(2)
const opt = (k, d) => { const i = argv.indexOf(`--${k}`); return i < 0 ? d : argv[i + 1] }
const flag = (k) => argv.includes(`--${k}`)
const BASE = opt('base', 'https://dipper-8fe5.onrender.com').replace(/\/$/, '')
const FPS = Number(opt('fps', 30)), WORKERS = Number(opt('workers', 4))
const W = 1920, H = 1080
const log = (...a) => console.log(`[make ${new Date().toTimeString().slice(0, 8)}]`, ...a)
const run = (cmd, args, o = {}) => new Promise((ok, fail) => {
  const p = spawn(cmd, args, { stdio: 'inherit', ...o }); p.on('exit', (c) => (c === 0 ? ok() : fail(new Error(`${cmd} exited ${c}`))))
})

await fs.mkdir(OUT, { recursive: true })

// ---------- 1. capture ----------
const CAP = path.join(OUT, 'capture')
if (!flag('reuse') || !existsSync(path.join(CAP, 'capture.json'))) {
  log('filming', BASE)
  await run('node', [path.join(HERE, 'capture.mjs'), BASE, CAP])
}
const capture = JSON.parse(await fs.readFile(path.join(CAP, 'capture.json'), 'utf8'))
const reachFile = path.join(OUT, 'reach.json')
if (!flag('reuse') || !existsSync(reachFile)) {
  const r = await fetch(`${capture.base}/api/v1/reaches/coimbra-ribeira-de-coselhas`); if (!r.ok) throw new Error(`reach: ${r.status}`)
  await fs.writeFile(reachFile, await r.text())
}

// Facts the narration quotes, read off the live app during capture.
const d = capture.desk.facts, ph = capture.phone.facts
const entry = d.meta.match(/Likely entry:\s*(O-\d+)\s*\((\d+)%\)/)
if (!entry) throw new Error(`no localized entry in "${d.meta}"`)
const facts = {
  checks: ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve'][d.checks] ?? String(d.checks),
  top: entry[1], topSay: entry[1].replace('O-', 'O '), p: entry[2],
  narrowed: ph.outcome.match(/about \d+%/)?.[0] ?? 'part',
  weather: d.meta.match(/Weather:\s*(.*?)(Harmful|$)/)?.[1]?.trim() ?? '',
}
const fill = (s) => s.replace(/\{(\w+)\}/g, (_, k) => facts[k] ?? `{${k}}`)

// ---------- 2. voice ----------
const VO = path.join(OUT, 'vo'); await fs.mkdir(VO, { recursive: true })
const wavSeconds = (file) => {
  const b = readFileSync(file); let i = 12
  const fmt = { rate: 48000, bytes: 2, ch: 1 }
  while (i < b.length - 8) {
    const id = b.toString('ascii', i, i + 4), size = b.readUInt32LE(i + 4)
    if (id === 'fmt ') { fmt.ch = b.readUInt16LE(i + 10); fmt.rate = b.readUInt32LE(i + 12); fmt.bytes = b.readUInt16LE(i + 22) / 8 }
    if (id === 'data') return size / (fmt.rate * fmt.bytes * fmt.ch)
    i += 8 + size + (size % 2)
  }
  throw new Error(`${file}: no data chunk`)
}
for (const s of SCENES) {
  if (!s.vo) continue
  s.text = fill(s.vo); s.sayText = fill(s.say ?? s.vo).replace(/(\d)%/g, '$1 percent')
  const hash = createHash('sha1').update(`${VOICE.name}|${VOICE.rate}|${s.sayText}`).digest('hex').slice(0, 10)
  s.voFile = path.join(VO, `${s.id}-${hash}.wav`)
  if (!existsSync(s.voFile)) execFileSync('say', ['-v', VOICE.name, '-r', String(VOICE.rate), '--file-format=WAVE', '--data-format=LEI16@48000', '-o', s.voFile, s.sayText])
  s.voDur = wavSeconds(s.voFile)
}
log('voiced', SCENES.filter((s) => s.vo).length, 'lines')

// ---------- 3. timeline ----------
let t = 0
const scenes = []
for (const s of SCENES) {
  const live = s.kind === 'phone' || s.kind === 'desk'
  const lead = s.lead ?? (live ? 0.3 : 0.6), pad = s.pad ?? (live ? 0.5 : 0.8), xin = scenes.length ? (s.xin ?? 0.6) : 0
  const need = s.vo ? lead + s.voDur + pad : 0
  const e = { id: s.id, kind: s.kind, step: s.step, head: s.head, cam: s.cam, xin, lead, text: s.text, voDur: s.voDur ?? 0 }
  if (live) {
    const sess = capture[s.kind], beats = sess.events.filter((x) => x.kind === 'beat')
    const i = beats.findIndex((b) => b.id === s.beat); if (i < 0) throw new Error(`no beat ${s.beat}`)
    const capStart = beats[i].t, capEnd = beats[i + 1]?.t ?? sess.frames.at(-1).t, capLen = capEnd - capStart
    const speed = capLen > need ? Math.min(s.maxSpeed ?? 1.6, capLen / need) : 1
    Object.assign(e, { session: s.kind, capStart, capEnd, speed, dur: Math.max(need, capLen / speed) })
  } else e.dur = Math.max(s.min ?? 0, need)
  e.start = +(t - xin).toFixed(3); t = e.start + e.dur
  if (s.vo) e.vo = { start: +(e.start + lead).toFixed(3), dur: s.voDur, file: path.relative(OUT, s.voFile) }
  scenes.push(e)
}
const duration = +t.toFixed(3)
// Taps as film times, for the click sounds.
const taps = []
for (const e of scenes.filter((x) => x.session)) for (const ev of capture[e.session].events)
  if (ev.kind === 'tap' && ev.t >= e.capStart && ev.t < e.capEnd) taps.push(+(e.start + (ev.t - e.capStart) / e.speed).toFixed(3))
const timeline = { fps: FPS, width: W, height: H, duration, base: capture.base, facts, subs: !flag('no-subs'),
  reach: 'reach.json', capture: { phone: capture.phone, desk: capture.desk }, scenes, taps }
await fs.writeFile(path.join(OUT, 'timeline.json'), JSON.stringify(timeline))
log(`timeline: ${scenes.length} scenes, ${Math.floor(duration / 60)}:${String(Math.round(duration % 60)).padStart(2, '0')}`)
for (const e of scenes) log(`  ${e.start.toFixed(1).padStart(6)}  ${e.id.padEnd(13)} ${e.dur.toFixed(1)} s${e.speed && e.speed > 1 ? `  (capture ×${e.speed.toFixed(2)})` : ''}`)

// Subtitles, for the upload page (the picture has them burned in too).
const stamp = (x) => { const ms = Math.round(x * 1000); const p = (n, w = 2) => String(n).padStart(w, '0')
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}` }
await fs.writeFile(path.join(OUT, 'dipper-demo.srt'), scenes.filter((e) => e.vo).map((e, i) =>
  `${i + 1}\n${stamp(e.vo.start)} --> ${stamp(e.vo.start + e.vo.dur + 0.3)}\n${e.text}\n`).join('\n'))

// ---------- 4. picture ----------
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml', '.wav': 'audio/wav' }
const server = http.createServer(async (req, res) => {
  const p = path.normalize(path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname)))
  if (!p.startsWith(HERE) && !p.startsWith(path.join(ROOT, 'web', 'public'))) { res.writeHead(403); return res.end() }
  try { const body = await fs.readFile(p); res.writeHead(200, { 'content-type': TYPES[path.extname(p)] ?? 'application/octet-stream' }); res.end(body) }
  catch { res.writeHead(404); res.end() }
})
await new Promise((ok) => server.listen(0, '127.0.0.1', ok))
const FILM = `http://127.0.0.1:${server.address().port}/video/film.html?timeline=out/timeline.json`

async function renderer() {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--use-angle=metal', '--hide-scrollbars', '--font-render-hinting=none'] })
  const page = await browser.newPage()
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 })
  page.on('pageerror', (e) => log('film error:', e.message))
  page.on('console', (m) => m.type() === 'error' && log('film console:', m.text()))
  await page.goto(FILM, { waitUntil: 'networkidle0' })
  await page.waitForFunction(() => window.film?.ready === true, { timeout: 60000 })
  const cdp = await page.createCDPSession()
  const frame = async (sec, format = 'jpeg') => {
    // Wait for two animation frames after the seek, or the screenshot can catch the previous paint.
    await page.evaluate(async (x) => { await window.film.seek(x); await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))) }, sec)
    const { data } = await cdp.send('Page.captureScreenshot', { format, quality: 95, optimizeForSpeed: true })
    return Buffer.from(data, 'base64')
  }
  return { frame, close: () => browser.close() }
}

const stills = opt('stills')
if (stills) {
  const dir = path.join(OUT, 'stills'); await fs.mkdir(dir, { recursive: true })
  const r = await renderer()
  for (const x of stills.split(',').map(Number)) {
    await fs.writeFile(path.join(dir, `t${x.toFixed(1).padStart(6, '0')}.png`), await r.frame(x, 'png')); log('still', x)
  }
  await r.close(); server.close(); process.exit(0)
}

const total = Math.ceil(duration * FPS), per = Math.ceil(total / WORKERS), started = Date.now()
let rendered = 0
const progress = setInterval(() => {
  const s = (Date.now() - started) / 1000; log(`frames ${rendered}/${total} (${(rendered / s).toFixed(1)}/s, about ${Math.round((total - rendered) / Math.max(rendered / s, 0.01) / 60)} min left)`)
}, 30000)
await Promise.all([...Array(WORKERS).keys()].map(async (k) => {
  const from = k * per, to = Math.min(total, from + per)
  if (from >= to) return
  const r = await renderer()
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p', '-r', String(FPS), path.join(OUT, `part${k}.mp4`)], { stdio: ['pipe', 'inherit', 'inherit'] })
  const closed = new Promise((ok, fail) => ff.on('exit', (c) => (c === 0 ? ok() : fail(new Error(`ffmpeg part ${k} exited ${c}`)))))
  for (let i = from; i < to; i++) {
    const buf = await r.frame(i / FPS)
    if (!ff.stdin.write(buf)) await new Promise((ok) => ff.stdin.once('drain', ok))
    rendered++
  }
  ff.stdin.end(); await closed; await r.close()
}))
clearInterval(progress); server.close()
const parts = [...Array(WORKERS).keys()].map((k) => path.join(OUT, `part${k}.mp4`)).filter((p) => existsSync(p))
await fs.writeFile(path.join(OUT, 'parts.txt'), parts.map((p) => `file '${p}'`).join('\n'))
await run('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', path.join(OUT, 'parts.txt'), '-c', 'copy', path.join(OUT, 'picture.mp4')])
log(`picture done in ${((Date.now() - started) / 60000).toFixed(1)} min`)

// ---------- 5. sound ----------
await run('uv', ['run', '--offline', 'python', path.join(HERE, 'audio.py'), path.join(OUT, 'timeline.json'), path.join(OUT, 'audio.wav')], { cwd: ROOT })

// ---------- 6. mux ----------
const final = path.join(OUT, 'dipper-demo.mp4')
await run('ffmpeg', ['-y', '-loglevel', 'error', '-i', path.join(OUT, 'picture.mp4'), '-i', path.join(OUT, 'audio.wav'),
  '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', '48000', '-c:a', 'aac', '-b:a', '192k',
  '-movflags', '+faststart', '-shortest', final])
for (const p of parts) await fs.rm(p)
log('done:', path.relative(ROOT, final), `(${(Number((await fs.stat(final)).size) / 1e6).toFixed(0)} MB)`)
