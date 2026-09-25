// Films the live app for the demo video: a citizen on a phone, then the operations room on a desktop.
// Each session saves JPEG frames with timestamps and an event log (beats, taps, element boxes, facts read off the
// screen). The film draws its own cursor and camera moves from that log, so the capture itself stays plain.
//   node video/capture.mjs https://dipper-8fe5.onrender.com video/out/capture
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(new URL('../web/package.json', import.meta.url))
const puppeteer = require('puppeteer-core')
const BASE = (process.argv[2] ?? 'https://dipper-8fe5.onrender.com').replace(/\/$/, '')
const OUT = process.argv[3] ?? 'video/out/capture'
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const REACH = 'coimbra-ribeira-de-coselhas'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function session(name, { w, h, dsf, mobile = false }) {
  const dir = path.join(OUT, name)
  await fs.rm(dir, { recursive: true, force: true }); await fs.mkdir(dir, { recursive: true })
  // Forcing the device scale on the command line is what makes headless screencast frames full resolution.
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, defaultViewport: null,
    args: ['--use-angle=metal', `--force-device-scale-factor=${dsf}`, `--window-size=${Math.max(w, 600)},${h + 200}`, '--hide-scrollbars', '--lang=en-GB'] })
  const page = (await browser.pages())[0]
  await page.setBypassCSP(true)  // the option picker below runs a small function in the page
  page.on('pageerror', (e) => console.log(`[${name}] pageerror`, e.message))
  const cdp = await page.createCDPSession()
  if (mobile) {
    // Windows cannot be narrower than 500 px, so a phone is emulated inside a larger one.
    await page.setUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')
    await page.setViewport({ width: w, height: h, deviceScaleFactor: dsf, isMobile: true, hasTouch: true })
  } else {
    // Headless windows lose some height to an invisible toolbar: resize until the page is exactly w × h.
    const { windowId } = await cdp.send('Browser.getWindowForTarget')
    for (let i = 0; i < 3; i++) {
      const [iw, ih] = await page.evaluate(() => [innerWidth, innerHeight])
      if (iw === w && ih === h) break
      const { bounds } = await cdp.send('Browser.getWindowBounds', { windowId })
      await cdp.send('Browser.setWindowBounds', { windowId, bounds: { width: bounds.width + w - iw, height: bounds.height + h - ih } })
      await sleep(300)
    }
    const [iw, ih] = await page.evaluate(() => [innerWidth, innerHeight])
    if (iw !== w || ih !== h) throw new Error(`${name}: page is ${iw}×${ih}, wanted ${w}×${h}`)
  }

  const t0 = Date.now() / 1000, frames = [], events = [], writes = []
  let n = 0
  cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
    cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {})
    const f = `${String(n++).padStart(5, '0')}.jpg`
    frames.push({ t: +(metadata.timestamp - t0).toFixed(3), f })
    writes.push(fs.writeFile(path.join(dir, f), Buffer.from(data, 'base64')))
  })
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: w * dsf, maxHeight: h * dsf })
  const ev = (kind, data = {}) => { const e = { t: +(Date.now() / 1000 - t0).toFixed(3), kind, ...data }; events.push(e); return e }

  const handle = async (target) => {
    if (typeof target !== 'string') return target
    const hd = await page.evaluateHandle((t) => (/^[.#[]/.test(t) ? document.querySelector(t) : null)
      ?? [...document.querySelectorAll('button, [role=tab], a, summary')].find((x) => x.textContent.trim() === t)
      ?? [...document.querySelectorAll('button, [role=tab], a, summary')].find((x) => x.textContent.trim().startsWith(t)), target)
    if (!(await hd.evaluate((x) => !!x))) throw new Error(`${name}: nothing matches "${target}"`)
    return hd
  }
  const rect = (hd) => hd.evaluate((x) => { const r = x.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height } })
  // Scroll smoothly (the viewer sees it) until the element is comfortably on screen.
  const reveal = async (hd, block = 'center') => {
    const r = await rect(hd)
    if (r.y >= 70 && r.y + r.h <= h - 30) return
    ev('scroll'); await hd.evaluate((x, b) => x.scrollIntoView({ behavior: 'smooth', block: b }), block); await sleep(1100)
  }
  const box = async (label, target) => {
    const hd = await handle(target); const r = await rect(hd); ev('box', { name: label, ...r }); return r
  }
  // The film moves its cursor to the element between "aim" and "tap", then shows the press.
  const tap = async (target, { travel = 750, after = 900, block } = {}) => {
    const hd = await handle(target); await reveal(hd, block)
    const r = await rect(hd), x = r.x + r.w / 2, y = r.y + r.h / 2
    ev('aim', { x, y }); await sleep(travel); ev('tap', { x, y })
    await hd.evaluate((el) => el.click()); await sleep(after)
    return hd
  }
  const choose = async (sel, pickOption) => {
    const hd = await handle(sel); await reveal(hd)
    const r = await rect(hd); ev('aim', { x: r.x + r.w / 2, y: r.y + r.h / 2 }); await sleep(750); ev('tap', { x: r.x + r.w / 2, y: r.y + r.h / 2 })
    const label = await hd.evaluate((s, pick) => {
      const o = new Function('opts', `return (${pick})(opts)`)([...s.options])
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value)
      s.dispatchEvent(new Event('change', { bubbles: true })); return o.text
    }, pickOption.toString())
    return label
  }
  const text = (sel) => page.$eval(sel, (e) => e.textContent.trim())
  const waitFor = (sel, timeout = 30000) => page.waitForSelector(sel, { timeout })
  const beat = async (id) => { console.log(`[${name}] ${id}`); return ev('beat', { id, url: await page.evaluate(() => location.pathname + location.hash) }) }
  const done = async (facts = {}) => {
    await sleep(400); await cdp.send('Page.stopScreencast'); await Promise.all(writes); await browser.close()
    return { w, h, dsf, frames, events, facts }
  }
  // What the case workspace believes right now, as shown in its left panel (percentages).
  const belief = () => page.evaluate(() => {
    const num = (x) => { const v = parseFloat(x.replace('<', '')); return Number.isFinite(v) ? v : 0 }
    const rows = (sel) => [...document.querySelectorAll(sel)].filter((li) => li.querySelector('.bar-label')).map((li) => {
      const [a, b] = li.querySelectorAll('.bar-label > span'); return [[...a.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('').replace('Outfall', '').trim(), num(b.textContent)] })
    return { hyp: rows('.panel.left ul.bars:not(.compact) li'), src: rows('.panel.left ul.bars.compact li') }
  })
  return { page, ev, tap, belief, choose, box, reveal, handle, text, waitFor, beat, done }
}

// ---------- citizen, phone ----------
async function phone() {
  const s = await session('phone', { w: 390, h: 844, dsf: 3, mobile: true })
  const { page } = s
  await page.goto(`${BASE}/#/citizen`, { waitUntil: 'networkidle0' }); await sleep(2500)
  await s.beat('p-open'); await sleep(2500)
  await s.beat('p-lang')
  await s.tap('Português', { after: 2200 }); await s.tap('English', { after: 900 })
  await s.beat('p-where')
  await s.choose('#reach', (opts) => opts.find((o) => o.value === 'coimbra-ribeira-de-coselhas') ?? opts[0]); await sleep(3000)
  const where = await s.choose('#landmark', (opts) => opts.find((o) => /^1\.[0-9]/.test(o.text)) ?? opts[Math.min(6, opts.length - 1)])
  await sleep(1600)
  await s.beat('p-signs')
  await s.tap('Grey or milky water', { after: 700 }); await s.tap('Sewage smell', { after: 1200 })
  await s.beat('p-send')
  await s.tap('Send report', { after: 400 })
  await s.waitFor('#thanks'); await sleep(1500)
  const caseId = (await s.text('#thanks')).match(/C-[\d-]*\d/)?.[0]
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await sleep(1500)
  await s.beat('p-mission')
  const mission = await s.handle('.mission'); await s.reveal(mission, 'start'); await sleep(6000)  // minimap tiles
  const missionText = await s.text('.mission-where')
  await s.beat('p-answer')
  await s.tap('Looks clean', { after: 300 })
  await s.waitFor('.outcome'); await sleep(600)
  await s.reveal(await s.handle('.outcome'), 'center'); await sleep(3800)
  const outcome = await s.text('.outcome p')
  await s.beat('p-end')
  return s.done({ where, caseId, mission: missionText, outcome })
}

// ---------- operations, desktop ----------
async function desk() {
  const s = await session('desk', { w: 1440, h: 900, dsf: 2 })
  const { page } = s
  await page.goto(`${BASE}/#/ops`, { waitUntil: 'networkidle0' }); await sleep(1500)
  await s.beat('d-signin'); await sleep(1200)
  await s.tap('Continue as investigator', { after: 2000 })
  await s.beat('d-replay')
  await s.box('demo', '.demo-box')
  await s.tap('Replay 18 Sep 2026 (dry weather)', { after: 200 })
  await s.waitFor('.case-head'); await sleep(5500)  // map tiles and the belief shading
  const caseHash = await page.evaluate(() => location.hash)
  const caseId = (await s.text('.case-head .eyebrow')).match(/C-[\d-]*\d/)?.[0]
  await s.beat('d-case')
  await s.box('head', '.case-head'); await s.box('left', '.panel.left'); await s.box('map', '.mapwrap'); await s.box('right', '.panel.right')
  await s.box('rec', '.rec.top')
  const beliefs = [await s.belief()]
  const rec = { title: await s.text('.rec.top .rec-title span:last-child'), reason: await s.text('.rec.top .reason') }
  await sleep(5200)
  await s.beat('d-search')
  let checks = 0
  for (; checks < 12; checks++) {
    if ((await s.text('.case-head .chip')).toLowerCase().includes('localized')) break
    await s.box('rec', '.rec.top')
    await s.tap('Run top check', { travel: 600, after: 2300 })
    beliefs.push({ ...(await s.belief()), result: await s.text('.ledger tbody tr:first-child td:nth-child(2)').catch(() => '') })
    if (checks === 1) await s.beat('d-search2')
  }
  await sleep(600)
  await s.beat('d-localized')
  await s.box('head', '.case-head'); await s.box('map', '.mapwrap')
  const title = await s.text('.case-head h1'), meta = await s.text('.case-head .meta')
  await sleep(4500)
  await s.beat('d-handoff')
  await s.tap('Hand off to utility', { after: 1600 })
  await s.tap('Hand-off & FHIR', { after: 2200 })
  await s.box('stats', '.stat-row')
  const stats = await s.text('.stat-row'), refs = await s.text('#panel-handoff .done').catch(() => '')
  await sleep(1800)
  const confirm = await s.handle('.confirm-card'); await s.reveal(confirm, 'center'); await s.box('confirm', '.confirm-card'); await sleep(3200)
  await s.beat('d-ph')
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' })); await sleep(900)
  await s.tap('Sign out', { after: 1000 })
  if (await page.evaluate(() => location.hash) !== caseHash) { await page.goto(`${BASE}/${caseHash}`, { waitUntil: 'networkidle0' }); await sleep(1000) }
  await s.tap('Continue as public-health officer', { after: 2400 })
  await s.tap('Advisory', { after: 1800 })
  await s.box('tiers', '.tiers'); await sleep(3800)
  await s.beat('d-approve')
  await s.tap('Approve and publish advisory', { after: 2200 })
  await s.beat('d-public')
  await page.evaluate(() => window.scrollTo({ top: 0 }))
  await page.goto(`${BASE}/#/public`, { waitUntil: 'networkidle0' }); await sleep(6500)
  await s.box('pubmap', '.public-map').catch(() => {})
  await sleep(2500)
  await s.beat('d-end')
  return s.done({ caseId, checks, title, meta, stats, refs, rec, beliefs })
}

await fs.mkdir(OUT, { recursive: true })
// Wake a sleeping free-plan instance before filming, so the first shot is not a loading screen.
for (let i = 0; i < 40; i++) { try { if ((await fetch(`${BASE}/api/ready`)).ok) break } catch {} await sleep(3000) }
const result = { base: BASE, captured: new Date().toISOString(), phone: await phone(), desk: await desk() }
await fs.writeFile(path.join(OUT, 'capture.json'), JSON.stringify(result, null, 1))
for (const k of ['phone', 'desk']) {
  const r = result[k], last = r.frames.at(-1)?.t ?? 0
  console.log(`${k}: ${r.frames.length} frames over ${last.toFixed(1)} s (${(r.frames.length / last).toFixed(1)} fps)`, JSON.stringify(r.facts))
}
