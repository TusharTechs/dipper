// The demo film. Every frame is a pure function of time: make.mjs calls film.seek(t) and screenshots the stage.
// To look at one moment in a browser: video/film.html?timeline=out/timeline.json&t=42 (served over http).
// Stream geometry is the real OpenStreetMap reach; numbers on screen come from the capture of the live app.
import { BENCH } from './story.mjs'

const Q = new URLSearchParams(location.search)
const TLPATH = Q.get('timeline') ?? 'out/timeline.json', DIR = TLPATH.replace(/[^/]*$/, '')
const TL = await (await fetch(TLPATH)).json()
const REACH = await (await fetch(DIR + TL.reach)).json()
const stage = document.getElementById('stage')
const F = TL.facts, DESK = TL.capture.desk, PHONE = TL.capture.phone, DF = DESK.facts, PF = PHONE.facts

// ---------- small tools ----------
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x))
const lerp = (a, b, u) => a + (b - a) * u
const E = {
  lin: (u) => u, out: (u) => 1 - (1 - u) ** 3, in: (u) => u * u * u,
  io: (u) => (u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2),
  back: (u) => { const c = 1.5; return 1 + (c + 1) * (u - 1) ** 3 + c * (u - 1) ** 2 },
}
const k = (t, a, b, e = E.io) => e(clamp((t - a) / Math.max(1e-6, b - a)))
const SVGTAGS = new Set(['svg', 'g', 'path', 'circle', 'ellipse', 'rect', 'line', 'polyline', 'polygon', 'text', 'tspan', 'defs',
  'filter', 'feGaussianBlur', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'mask', 'use'])
function h(tag, attrs = {}, parent = null, text = null) {
  const e = SVGTAGS.has(tag) ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag)
  for (const [a, v] of Object.entries(attrs)) {
    if (a === 'style') Object.assign(e.style, v)
    else if (a === 'html') e.innerHTML = v
    else e.setAttribute(a, v)
  }
  if (text != null) e.textContent = text
  if (parent) parent.appendChild(e)
  return e
}
const div = (parent, x, y, cls = '', html = '', style = {}) =>
  h('div', { class: `abs ${cls}`, html, style: { left: `${x}px`, top: `${y}px`, ...style } }, parent)
const op = (e, o) => { e.style.opacity = o; e.style.visibility = o <= 0.002 ? 'hidden' : 'visible' }
const rise = (e, u, d = 24) => { op(e, u); e.style.transform = `translateY(${(1 - u) * d}px)` }
const pop = (e, u) => { op(e, clamp(u * 1.6)); e.style.transform = `scale(${lerp(0.6, 1, E.back(clamp(u)))})` }
const fmt = (n) => Math.round(n).toLocaleString('en-GB')
function words(parent, x, y, text, cls, style = {}) {
  const el = div(parent, x, y, cls, '', style)
  const ws = text.split(' ').map((w, i) => { if (i) el.appendChild(document.createTextNode(' ')); return h('span', { class: 'word' }, el, w) })
  return { el, ws, reveal(t, t0, step = 0.07, dur = 0.55) { ws.forEach((w, i) => rise(w, k(t, t0 + i * step, t0 + i * step + dur, E.out), 26)) } }
}
// When a word is spoken, estimated from its position in the line (pauses at punctuation count extra).
function wt(S, word, n = 0) {
  if (!S.text) return S.lead ?? 0
  const low = S.text.toLowerCase(); let i = -1
  for (let j = 0; j <= n; j++) { i = low.indexOf(word.toLowerCase(), i + 1); if (i < 0) break }
  if (i < 0) { console.error(`film: "${word}" is not in the ${S.id} line`); return S.lead }
  const weight = (s) => [...s].reduce((a, ch) => a + (',;:'.includes(ch) ? 7 : '.?!'.includes(ch) ? 11 : 1), 0)
  return S.lead + S.voDur * (weight(low.slice(0, i)) / weight(low))
}
let pending = []
function setImg(img, src) {
  if (img.dataset.src === src) return
  img.dataset.src = src; img.src = src; pending.push(img.decode().catch(() => {}))
}

// ---------- the stream, from the real reach ----------
const G = (() => {
  const nodes = new Map(), edges = [], cands = [], places = []
  for (const f of REACH.features) {
    const p = f.properties
    if (p.role === 'node') nodes.set(p.id, { ll: f.geometry.coordinates, d: p.dist_to_outlet_m })
    else if (p.role === 'edge') edges.push({ ...p, cs: f.geometry.coordinates })
    else if (p.role === 'candidate') cands.push(p)
    else if (p.role === 'place') places.push(p)
  }
  const from = new Map(edges.map((e) => [e.from, e])), tos = new Set(edges.map((e) => e.to))
  let cur = [...from.keys()].find((id) => !tos.has(id))
  const ll = [], nodeIdx = new Map([[cur, 0]]), culverts = []
  while (from.has(cur)) {
    const e = from.get(cur), a = Math.max(0, ll.length - 1)
    e.cs.forEach((c, i) => { if (i || !ll.length) ll.push(c) })
    if (e.culvert) culverts.push([a, ll.length - 1])
    cur = e.to; nodeIdx.set(cur, ll.length - 1)
  }
  const m = ll.map(([lon, lat]) => [lon * Math.PI / 180, -Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360))])
  const cum = [0]; for (let i = 1; i < m.length; i++) cum.push(cum[i - 1] + Math.hypot(m[i][0] - m[i - 1][0], m[i][1] - m[i - 1][1]))
  const frac = (i) => cum[i] / cum.at(-1)
  const onPath = [...nodeIdx.entries()].map(([id, i]) => ({ i, d: nodes.get(id).d }))
  const fracDist = (metres) => frac(onPath.reduce((b, x) => (Math.abs(x.d - metres) < Math.abs(b.d - metres) ? x : b)).i)
  const cand = cands.map((c) => ({ ...c, s: frac(nodeIdx.get(c.node_id)) })).sort((a, b) => a.s - b.s)
  const place = places.map((p) => ({ ...p, s: frac(nodeIdx.get(p.node_id)) }))
  return { m, frac, fracDist, cand, place, culverts, lat0: ll[0][1], name: REACH.properties.name, city: REACH.properties.city }
})()
const candS = (label) => G.cand.find((c) => c.label === label)?.s ?? 0.5
const kmIn = (text, dflt) => { const x = text?.match(/(\d+(?:\.\d+)?) km above/); return x ? Number(x[1]) * 1000 : dflt }

function fitPath(box) {
  const xs = G.m.map((p) => p[0]), ys = G.m.map((p) => p[1])
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const s = Math.min(box.w / (x1 - x0), box.h / (y1 - y0))
  const ox = box.x + (box.w - (x1 - x0) * s) / 2, oy = box.y + (box.h - (y1 - y0) * s) / 2
  const pts = G.m.map(([x, y]) => [ox + (x - x0) * s, oy + (y - y0) * s])
  const cum = [0]; for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  const L = cum.at(-1)
  const seg = (u) => { const d = clamp(u) * L; let i = 1; while (i < cum.length - 1 && cum[i] < d) i++; return [i, (d - cum[i - 1]) / Math.max(1e-9, cum[i] - cum[i - 1])] }
  const at = (u) => { const [i, f] = seg(u); return [lerp(pts[i - 1][0], pts[i][0], f), lerp(pts[i - 1][1], pts[i][1], f)] }
  const angle = (u) => { const [i] = seg(u); return Math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0]) }
  const sub = (a, b) => {
    const out = [at(a)]; for (let i = 0; i < pts.length; i++) if (cum[i] > a * L && cum[i] < b * L) out.push(pts[i])
    out.push(at(b)); return 'M' + out.map((p) => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' L')
  }
  const mpp = 6378137 * Math.cos(G.lat0 * Math.PI / 180) / s
  return { pts, L, at, angle, sub, mpp, d: sub(0, 1) }
}

let UID = 0
function StreamView(parent, box) {
  const P = fitPath(box), id = `sv${UID++}`, K = 120
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, parent)
  const defs = h('defs', {}, svg)
  const blur = h('filter', { id: `${id}b`, x: '-10%', y: '-40%', width: '120%', height: '180%' }, defs); h('feGaussianBlur', { stdDeviation: 10 }, blur)
  const bank = h('path', { d: P.d, class: 'bank' }, svg)
  const glow = h('path', { d: P.d, class: 'glow', filter: `url(#${id}b)` }, svg)
  const water = h('path', { d: P.d, class: 'water' }, svg)
  const heatG = h('g', { style: { opacity: 0 } }, svg)
  const segs = [...Array(K).keys()].map((i) => h('path', { d: P.sub(i / K, (i + 1.02) / K), class: 'seg' }, heatG))
  const pglow = h('path', { d: P.d, class: 'pglow', filter: `url(#${id}b)`, style: { opacity: 0 } }, svg)
  const pol = h('path', { d: P.d, class: 'pol', style: { opacity: 0 } }, svg)
  const cul = h('g', { style: { opacity: 0 } }, svg)
  const culPaths = G.culverts.map(([a, b]) => h('path', { d: P.sub(G.frac(a), G.frac(b)), class: 'culvert' }, cul))
  const flow = h('path', { d: P.d, class: 'flow' }, svg)
  const marks = h('g', {}, svg)
  const all = h('g', {}, svg); [bank, glow, water, heatG, pglow, pol, cul, flow].forEach((e) => all.appendChild(e)); svg.insertBefore(all, marks)
  return {
    P, svg, marks, all, culPaths,
    draw(u) { for (const e of [bank, glow, water]) e.style.strokeDasharray = `${u * P.L} ${P.L * 2}` },
    flow(T, o) { flow.style.strokeDashoffset = `${-T * 46}`; flow.style.opacity = o },
    pollute(a, b, o = 1) {
      for (const e of [pol, pglow]) { e.style.strokeDasharray = `${Math.max(0, b - a) * P.L} ${P.L * 2}`; e.style.strokeDashoffset = `${-a * P.L}` }
      pol.style.opacity = o; pglow.style.opacity = o * 0.6
    },
    heat(fn, o) { heatG.style.opacity = o; if (o > 0) segs.forEach((e, i) => e.setAttribute('stroke', heatColor(fn((i + 0.5) / K)))) },
    culverts(o) { cul.style.opacity = o },
  }
}
const STOPS = [[0, [94, 142, 140]], [0.18, [133, 165, 140]], [0.4, [226, 163, 59]], [0.7, [214, 88, 58]], [1, [196, 52, 40]]]
function heatColor(v) {
  v = clamp(v); let i = 1; while (i < STOPS.length - 1 && STOPS[i][0] < v) i++
  const [a, ca] = STOPS[i - 1], [b, cb] = STOPS[i], u = (v - a) / (b - a)
  return `rgb(${ca.map((c, j) => Math.round(lerp(c, cb[j], u))).join(',')})`
}
// The chance each stretch is polluted: the probability of every source at or upstream of it (as in the app).
function beliefFn(b) {
  const src = b.src.map(([label, p]) => ({ s: candS(label), p: p / 100 }))
  const rest = Math.max(0, 1 - src.reduce((a, x) => a + x.p, 0))
  return (s) => src.reduce((a, x) => a + (x.s <= s ? x.p : 0), rest * 0.35)
}
const pOf = (b, label) => (b.src.find((x) => x[0] === label)?.[1] ?? 0) / 100
const BELIEFS = DF.beliefs ?? []

// ---------- shared pieces ----------
function backdrop(root) {
  h('div', { class: 'backdrop' }, root)
  const dots = h('div', { class: 'dots' }, root)
  return (T) => { dots.style.transform = `translate(${(T * 5) % 34}px, ${(T * 2.5) % 34}px)` }
}
function scaleBar(parent, P, x, y) {
  const px = 500 / P.mpp, g = h('g', {}, parent)
  h('line', { x1: x, y1: y, x2: x + px, y2: y, stroke: '#93aaa7', 'stroke-width': 2 }, g)
  for (const xx of [x, x + px]) h('line', { x1: xx, y1: y - 7, x2: xx, y2: y + 7, stroke: '#93aaa7', 'stroke-width': 2 }, g)
  h('text', { x: x + px + 14, y: y + 6, class: 'lbl small' }, g, '500 m')
  return g
}
function ringAt(parent, [x, y], r, stroke = '#fff', width = 2.5, fill = 'rgba(7,17,20,0.85)') {
  return h('circle', { cx: x, cy: y, r, fill, stroke, 'stroke-width': width }, parent)
}
const LOGO = {
  tail: 'M22.2 21.2 L12.2 12.9 Q11.3 11.3 13.2 11.6 L26.6 17.2 Z',
  pin: 'M32 51.2 C28.6 45.5 16.5 37.6 16.5 26.5 A15.5 15.5 0 0 1 47.5 26.5 C47.5 37.6 35.4 45.5 32 51.2 Z',
  white: 'M49 23.6 C45.6 25.3 41.6 25.6 38.3 24.9 C36.4 30.2 36.7 36.6 38.6 43.6 L49 43.6 Z',
  beak: 'M46.4 19.4 L54.6 21.7 L47.1 24.3 Z',
}
function makeLogo(parent, x, y, size) {
  const id = `lg${UID++}`
  const svg = h('svg', { viewBox: '0 0 64 64', width: size, height: size, class: 'abs', style: { left: `${x}px`, top: `${y}px`, overflow: 'visible' } }, parent)
  const defs = h('defs', {}, svg), clip = h('clipPath', { id: `${id}c` }, defs); h('path', { d: LOGO.pin }, clip)
  const bg = h('rect', { width: 64, height: 64, rx: 15, fill: '#157F78', style: { transformOrigin: '32px 32px' } }, svg)
  const r1 = h('ellipse', { cx: 32, cy: 52.6, rx: 9.6, ry: 2.7, fill: 'none', stroke: '#BFE9E4', 'stroke-width': 2.4, style: { transformOrigin: '32px 52.6px' } }, svg)
  const r2 = h('ellipse', { cx: 32, cy: 53.2, rx: 19.5, ry: 5.3, fill: 'none', stroke: '#BFE9E4', 'stroke-width': 2, style: { transformOrigin: '32px 53.2px' } }, svg)
  const tail = h('path', { d: LOGO.tail, fill: '#0F1E24' }, svg)
  const pinLine = h('path', { d: LOGO.pin, fill: 'none', stroke: '#fff', 'stroke-width': 1.2, pathLength: 1, 'stroke-dasharray': '1 1' }, svg)
  const pin = h('path', { d: LOGO.pin, fill: '#0F1E24' }, svg)
  const white = h('path', { d: LOGO.white, fill: '#fff', 'clip-path': `url(#${id}c)` }, svg)
  const beak = h('path', { d: LOGO.beak, fill: '#0F1E24' }, svg)
  const eye = h('circle', { cx: 41.2, cy: 19.3, r: 1.9, fill: '#fff', style: { transformOrigin: '41.2px 19.3px' } }, svg)
  // u: 0 → 1 builds the mark; T keeps the ripples moving afterwards.
  return (u, T) => {
    bg.style.transform = `scale(${E.back(k(u, 0, 0.3, E.lin))})`; op(bg, k(u, 0, 0.12))
    pinLine.setAttribute('stroke-dashoffset', 1 - k(u, 0.2, 0.55)); op(pinLine, 1 - k(u, 0.6, 0.7))
    op(pin, k(u, 0.5, 0.7)); op(tail, k(u, 0.6, 0.75)); op(white, k(u, 0.68, 0.82)); op(beak, k(u, 0.72, 0.85))
    eye.style.transform = `scale(${E.back(k(u, 0.85, 1, E.lin))})`
    const w = k(u, 0.75, 1)
    r1.style.transform = `scale(${w * (1 + 0.06 * Math.sin(T * 2.4))})`; r2.style.transform = `scale(${w * (1 + 0.05 * Math.sin(T * 2.4 - 1))})`
    op(r1, w); op(r2, w * 0.55)
  }
}
function liveBadge(root) { return div(root, 60, 40, 'live-badge', '<i></i>LIVE <span>the deployed app</span>') }

// ---------- scenes ----------
const KINDS = {}
const WIDE = { x: 150, y: 260, w: 1620, h: 620 }
const TOP = PF.caseId ? DF : DF

// A shared street-level view of the stream for the first three scenes, so cuts between them are seamless.
function problemStream(root) {
  const drift = backdrop(root)
  const sv = StreamView(root, WIDE)
  const places = G.place.map((p) => {
    const [x, y] = sv.P.at(p.s), g = h('g', {}, sv.marks)
    h('circle', { cx: x, cy: y, r: 20, fill: 'rgba(157,134,224,0.18)' }, g)
    h('circle', { cx: x, cy: y, r: 8, fill: '#9d86e0', stroke: '#fff', 'stroke-width': 2 }, g)
    h('text', { x, y: y - 30, 'text-anchor': 'middle', class: 'lbl place' }, g, p.label)
    h('text', { x, y: y + 42, 'text-anchor': 'middle', class: 'lbl small' }, g, p.kind)
    return g
  })
  const bar = scaleBar(sv.marks, sv.P, 150, 930)
  const eb = div(root, 150, 118, 'eyebrow', `${G.name} · ${G.city}, Portugal`)
  return { drift, sv, places, bar, eb }
}
function sceneHeadline(root, S, text, t0 = 0.3) {
  const w = words(root, 150, 156, text, 'headline')
  return (t) => { w.reveal(t, t0); op(w.el, 1 - k(t, S.dur - 0.45, S.dur - 0.05)) }
}

KINDS.open = (root, S) => {
  const { drift, sv, places, bar, eb } = problemStream(root)
  const head = sceneHeadline(root, S, 'A city stream.', 1.8)
  const tC = wt(S, 'Children'), tW = wt(S, 'walk')
  return (t, T) => {
    drift(T); sv.draw(k(t, 0.4, 4.4)); sv.flow(T, 0.55 * k(t, 3.4, 4.8))
    op(eb, k(t, 1.2, 2.2)); head(t); op(bar, k(t, 4, 5))
    places.forEach((g, i) => op(g, k(t, (i ? tW : tC) - 0.2, (i ? tW : tC) + 0.5)))
  }
}

KINDS.grey = (root, S) => {
  const { drift, sv, places, bar, eb } = problemStream(root)
  const head = sceneHeadline(root, S, 'Then it turns grey.', 0.2)
  const s0 = candS(F.top), tGrey = wt(S, 'grey'), tSmell = wt(S, 'smell'), tWhere = wt(S, 'Somewhere')
  const chip = div(root, 1180, 124, 'chip', `<span style="color:#f3c969">☀</span> ${F.weather.replace(/, max.*/, '')}`)
  const waves = [0.25, 0.5, 0.75].map((f, i) => {
    const [x, y] = sv.P.at(s0 + (1 - s0) * f)
    return { g: h('path', { d: `M${x - 14} ${y} q7 -12 0 -24 q-7 -12 0 -24 q7 -12 0 -24`, fill: 'none', stroke: '#b9b29a', 'stroke-width': 3, 'stroke-linecap': 'round' }, sv.marks), ph: i * 0.33 }
  })
  const [qx, qy] = sv.P.at(s0 - 0.04)
  const fog = h('g', {}, sv.marks)
  h('circle', { cx: qx, cy: qy, r: 170, fill: 'rgba(226,163,59,0.10)', stroke: 'rgba(226,163,59,0.45)', 'stroke-width': 2, 'stroke-dasharray': '6 10' }, fog)
  h('text', { x: qx, y: qy - 190, 'text-anchor': 'middle', class: 'lbl', style: { fill: '#f3c969', fontSize: '24px' } }, fog, 'a pipe, somewhere upstream')
  return (t, T) => {
    drift(T); sv.draw(1); sv.flow(T, 0.55); op(eb, 1); op(bar, 1); places.forEach((g) => op(g, 1)); head(t)
    op(chip, k(t, wt(S, 'dry') - 0.3, wt(S, 'dry') + 0.3))
    sv.pollute(s0, s0 + (1 - s0) * k(t, tGrey - 0.3, tGrey + 3.4, E.io), k(t, tGrey - 0.3, tGrey + 0.3))
    for (const w of waves) {
      const cyc = ((T * 0.55 + w.ph) % 1)
      op(w.g, k(t, tSmell - 0.2, tSmell + 0.6) * Math.sin(cyc * Math.PI) * 0.9)
      w.g.style.transform = `translateY(${-cyc * 40}px)`
    }
    op(fog, k(t, tWhere - 0.2, tWhere + 0.6) * (0.75 + 0.25 * Math.sin(T * 3)))
  }
}

KINDS.haystack = (root, S) => {
  const { drift, sv, places, bar, eb } = problemStream(root)
  const head = sceneHeadline(root, S, 'Which pipe is it?', 0.2)
  const s0 = candS(F.top), truth = G.cand.find((c) => c.label === F.top)
  const tDoz = wt(S, 'dozens'), tCrew = wt(S, 'crews'), tClean = wt(S, 'looks clean'), tDirty = wt(S, 'dirty')
  const rings = G.cand.map((c) => {
    const [x, y] = sv.P.at(c.s), g = h('g', {}, sv.marks), up = (G.cand.indexOf(c) % 2) ? 1 : -1
    const plume = h('circle', { cx: x, cy: y, r: 18, fill: 'rgba(160,150,120,0.55)' }, g)
    const ring = ringAt(g, [x, y], 10)
    h('text', { x, y: y + up * 30 + (up > 0 ? 8 : 0), 'text-anchor': 'middle', class: 'lbl small' }, g, c.label)
    const tick = h('text', { x, y: y - up * 26 + (up < 0 ? 12 : 0), 'text-anchor': 'middle', class: 'lbl', style: { fontSize: '17px' } }, g, 'clean')
    return { c, g, ring, plume, tick, x, y }
  })
  // The crew walks upstream from the outlet, outfall by outfall; the true source happens to be quiet when they pass.
  const route = [...rings].sort((a, b) => b.c.s - a.c.s)
  const iTruth = route.findIndex((r) => r.c === truth)
  const visits = route.map((r, i) => ({ r, at: i <= iTruth ? lerp(tCrew + 0.5, tClean - 0.2, i / Math.max(1, iTruth)) : tClean - 0.2 + (i - iTruth) * 0.95 }))
  const walker = h('g', {}, sv.marks)
  h('circle', { r: 15, fill: '#fff', stroke: '#157f78', 'stroke-width': 4 }, walker)
  h('text', { y: -28, 'text-anchor': 'middle', class: 'lbl', style: { fontSize: '17px' } }, walker, 'field crew')
  const counter = div(root, 1320, 124, 'chip', '')
  return (t, T) => {
    drift(T); sv.draw(1); sv.flow(T, 0.55); op(eb, 1); op(bar, 1); places.forEach((g) => op(g, 1)); head(t)
    sv.pollute(s0, 1, 1)
    rings.forEach((r, i) => pop(r.g, k(t, tDoz - 0.3 + i * 0.07, tDoz + 0.2 + i * 0.07, E.lin)))
    for (const r of rings) r.g.style.transformOrigin = `${r.x}px ${r.y}px`
    // walker position
    let s = 1, done = 0
    for (const v of visits) { if (t >= v.at) { s = v.r.c.s; done++ } }
    const nxt = visits[done], prev = visits[done - 1]
    if (nxt && t >= tCrew) { const a = prev ? prev.at + 0.3 : tCrew, u = k(t, a, nxt.at, E.io); s = lerp(prev ? prev.r.c.s : 1, nxt.r.c.s, u) }
    const [wx, wy] = sv.P.at(s); walker.setAttribute('transform', `translate(${wx},${wy - 34})`); op(walker, k(t, tCrew - 0.4, tCrew))
    visits.forEach((v, i) => {
      const seen = t >= v.at
      op(v.r.tick, seen ? 1 : 0)
      if (v.r.c === truth) {
        const dirty = t >= tDirty
        v.r.tick.textContent = dirty ? 'discharging' : 'looked clean'
        v.r.tick.style.fill = dirty ? '#ff7a5c' : '#f3c969'
        v.r.ring.setAttribute('stroke', dirty ? '#ff7a5c' : '#fff'); v.r.ring.setAttribute('r', dirty ? 13 + 2 * Math.sin(T * 8) : 10)
        const on = dirty || (t < v.at - 0.8 && ((T * 0.7) % 1) < 0.5)
        op(v.r.plume, on ? 1 : 0)
      } else { op(v.r.plume, 0); v.r.tick.style.fill = '#93aaa7' }
    })
    counter.innerHTML = `Checks <b style="margin:0 18px 0 6px">${done}</b> Day <b style="margin-left:6px">${1 + Math.floor(done / 3)}</b>`
    op(counter, k(t, tCrew - 0.2, tCrew + 0.3))
  }
}

KINDS.scale = (root, S) => {
  const drift = backdrop(root)
  const eb = div(root, 150, 250, 'eyebrow', 'Misconnected drains')
  const num = div(root, 146, 300, '', '', { fontSize: '108px', fontWeight: 800, letterSpacing: '-0.03em', color: '#fff', lineHeight: 1.05 })
  const lab = div(root, 150, 450, 'body', '<b>homes in the UK alone</b>, sending sewage<br>to streams instead of the treatment works', { width: '760px', fontSize: '34px' })
  const src = div(root, 150, 600, 'body', 'Estimate: CIWEM, “Drain misconnections”', { fontSize: '22px' })
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, root)
  const cols = 19, rows = 15, cells = []
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const x = 1170 + c * 32, y = 250 + r * 32
    cells.push({ e: h('path', { d: `M${x} ${y + 10} l10 -9 l10 9 v11 h-20 z`, fill: '#1c3238' }, svg), o: (Math.sin((r * 31 + c * 17) * 12.9898) * 43758.5453) % 1 })
  }
  const t0 = wt(S, 'estimated') - 0.2, t1 = wt(S, 'homes') + 0.5
  return (t, T) => {
    drift(T); op(eb, k(t, 0.1, 0.6)); rise(lab, k(t, t1 - 0.4, t1 + 0.3)); op(src, k(t, t1, t1 + 0.6))
    const u = k(t, t0, t1, E.out)
    num.textContent = `${fmt(150000 * u)} – ${fmt(500000 * u)}`; rise(num, k(t, t0 - 0.3, t0 + 0.2))
    for (const c of cells) {
      const lit = Math.abs(c.o) < u * 0.97
      c.e.setAttribute('fill', lit ? (Math.abs(c.o) < 0.3 * u ? '#e2a33b' : '#8d8672') : '#1c3238')
    }
  }
}

KINDS.void = (root, S) => {
  const drift = backdrop(root)
  const msgs = ['The stream by the school is grey again.', 'Strong sewage smell on the park path.', 'Is it safe for my dog to swim here?']
  const times = [wt(S, 'walkers'), wt(S, 'parents'), wt(S, 'schools')]
  const bubbles = msgs.map((m, i) => {
    const b = div(root, 190 + i * 70, 260 + i * 170, '', `<div style="font-size:30px;font-weight:550;color:#fff">${m}</div><div class="meta" style="margin-top:10px;font-size:20px;color:#93aaa7">Sent ✓</div>`,
      { width: '620px', padding: '26px 30px', borderRadius: '26px 26px 26px 8px', background: 'rgba(21,127,120,0.28)', border: '1px solid rgba(191,233,228,0.18)' })
    return { b, meta: b.querySelector('.meta') }
  })
  const head = words(root, 1080, 380, 'Reported. Then silence.', 'headline', { width: '700px' })
  const tGone = wt(S, 'never hear back'), tSearch = wt(S, 'never reaches')
  const note = div(root, 1082, 560, 'body', 'No reply, no follow-up, and nothing<br>the search can use.', { width: '700px' })
  return (t, T) => {
    drift(T)
    bubbles.forEach(({ b, meta }, i) => {
      const u = k(t, times[i] - 0.3, times[i] + 0.3, E.out), gone = k(t, tSearch - 0.2 + i * 0.12, tSearch + 1.4 + i * 0.12, E.in)
      op(b, u * (1 - gone)); b.style.transform = `translateY(${(1 - u) * 30 - gone * 160}px)`; b.style.filter = `blur(${gone * 14}px)`
      const noReply = t > times[i] + 1.2
      meta.textContent = noReply ? 'Sent ✓ · no reply' : 'Sent ✓'; meta.style.color = noReply ? '#ff9a80' : '#93aaa7'
    })
    head.reveal(t, tGone - 0.6); rise(note, k(t, tGone, tGone + 0.6))
  }
}

KINDS.law = (root, S) => {
  const drift = backdrop(root)
  const card = div(root, 150, 210, 'card paper', '', { width: '960px', height: '640px', padding: '54px 60px' })
  h('div', { class: 'eyebrow', style: { color: '#157f78' } }, card, 'Directive (EU) 2024/3019')
  h('div', { style: { fontSize: '46px', fontWeight: 800, letterSpacing: '-0.02em', margin: '14px 0 36px', lineHeight: 1.1 } }, card, 'Urban Wastewater Treatment, recast')
  const lines = ['Integrated urban wastewater management plans', 'For agglomerations of 100,000 p.e. and above', 'Covering storm overflows and urban runoff', 'In place by 2033']
  const rows = lines.map((l) => {
    const r = h('div', { style: { position: 'relative', fontSize: '31px', fontWeight: 600, padding: '14px 18px', margin: '0 -18px 8px' } }, card)
    const hl = h('div', { style: { position: 'absolute', inset: 0, background: '#f6d9a0', borderRadius: '10px', transformOrigin: '0 50%' } }, r)
    h('span', { style: { position: 'relative' } }, r, l); return hl
  })
  const times = [wt(S, 'plan'), wt(S, 'large cities'), wt(S, 'storm overflows'), wt(S, '2033')]
  const year = div(root, 1260, 330, '', '2033', { fontSize: '210px', fontWeight: 800, letterSpacing: '-0.04em', color: '#fff' })
  const yl = div(root, 1270, 570, 'body', 'plans due for every large city<br>in the European Union', { width: '560px' })
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, root)
  h('line', { x1: 1270, y1: 700, x2: 1760, y2: 700, stroke: '#1c3238', 'stroke-width': 8, 'stroke-linecap': 'round' }, svg)
  const fill = h('line', { x1: 1270, y1: 700, x2: 1270, y2: 700, stroke: '#2fb5aa', 'stroke-width': 8, 'stroke-linecap': 'round' }, svg)
  h('text', { x: 1270, y: 745, class: 'lbl small' }, svg, 'Today'); h('text', { x: 1760, y: 745, class: 'lbl small', 'text-anchor': 'end' }, svg, '2033')
  return (t, T) => {
    drift(T); rise(card, k(t, 0, 0.7, E.out))
    rows.forEach((hl, i) => { hl.style.transform = `scaleX(${k(t, times[i] - 0.2, times[i] + 0.5)})` })
    rise(year, k(t, times[3] - 0.5, times[3] + 0.2)); rise(yl, k(t, times[3], times[3] + 0.5))
    fill.setAttribute('x2', lerp(1270, 1760, k(t, times[3], times[3] + 1.6)))
  }
}

KINDS.question = (root, S) => {
  const drift = backdrop(root)
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, root)
  const rings = [0, 1, 2].map(() => h('circle', { cx: 960, cy: 540, r: 10, fill: 'none', stroke: '#2fb5aa', 'stroke-width': 2 }, svg))
  const box = div(root, 0, 390, '', '', { width: '1920px', textAlign: 'center' })
  const line1 = h('div', { class: 'headline', style: { fontSize: '96px' } }, box), line2 = h('div', { class: 'headline', style: { fontSize: '96px', color: '#43c3b7' } }, box)
  const ws = []
  for (const [line, text] of [[line1, 'What if every report'], [line2, 'made the search smarter?']])
    text.split(' ').forEach((w, i) => { if (i) line.appendChild(document.createTextNode(' ')); ws.push(h('span', { class: 'word' }, line, w)) })
  return (t, T) => {
    drift(T)
    ws.forEach((w, i) => rise(w, k(t, S.lead + (i / ws.length) * S.voDur - 0.15, S.lead + (i / ws.length) * S.voDur + 0.35, E.out), 30))
    rings.forEach((r, i) => { const c = ((T * 0.25 + i / 3) % 1); r.setAttribute('r', 40 + c * 900); op(r, (1 - c) * 0.35) })
  }
}

KINDS.logo = (root, S) => {
  const drift = backdrop(root)
  const logo = makeLogo(root, 330, 250, 330)
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, root)
  const waves = [0, 1, 2].map(() => h('ellipse', { cx: 495, cy: 525, rx: 10, ry: 3, fill: 'none', stroke: '#bfe9e4', 'stroke-width': 2 }, svg))
  const word = div(root, 760, 262, '', 'Dipper', { fontSize: '200px', fontWeight: 800, letterSpacing: '-0.045em', color: '#fff', lineHeight: 1 })
  const tag = div(root, 772, 490, '', 'Find urban stream pollution at its source.', { fontSize: '44px', fontWeight: 600, color: '#bfe9e4' })
  const tBird = wt(S, 'songbird'), tTurn = wt(S, 'turns citizen')
  const bird = div(root, 772, 580, 'body', 'Named after the white-throated dipper, <i>Cinclus cinclus</i>:<br>a songbird of fast, clean streams, used as a living sign of their health.', { width: '980px', fontSize: '27px' })
  const flow = div(root, 772, 700, '', '', { display: 'flex', gap: '18px', alignItems: 'center' })
  const chips = ['Citizen reports', 'A smarter search', 'The polluting pipe'].map((x, i) => {
    if (i) h('div', { style: { fontSize: '30px', color: '#2fb5aa' } }, flow, '→')
    return h('div', { class: `chip ${i === 2 ? 'teal' : ''}`, style: { fontSize: '26px' } }, flow, x)
  })
  return (t, T) => {
    drift(T); logo(k(t, 0.2, 2.4, E.lin), T)
    waves.forEach((w, i) => { const c = ((T * 0.3 + i / 3) % 1); w.setAttribute('rx', 60 + c * 520); w.setAttribute('ry', 14 + c * 120); op(w, (1 - c) * 0.3 * k(t, 2.2, 3)) })
    const u = k(t, 1.8, 2.7, E.out); op(word, u); word.style.clipPath = `inset(0 ${(1 - u) * 100}% 0 0)`; word.style.transform = `translateX(${(1 - u) * -30}px)`
    rise(tag, k(t, 2.5, 3.2, E.out)); rise(bird, k(t, tBird - 0.4, tBird + 0.3))
    chips.forEach((c, i) => rise(c, k(t, tTurn - 0.2 + i * 0.5, tTurn + 0.3 + i * 0.5, E.out)))
    ;[...flow.children].filter((x) => !x.classList.contains('chip')).forEach((a, i) => op(a, k(t, tTurn + 0.2 + i * 0.5, tTurn + 0.5 + i * 0.5)))
  }
}

// ---------- how it works: five steps on one stream ----------
const HOW = [
  { title: 'Reports become evidence', body: 'Each report is snapped to a stream network built from <b>OpenStreetMap</b>: flow direction, culverts, and gaps bridged.' },
  { title: 'One belief: what, and where', body: 'An exact joint probability over <b>six explanations</b> and <b>every candidate outfall</b>. Dry days favour a misconnection, rain an overflow.' },
  { title: 'The next best check', body: 'Every check at every point is scored on <b>value of information</b>, against cost and delay. Clean results count too.' },
  { title: 'A mission for the reporter', body: 'Citizen checks are also charged for the <b>walk from where they reported</b>. One short, nearby check.' },
  { title: 'People decide', body: 'The utility gets a <b>FHIR R4 bundle</b> on the OneAquaHealth IG. A public-health officer <b>approves</b> every advisory.' },
]
const SHORT = { 'Foul sewage': 'Foul sewage', 'Chemical or detergent discharge': 'Chemical', 'Algal bloom': 'Algal bloom', 'Wet-weather sewer overflow': 'Sewer overflow', 'Natural or benign': 'Natural or benign', 'Sediment runoff': 'Sediment' }
const shortHyp = (l) => SHORT[l.split(' (')[0]] ?? l.split(' (')[0]

KINDS.how = (root, S) => {
  const step = S.step, drift = backdrop(root)
  const sv = StreamView(root, { x: 790, y: 190, w: 1040, h: 640 })
  const P = sv.P, b0 = BELIEFS[0] ?? { hyp: [], src: [] }, b1 = BELIEFS[1] ?? b0
  // left column
  const eb = div(root, 120, 180, 'eyebrow', `How it works · ${step} of 5`)
  const dots = div(root, 120, 222, '', [1, 2, 3, 4, 5].map((i) => `<i style="display:inline-block;width:${i === step ? 40 : 12}px;height:12px;border-radius:6px;margin-right:10px;background:${i <= step ? '#2fb5aa' : '#1c3238'}"></i>`).join(''))
  const title = words(root, 120, 262, HOW[step - 1].title, 'title', { width: '620px' })
  const body = div(root, 120, 400, 'body', HOW[step - 1].body, { width: '600px' })
  const T0 = (w, d = 0) => (w ? wt(S, w) : 0) + d
  const upd = []  // per-scene updaters for the current step
  const at = (s) => P.at(s)

  // 1: reports snap to the stream; flow direction; culverts
  const reps = [1650, 1320, 1050].map((m) => G.fracDist(m))
  const pins = reps.map((s, i) => {
    const [x, y] = at(s), a = P.angle(s) + Math.PI / 2, off = 62 * (i % 2 ? 1 : -1)
    const px = x + Math.cos(a) * off, py = y + Math.sin(a) * off
    const g = h('g', {}, sv.marks)
    const link = h('line', { x1: px, y1: py, x2: x, y2: y, stroke: '#f3c969', 'stroke-width': 2, 'stroke-dasharray': '4 5' }, g)
    const pin = h('g', {}, g)
    h('path', { d: 'M0 0 C-4 -8 -12 -13 -12 -22 A12 12 0 0 1 12 -22 C12 -13 4 -8 0 0 Z', fill: '#e2a33b', stroke: '#fff', 'stroke-width': 2 }, pin)
    h('circle', { cx: 0, cy: -22, r: 4.5, fill: '#fff' }, pin)
    return { g, link, pin, x, y, px, py }
  })
  const snapLbl = h('text', { x: pins[1].px + 22, y: pins[1].py + 60, class: 'lbl', style: { fill: '#f3c969' } }, sv.marks, 'snapped to the stream')
  const chevrons = [...Array(14).keys()].map(() => h('path', { d: 'M-6 -7 L4 0 L-6 7', fill: 'none', stroke: '#bfe9e4', 'stroke-width': 3, 'stroke-linecap': 'round' }, sv.marks))
  const cul0 = G.culverts[0]
  const culLbl = cul0 ? h('text', { x: at(G.frac(cul0[0]))[0], y: at(G.frac(cul0[0]))[1] - 26, 'text-anchor': 'middle', class: 'lbl small', style: { fill: '#bfe9e4' } }, sv.marks, 'culvert') : null
  upd.push((t, T, cur) => {
    const tr = cur === 1 ? T0('snapped', -0.6) : -99
    pins.forEach((p, i) => {
      const a = cur === 1 ? tr + i * 0.35 : -99, fall = k(t, a, a + 0.5, E.out), snap = k(t, a + 0.9, a + 1.5, E.io)
      const x = lerp(p.px, p.x, snap), y = lerp(p.py - 90 * (1 - fall), p.y, snap)
      p.pin.setAttribute('transform', `translate(${x},${y})`); op(p.pin, fall); op(p.link, fall * (1 - snap) * 0.9)
    })
    op(snapLbl, cur === 1 ? k(t, tr + 1.2, tr + 1.7) * (1 - k(t, S.dur - 0.5, S.dur)) : 0)
    const flowOn = cur === 1 ? k(t, T0('flow direction', -0.4), T0('flow direction', 0.3)) : cur === 2 ? 1 - k(t, 0, 0.6) : 0
    chevrons.forEach((c, i) => {
      const s = ((T * 0.025 + i / chevrons.length) % 1), [x, y] = at(s)
      c.setAttribute('transform', `translate(${x},${y}) rotate(${P.angle(s) * 180 / Math.PI})`); op(c, flowOn * Math.sin(s * Math.PI) * 0.9)
    })
    const culOn = cur === 1 ? k(t, T0('culverts', -0.3), T0('culverts', 0.3)) : cur === 2 ? 1 - k(t, 0, 0.6) : 0
    sv.culverts(culOn); if (culLbl) op(culLbl, culOn)
  })

  // 2: belief over outfalls (rings + heat) and explanations (bars)
  const rings = G.cand.map((c) => {
    const [x, y] = at(c.s), g = h('g', {}, sv.marks)
    const r = ringAt(g, [x, y], 8, '#fff', 2.5, 'rgba(7,17,20,0.7)')
    const l = h('text', { x, y: y - 22, 'text-anchor': 'middle', class: 'lbl small' }, g, c.label)
    return { c, g, r, l, x, y }
  })
  const bars = div(root, 120, 600, '', '', { width: '600px' })
  const hypRows = b0.hyp.slice(0, 6).map(([label, p]) => {
    const row = h('div', { style: { display: 'grid', gridTemplateColumns: '220px 1fr 70px', alignItems: 'center', gap: '14px', margin: '0 0 10px', fontSize: '21px', color: '#eaf4f2' } }, bars)
    h('span', {}, row, shortHyp(label))
    const track = h('div', { style: { height: '10px', borderRadius: '5px', background: '#1c3238', overflow: 'hidden' } }, row)
    const fill = h('div', { style: { height: '100%', width: '0%', background: p > 50 ? '#d2553b' : '#8fa7a5' } }, track)
    const num = h('span', { style: { textAlign: 'right', color: '#93aaa7' } }, row, '0%')
    return { fill, num, p }
  })
  const wchip = div(root, 1290, 120, 'chip', `<span style="color:#f3c969">☀</span> ${F.weather.replace(/, max.*/, '')}`)
  const f0 = beliefFn(b0), f1 = beliefFn(b1)
  // 3: the next best check and both outcomes
  const recS = G.fracDist(kmIn(DF.rec?.title, 2300))
  const others = [0.3, 0.45, 0.62, 0.86].map((s) => at(s))
  const diamonds = [...others, at(recS)].map(([x, y], i) => h('rect', { x: x - 9, y: y - 9, width: 18, height: 18, transform: `rotate(45 ${x} ${y})`, fill: i === 4 ? '#2fb5aa' : 'rgba(191,233,228,0.35)', stroke: '#fff', 'stroke-width': 2 }, sv.marks))
  const [rx, ry] = at(recS)
  const pulse = h('circle', { cx: rx, cy: ry, r: 20, fill: 'none', stroke: '#2fb5aa', 'stroke-width': 3 }, sv.marks)
  const reason = (DF.rec?.reason ?? '').split(/(?<=\.)\s+/)
  const outcome = div(root, 1180, 640, 'card', `<div class="eyebrow" style="font-size:16px;margin-bottom:10px">Next best check</div>
    <div style="font-size:24px;font-weight:700;color:#fff;margin-bottom:14px">${DF.rec?.title ?? ''}</div>
    ${reason.map((r) => `<div style="font-size:20px;line-height:1.4;color:#c6d6d3;margin-top:6px">${r}</div>`).join('')}`, { width: '640px', padding: '24px 28px' })
  const result = /polluted|positive/i.test(b1.result ?? '') ? 'polluted' : 'clean'
  const stamp = h('g', {}, sv.marks)
  h('rect', { x: rx - 50, y: ry - 70, width: 100, height: 36, rx: 18, fill: result === 'clean' ? '#3f8f5a' : '#d2553b' }, stamp)
  h('text', { x: rx, y: ry - 45, 'text-anchor': 'middle', class: 'lbl', style: { fontSize: '19px' } }, stamp, result)
  const formula = div(root, 120, 610, 'card', `<div class="mono" style="font-size:22px;color:#fff">value = EVSI + 1.2 × bits<br>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;− cost − delay</div>
    <div style="font-size:18px;color:#93aaa7;margin-top:12px">EVSI: what the check is worth to the advisory decision.<br>bits: how much it narrows down where the source is.</div>`, { width: '600px', padding: '24px 28px' })
  // 4: the reporter's mission
  const repS = G.fracDist(kmIn(PF.where, 1100)), misS = G.fracDist(kmIn(PF.mission, 2400))
  const walk = h('path', { d: P.sub(Math.min(repS, misS), Math.max(repS, misS)), fill: 'none', stroke: '#fff', 'stroke-width': 4, 'stroke-dasharray': '2 10', 'stroke-linecap': 'round' }, sv.marks)
  const [px, py] = at(repS), [mx, my] = at(misS)
  const phone = h('g', { transform: `translate(${px},${py + 40})` }, sv.marks)
  h('rect', { x: -14, y: 0, width: 28, height: 48, rx: 6, fill: '#0f1e24', stroke: '#fff', 'stroke-width': 2.5 }, phone)
  h('text', { x: 0, y: 76, 'text-anchor': 'middle', class: 'lbl small' }, phone, 'reported here')
  const flag = ringAt(sv.marks, [mx, my], 14, '#fff', 4, '#2fb5aa')
  const dist = PF.mission?.match(/about ([\d.,]+ k?m)/)?.[1] ?? ''
  const LANGS = [['English', 'Can you help narrow it down?'], ['Norsk', 'Kan du hjelpe oss å finne kilden?'], ['Nederlands', 'Kunt u helpen de bron te vinden?'], ['Português', 'Pode ajudar a localizar a origem?']]
  const bubble = div(root, Math.min(mx - 40, 1400), my - 190, 'card', '', { width: '420px', padding: '18px 22px' })
  // 5: people decide
  const stats = [...(DF.stats ?? '').matchAll(/(\d+) ([A-Z][A-Za-z]+)/g)].map((m) => [m[2], m[1]])
  const fhir = div(root, 790, 190, 'card', `<div class="eyebrow" style="font-size:16px">To the utility</div>
    <div style="font-size:30px;font-weight:800;color:#fff;margin:8px 0 4px">HL7 FHIR R4 bundle</div>
    <div style="font-size:19px;color:#93aaa7;margin-bottom:16px">OneAquaHealth IG + 9 Dipper profiles</div>
    <div style="display:flex;flex-wrap:wrap;gap:8px">${stats.map(([r, n]) => `<span class="chip" style="font-size:17px;padding:7px 13px">${n} ${r}</span>`).join('')}</div>
    <div style="font-size:19px;color:#8fd1a8;margin-top:18px">✓ ${DF.refs || 'All references resolve.'}<br>✓ 0 errors in the official HL7 validator</div>`, { width: '500px' })
  const tiers = [['Observed', 'what people saw, smelled or measured'], ['Inferred', "the model's estimate, with its probability"], ['Possible risk', 'to people, animals and the stream'], ['Needs confirmation', 'what only a lab can confirm']]
  const adv = div(root, 1330, 190, 'card', `<div class="eyebrow" style="font-size:16px">To the public</div>
    <div style="font-size:30px;font-weight:800;color:#fff;margin:8px 0 16px">Contact advisory</div>
    ${tiers.map(([a, b]) => `<div class="tier" style="border-left:4px solid #2fb5aa;padding:6px 0 6px 14px;margin-bottom:10px"><div style="font-size:21px;font-weight:700;color:#fff">${a}</div><div style="font-size:17px;color:#93aaa7">${b}</div></div>`).join('')}
    <div class="ok chip teal" style="margin-top:8px;font-size:19px">✓ Approved by a public-health officer</div>`, { width: '500px' })
  const tierEls = [...adv.querySelectorAll('.tier')], ok = adv.querySelector('.ok')
  const dest = [div(root, 790, 760, 'chip', '→ Utility: confirm with a dye test'), div(root, 1330, 760, 'chip', '→ Public advisory map')]

  return (t, T) => {
    drift(T); sv.draw(1); sv.flow(T, 0.45)
    op(eb, 1); op(dots, 1); title.reveal(t, 0.15, 0.06); rise(body, k(t, 0.45, 1.0, E.out))
    for (const u of upd) u(t, T, step)
    // rings and heat (from step 2 on)
    const ringOn = step < 2 ? 0 : step === 2 ? k(t, T0('every candidate', -0.5), T0('every candidate', 0.6)) : 1
    const heatOn = step < 2 ? 0 : step === 2 ? k(t, T0('where it enters', -0.3), T0('where it enters', 1.0)) : 1
    const m = step < 3 ? 0 : step === 3 ? k(t, T0('Even', 0.2), T0('Even', 1.8)) : 1
    const fb = (s) => lerp(f0(s), f1(s), m)
    sv.heat(fb, heatOn * (step === 5 ? 1 - 0.7 * k(t, 0, 0.8) : 1))
    rings.forEach((r, i) => {
      op(r.g, ringOn * k(ringOn, i / 28, i / 28 + 0.5) * (step === 5 ? 1 - 0.7 * k(t, 0, 0.8) : 1))
      const p = lerp(pOf(b0, r.c.label), pOf(b1, r.c.label), m)
      r.r.setAttribute('r', 7 + 30 * Math.sqrt(p) * heatOn)
      r.l.textContent = p >= 0.05 && heatOn > 0.5 ? `${r.c.label} ${Math.round(p * 100)}%` : r.c.label
    })
    op(bars, step === 2 ? k(t, 1.0, 1.6) : 0)
    hypRows.forEach((r, i) => { const u = k(t, 1.2 + i * 0.12, 2.6 + i * 0.12); r.fill.style.width = `${r.p * u}%`; r.num.textContent = `${Math.round(r.p * u)}%` })
    op(wchip, step === 2 ? k(t, T0('weather', -0.4), T0('weather', 0.2)) : 0)
    // 3
    const s3 = step === 3
    diamonds.forEach((d, i) => op(d, s3 ? k(t, T0('next best', -0.2) + i * 0.12, T0('next best', 0.2) + i * 0.12) * (i === 4 ? 1 : 1 - 0.7 * k(t, T0('most', 0), T0('most', 0.6))) : 0))
    const pu = ((T * 0.8) % 1); pulse.setAttribute('r', 16 + pu * 26); op(pulse, s3 ? (1 - pu) * k(t, T0('most', -0.2), T0('most', 0.3)) : 0)
    rise(outcome, s3 ? k(t, T0('most', 0), T0('most', 0.6), E.out) : 0)
    pop(stamp, s3 ? k(t, T0('Even', -0.1), T0('Even', 0.4), E.lin) : 0); stamp.style.transformOrigin = `${rx}px ${ry - 52}px`
    rise(formula, s3 ? k(t, T0('least effort', -0.4), T0('least effort', 0.3), E.out) : 0)
    // 4
    const s4 = step === 4, wu = s4 ? k(t, T0('ask', -0.3), T0('ask', 1.6)) : 0
    walk.style.strokeDashoffset = `${-T * 30}`; op(walk, wu); op(phone, s4 ? k(t, 0.2, 0.8) : 0); pop(flag, s4 ? k(t, T0('short mission', -0.3), T0('short mission', 0.2), E.lin) : 0)
    flag.style.transformOrigin = `${mx}px ${my}px`
    const tl = s4 ? T0('own language', -0.3) : 0, li = s4 ? clamp(Math.floor((t - tl) / 0.8), 0, 3) : 0
    const [lang, text] = LANGS[t < tl ? 0 : li]
    bubble.innerHTML = `<div class="eyebrow" style="font-size:15px">${lang}${dist ? ` · about ${dist} away` : ''}</div><div style="font-size:24px;font-weight:700;color:#fff;margin-top:6px">${text}</div>`
    rise(bubble, s4 ? k(t, T0('short mission', -0.1), T0('short mission', 0.4), E.out) : 0)
    // 5
    const s5 = step === 5
    rise(fhir, s5 ? k(t, T0('utility', -0.4), T0('utility', 0.3), E.out) : 0)
    rise(adv, s5 ? k(t, T0('public-health', -0.4), T0('public-health', 0.3), E.out) : 0)
    tierEls.forEach((e, i) => { e.style.borderLeftColor = s5 && t > T0(['observed', 'inferred', 'inferred', 'inferred'][i], i > 1 ? 0.4 * (i - 1) : 0) ? '#f3c969' : '#2fb5aa' })
    pop(ok, s5 ? k(t, T0('approves', -0.1), T0('approves', 0.4), E.lin) : 0)
    rise(dest[0], s5 ? k(t, T0('utility', 0.6), T0('utility', 1.2)) : 0); rise(dest[1], s5 ? k(t, T0('approves', 0.6), T0('approves', 1.2)) : 0)
  }
}

KINDS.bench = (root, S) => {
  const drift = backdrop(root)
  const eb = div(root, 150, 150, 'eyebrow', 'SourceBench · simulation')
  const title = words(root, 150, 190, 'Twice the success of walking the bank.', 'headline', { width: '1600px' })
  const tOk = wt(S, 'doubles'), tChecks = wt(S, 'half the checks'), tCost = wt(S, 'lower cost')
  const chart = (x, label, key, max, unit, t0) => {
    div(root, x, 350, 'eyebrow', label, { color: '#93aaa7' })
    return BENCH.map((b, i) => {
      const y = 410 + i * 120
      div(root, x, y, '', b.name, { fontSize: '26px', fontWeight: b.us ? 800 : 550, color: b.us ? '#fff' : '#c6d6d3' })
      const track = div(root, x, y + 44, '', '', { width: '640px', height: '34px', borderRadius: '8px', background: '#12252b' })
      const fill = h('div', { style: { height: '100%', width: '0%', borderRadius: '8px', background: b.us ? 'linear-gradient(90deg,#157f78,#2fb5aa)' : '#51676a' } }, track)
      const num = div(root, x + 660, y + 38, '', '', { fontSize: '36px', fontWeight: 800, color: b.us ? '#43c3b7' : '#c6d6d3' })
      return (t) => { const u = k(t, t0 + i * 0.18, t0 + 1.1 + i * 0.18, E.out); fill.style.width = `${(b[key] / max) * 100 * u}%`; num.textContent = `${(b[key] * u).toFixed(key === 'checks' && b[key] % 1 ? 1 : 0)}${unit}`; op(num, u) }
    })
  }
  const a = chart(150, 'Localized the right outfall', 'ok', 60, '%', tOk - 0.8), b = chart(1010, 'Median checks when it did', 'checks', 22, '', tChecks - 0.8)
  const cost = div(root, 1010, 790, 'chip', `Mean cost per case: <b style="color:#43c3b7;margin-left:8px">1.30</b>&nbsp;Dipper · 1.49 bank walk`)
  const foot = div(root, 150, 784, 'body', 'Simulation, not field results: 7 stream networks (5 real OneAquaHealth streams, 2 synthetic), 40 trials each, a 25-check budget, and a world noisier than the model.', { fontSize: '20px', width: '780px' })
  return (t, T) => {
    drift(T); op(eb, k(t, 0, 0.5)); title.reveal(t, 0.2, 0.06); a.forEach((f) => f(t)); b.forEach((f) => f(t))
    rise(cost, k(t, tCost - 0.3, tCost + 0.3)); op(foot, k(t, 1, 1.8) * 0.9)
  }
}

KINDS.live = (root, S) => {
  const drift = backdrop(root)
  const dot = div(root, 840, 440, '', '', { width: '34px', height: '34px', borderRadius: '50%', background: '#ff4d3d', boxShadow: '0 0 40px #ff4d3d' })
  const live = div(root, 900, 418, '', 'LIVE', { fontSize: '76px', fontWeight: 800, letterSpacing: '0.12em', color: '#fff' })
  const note = div(root, 0, 540, '', 'The deployed app, recorded as it runs', { width: '1920px', textAlign: 'center', fontSize: '34px', color: '#bfe9e4' })
  return (t, T) => {
    drift(T); op(dot, k(t, 0, 0.3) * (0.6 + 0.4 * Math.sin(T * 5))); rise(live, k(t, 0.1, 0.6, E.out)); rise(note, k(t, 0.6, 1.2, E.out))
  }
}

// ---------- live capture ----------
function frameAt(sess, c) {
  const fr = TL.capture[sess].frames
  let lo = 0, hi = fr.length - 1
  if (c <= fr[0].t) return fr[0].f
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (fr[mid].t <= c) lo = mid; else hi = mid - 1 }
  return `${DIR}capture/${sess}/${fr[lo].f}`
}
const capTime = (S, t) => Math.min(S.capEnd, S.capStart + t * S.speed)
const pairs = (sess) => {
  const ev = TL.capture[sess].events, aims = ev.filter((e) => e.kind === 'aim'), taps = ev.filter((e) => e.kind === 'tap')
  return aims.map((a, i) => ({ a, tap: taps[i] }))
}
const PHONE_SHOTS = TL.scenes.filter((s) => s.kind === 'phone')

KINDS.phone = (root, S) => {
  const drift = backdrop(root); liveBadge(root)
  const sc = 1.05, sw = 390 * sc, sh = 844 * sc, dx = 300, dy = (1080 - sh - 30) / 2
  const dev = div(root, dx, dy, 'device', '', {})
  const screen = h('div', { class: 'screen', style: { width: `${sw}px`, height: `${sh}px` } }, dev)
  const img = h('img', { style: { width: `${sw}px`, height: `${sh}px` } }, screen)
  const touch = h('div', { class: 'touch' }, screen), ripple = h('div', { class: 'ripple' }, screen)
  const n = PHONE_SHOTS.indexOf(PHONE_SHOTS.find((x) => x.id === S.id)) + 1
  const col = div(root, 900, 0, '', '', { width: '900px', height: '1080px', display: 'flex', flexDirection: 'column', justifyContent: 'center' })
  const eb = h('div', { class: 'eyebrow', style: { marginBottom: '22px' } }, col, `The citizen · ${n} of ${PHONE_SHOTS.length}`)
  const head = words(col, 0, 0, S.head ?? '', 'headline', { position: 'relative', fontSize: '84px' })
  const sub = h('div', { style: { marginTop: '34px', width: '860px', fontSize: '36px', lineHeight: 1.4, color: '#dfeae8', fontWeight: 500 } }, col, S.text ?? '')
  const P2 = pairs('phone')
  return (t, T) => {
    drift(T)
    const c = capTime(S, t); setImg(img, frameAt('phone', c))
    op(eb, 1); head.reveal(t, 0, 0.05, 0.4); op(head.el, 1 - k(t, S.dur - 0.25, S.dur)); op(sub, k(t, S.lead - 0.1, S.lead + 0.3) * (1 - k(t, S.dur - 0.25, S.dur)))
    let tv = 0, rv = 0, x = 0, y = 0
    for (const { a, tap } of P2) {
      if (!tap || c < a.t - 0.05 || c > tap.t + 0.8) continue
      x = a.x * sc; y = a.y * sc
      tv = k(c, a.t, a.t + 0.25) * (1 - k(c, tap.t + 0.3, tap.t + 0.6))
      rv = c >= tap.t ? k(c, tap.t, tap.t + 0.5, E.out) : 0
    }
    css(touch, x, y, tv, `scale(${rv > 0 && rv < 0.4 ? 0.82 : 1})`); css(ripple, x, y, rv > 0 ? (1 - rv) * 0.9 : 0, `scale(${0.5 + rv * 1.6})`)
  }
}
function css(e, x, y, o, tf) { e.style.left = `${x}px`; e.style.top = `${y}px`; op(e, o); e.style.transform = tf }

// Desktop: a browser window with a camera that moves between named boxes the capture logged.
const DESK_SCENES = TL.scenes.filter((s) => s.kind === 'desk')
const boxAt = (name, c) => { const bs = DESK.events.filter((e) => e.kind === 'box' && e.name === name); let b = null; for (const e of bs) if (e.t <= c + 0.05) b = e; return b ?? bs.find((e) => e.t > c) }
function viewFor(name, z, c) {
  if (name === 'full' || !z || z <= 1) return { x: 0, y: 0, z: 1 }
  const b = boxAt(name, c); if (!b) return { x: 0, y: 0, z: 1 }
  const w = 1440 / z, hh = 900 / z
  // Centre the box, but start from its left or top edge when it is wider or taller than the view.
  const place = (bx, bw, vw, room) => clamp(bw > vw * 0.9 ? bx - 16 : bx + bw / 2 - vw / 2, 0, room)
  return { x: place(b.x, b.w, w, 1440 - w), y: place(b.y, b.h, hh, 900 - hh), z }
}
const mixView = (a, b, u) => ({ x: lerp(a.x, b.x, u), y: lerp(a.y, b.y, u), z: lerp(a.z, b.z, u) })
const CAMS = new Map()
{
  let last = { x: 0, y: 0, z: 1 }
  for (const S of DESK_SCENES) {
    const kfs = (S.cam ?? [[0, 'full']]).map(([at, name, z]) => ({ at, v: viewFor(name, z, S.capStart + at * S.speed) }))
    CAMS.set(S.id, { from: last, kfs }); last = kfs.at(-1).v
  }
}
KINDS.desk = (root, S) => {
  const drift = backdrop(root)
  const sc = 1.0625, vw = 1440 * sc, vh = 900 * sc, wx = (1920 - vw) / 2, wy = 26
  const win = div(root, wx, wy, 'window', '', { width: `${vw}px` })
  const bar = h('div', { class: 'titlebar' }, win)
  for (const c of ['#ff5f57', '#febc2e', '#28c840']) h('i', { style: { background: c } }, bar)
  const url = h('div', { class: 'url' }, bar)
  const view = h('div', { class: 'viewport', style: { width: `${vw}px`, height: `${vh}px` } }, win)
  const inner = h('div', { style: { position: 'absolute', left: 0, top: 0, width: '1440px', height: '900px', transformOrigin: '0 0' } }, view)
  const img = h('img', { style: { width: '1440px', height: '900px' } }, inner)
  const click = h('div', { class: 'click' }, view)
  const cursor = h('svg', { class: 'cursor', viewBox: '0 0 30 30', html: '<path d="M4 3 L4 24 L9.5 18.5 L13.5 27 L17 25.4 L13 17 L21 17 Z" fill="#111" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>' }, view)
  const cam = CAMS.get(S.id), P2 = pairs('desk'), beats = DESK.events.filter((e) => e.kind === 'beat')
  const camAt = (t) => { let v = cam.from; for (const f of cam.kfs) { if (t < f.at) break; v = mixView(v, f.v, k(t, f.at, f.at + 1.3)) } return v }
  const cursorAt = (c) => {
    let pos = { x: 1250, y: 760 }, press = 0, ring = 0
    for (const { a, tap } of P2) {
      if (!tap || c < a.t) break
      const u = k(c, a.t, tap.t, E.io); pos = { x: lerp(pos.x, a.x, u), y: lerp(pos.y, a.y, u) }
      if (c >= tap.t && c < tap.t + 0.6) { ring = k(c, tap.t, tap.t + 0.55, E.out); press = c < tap.t + 0.15 ? 1 : 0 }
    }
    return { ...pos, press, ring }
  }
  return (t, T) => {
    drift(T)
    const c = capTime(S, t); setImg(img, frameAt('desk', c))
    const v = camAt(t); inner.style.transform = `scale(${sc * v.z}) translate(${-v.x}px, ${-v.y}px)`
    const cur = cursorAt(c), X = (cur.x - v.x) * v.z * sc, Y = (cur.y - v.y) * v.z * sc
    cursor.style.transform = `translate(${X - 3}px, ${Y - 3}px) scale(${cur.press ? 0.86 : 1})`
    css(click, X, Y, cur.ring > 0 ? (1 - cur.ring) : 0, `scale(${0.4 + cur.ring * 1.4})`)
    let u = beats[0]?.url ?? '/'; for (const b of beats) if (b.t <= c) u = b.url
    const id = u.match(/#\/ops\/([^/?]+)/)?.[1]
    url.textContent = `Dipper · ${id ? `Case ${decodeURIComponent(id)}` : u.includes('#/public') ? 'Public advisories' : 'Operations'}`
  }
}

// ---------- close ----------
KINDS.loop = (root, S) => {
  const drift = backdrop(root)
  const head = words(root, 150, 150, 'One loop, from a walker to a verified fix.', 'title', { width: '1600px' })
  const names = [['Report', 'a citizen, in a minute'], ['Case', 'reports grouped per stretch'], ['Next best check', 'value of information'], ['Source', 'localized outfall'], ['Hand-off', 'FHIR to the utility'], ['Advisory', 'approved by public health'], ['Fix verified', 'after a clean follow-up']]
  const keys = ['Report', 'Case', 'Next best', 'Source', 'Hand-off', 'Advisory', 'Fix verified']
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, root)
  const pts = names.map((_, i) => [210 + i * 250, 560 + (i % 2 ? 70 : -40)])
  const d = 'M' + pts.map((p) => p.join(' ')).join(' L')
  h('path', { d, fill: 'none', stroke: '#15282e', 'stroke-width': 14, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, svg)
  const line = h('path', { d, fill: 'none', stroke: '#43c3b7', 'stroke-width': 6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', pathLength: 1, 'stroke-dasharray': '1 1' }, svg)
  const nodes = names.map(([a, b], i) => {
    const [x, y] = pts[i], g = h('g', { style: { transformOrigin: `${x}px ${y}px` } }, svg)
    h('circle', { cx: x, cy: y, r: 34, fill: i === 6 ? '#2fb5aa' : '#0d1d22', stroke: '#43c3b7', 'stroke-width': 4 }, g)
    h('text', { x, y: y + 10, 'text-anchor': 'middle', class: 'lbl', style: { fontSize: '28px', fontWeight: 800 } }, g, i === 6 ? '✓' : String(i + 1))
    h('text', { x, y: y + 80, 'text-anchor': 'middle', class: 'lbl', style: { fontSize: '26px', fontWeight: 750 } }, g, a)
    h('text', { x, y: y + 110, 'text-anchor': 'middle', class: 'lbl small', style: { fontSize: '19px' } }, g, b)
    return g
  })
  const times = keys.map((w) => wt(S, w))
  return (t, T) => {
    drift(T); head.reveal(t, 0.1, 0.05)
    nodes.forEach((g, i) => pop(g, k(t, times[i] - 0.2, times[i] + 0.3, E.lin)))
    let u = 0; times.forEach((x, i) => { if (i) u = Math.max(u, (i - 1 + k(t, times[i - 1], x)) / 6) })
    line.setAttribute('stroke-dashoffset', 1 - u)
  }
}

const ICONS = {
  data: '<circle cx="32" cy="32" r="22" fill="none" stroke="#43c3b7" stroke-width="4"/><path d="M10 32h44M32 10c9 8 9 36 0 44M32 10c-9 8-9 36 0 44" fill="none" stroke="#43c3b7" stroke-width="3.5"/>',
  std: '<path d="M22 14c-8 0-8 6-8 12s-4 6-4 6 4 0 4 6 0 12 8 12M42 14c8 0 8 6 8 12s4 6 4 6-4 0-4 6 0 12-8 12" fill="none" stroke="#43c3b7" stroke-width="4" stroke-linecap="round"/><circle cx="32" cy="32" r="4" fill="#43c3b7"/>',
  priv: '<path d="M32 8l20 8v14c0 13-9 22-20 26-11-4-20-13-20-26V16z" fill="none" stroke="#43c3b7" stroke-width="4" stroke-linejoin="round"/><path d="M23 32l7 7 12-13" fill="none" stroke="#43c3b7" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
  a11y: '<circle cx="32" cy="12" r="5" fill="#43c3b7"/><path d="M14 22l18 4 18-4M32 26v12l-9 16M32 38l9 16" fill="none" stroke="#43c3b7" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
  box: '<path d="M32 8l22 12v24L32 56 10 44V20z M10 20l22 12 22-12 M32 32v24" fill="none" stroke="#43c3b7" stroke-width="4" stroke-linejoin="round"/>',
}
KINDS.pillars = (root, S) => {
  const drift = backdrop(root)
  const head = words(root, 150, 150, 'Built to be adopted.', 'headline', { width: '1600px' })
  const cards = [
    ['data', 'Open data', 'OpenStreetMap streams and Open-Meteo weather', 'open data'],
    ['std', 'Open standards', 'HL7 FHIR R4 on the OneAquaHealth IG, 0 validator errors', 'open standards'],
    ['priv', 'Private by design', 'Anonymous reports, faces blurred, no IP addresses in logs', 'private'],
    ['a11y', 'Accessible', '4 languages, works offline, 0 axe accessibility violations', 'accessible'],
    ['box', 'One container', 'Web app and API together, deploys anywhere', 'single container'],
  ].map(([ic, a, b, w], i) => ({ w, e: div(root, 150 + i * 332, 330, 'card', `<svg viewBox="0 0 64 64" width="64" height="64">${ICONS[ic]}</svg>
    <div style="font-size:30px;font-weight:800;color:#fff;margin:22px 0 10px">${a}</div><div style="font-size:22px;line-height:1.4;color:#a9bebb">${b}</div>`, { width: '304px', height: '360px' }) }))
  const cities = [...new Set(['Coimbra', 'Oslo', 'Ghent'])]
  const row = div(root, 150, 760, '', `<span class="eyebrow" style="margin-right:22px">Ready for any city</span>${cities.map((c) => `<span class="chip" style="margin-right:12px">${c}</span>`).join('')}<span class="body" style="font-size:22px">six real streams mapped today</span>`)
  const tCity = wt(S, 'any city')
  return (t, T) => { drift(T); head.reveal(t, 0.1); cards.forEach((c) => rise(c.e, k(t, wt(S, c.w) - 0.3, wt(S, c.w) + 0.3, E.out))); rise(row, k(t, tCity - 0.4, tCity + 0.2)) }
}

KINDS.end = (root, S) => {
  const drift = backdrop(root)
  const logo = makeLogo(root, 840, 190, 240)
  const svg = h('svg', { viewBox: '0 0 1920 1080', class: 'layer' }, root)
  const waves = [0, 1, 2].map(() => h('ellipse', { cx: 960, cy: 390, rx: 10, ry: 3, fill: 'none', stroke: '#bfe9e4', 'stroke-width': 2 }, svg))
  const word = div(root, 0, 470, '', 'Dipper', { width: '1920px', textAlign: 'center', fontSize: '150px', fontWeight: 800, letterSpacing: '-0.045em', color: '#fff' })
  const tag = div(root, 0, 650, '', 'Every report brings the source closer.', { width: '1920px', textAlign: 'center', fontSize: '42px', fontWeight: 600, color: '#bfe9e4' })
  const what = div(root, 0, 740, 'body', 'Find urban stream pollution at its source.', { width: '1920px', textAlign: 'center', fontSize: '28px' })
  const black = div(root, 0, 0, '', '', { width: '1920px', height: '1080px', background: '#000' })
  return (t, T) => {
    drift(T); logo(k(t, 0.1, 1.8, E.lin), T)
    waves.forEach((w, i) => { const c = ((T * 0.3 + i / 3) % 1); w.setAttribute('rx', 40 + c * 700); w.setAttribute('ry', 10 + c * 160); op(w, (1 - c) * 0.28 * k(t, 1.5, 2.4)) })
    rise(word, k(t, 1.0, 1.7, E.out)); rise(tag, k(t, S.lead + 0.6, S.lead + 1.3, E.out)); rise(what, k(t, S.lead + 1.6, S.lead + 2.3))
    op(black, k(t, S.dur - 1.4, S.dur - 0.1, E.in))
  }
}

// ---------- assemble ----------
const built = TL.scenes.map((S, i) => {
  const root = h('div', { class: 'scene', style: { zIndex: i + 1 } }, stage)
  if (!KINDS[S.kind]) throw new Error(`no scene kind ${S.kind}`)
  return { S, root, draw: KINDS[S.kind](root, S, i) }
})
h('div', { class: 'vignette', style: { zIndex: 999 } }, stage)
const subs = h('div', { id: 'subs' }, stage)
const grain = h('div', { id: 'grain' }, stage)
{
  const c = document.createElement('canvas'); c.width = c.height = 256
  const g = c.getContext('2d'), im = g.createImageData(256, 256)
  let s = 7; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647)
  for (let i = 0; i < im.data.length; i += 4) { const v = rnd() * 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255 }
  g.putImageData(im, 0, 0); grain.style.backgroundImage = `url(${c.toDataURL()})`
}
const NO_SUBS = new Set(['phone', 'question', 'loop', 'end'])

async function seek(T) {
  pending = []
  let top = null
  for (const b of built) {
    const { S } = b, on = T >= S.start - 1e-6 && T < S.start + S.dur + 1e-6
    b.root.style.display = on ? '' : 'none'
    if (!on) continue
    const t = T - S.start
    b.root.style.opacity = b === built[0] ? k(t, 0, 1.2, E.lin) : S.xin > 0 ? k(t, 0, S.xin, E.lin) : 1
    b.draw(t, T); top = S
  }
  const cur = TL.scenes.find((S) => S.vo && T >= S.vo.start - 0.1 && T <= S.vo.start + S.vo.dur + 0.25)
  const showSubs = TL.subs && Q.get('subs') !== '0' && cur && !NO_SUBS.has(cur.kind) && !(top && NO_SUBS.has(top.kind))
  if (showSubs) { subs.textContent = cur.text; op(subs, k(T, cur.vo.start - 0.1, cur.vo.start + 0.1, E.lin) * (1 - k(T, cur.vo.start + cur.vo.dur + 0.05, cur.vo.start + cur.vo.dur + 0.25, E.lin))) } else op(subs, 0)
  const f = Math.round(T * TL.fps); grain.style.backgroundPosition = `${(f * 97) % 256}px ${(f * 61) % 256}px`
  await Promise.all(pending)
}
await document.fonts.ready
window.film = { ready: true, seek, duration: TL.duration }
if (Q.has('t')) await seek(Number(Q.get('t')))
if (Q.has('play')) { const t0 = performance.now() - Number(Q.get('play') || 0) * 1000; const loop = async () => { await seek((performance.now() - t0) / 1000); requestAnimationFrame(loop) }; loop() }
