import { useCallback, useEffect, useState } from 'react'
import CaseMap from './CaseMap'
import { api, REACH_ID, type CaseView, type GeoJSON, type Recommendation } from './api'

const pct = (p: number) => `${Math.round(p * 100)}%`
const KIND_LABEL: Record<string, string> = {
  report: 'Report', instream_look: 'Stream look', outfall_look: 'Outfall look', ammonium_strip: 'Ammonium strip', lab_ecoli: 'Lab E. coli',
}
const STATUS_LABEL: Record<string, string> = {
  open: 'Open', localizing: 'Localizing', localized: 'Source localized', handed_off: 'Handed to utility',
  fixed: 'Fixed', verified: 'Verified', closed: 'Closed', dismissed: 'Dismissed',
}

export default function Workspace({ caseId, onCase }: { caseId: string | null; onCase: (id: string) => void }) {
  const [reach, setReach] = useState<GeoJSON | null>(null)
  const [view, setView] = useState<CaseView | null>(null)
  const [hover, setHover] = useState<Recommendation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [approver, setApprover] = useState('tech-01')
  const [scenario, setScenario] = useState(false)

  useEffect(() => { api.reach(REACH_ID).then(setReach).catch((e) => setError(String(e.message))) }, [])
  useEffect(() => {
    if (!caseId) { setView(null); return }
    api.case(caseId).then((v) => { setView(v); setScenario(v.observations.some((o) => o.tier === 'simulated')) })
      .catch((e) => setError(String(e.message)))
  }, [caseId])

  const run = useCallback(async (fn: () => Promise<CaseView>) => {
    setBusy(true); setError(null)
    try { const v = await fn(); setView(v); setHover(null) } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }, [])

  const start = (wet: boolean) => run(async () => {
    const v = await api.startScenario(wet); setScenario(true); onCase(v.id); return v
  })

  if (!view) {
    return (
      <div className="empty">
        <div className="empty-card">
          <h1>Operations</h1>
          <p>No case is open. Start the C-014 scenario replay on Ribeira de Coselhas, Coimbra. The stream map and weather are real. The reports, outfalls and check results are simulated.</p>
          <div className="row">
            <button className="primary" disabled={busy} onClick={() => start(false)}>Replay 18 Sep 2026 (dry)</button>
            <button disabled={busy} onClick={() => start(true)}>Replay 24 Aug 2026 (after rain)</button>
          </div>
          {error && <p className="error">{error}. Is the API running on port 8000?</p>}
        </div>
      </div>
    )
  }

  const top = view.recommendations[0]
  const target = hover ?? top ?? null
  const localized = view.status === 'localized'

  return (
    <div className="workspace">
      {scenario && <div className="banner">Scenario replay · real stream geometry and weather · simulated outfalls, reports and results</div>}
      <header className="case-head">
        <div>
          <span className="eyebrow">Case {view.id} · {view.reach}, {view.city}</span>
          <h1>{view.hypotheses[0].label}</h1>
          <div className="meta">
            <span className={`chip st-${view.status}`}>{STATUS_LABEL[view.status] ?? view.status}</span>
            <span>Likely entry: <b>{view.top_source.label} ({pct(view.top_source.p)})</b></span>
            <span>Weather: {view.context.summary}</span>
            <span>P(harmful): {pct(view.p_harmful)}</span>
          </div>
        </div>
        <div className="head-actions">
          <label className="approver">Approver <input id="approver" value={approver} onChange={(e) => setApprover(e.target.value)} /></label>
          <button className={localized ? 'primary' : ''} disabled={busy || !['localized'].includes(view.status)}
            aria-label="Notify utility" title={localized ? 'Send the evidence pack to the utility' : 'Available once one outfall reaches 85%'}
            onClick={() => run(() => api.action(view.id, 'notify_utility', approver || null, { outfall: view.top_source.id }))}>
            Notify utility
          </button>
          <button disabled={busy || !view.advisory_suggested || view.actions.some((a) => a.type === 'advisory')}
            onClick={() => run(() => api.action(view.id, 'advisory', approver || null, { reach: view.reach }))}>
            Approve advisory
          </button>
          <a className="button" href={`/api/v1/cases/${view.id}/fhir`} target="_blank" rel="noreferrer">FHIR bundle</a>
        </div>
      </header>
      {error && <div className="error bar">{error}</div>}

      <div className="grid">
        <aside className="panel left">
          <h2>What it is</h2>
          <ul className="bars">
            {view.hypotheses.map((h) => (
              <li key={h.id}>
                <div className="bar-label"><span>{h.label}</span><span className="num">{pct(h.p)}</span></div>
                <div className="bar"><div className={`fill ${h.harmful ? 'harm' : ''}`} style={{ width: `${Math.max(1, h.p * 100)}%` }} /></div>
              </li>
            ))}
          </ul>
          <h2>Where it enters</h2>
          <ul className="bars compact">
            {[...view.sources].sort((a, b) => b.p - a.p).slice(0, 5).map((s) => (
              <li key={s.id}>
                <div className="bar-label"><span>{s.label}{s.synthetic && <em className="tag">synthetic</em>}</span><span className="num">{pct(s.p)}</span></div>
                <div className="bar"><div className="fill src" style={{ width: `${Math.max(1, s.p * 100)}%` }} /></div>
              </li>
            ))}
            <li className="muted small">Upstream or unmapped: {pct(view.outside_or_unmapped)}</li>
          </ul>
          <h2>What we don't know</h2>
          <ul className="unknowns">{view.unknowns.map((u) => <li key={u}>{u}</li>)}</ul>
          {view.exposure.length > 0 && <>
            <h2>Who may be in contact</h2>
            <ul className="exposure">
              {view.exposure.map((e) => (
                <li key={e.id}><span>{e.label} <span className="muted">({e.kind.replace('_', ' ')})</span></span>
                  <span className="num">{pct(e.p_affected)}{e.minutes_from_likely_source != null && ` · ~${e.minutes_from_likely_source} min`}</span></li>
              ))}
            </ul>
            <p className="muted small">Proximity estimate, not a health-risk prediction.</p>
          </>}
        </aside>

        <section className="mapwrap">
          <CaseMap reach={reach} view={view} target={target} />
          <div className="legend">
            <span><i className="sw low" />unlikely</span><span><i className="sw mid" />possible</span><span><i className="sw high" />likely polluted</span>
            <span><i className="dot rep" />report</span><span><i className="dot pos" />positive</span><span><i className="dot clean" />clean</span>
            <span><i className="dot place" />contact place</span><span><i className="ring" />next check</span>
          </div>
        </section>

        <aside className="panel right">
          <div className="panel-head">
            <h2>{['open', 'localizing'].includes(view.status) ? 'Next best check' : 'Optional confirmation checks'}</h2>
            {scenario && <button className="small primary" disabled={busy || view.status !== 'localizing' && view.status !== 'open'}
              onClick={() => run(async () => (await api.autostep(view.id)).case)}>Run top check (simulated result)</button>}
          </div>
          {view.recommendations.length === 0 && <p className="muted">No checks available.</p>}
          {!['open', 'localizing'].includes(view.status) && (
            <p className="done">Search complete: {view.top_source.label} at {pct(view.top_source.p)}.
              {view.status === 'localized' ? ' Notify the utility to hand over the evidence pack.' : ' The utility traces the pipe (dye test or CCTV) and confirms.'}</p>)}
          <ol className="recs">
            {view.recommendations.map((r, i) => (
              <li key={r.check.key} className={i === 0 ? 'rec top' : 'rec'} onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)}>
                <div className="rec-title"><span className="rank">{i + 1}</span><span>{r.label}</span></div>
                <p className="reason">{r.reason}</p>
                <div className="rec-meta">
                  <span>value {r.score.toFixed(3)}</span><span>cost {r.cost.toFixed(2)}</span>
                  <span>{r.check.role}</span>{r.delay_h > 0 && <span>{r.delay_h} h wait</span>}
                  {r.changes_decision && <span className="chip st-localized">may change advisory</span>}
                </div>
                <div className="rec-buttons">
                  <span className="muted small">Record result:</span>
                  <button className="small" disabled={busy} onClick={() => run(() => api.check(view.id, { ...r.check, positive: false }))}>Clean</button>
                  <button className="small warn" disabled={busy} onClick={() => run(() => api.check(view.id, { ...r.check, positive: true }))}>Polluted</button>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>

      <section className="panel ledger">
        <h2>Evidence ledger</h2>
        <div className="tablewrap">
          <table>
            <thead><tr><th>#</th><th>Evidence</th><th>Tier</th><th className="num" title="log10 likelihood ratio for harmful point-source pollution">Evidence for harmful (bans)</th><th>Explanation shift</th><th className="num">Location uncertainty</th><th>Leading entry after</th></tr></thead>
            <tbody>
              {[...view.ledger].reverse().map((e) => (
                <tr key={e.index}>
                  <td className="num">{e.index}</td>
                  <td>{e.text}</td>
                  <td><span className={`tier ${e.tier}`}>{e.tier}</span></td>
                  <td className="num">{(e.harm_bans ?? 0) > 0 ? '+' : ''}{(e.harm_bans ?? 0).toFixed(2)}</td>
                  <td>{e.weight_for ? `${e.weight_for} ${e.weight_bans > 0 ? '+' : ''}${e.weight_bans.toFixed(2)}` : '·'}</td>
                  <td className="num">{e.entropy_before_bits.toFixed(2)} → {e.entropy_after_bits.toFixed(2)} bits</td>
                  <td>{view.sources.find((s) => s.id === e.top_source_after[0])?.label ?? 'upstream or unmapped'} {pct(e.top_source_after[1])}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">{view.model.note} Kinds: {Object.values(KIND_LABEL).join(', ')}.</p>
      </section>
    </div>
  )
}
