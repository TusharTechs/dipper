import { useEffect, useMemo, useState } from 'react'
import { useAnnounce } from './App'
import CaseMap from './Map'
import { api, ApiError, DEFAULT_REACH, type CitizenCase, type GeoJSON, type PhotoResult, type ReachInfo } from './api'

type Lang = 'pt' | 'en'
const T = {
  en: {
    title: 'Report a sign of pollution', intro: 'Seen grey water, a sewage smell, foam or a pipe running in dry weather? Tell us where. It takes under a minute.',
    stream: 'Stream', where: 'Where are you?', useLoc: 'Use my location', tapHint: 'Or tap the map where you are standing by the stream.',
    picked: 'Location set', what: 'What do you see or smell?', none: 'Pick at least one sign, or send a report that the water looks clean.',
    clean: 'The water looks clean', send: 'Send report', sending: 'Sending…',
    photo: 'Add a photo (optional)', photoConsent: 'Photos are checked by an AI service to read the water. Location data is removed and faces are blurred first. Photos are deleted after the retention period.',
    thanks: 'Thank you. Your report is part of case', offline: 'You are offline. Your report is saved on this phone and will be sent automatically.',
    queued: 'report(s) waiting to be sent', status: 'Case status', mission: 'Can you help narrow it down?', missionHelp: 'One short check nearby makes the search much faster:',
    go: 'Go to', lookFor: 'Look and smell for grey or milky water, a sewage smell, or a pipe running when it has not rained.',
    looksClean: 'Looks clean', polluted: 'Polluted', cantGo: "I can't go now", outcome: 'What your check did',
    narrowed: 'Thank you. Your check ruled out about {n}% of the places the source could be. The team sees it now.', noChange: 'Thank you. Your check confirmed what we knew; the team sees it now.', photoRead: 'Photo checked', photoNot: 'Photo not analysed', keep: 'Keep my answer',
    another: 'Report something else', safety: 'Stay on the bank. Do not touch the water or pipes.', advisory: 'Public advisory',
    faces: 'faces blurred (automatic detection can miss some)', farAway: 'That point is too far from the mapped stream. Move closer to the water.',
    landmark: 'Or choose the nearest point from a list', pipe: 'the pipe marked', streamAt: 'the stream bank', about: 'about', fromYou: 'from where you reported', choose: 'Choose a point…', near: 'near', up: 'km above where the stream ends',
  },
  pt: {
    title: 'Comunicar um sinal de poluição', intro: 'Viu água cinzenta, cheiro a esgoto, espuma ou um tubo a descarregar sem chuva? Diga-nos onde. Demora menos de um minuto.',
    stream: 'Ribeira', where: 'Onde está?', useLoc: 'Usar a minha localização', tapHint: 'Ou toque no mapa onde está, junto à ribeira.',
    picked: 'Localização definida', what: 'O que vê ou cheira?', none: 'Escolha pelo menos um sinal, ou comunique que a água parece limpa.',
    clean: 'A água parece limpa', send: 'Enviar', sending: 'A enviar…',
    photo: 'Adicionar fotografia (opcional)', photoConsent: 'As fotografias são analisadas por um serviço de IA para ler a água. Primeiro, a localização é removida e os rostos são desfocados. As fotografias são apagadas no fim do prazo de conservação.',
    thanks: 'Obrigado. A sua comunicação faz parte do caso', offline: 'Está sem ligação. A comunicação ficou guardada neste telemóvel e será enviada automaticamente.',
    queued: 'comunicação(ões) por enviar', status: 'Estado do caso', mission: 'Pode ajudar a localizar a origem?', missionHelp: 'Uma verificação rápida aqui perto acelera muito a procura:',
    go: 'Vá até', lookFor: 'Procure água cinzenta ou leitosa, cheiro a esgoto, ou um tubo a descarregar sem ter chovido.',
    looksClean: 'Parece limpa', polluted: 'Poluída', cantGo: 'Agora não posso', outcome: 'O que a sua verificação fez',
    narrowed: 'Obrigado. A sua verificação excluiu cerca de {n}% dos locais onde a origem podia estar. A equipa já a vê.', noChange: 'Obrigado. A sua verificação confirmou o que já sabíamos; a equipa já a vê.', photoRead: 'Fotografia verificada', photoNot: 'Fotografia não analisada', keep: 'Manter a minha resposta',
    another: 'Comunicar outra coisa', safety: 'Fique na margem. Não toque na água nem nos tubos.', advisory: 'Aviso público',
    faces: 'rostos desfocados (a deteção automática pode falhar alguns)', farAway: 'Esse ponto está longe da ribeira mapeada. Aproxime-se da água.',
    landmark: 'Ou escolha o ponto mais próximo numa lista', pipe: 'o tubo marcado', streamAt: 'a margem da ribeira', about: 'cerca de', fromYou: 'de onde comunicou', choose: 'Escolha um ponto…', near: 'perto de', up: 'km acima da foz da ribeira',
  },
}
const FEATURES: { id: string; en: string; pt: string }[] = [
  { id: 'grey', en: 'Grey or milky water', pt: 'Água cinzenta ou leitosa' },
  { id: 'sewage_odour', en: 'Sewage smell', pt: 'Cheiro a esgoto' },
  { id: 'pipe_flowing', en: 'Pipe discharging', pt: 'Tubo a descarregar' },
  { id: 'foam', en: 'Foam', pt: 'Espuma' },
  { id: 'brown_turbid', en: 'Brown, muddy water', pt: 'Água castanha, turva' },
  { id: 'green', en: 'Green water or scum', pt: 'Água verde ou película' },
  { id: 'dead_fish', en: 'Dead fish', pt: 'Peixes mortos' },
  { id: 'sewage_fungus', en: 'Grey slimy growth', pt: 'Crescimento cinzento viscoso' },
]
const STATUS: Record<string, { en: string; pt: string }> = {
  open: { en: 'Open', pt: 'Aberto' }, localizing: { en: 'Searching for the source', pt: 'À procura da origem' },
  localized: { en: 'Source located', pt: 'Origem localizada' }, handed_off: { en: 'Sent to the water utility', pt: 'Enviado à entidade gestora' },
  fixed: { en: 'Fixed', pt: 'Resolvido' }, verified: { en: 'Fix verified', pt: 'Resolução confirmada' },
  closed: { en: 'Closed', pt: 'Fechado' }, dismissed: { en: 'No pollution source found', pt: 'Sem origem de poluição' },
}
const QUEUE_KEY = 'dipper.queue'
type Queued = { reach_id: string; lat: number; lon: number; features: Record<string, boolean> }
const readQueue = (): Queued[] => { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]') } catch { return [] } }
const writeQueue = (q: Queued[]) => { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q)) } catch { /* storage unavailable */ } }

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
  const [lang, setLang] = useState<Lang>(() => (navigator.language?.toLowerCase().startsWith('pt') ? 'pt' : 'en'))
  const t = T[lang]
  const [reaches, setReaches] = useState<ReachInfo[]>([])
  const [reachId, setReachId] = useState(DEFAULT_REACH)
  const [reach, setReach] = useState<GeoJSON | null>(null)
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null)
  const [pickedKey, setPickedKey] = useState('')
  const [feats, setFeats] = useState<Record<string, boolean>>({})
  const [cleanReport, setCleanReport] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [caseId, setCaseId] = useState<string | null>(null)
  const [summary, setSummary] = useState<CitizenCase | null>(null)
  const [photoRes, setPhotoRes] = useState<PhotoResult['photo'] | null>(null)
  const [kept, setKept] = useState<string[]>([])
  const [outcome, setOutcome] = useState<number | null>(null)
  const [skipMission, setSkipMission] = useState(false)
  const [queued, setQueued] = useState(readQueue().length)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.reaches().then(setReaches).catch(() => {}) }, [])
  useEffect(() => { setReach(null); setPicked(null); setPickedKey(''); api.reach(reachId).then(setReach).catch((e) => setError(e.message)) }, [reachId])
  useEffect(() => {
    const flush = async () => {
      const q = readQueue(); const left: Queued[] = []
      for (const item of q) { try { await api.signal(item) } catch { left.push(item) } }
      writeQueue(left); setQueued(left.length)
    }
    window.addEventListener('online', flush); if (navigator.onLine) flush()
    return () => window.removeEventListener('online', flush)
  }, [])

  const marks = useMemo(() => landmarks(reach), [reach])
  const refresh = async (id: string) => setSummary(await api.citizenCase(id, picked))
  const locate = () => navigator.geolocation?.getCurrentPosition(
    (p) => { setPicked({ lat: p.coords.latitude, lon: p.coords.longitude }); announce(t.picked) },
    () => setError(t.tapHint), { enableHighAccuracy: true, timeout: 10000 })

  const send = async () => {
    if (!picked) { setError(t.tapHint); return }
    const answers = cleanReport ? {} : feats
    if (!cleanReport && !Object.values(feats).some(Boolean)) { setError(t.none); return }
    setBusy(true); setError(null)
    const body = { reach_id: reachId, lat: picked.lat, lon: picked.lon, features: answers }
    try {
      let id: string
      if (file) { const r = await api.signalPhoto(file, body); setPhotoRes(r.photo); id = r.case_id }
      else { id = (await api.signal(body)).case_id }
      setCaseId(id); await refresh(id); announce(`${t.thanks} ${id}`)
      window.setTimeout(() => document.getElementById('thanks')?.focus(), 0)
    } catch (e: any) {
      if (!(e instanceof ApiError)) { const q = [...readQueue(), body]; writeQueue(q); setQueued(q.length); setError(t.offline) }
      else setError(e.status === 422 && /stream/.test(e.message) ? t.farAway : e.message)
    } finally { setBusy(false) }
  }

  const outcomeText = (cut: number) => (cut >= 1 ? t.narrowed.replace('{n}', String(cut)) : t.noChange)
  const answer = async (positive: boolean) => {
    if (!caseId || !summary?.mission) return
    setBusy(true)
    try {
      const r = await api.citizenCheck(caseId, summary.mission.key, positive)
      const cut = Math.max(0, Math.round((1 - 2 ** -r.search_narrowed_bits) * 100))
      setOutcome(cut); await refresh(caseId); announce(`${t.outcome}: ${outcomeText(cut)}`)
    } catch (e: any) { setError(e.message); await refresh(caseId) } finally { setBusy(false) }
  }

  const missionWhere = (() => {
    const m = summary?.mission
    if (!m) return ''
    const near = marks.filter((l) => l.place).map((l) => ({ l, d: Math.hypot((l.lat - m.lat) * 111_320, (l.lon - m.lon) * 111_320 * Math.cos(m.lat * Math.PI / 180)) }))
      .filter((x) => x.d < 400).sort((a, b) => a.d - b.d)[0]
    const spot = m.outfall ? `${t.pipe} ${m.outfall}` : `${t.streamAt} ${m.km_above_outlet.toFixed(1)} ${t.up}`
    return near ? `${spot} (${t.near} ${near.l.place})` : spot
  })()

  const reset = () => { setCaseId(null); setSummary(null); setFeats({}); setCleanReport(false); setPicked(null); setPickedKey(''); setOutcome(null); setFile(null); setPhotoRes(null); setKept([]); setSkipMission(false) }

  return (
    <div className="citizen" lang={lang}>
      <div className="phone">
        <div className="phone-head">
          <div className="lang" role="group" aria-label="Language / Idioma">
            {(['pt', 'en'] as Lang[]).map((l) => (
              <button key={l} lang={l} aria-pressed={l === lang} className={l === lang ? 'on' : ''} onClick={() => setLang(l)}>{l === 'pt' ? 'Português' : 'English'}</button>))}
          </div>
        </div>
        {queued > 0 && <p className="note" role="status">{queued} {t.queued}</p>}

        {!caseId && <>
          <h1>{t.title}</h1>
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
              : `${m.km!.toFixed(1)} ${t.up}${m.nearPlace ? ` (${t.near} ${m.nearPlace})` : ''}`}</option>)}
          </select>
          {picked && <p className="muted small" role="status">{t.picked}: {(() => {
            const m = marks.find((x) => x.key === pickedKey)
            return m ? (m.place ? `${t.near} ${m.place}` : `${m.km!.toFixed(1)} ${t.up}`) : `${picked.lat.toFixed(5)}, ${picked.lon.toFixed(5)}`
          })()}</p>}
          <fieldset className="toggles-set" disabled={cleanReport}>
            <legend>{t.what}</legend>
            <div className="toggles">{FEATURES.map((f) => (
              <button key={f.id} type="button" className={feats[f.id] ? 'toggle on' : 'toggle'} aria-pressed={!!feats[f.id]}
                onClick={() => setFeats((s) => ({ ...s, [f.id]: !s[f.id] }))}>{f[lang]}</button>))}</div>
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
          {summary.advisory && <div className="advisory-box" role="note"><strong>{t.advisory}</strong><p>{summary.advisory[lang]}</p></div>}
          {photoRes && <div className="photo-res">
            <strong>{photoRes.status === 'analysed' ? t.photoRead : t.photoNot}</strong>
            <span className="muted small"> · {photoRes.faces_blurred} {t.faces}{photoRes.reason ? ` · ${photoRes.reason}` : ''}</span>
            {(photoRes.conflicts ?? []).filter((c) => !kept.includes(c.feature)).map((c) => (
              <div key={c.feature} className="conflict"><span lang="en">{c.prompt}</span>
                <button className="small" onClick={() => setKept((k) => [...k, c.feature])}>{t.keep}</button></div>))}
          </div>}
          {outcome != null && <div className="outcome" role="status"><h2>{t.outcome}</h2><p>{outcomeText(outcome)}</p></div>}
          {summary.mission && !skipMission && (
            <section className="mission" aria-labelledby="mission-h">
              <h2 id="mission-h">{t.mission}</h2>
              <p>{t.missionHelp}</p>
              <p className="mission-where">{t.go} <strong>{missionWhere}</strong>{summary.mission.walk_m != null && summary.mission.walk_m > 30
                && <span className="muted"> · {t.about} {summary.mission.walk_m < 1000 ? `${Math.round(summary.mission.walk_m / 10) * 10} m` : `${(summary.mission.walk_m / 1000).toFixed(1)} km`} {t.fromYou}</span>}</p>
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
