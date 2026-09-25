// README screenshots. Needs a fresh demo site (DIPPER_DEMO=1, empty database) and Chrome:
//   node scripts/screenshots.mjs http://localhost:8000 ../docs/screenshots
import puppeteer from 'puppeteer-core'
const BASE = process.argv[2] ?? 'http://localhost:8000', OUT = process.argv[3] ?? '../docs/screenshots'
const chrome = process.env.CHROME_PATH ?? (process.platform === 'darwin'
  ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '/usr/bin/google-chrome')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const browser = await puppeteer.launch({ executablePath: chrome,
  headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--lang=en-GB'] })
const page = await browser.newPage()
page.on('pageerror', (e) => console.log('pageerror', e.message))
const click = (text) => page.evaluate((t) => { const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === t || x.textContent.includes(t)); if (!b) return false; b.click(); return true }, text)
const tab = (name) => page.evaluate((n) => [...document.querySelectorAll('[role=tab]')].find((t) => t.textContent.startsWith(n)).click(), name)
const shot = async (name, full = false) => { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full }); console.log('saved', name) }

// ---- operations, desktop ----
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1.5 })
await page.goto(`${BASE}/#/ops`, { waitUntil: 'networkidle0' }); await sleep(800)
await click('Continue as investigator'); await sleep(1200)
await click('dry weather'); await sleep(5000)
for (let i = 0; i < 3; i++) { await click('Run top check'); await sleep(1500) }
await sleep(2500); await shot('workspace-searching')
for (let i = 0; i < 8; i++) { const st = await page.$eval('.chip', (e) => e.textContent); if (st.includes('localized')) break; await click('Run top check'); await sleep(1500) }
await sleep(2500); await shot('workspace-localized')
await click('Hand off to utility'); await sleep(1500)
await tab('Hand-off'); await sleep(1000); await shot('handoff-fhir')
await click('Sign out'); await sleep(800)
await page.goto(`${BASE}/#/ops/C-014`, { waitUntil: 'networkidle0' }); await sleep(800)
await click('Continue as public-health officer'); await sleep(2000)
await tab('Advisory'); await sleep(800); await shot('advisory-approval', true)
await click('Approve and publish advisory'); await sleep(1500)
await page.goto(`${BASE}/#/public`, { waitUntil: 'networkidle0' }); await sleep(5000); await shot('public-advisories')
await page.goto(`${BASE}/#/bench`, { waitUntil: 'networkidle0' }); await sleep(1500); await shot('sourcebench', true)

// ---- citizen, phone ----
await page.setViewport({ width: 390, height: 844, deviceScaleFactor: 2, isMobile: true, hasTouch: true })
await page.goto(`${BASE}/#/citizen`, { waitUntil: 'networkidle0' }); await sleep(1000)
await page.select('#reach', 'coimbra-ribeira-dos-covões'); await sleep(3000)
await page.evaluate(() => { const s = document.getElementById('landmark'); const o = [...s.options].find((o) => o.text.startsWith('0.5')) ?? s.options[4]
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value); s.dispatchEvent(new Event('change', { bubbles: true })) })
await click('Grey or milky water'); await click('Sewage smell'); await sleep(2500)
await page.evaluate(() => document.querySelector('.minimap').scrollIntoView({ block: 'start' })); await sleep(500)
await shot('citizen-report')
await click('Send report'); await sleep(9000)  // let the mission map load its tiles
await page.evaluate(() => window.scrollTo(0, 0)); await sleep(500)
await shot('citizen-mission', true)
await browser.close()
