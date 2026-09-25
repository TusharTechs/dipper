// Renders the Devpost image gallery (3:2, 1800 × 1200 JPEG) from the film and the live capture, after make.mjs:
//   node video/gallery.mjs   →   video/out/gallery/01-….jpg
// Film stills are rendered without subtitles; app screens are full-resolution frames of the live capture.
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const puppeteer = require('puppeteer-core')
const HERE = path.dirname(fileURLToPath(import.meta.url)), ROOT = path.dirname(HERE), OUT = path.join(HERE, 'out', 'gallery')
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const TL = JSON.parse(await fs.readFile(path.join(HERE, 'out', 'timeline.json'), 'utf8'))
await fs.rm(OUT, { recursive: true, force: true }); await fs.mkdir(path.join(OUT, 'src'), { recursive: true })

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml' }
const server = http.createServer(async (req, res) => {
  const p = path.normalize(path.join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname)))
  if (!p.startsWith(HERE) && !p.startsWith(path.join(ROOT, 'web', 'public'))) { res.writeHead(403); return res.end() }
  try { const body = await fs.readFile(p); res.writeHead(200, { 'content-type': TYPES[path.extname(p)] ?? 'application/octet-stream' }); res.end(body) }
  catch { res.writeHead(404); res.end() }
})
await new Promise((ok) => server.listen(0, '127.0.0.1', ok))
const BASE = `http://127.0.0.1:${server.address().port}/video`

const scene = (id) => TL.scenes.find((s) => s.id === id)
const beat = (sess, id) => TL.capture[sess].events.find((e) => e.kind === 'beat' && e.id === id).t
const frame = (sess, t) => `out/capture/${sess}/${TL.capture[sess].frames.filter((f) => f.t <= t).at(-1).f}`
const film = (id, dt) => ({ kind: 'film', t: scene(id).start + dt, id })

const ITEMS = [
  { name: '02-the-problem', ...film('haystack', 10.5), eyebrow: 'The problem', title: 'Which pipe is polluting the stream?' },
  { name: '03-the-loss', ...film('void', 6.2), eyebrow: 'The problem', title: 'The people who notice first never hear back' },
  { name: '04-citizen', kind: 'phones', eyebrow: 'Citizen app · live', title: 'Report in a minute, then help narrow it down',
    shots: [[frame('phone', beat('phone', 'p-send') - 0.1), 'Report what you see'], [frame('phone', beat('phone', 'p-answer') - 0.3), 'Get a nearby check'], [frame('phone', beat('phone', 'p-end') - 0.1), 'See what it changed']] },
  { name: '05-belief', ...film('how-belief', 9.5), eyebrow: 'How it works', title: 'One belief over what the pollution is, and where' },
  { name: '06-next-check', ...film('how-check', 9.0), eyebrow: 'How it works', title: 'The next best check, by value of information' },
  { name: '07-workspace', kind: 'desk', src: frame('desk', beat('desk', 'd-search') - 0.2), bar: 'Dipper · Case C-014', eyebrow: 'Investigator · live', title: 'Probability along the real stream, next checks beside it' },
  { name: '08-localized', kind: 'desk', src: frame('desk', beat('desk', 'd-handoff') - 0.2), bar: 'Dipper · Case C-014', eyebrow: 'Investigator · live', title: `Source localized: outfall ${TL.facts.top} at ${TL.facts.p}%` },
  { name: '09-fhir', kind: 'desk', src: frame('desk', beat('desk', 'd-handoff') + 5.2), bar: 'Dipper · Case C-014', eyebrow: 'Handover · live', title: 'A validated FHIR R4 bundle for the utility' },
  { name: '10-advisory', kind: 'desk', src: frame('desk', beat('desk', 'd-approve') - 0.3), bar: 'Dipper · Case C-014', eyebrow: 'Public health · live', title: 'A person approves every public advisory' },
  { name: '11-public-map', kind: 'desk', src: frame('desk', beat('desk', 'd-end') - 0.1), bar: 'Dipper · Public advisories', eyebrow: 'The public · live', title: 'Advisories on a public map, in two languages' },
  { name: '12-sourcebench', ...film('bench', 9.5), eyebrow: 'Results · simulation', title: 'Twice the success of walking the bank' },
  { name: '13-loop', ...film('loop', 8.1), eyebrow: 'End to end', title: 'From a walker’s report to a verified fix' },
  { name: '14-adoption', ...film('pillars', 8.95), eyebrow: 'Built to be adopted', title: 'Open data, open standards, private by design' },
]

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--use-angle=metal', '--font-render-hinting=none'] })
// film stills, without subtitles
const fp = await browser.newPage(); await fp.setViewport({ width: 1920, height: 1080 })
fp.on('pageerror', (e) => console.log('film error:', e.message))
await fp.goto(`${BASE}/film.html?timeline=out/timeline.json&subs=0`, { waitUntil: 'networkidle0' })
await fp.waitForFunction(() => window.film?.ready === true, { timeout: 60000 })
for (const it of ITEMS.filter((x) => x.kind === 'film')) {
  await fp.evaluate(async (t) => { await window.film.seek(t); await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))) }, it.t)
  await fp.screenshot({ path: path.join(OUT, 'src', `${it.name}.png`) }); it.src = `out/gallery/src/${it.name}.png`
}
// compose each 3:2 image
const page = await browser.newPage(); await page.setViewport({ width: 1800, height: 1200 })
page.on('pageerror', (e) => console.log('gallery error:', e.message))
for (const it of ITEMS) {
  await page.goto(`${BASE}/gallery.html?item=${encodeURIComponent(JSON.stringify(it))}`, { waitUntil: 'networkidle0' })
  await page.waitForFunction(() => window.ready, { timeout: 30000 })
  await page.screenshot({ path: path.join(OUT, `${it.name}.jpg`), type: 'jpeg', quality: 90 })
  console.log(it.name)
}
await fs.copyFile(path.join(HERE, 'out', 'thumb-devpost.jpg'), path.join(OUT, '01-cover.jpg'))
await fs.rm(path.join(OUT, 'src'), { recursive: true })
await browser.close(); server.close()
