import { useEffect, useState } from 'react'
import CaseMap from './CaseMap'
import { api, REACH_ID, signalPhoto, type CaseView, type GeoJSON, type PhotoResult, type Recommendation } from './api'

type Lang = 'pt' | 'en'
const T = {
  en: {
    title: 'Report a sign of pollution', where: 'Tap the map where you are standing by the stream.',
    what: 'What do you see or smell?', send: 'Send report', sending: 'Sending…',
    thanks: 'Thank you. Your report is part of case', others: 'Other reports on this stretch',
    helpQ: 'Can you help narrow it down? One short check nearby:', go: 'Go to', lookFor: 'Look and smell for grey or milky water, a sewage smell, a pipe running in dry weather.',
    clean: 'Looks clean', polluted: 'Polluted', cantGo: "I can't go now",
    outcome: 'What your help did', ruledOut: 'Your check changed the search:', status: 'Case status',
    another: 'Report something else', safety: 'Stay on the bank. Do not touch the water or pipes.',
    pickFirst: 'Tap the map first.', mission: 'Your mission',
    photo: 'Add a photo (optional)', photoPrivacy: 'Location data is removed and faces are blurred before the photo is analysed.',
    photoRead: 'Photo checked', photoNot: 'Photo saved but not analysed', keep: 'Keep my answer', blurred: 'faces blurred',
  },
  pt: {
    title: 'Comunicar um sinal de poluição', where: 'Toque no mapa onde está, junto à ribeira.',
    what: 'O que vê ou cheira?', send: 'Enviar', sending: 'A enviar…',
    thanks: 'Obrigado. A sua comunicação faz parte do caso', others: 'Outras comunicações neste troço',
    helpQ: 'Pode ajudar a localizar a origem? Uma verificação rápida aqui perto:', go: 'Vá até', lookFor: 'Procure água cinzenta ou leitosa, cheiro a esgoto, um tubo a descarregar sem chuva.',
    clean: 'Parece limpa', polluted: 'Poluída', cantGo: 'Agora não posso',
    outcome: 'O que a sua ajuda fez', ruledOut: 'A sua verificação mudou a procura:', status: 'Estado do caso',
    another: 'Comunicar outra coisa', safety: 'Fique na margem. Não toque na água nem nos tubos.',
    pickFirst: 'Toque primeiro no mapa.', mission: 'A sua missão',
    photo: 'Adicionar fotografia (opcional)', photoPrivacy: 'A localização é removida e os rostos são desfocados antes de a fotografia ser analisada.',
    photoRead: 'Fotografia verificada', photoNot: 'Fotografia guardada mas não analisada', keep: 'Manter a minha resposta', blurred: 'rostos desfocados',
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
  localized: { en: 'Source located', pt: 'Origem localizada' }, handed_off: { en: 'Sent to the utility', pt: 'Enviado à entidade gestora' },
  fixed: { en: 'Fixed', pt: 'Resolvido' }, verified: { en: 'Fix verified', pt: 'Resolução confirmada' },
  closed: { en: 'Closed', pt: 'Fechado' }, dismissed: { en: 'No pollution source found', pt: 'Sem origem de poluição' },
}

export default function Citizen() {
  const [lang, setLang] = useState<Lang>('pt')
  const t = T[lang]
  const [reach, setReach] = useState<GeoJSON | null>(null)
  const [picked, setPicked] = useState<{ lat: number; lon: number } | null>(null)
  const [feats, setFeats] = useState<Record<string, boolean>>({})
  const [caseId, setCaseId] = useState<string | null>(null)
  const [view, setView] = useState<CaseView | null>(null)
  const [mission, setMission] = useState<Recommendation | null>(null)
  const [change, setChange] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [photoRes, setPhotoRes] = useState<PhotoResult['photo'] | null>(null)
  const [kept, setKept] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const observer = 'cit-demo'

  useEffect(() => { api.reach(REACH_ID).then(setReach).catch((e) => setError(e.message)) }, [])

  const refresh = async (id: string) => {
    const v = await api.case(id)
    setView(v)
    const recs = await api.recommendations(id, ['citizen'], 1)
    setMission(['open', 'localizing'].includes(v.status) ? recs[0] ?? null : null)
  }

  const send = async () => {
    if (!picked) { setError(t.pickFirst); return }
    setBusy(true); setError(null)
    try {
      let id: string
      if (file) {
        const r = await signalPhoto(file, { reach_id: REACH_ID, lat: picked.lat, lon: picked.lon, features: feats, observer })
        setPhotoRes(r.photo); id = r.case_id
      } else {
        const r = await api.signal({ reach_id: REACH_ID, lat: picked.lat, lon: picked.lon, features: feats, role: 'citizen', observer })
        id = r.case_id
      }
      setCaseId(id)
      await refresh(id)
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }

  const answer = async (positive: boolean) => {
    if (!caseId || !mission) return
    setBusy(true)
    try {
      const branch = positive ? mission.if_positive : mission.if_negative
      await api.check(caseId, { ...mission.check, positive, observer })
      setChange(`${branch.zone} (${Math.round(branch.zone_mass * 100)}%)`)
      await refresh(caseId)
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }

  const reset = () => { setCaseId(null); setView(null); setMission(null); setFeats({}); setPicked(null); setChange(null); setFile(null); setPhotoRes(null); setKept([]) }

  return (
    <div className="citizen">
      <div className="phone">
        <header className="phone-head">
          <strong>Dipper</strong>
          <div className="lang" role="group" aria-label="Language">
            {(['pt', 'en'] as Lang[]).map((l) => <button key={l} className={l === lang ? 'on' : ''} onClick={() => setLang(l)}>{l.toUpperCase()}</button>)}
          </div>
        </header>

        {!caseId && <>
          <h1>{t.title}</h1>
          <p className="muted">{t.where}</p>
          <div className="minimap"><CaseMap reach={reach} picked={picked} onPick={(lat, lon) => setPicked({ lat, lon })} height={220} /></div>
          <h2>{t.what}</h2>
          <div className="toggles">
            {FEATURES.map((f) => (
              <button key={f.id} className={feats[f.id] ? 'toggle on' : 'toggle'} aria-pressed={!!feats[f.id]}
                onClick={() => setFeats((s) => ({ ...s, [f.id]: !s[f.id] }))}>{f[lang]}</button>
            ))}
          </div>
          <label className="photo-pick" htmlFor="photo-input">
            <span>{file ? file.name : t.photo}</span>
            <input id="photo-input" type="file" accept="image/*" capture="environment" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <p className="muted small">{t.photoPrivacy}</p>
          <button className="primary wide" disabled={busy} onClick={send}>{busy ? t.sending : t.send}</button>
          <p className="muted small">{t.safety}</p>
        </>}

        {caseId && view && <>
          <div className="thanks"><strong>{t.thanks} {view.id}.</strong> {t.others}: {view.observations.filter((o) => o.kind === 'report').length - 1}.</div>
          <p><span className="muted">{t.status}:</span> <b>{STATUS[view.status]?.[lang] ?? view.status}</b></p>
          {photoRes && <div className="photo-res">
            <strong>{photoRes.status === 'analysed' ? t.photoRead : t.photoNot}</strong>
            <span className="muted small"> · {photoRes.faces_blurred} {t.blurred}{photoRes.reason ? ` · ${photoRes.reason}` : ''}</span>
            {(photoRes.conflicts ?? []).filter((c) => !kept.includes(c.feature)).map((c) => (
              <div key={c.feature} className="conflict"><span>{c.prompt}</span>
                <button className="small" onClick={() => setKept((k) => [...k, c.feature])}>{t.keep}</button></div>))}
          </div>}
          {change && <div className="outcome"><h2>{t.outcome}</h2><p>{t.ruledOut} {change}</p></div>}
          {mission && <div className="mission">
            <span className="eyebrow">{t.mission}</span>
            <p>{t.helpQ}</p>
            <h2>{t.go} {mission.check.candidate_id ? view.sources.find((s) => s.id === mission.check.candidate_id)?.label : mission.label.split(' at ').pop()}</h2>
            <div className="minimap"><CaseMap reach={reach} view={view} target={mission} height={200} /></div>
            <p>{t.lookFor}</p>
            <div className="row">
              <button className="wide" disabled={busy} onClick={() => answer(false)}>{t.clean}</button>
              <button className="wide warn" disabled={busy} onClick={() => answer(true)}>{t.polluted}</button>
            </div>
            <button className="linkish" onClick={() => setMission(null)}>{t.cantGo}</button>
          </div>}
          <button className="wide" onClick={reset}>{t.another}</button>
        </>}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
