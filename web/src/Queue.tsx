import { useEffect, useState } from 'react'
import { useAnnounce, useAuth } from './App'
import { api, pct, STATUS_LABEL, type CaseSummary } from './api'

export default function Queue() {
  const { config, user } = useAuth()
  const announce = useAnnounce()
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.cases().then(setCases).catch((e) => setError(e.message)) }, [])

  const start = async (wet: boolean) => {
    setBusy(true); setError(null)
    try {
      const v = await api.startScenario(wet)
      announce(`Scenario case ${v.id} opened`)
      window.location.hash = `#/ops/${encodeURIComponent(v.id)}`
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <h1>Case queue</h1>
      <p className="muted lead">Each case gathers the reports about one stretch of stream. Open a case to see what is most likely happening, where it enters, and the best next check.</p>
      {config?.demo && user?.role !== 'public_health' && (
        <section className="card demo-box" aria-labelledby="demo-h">
          <h2 id="demo-h">Scenario replay · Ribeira de Coselhas, Coimbra</h2>
          <p>Real stream geometry and real weather. Candidate outfalls, citizen reports and check results are <strong>simulated</strong> and labelled as such.</p>
          <div className="row">
            <button className="primary" disabled={busy} onClick={() => start(false)}>Replay 18 Sep 2026 (dry weather)</button>
            <button disabled={busy} onClick={() => start(true)}>Replay 24 Aug 2026 (after 24 mm of rain)</button>
          </div>
        </section>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {!cases ? <p className="muted">Loading cases…</p> : cases.length === 0 ? (
        <p className="muted">No cases yet. Citizen reports open cases automatically.</p>
      ) : (
        <div className="tablewrap" tabIndex={0} role="region" aria-label="Cases">
          <table>
            <caption className="sr-only">Open and recent cases, most recent activity first</caption>
            <thead><tr><th scope="col">Case</th><th scope="col">Stream</th><th scope="col">Status</th><th scope="col">Leading explanation</th>
              <th scope="col">Likely entry</th><th scope="col" className="num">P(harmful)</th><th scope="col" className="num">Evidence</th></tr></thead>
            <tbody>{cases.map((c) => (
              <tr key={c.id}>
                <th scope="row"><a href={`#/ops/${encodeURIComponent(c.id)}`}>{c.id}</a>{c.simulated && <em className="tag">simulated</em>}</th>
                <td>{c.reach}, {c.city}</td>
                <td><span className={`chip st-${c.status}`}>{STATUS_LABEL[c.status] ?? c.status}</span></td>
                <td>{c.leading_hypothesis.label} ({pct(c.leading_hypothesis.p)})</td>
                <td>{c.top_source.label} ({pct(c.top_source.p)})</td>
                <td className="num">{pct(c.p_harmful)}</td><td className="num">{c.signals}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}
