import { useEffect, useMemo, useState } from 'react'
import { useAnnounce } from './App'
import CaseMap from './Map'
import { api, ApiError, DEFAULT_REACH, type CitizenCase, type GeoJSON, type PhotoResult, type ReachInfo } from './api'
import { FEATURES, LANG_NAME, STATUS, T, km, languagesFor, pick, preferredLang, type Lang } from './i18n'

const QUEUE_KEY = 'dipper.queue'
type Queued = { reach_id: string; lat: number; lon: number; features: Record<string, boolean>; observed_at: string; client_id: string }
const readQueue = (): Queued[] => { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]') } catch { return [] } }
const writeQueue = (q: Queued[]) => { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)) } catch { /* storage unavailable */ } }
let flushing = false  // one flush at a time: the page load and the 'online' event can both start one

// The report token lets this phone follow its own reports after a reload. Kept on the device only.
const RECENT_KEY = 'dipper.reports'
type Recent = { case_id: string; token: string; reach: string; at: string }
const readRecent = (): Recent[] => {
  try {
    const cutoff = Date.now() - 14 * 86400_000
    return (JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') as Recent[]).filter((r) => Date.parse(r.at) > cutoff)
  } catch { return [] }
}
const remember = (r: Recent) => {
  try {
    const list = [r, ...readRecent().filter((x) => x.case_id !== r.case_id)].slice(0, 10)
    localStorage.setItem(RECENT_KEY, JSON.stringify(list))
  } catch { /* storage unavailable */ }
}

/** A keyboard and screen-reader alternative to tapping the map: named places, then points every ~250 m along the stream. */
type Landmark = { key: string; lat: number; lon: number; place?: string; km?: number; nearPlace?: string }
function landmarks(reach: GeoJSON | null): Landmark[] {
  if (!reach) return []
  const nodes = new Map<string, { lat: number; lon: number; d: number }>()
  for (const f of reach.features) if (f.properties.role === 'node')
    nodes.set(f.properties.id, { lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], d: f.properties.dist_to_outlet_m ?? 0 })
  const places = reach.features.filter((f) => f.properties.role === 'place' && nodes.has(f.properties.node_id))
    .map((f) => ({ label: f.properties.label as string, n: nodes.get(f.properties.node_id)! }))
  const out: Landmark[] = places.map((p, i) => ({ key: `p${i}`, lat: p.n.lat, lon: p.n.lon, place: p.label }))
  const sorted = [...nodes.values()].sort((a, b) => a.d - b.d)
  let next = 0
  for (const n of sorted) {
    if (n.d < next) continue
    next = n.d + 250
    const close = places.map((p) => ({ p, m: Math.hypot((p.n.lat - n.lat) * 111_320, (p.n.lon - n.lon) * 111_320 * Math.cos(n.lat * Math.PI / 180)) }))
      .filter((x) => x.m < 400).sort((a, b) => a.m - b.m)[0]
    out.push({ key: `n${out.length}`, lat: n.lat, lon: n.lon, km: n.d / 1000, nearPlace: close?.p.label })
  }
  return out
}

export default function Citizen() {
  const announce = useAnnounce()
  const [reaches, setReaches] = useState<ReachInfo[]>([])
  const [reachId, setReachId] = useState(DEFAULT_REACH)
  const offered = languagesFor(reaches.find((r) => r.id === reachId)?.city ?? 'Coimbra')
  const [chosen, setLang] = useState<Lang | null>(null)
  const lang: Lang = chosen && offered.includes(chosen) ? chosen : preferredLang(offered)
  const t = T[lang]
  const [token, setToken] = useState<string | null>(null)
  const [reach, setReach] = useState<GeoJSON | null>(null)
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null)
  const [pickedKey, setPickedKey] = useState('')
  const [feats, setFeats] = useState<Record<string, boolean>>({})
  const [cleanReport, setCleanReport] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [summary, setSummary] = useState<CitizenCase | null>(null)
  const [photoRes, setPhotoRes] = useState<PhotoResult['photo'] | null>(null)
  const [dismissed, setDismissed] = useState<string[]>([])
  const [recent, setRecent] = useState<Recent[]>(readRecent)
  const [cleanNoCase, setCleanNoCase] = useState(false)
  const [outcome, setOutcome] = useState<number | null>(null)
  const [skipMission, setSkipMission] = useState(false)
  const [queued, setQueued] = useState(readQueue().length)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.reaches().then(setReaches).catch(() => {}) }, [])
  useEffect(() => { setReach(null); setPicked(null); setPickedKey(''); api.reach(reachId).then(setReach).catch((e) => setError(e.message)) }, [reachId])
  useEffect(() => {
    const flush = async () => {
      if (flushing) return
      flushing = true
      try {
        const q = readQueue(); const left: Queued[] = []
        for (const item of q) {
          try {
            const r = await api.signal(item)
            if (r.case_id && r.report_token) remember({ case_id: r.case_id, token: r.report_token, reach: item.reach_id, at: item.observed_at })
          } catch (e) {  // keep it for later unless the server rejected the report itself (bad location or data)
            if (!(e instanceof ApiError) || e.status >= 500 || e.status === 409 || e.status === 429) left.push(item)
          }
        }
        writeQueue(left); setQueued(left.length); setRecent(readRecent())
      } finally { flushing = false }
    }
    window.addEventListener('online', flush); if (navigator.onLine) flush()
    return () => window.removeEventListener('online', flush)
  }, [])

  const marks = useMemo(() => landmarks(reach), [reach])
  const refresh = async (id: string, tok = token) => { if (tok) setSummary(await api.citizenCase(id, tok)) }
  const locate = () => navigator.geolocation?.getCurrentPosition(
    (p) => { setPicked({ lat: p.coords.latitude, lon: p.coords.longitude }); announce(t.picked) },
    () => setError(t.tapHint), { enableHighAccuracy: true, timeout: 10000 })

  const send = async () => {
    if (!picked) { setError(t.tapHint); return }
    const answers = cleanReport ? {} : feats
    if (!cleanReport && !Object.values(feats).some(Boolean)) { setError(t.none); return }
    setBusy(true); setError(null)
    const body = { reach_id: reachId, lat: picked.lat, lon: picked.lon, features: answers }
    const queuedBody: Queued = { ...body, observed_at: new Date().toISOString(), client_id: crypto.randomUUID().replace(/-/g, '') }
    try {
      const r = file ? await api.signalPhoto(file, body) : await api.signal(queuedBody)
      if ('photo' in r) setPhotoRes(r.photo)
      if (!r.case_id || !r.report_token) { setCleanNoCase(true); announce(t.cleanThanks); return }
      remember({ case_id: r.case_id, token: r.report_token, reach: reachId, at: queuedBody.observed_at }); setRecent(readRecent())
      setToken(r.report_token); setCaseId(r.case_id); await refresh(r.case_id, r.report_token); announce(`${t.thanks} ${r.case_id}`)
      window.setTimeout(() => document.getElementById('thanks')?.focus(), 0)
    } catch (e: any) {
      if (!(e instanceof ApiError)) {
        const q = [...readQueue(), queuedBody]; writeQueue(q); setQueued(q.length)
        setError(file ? `${t.offline} ${t.offlinePhoto}` : t.offline)
      } else setError(e.status === 422 && /stream/.test(e.message) ? t.farAway : e.message)
    } finally { setBusy(false) }
  }

  const outcomeText = (cut: number) => (cut >= 1 ? t.narrowed.replace('{n}', String(cut)) : t.noChange)
  const answer = async (positive: boolean) => {
    if (!caseId || !token || !summary?.mission) return
    setBusy(true)
    try {
      const r = await api.citizenCheck(caseId, token, summary.mission.key, positive)
      const cut = Math.max(0, Math.round((1 - 2 ** -r.search_narrowed_bits) * 100))
      setOutcome(cut); await refresh(caseId); announce(`${t.outcome}: ${outcomeText(cut)}`)
    } catch (e: any) { setError(e.message); await refresh(caseId) } finally { setBusy(false) }
  }

  const missionWhere = (() => {
    const m = summary?.mission
    if (!m) return ''
    const near = marks.filter((l) => l.place).map((l) => ({ l, d: Math.hypot((l.lat - m.lat) * 111_320, (l.lon - m.lon) * 111_320 * Math.cos(m.lat * Math.PI / 180)) }))
      .filter((x) => x.d < 400).sort((a, b) => a.d - b.d)[0]
    const spot = m.kind === 'outfall' ? t.outfall : `${t.streamAt} ${km(m.km_above_outlet, lang)} ${t.up}`
    return near ? `${spot} (${t.near} ${near.l.place})` : spot
  })()

  const reset = () => { setCaseId(null); setSummary(null); setFeats({}); setCleanReport(false); setPicked(null); setPickedKey(''); setOutcome(null); setFile(null); setPhotoRes(null); setDismissed([]); setSkipMission(false); setToken(null); setCleanNoCase(false) }
  const reopen = async (r: Recent) => {
    setError(null); setReachId(r.reach); setToken(r.token); setCaseId(r.case_id)
    try { await refresh(r.case_id, r.token) } catch (e: any) { setError(e.message); setCaseId(null) }
  }

  return (
    <div className="citizen" lang={lang}>
      <div className="phone">
        <div className="phone-head">
          {offered.length > 1 && <div className="lang" role="group" aria-label={offered.map((l) => T[l].language).join(' / ')}>
            {offered.map((l) => (
              <button key={l} lang={l} aria-pressed={l === lang} className={l === lang ? 'on' : ''} onClick={() => setLang(l)}>{LANG_NAME[l]}</button>))}
          </div>}
        </div>
        {queued > 0 && <p className="note" role="status">{queued} {t.queued}</p>}

        {cleanNoCase && <>
          <h1 className="thanks" id="thanks" tabIndex={-1}>{t.cleanThanks}</h1>
          <button className="wide" onClick={reset}>{t.another}</button>
        </>}

        {!caseId && !cleanNoCase && <>
          <h1>{t.title}</h1>
          {recent.length > 0 && <nav className="recent" aria-label={t.recent}>
            <h2>{t.recent}</h2>
            <ul>{recent.map((r) => <li key={r.case_id}><button className="linkish" onClick={() => reopen(r)}>
              {r.case_id} · {reaches.find((x) => x.id === r.reach)?.name ?? r.reach} · {new Date(r.at).toLocaleDateString(lang === 'nb' ? 'nb-NO' : lang)}</button></li>)}</ul>
          </nav>}
          <p className="muted">{t.intro}</p>
          {reaches.length > 1 && <>
            <label htmlFor="reach">{t.stream}</label>
            <select id="reach" value={reachId} onChange={(e) => setReachId(e.target.value)}>
              {reaches.map((r) => <option key={r.id} value={r.id}>{r.name}, {r.city}</option>)}</select></>}
          <h2>{t.where}</h2>
          <button className="wide" onClick={locate}>{t.useLoc}</button>
          <p className="muted small" id="tap-hint">{t.tapHint}</p>
          <div className="minimap"><CaseMap reach={reach} citizen picked={picked} onPick={(lat, lon) => { setPicked({ lat, lon }); setPickedKey(''); announce(t.picked) }} height={220}
            label={t.tapHint} /></div>
          <label htmlFor="landmark">{t.landmark}</label>
          <select id="landmark" value={pickedKey} onChange={(e) => {
            const l = marks.find((m) => m.key === e.target.value); setPickedKey(e.target.value)
            if (l) { setPicked({ lat: l.lat, lon: l.lon }); announce(t.picked) } }}>
            <option value="">{t.choose}</option>
            {marks.map((m) => <option key={m.key} value={m.key}>{m.place ? `${t.near} ${m.place}`
              : `${km(m.km!, lang)} ${t.up}${m.nearPlace ? ` (${t.near} ${m.nearPlace})` : ''}`}</option>)}
          </select>
          {picked && <p className="muted small" role="status">{t.picked}: {(() => {
            const m = marks.find((x) => x.key === pickedKey)
            return m ? (m.place ? `${t.near} ${m.place}` : `${km(m.km!, lang)} ${t.up}`) : `${picked.lat.toFixed(5)}, ${picked.lon.toFixed(5)}`
          })()}</p>}
          <fieldset className="toggles-set" disabled={cleanReport}>
            <legend>{t.what}</legend>
            <div className="toggles">{FEATURES.map((f) => (
              <button key={f.id} type="button" className={feats[f.id] ? 'toggle on' : 'toggle'} aria-pressed={!!feats[f.id]}
                onClick={() => setFeats((s) => ({ ...s, [f.id]: !s[f.id] }))}>{f.label[lang]}</button>))}</div>
          </fieldset>
          <label className="check"><input type="checkbox" checked={cleanReport} onChange={(e) => setCleanReport(e.target.checked)} /> {t.clean}</label>
          <label className="photo-pick" htmlFor="photo-input">
            <span>{file ? file.name : t.photo}</span>
            <input id="photo-input" type="file" accept="image/*" capture="environment" aria-describedby="photo-consent"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <p id="photo-consent" className="muted small">{t.photoConsent}</p>
          <button className="primary wide" disabled={busy} onClick={send}>{busy ? t.sending : t.send}</button>
          <p className="muted small">{t.safety}</p>
        </>}

        {caseId && summary && <>
          <h1 className="thanks" id="thanks" tabIndex={-1}>{t.thanks} {summary.id}.</h1>
          <p><span className="muted">{t.status}:</span> <strong>{STATUS[summary.status]?.[lang] ?? summary.status}</strong></p>
          {summary.advisory && <div className="advisory-box" role="note"><strong>{t.advisory}</strong><p lang={summary.advisory[lang] ? lang : 'en'}>{pick(summary.advisory, lang)}</p></div>}
          {photoRes && <div className="photo-res">
            <strong>{photoRes.status === 'analysed' ? t.photoRead : t.photoNot}</strong>
            <span className="muted small"> · {photoRes.faces_blurred} {t.faces}{photoRes.reason ? ` · ${photoRes.reason}` : ''}</span>
            {(photoRes.conflicts ?? []).filter((c) => !dismissed.includes(c.feature)).map((c) => {
              const f = FEATURES.find((x) => x.id === c.feature)?.label[lang].toLowerCase() ?? c.feature
              return <div key={c.feature} className="conflict" role="note"><span>{(c.citizen_said ? t.conflictNotSeen : t.conflictSeen).replace('{f}', f)}</span>
                <button className="small" onClick={() => setDismissed((k) => [...k, c.feature])}>{t.gotIt}</button></div>
            })}
          </div>}
          {outcome != null && <div className="outcome" role="status"><h2>{t.outcome}</h2><p>{outcomeText(outcome)}</p></div>}
          {summary.mission && !skipMission && (
            <section className="mission" aria-labelledby="mission-h">
              <h2 id="mission-h">{t.mission}</h2>
              <p>{t.missionHelp}</p>
              <p className="mission-where">{t.go} <strong>{missionWhere}</strong>{summary.mission.walk_m != null && summary.mission.walk_m > 30
                && <span className="muted"> · {t.about} {summary.mission.walk_m < 1000 ? `${Math.round(summary.mission.walk_m / 10) * 10} m` : `${km(summary.mission.walk_m / 1000, lang)} km`} {t.fromYou}</span>}</p>
              <div className="minimap"><CaseMap reach={reach} citizen picked={{ lat: summary.mission.lat, lon: summary.mission.lon }} height={200}
                label={`${t.go} ${missionWhere}`} /></div>
              <p>{t.lookFor}</p>
              <div className="row">
                <button className="wide" disabled={busy} onClick={() => answer(false)}>{t.looksClean}</button>
                <button className="wide warn" disabled={busy} onClick={() => answer(true)}>{t.polluted}</button>
              </div>
              <button className="linkish" onClick={() => setSkipMission(true)}>{t.cantGo}</button>
            </section>)}
          <button className="wide" onClick={reset}>{t.another}</button>
        </>}
        {error && <p className="error" role="alert">{error}</p>}
      </div>
    </div>
  )
}
