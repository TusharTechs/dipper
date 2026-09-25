import { useEffect, useMemo, useState } from 'react'
import CaseMap from './Map'
import { api, type PublicAdvisory } from './api'
import { LANG_NAME, T, preferredLang, type Lang } from './i18n'

export default function PublicMap() {
  const [items, setItems] = useState<PublicAdvisory[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const all: Lang[] = ['en', 'pt', 'nb', 'nl']
  const [lang, setLang] = useState<Lang>(() => preferredLang(all))
  const t = T[lang]
  const rank = (l: string) => (l === lang ? 0 : l === 'en' ? 2 : 1)
  useEffect(() => { api.advisories().then(setItems).catch((e) => setError(e.message)) }, [])
  const stretches = useMemo(() => (items ?? []).map((a) => a.stretch.coordinates), [items])
  return (
    <div className="page">
      <div className="lang" role="group" aria-label={all.map((l) => T[l].language).join(' / ')}>
        {all.map((l) => <button key={l} lang={l} aria-pressed={l === lang} className={l === lang ? 'on' : ''} onClick={() => setLang(l)}>{LANG_NAME[l]}</button>)}
      </div>
      <h1 lang={lang}>{t.pubTitle}</h1>
      <p className="muted lead" lang={lang}>{t.pubLead}</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!items ? <p className="muted" role="status">{t.loading}</p> : items.length === 0 ? (
        <p className="done" lang={lang}>{t.pubNone} <span className="muted">{t.pubNoneNote}</span></p>
      ) : <>
        <div className="public-map"><CaseMap reach={null} stretches={stretches} height={380}
          label={t.pubMap} /></div>
        <ul className="advisories">{items.map((a) => (
          <li key={a.case} className="card">
            <h2>{a.reach}, {a.city} {a.simulated && <em className="tag" lang={lang}>{t.simulated}</em>}</h2>
            {/* the reader's language first, then the city's, then English */}
            {Object.entries(a.text).sort(([x], [y]) => rank(x) - rank(y)).map(([l, text]) => (
              <p key={l} lang={l}><span className="muted small">{LANG_NAME[l as Lang] ?? l} · </span>{text}</p>))}
            <p className="muted small"><time dateTime={a.issued_at}>{new Date(a.issued_at).toLocaleString()}</time></p>
          </li>))}</ul>
      </>}
    </div>
  )
}
