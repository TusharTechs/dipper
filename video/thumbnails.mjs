// Renders the video thumbnails from thumbnails.html, after make.mjs has made video/out/timeline.json:
//   node video/thumbnails.mjs   →   video/out/thumb-youtube.jpg (16:9) and video/out/thumb-devpost.jpg (3:2)
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const puppeteer = require('puppeteer-core')
const HERE = path.dirname(fileURLToPath(import.meta.url))
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const TYPES = { '.html': 'text/html', '.json': 'application/json', '.jpg': 'image/jpeg' }
const server = http.createServer(async (req, res) => {
  const p = path.normalize(path.join(HERE, decodeURIComponent(new URL(req.url, 'http://x').pathname)))
  if (!p.startsWith(HERE)) { res.writeHead(403); return res.end() }
  try { const body = await fs.readFile(p); res.writeHead(200, { 'content-type': TYPES[path.extname(p)] ?? 'application/octet-stream' }); res.end(body) }
  catch { res.writeHead(404); res.end() }
})
await new Promise((ok) => server.listen(0, '127.0.0.1', ok))
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ['--use-angle=metal', '--font-render-hinting=none'] })
// YouTube wants 16:9 under 2 MB; Devpost's gallery thumbnail is 3:2.
for (const [mode, w, h, scale] of [['youtube', 1280, 720, 1.5], ['devpost', 1500, 1000, 2]]) {
  const page = await browser.newPage()
  page.on('pageerror', (e) => console.log(mode, 'error:', e.message))
  await page.setViewport({ width: w, height: h, deviceScaleFactor: scale })
  await page.goto(`http://127.0.0.1:${server.address().port}/thumbnails.html?mode=${mode}`, { waitUntil: 'networkidle0' })
  await page.waitForFunction(() => window.ready, { timeout: 30000 })
  const file = path.join(HERE, 'out', `thumb-${mode}.jpg`)
  await page.screenshot({ path: file, type: 'jpeg', quality: 92, clip: { x: 0, y: 0, width: w, height: h } })
  console.log(`${path.relative(process.cwd(), file)}: ${w * scale}×${h * scale}, ${((await fs.stat(file)).size / 1e6).toFixed(2)} MB`)
}
await browser.close(); server.close()
