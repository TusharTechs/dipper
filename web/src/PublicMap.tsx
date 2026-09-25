import { useEffect, useMemo, useState } from 'react'
import CaseMap from './Map'
import { api, type PublicAdvisory } from './api'
import { LANG_NAME, type Lang } from './i18n'

export default function PublicMap() {
  const [items, setItems] = useState<PublicAdvisory[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => { api.advisories().then(setItems).catch((e) => setError(e.message)) }, [])
  const stretches = useMemo(() => (items ?? []).map((a) => a.stretch.coordinates), [items])
  return (
    <div className="page">
      <h1>Public advisories</h1>
      <p className="muted lead">Stretches of urban streams where contact with the water is currently discouraged. Each advisory was approved by a public-health officer. Suspected pipes and addresses are never shown.</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!items ? <p className="muted" role="status">Loading…</p> : items.length === 0 ? (
        <p className="done">No active advisories. <span className="muted">This does not mean the water is safe to drink or swim in.</span></p>
      ) : <>
        <div className="public-map"><CaseMap reach={null} stretches={stretches} height={380}
          label={`Map of ${items.length} advisory stretch(es), shown in red`} /></div>
        <ul className="advisories">{items.map((a) => (
          <li key={a.case} className="card">
            <h2>{a.reach}, {a.city} {a.simulated && <em className="tag">simulated demo</em>}</h2>
            {/* the city's language first, then English */}
            {Object.entries(a.text).sort(([x], [y]) => (x === 'en' ? 1 : 0) - (y === 'en' ? 1 : 0)).map(([l, text]) => (
              <p key={l} lang={l}><span className="muted small">{LANG_NAME[l as Lang] ?? l} · </span>{text}</p>))}
            <p className="muted small"><time dateTime={a.issued_at}>{new Date(a.issued_at).toLocaleString()}</time></p>
          </li>))}</ul>
      </>}
    </div>
  )
}
