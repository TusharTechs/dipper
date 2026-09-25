// Accessibility audit: axe-core (WCAG 2.2 AA + best practice) on every screen and case tab, at desktop and
// phone widths, plus a horizontal-overflow check. Needs a running demo site (DIPPER_DEMO=1) and Chrome.
//   node scripts/a11y.mjs http://localhost:8000
// CHROME_PATH overrides the browser location. Exits 1 on any violation.
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import puppeteer from 'puppeteer-core'

const BASE = process.argv[2] ?? 'http://localhost:8000'
const axeSource = readFileSync(createRequire(import.meta.url).resolve('axe-core/axe.min.js'), 'utf8')
const chrome = process.env.CHROME_PATH ?? (process.platform === 'darwin'
  ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '/usr/bin/google-chrome')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const browser = await puppeteer.launch({ executablePath: chrome, headless: true,
  args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] })
const page = await browser.newPage()
await page.setBypassCSP(true) // the site's CSP (correctly) blocks injected scripts; allow axe for the audit only
const click = (t) => page.evaluate((t) => { const b = [...document.querySelectorAll('button')].find((e) => e.textContent.includes(t)); b?.click(); return !!b }, t)
const tab = (n) => page.evaluate((n) => [...document.querySelectorAll('[role=tab]')].find((t) => t.textContent.startsWith(n))?.click(), n)
let failures = 0
async function audit(label) {
  await page.evaluate(axeSource)
  const violations = await page.evaluate(async () => (await window.axe.run(document, {
    runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'] })).violations
    .map((v) => `${v.id} (${v.nodes.length}): ${v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(', ')}`))
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  if (overflow > 1) violations.push(`horizontal scroll: ${overflow}px`)
  failures += violations.length
  console.log(`${violations.length ? 'FAIL' : 'ok  '} ${label}${violations.length ? '\n     ' + violations.join('\n     ') : ''}`)
}

for (const [width, height, name] of [[1440, 900, 'desktop'], [375, 812, 'phone'], [320, 640, 'small phone']]) {
  await page.setViewport({ width, height, isMobile: width < 500 })
  for (const route of ['citizen', 'public', 'bench', 'about']) {
    await page.goto(`${BASE}/#/${route}`, { waitUntil: 'networkidle0' }); await sleep(1200); await audit(`${name} · ${route}`)
  }
  await page.goto(`${BASE}/#/ops`, { waitUntil: 'networkidle0' })
  await page.evaluate(() => sessionStorage.clear()); await page.reload({ waitUntil: 'networkidle0' }); await sleep(500)
  await audit(`${name} · sign-in`)
  await click('Continue as investigator'); await sleep(1200); await audit(`${name} · case queue`)
  if (!(await page.evaluate(() => document.querySelector('a[href^="#/ops/C-"]')))) { await click('dry weather'); await sleep(4000) }
  else { await page.evaluate(() => document.querySelector('a[href^="#/ops/C-"]').click()); await sleep(2500) }
  for (const t of ['Investigation', 'Advisory', 'Hand-off', 'Timeline']) { await tab(t); await sleep(700); await audit(`${name} · case ${t}`) }
}
await browser.close()
console.log(failures ? `\n${failures} problem(s)` : '\nNo accessibility violations.')
process.exit(failures ? 1 : 0)
