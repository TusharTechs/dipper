import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useAnnounce, useAuth } from './App'
import CaseMap from './Map'
import { LANG_NAME, type Lang } from './i18n'
import { api, pct, STATUS_LABEL, type CaseView, type GeoJSON, type Recommendation } from './api'

type Tab = 'investigation' | 'advisory' | 'handoff' | 'timeline'
const TABS: { id: Tab; label: string }[] = [
  { id: 'investigation', label: 'Investigation' }, { id: 'advisory', label: 'Advisory' },
  { id: 'handoff', label: 'Hand-off & FHIR' }, { id: 'timeline', label: 'Timeline' },
]
const ACTIVE = ['open', 'localizing']

export default function Workspace({ caseId }: { caseId: string }) {
  const { user, config } = useAuth()
  const announce = useAnnounce()
  const [view, setView] = useState<CaseView | null>(null)
  const [reach, setReach] = useState<GeoJSON | null>(null)
  const [tab, setTab] = useState<Tab>('investigation')
  const [hover, setHover] = useState<Recommendation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const inspector = user?.role === 'inspector' || user?.role === 'admin'
  const publicHealth = user?.role === 'public_health' || user?.role === 'admin'

  const load = useCallback(async () => {
    try {
      const v = await api.case(caseId)
      setView(v)
      if (!reach) {
        const reaches = await api.reaches()
        const r = reaches.find((x) => x.name === v.reach)
        if (r) setReach(await api.reach(r.id))
      }
    } catch (e: any) { setError(e.message) }
  }, [caseId, reach])
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  const run = async (fn: () => Promise<CaseView>, say: (v: CaseView) => string) => {
    setBusy(true); setError(null)
    try { const v = await fn(); setView(v); setHover(null); announce(say(v)) }
    catch (e: any) { setError(e.message); announce(`Error: ${e.message}`) } finally { setBusy(false) }
  }
  const summary = (v: CaseView) => `Most likely entry ${v.top_source.label} at ${pct(v.top_source.p)}. Status: ${STATUS_LABEL[v.status] ?? v.status}.`

  const onTabKey = (e: KeyboardEvent, i: number) => {
    const n = e.key === 'ArrowRight' ? (i + 1) % TABS.length : e.key === 'ArrowLeft' ? (i - 1 + TABS.length) % TABS.length :
      e.key === 'Home' ? 0 : e.key === 'End' ? TABS.length - 1 : -1
    if (n >= 0) { e.preventDefault(); setTab(TABS[n].id); tabRefs.current[TABS[n].id]?.focus() }
  }

  const [confirmDismiss, setConfirmDismiss] = useState(false)
  if (error && !view) return <div className="page"><p className="error" role="alert">{error}</p><a href="#/ops">Back to the case queue</a></div>
  if (!view) return <div className="page"><p className="muted" role="status">Loading case…</p></div>

  const active = ACTIVE.includes(view.status)
  const lead = view.hypotheses[0]
  const advisory = view.actions.find((a) => a.type === 'advisory')

  return (
    <div className="workspace">
      {view.simulated && <p className="banner" role="note">Scenario replay · real stream geometry and weather · simulated outfalls, reports and check results</p>}
      <div className="case-head">
        <div>
          <p className="eyebrow"><a href="#/ops">Cases</a> / {view.id} · {view.reach}, {view.city}</p>
          <h1>{lead.label} <span className="muted h1-sub">{pct(lead.p)} likely</span></h1>
          <ul className="meta" aria-label="Case summary">
            <li><span className={`chip st-${view.status}`}>{STATUS_LABEL[view.status] ?? view.status}</span></li>
            <li>Likely entry: <strong>{view.top_source.label} ({pct(view.top_source.p)})</strong></li>
            <li>Weather: {view.context.summary}</li>
            <li>Harmful pollution: {pct(view.p_harmful)}</li>
          </ul>
        </div>
        <div className="head-actions">
          {inspector && view.status === 'localized' && (
            <button className="primary" disabled={busy} onClick={() => run(() => api.action(view.id, 'notify_utility'),
              (v) => `Case handed to the utility. ${summary(v)}`)}>Hand off to utility</button>)}
          {inspector && view.status === 'handed_off' && <>
            <button disabled={busy} onClick={() => run(() => api.action(view.id, 'reopen', { note: 'the utility could not confirm the entry point' }),
              (v) => `Search reopened: ${view.top_source.label} was not confirmed. ${summary(v)}`)}>Not confirmed · reopen</button>
            <button disabled={busy} onClick={() => run(() => api.action(view.id, 'fixed'), () => 'Marked as fixed')}>Mark fixed</button>
          </>}
          {inspector && ['verified', 'dismissed'].includes(view.status) && (
            <button disabled={busy} onClick={() => run(() => api.action(view.id, 'close'), () => 'Case closed')}>Close case</button>)}
          {inspector && ['open', 'localizing', 'localized'].includes(view.status) && (confirmDismiss
            ? <span className="row"><button className="warn" disabled={busy} onClick={() => { setConfirmDismiss(false)
                run(() => api.action(view.id, 'dismiss', { note: 'no pollution source found' }), () => 'Case dismissed') }}>Confirm dismiss</button>
                <button className="linkish" onClick={() => setConfirmDismiss(false)}>Keep searching</button></span>
            : <button className={view.dismiss_proposed ? 'warn' : ''} disabled={busy} onClick={() => setConfirmDismiss(true)}>Dismiss…</button>)}
          {inspector && view.status === 'fixed' && view.fix_confirmed_clean && (
            <button className="primary" disabled={busy} onClick={() => run(() => api.action(view.id, 'verified'), () => 'Fix verified')}>Verify fix</button>)}
        </div>
      </div>
      {inspector && view.status === 'fixed' && !view.fix_confirmed_clean && (
        <section className="follow-up" aria-labelledby="follow-up-h">
          <h2 id="follow-up-h">Follow-up after the fix</h2>
          <p>Check {view.top_source.label} again, ideally in dry weather. Is it clean now?</p>
          <div className="row" role="group" aria-label={`Follow-up result at ${view.top_source.label}`}>
            <button disabled={busy} onClick={() => run(() => api.action(view.id, 'follow_up', { clean: true }),
              () => 'Follow-up recorded: clean. You can now verify the fix.')}>Clean</button>
            <button className="warn" disabled={busy} onClick={() => run(() => api.action(view.id, 'follow_up', { clean: false }),
              () => 'Follow-up recorded: still polluted. The case is back with the utility.')}>Still polluted</button>
          </div>
          <p className="muted small">A fix counts as verified only after a clean follow-up. Follow-ups are kept apart from the source search, which explains the discharge that was found.</p>
        </section>)}
      {view.needs_trained_check && ['open', 'localizing'].includes(view.status) && (
        <p className="note bar" role="note">{view.top_source.label} holds {pct(view.top_source.p)} of the probability, but all evidence so far
          comes from the public. One check by a trained volunteer or staff member is needed before hand-off.</p>)}
      {view.dismiss_proposed && ['open', 'localizing'].includes(view.status) && (
        <p className="note bar" role="note">The evidence points to a natural or benign cause, not a pollution source. Consider dismissing the case.</p>)}
      {error && <p className="error bar" role="alert">{error}</p>}

      <div className="tabs" role="tablist" aria-label="Case views">
        {TABS.map((t, i) => (
          <button key={t.id} ref={(el) => { tabRefs.current[t.id] = el }} role="tab" id={`tab-${t.id}`} aria-controls={`panel-${t.id}`}
            aria-selected={tab === t.id} tabIndex={tab === t.id ? 0 : -1} className={tab === t.id ? 'tab on' : 'tab'}
            onClick={() => setTab(t.id)} onKeyDown={(e) => onTabKey(e, i)}>
            {t.label}{t.id === 'advisory' && view.advisory_draft.suggested && !advisory && <span className="dot-badge" aria-label="(suggested)" />}
          </button>))}
      </div>

      {tab === 'investigation' && (
        <div role="tabpanel" id="panel-investigation" aria-labelledby="tab-investigation">
          <div className="grid">
            <section className="panel left" aria-label="What the evidence says" tabIndex={0}>
              <h2>What it is</h2>
              <ul className="bars">{view.hypotheses.map((h) => (
                <li key={h.id}>
                  <div className="bar-label"><span>{h.label}</span><span className="num">{pct(h.p)}</span></div>
                  <div className="bar" aria-hidden="true"><div className={`fill ${h.harmful ? 'harm' : ''}`} style={{ width: `${Math.max(1, h.p * 100)}%` }} /></div>
                </li>))}</ul>
              <h2>Where it enters</h2>
              <ul className="bars compact">{[...view.sources].sort((a, b) => b.p - a.p).slice(0, 5).map((s) => (
                <li key={s.id}>
                  <div className="bar-label"><span>Outfall {s.label}{s.synthetic && <em className="tag">synthetic</em>}</span><span className="num">{pct(s.p)}</span></div>
                  <div className="bar" aria-hidden="true"><div className="fill src" style={{ width: `${Math.max(1, s.p * 100)}%` }} /></div>
                </li>))}
                <li className="muted small">Upstream or not yet mapped: {pct(view.outside_or_unmapped)}</li></ul>
              <h2>What we don't know</h2>
              <ul className="unknowns">{view.unknowns.map((u) => <li key={u}>{u}</li>)}</ul>
              {view.exposure.length > 0 && <>
                <h2>Who may be in contact</h2>
                <ul className="exposure">{view.exposure.map((e) => (
                  <li key={e.id}><span>{e.label} <span className="muted">({e.kind.replace('_', ' ')})</span></span>
                    <span className="num">{pct(e.p_affected)}{e.minutes_from_likely_source != null && ` · ~${e.minutes_from_likely_source} min`}</span></li>))}</ul>
                <p className="muted small">Proximity estimate, not a health-risk prediction.</p></>}
              <details className="howto"><summary>How to read this</summary>
                <p>Every number is a probability from the evidence ledger below. Clean checks count: they lower the chance that the source is upstream of where they were taken. Nothing here confirms pathogens; only a lab sample can.</p></details>
            </section>

            <div className="mapwrap">
              <CaseMap reach={reach} view={view} target={hover ?? (active ? view.recommendations[0] : null)}
                label={`Map of ${view.reach}. Stream shaded by probability of pollution. Most likely entry ${view.top_source.label}.`} />
              <div className="legend" aria-hidden="true">
                <span><i className="sw low" />unlikely</span><span><i className="sw mid" />possible</span><span><i className="sw high" />likely polluted</span>
                <span><i className="dot rep" />report</span><span><i className="dot pos" />positive</span><span><i className="dot clean" />clean</span>
                <span><i className="dot place" />contact place</span><span><i className="ring" />next check</span>
              </div>
            </div>

            <section className="panel right" aria-label="Next checks" tabIndex={0}>
              <div className="panel-head">
                <h2>{active ? 'Next best check' : 'Search complete'}</h2>
                {view.simulated && inspector && active && config?.demo && (
                  <button className="small primary" disabled={busy}
                    onClick={() => run(async () => (await api.autostep(view.id)).case, (v) => `Check done. ${summary(v)}`)}>
                    Run top check <span className="sr-only">(simulated result)</span><span aria-hidden="true">(simulated)</span></button>)}
              </div>
              {!active && <p className="done">{view.top_source.label} holds {pct(view.top_source.p)} of the probability.
                {view.status === 'localized' ? ' Hand off to the utility to confirm with a dye test or CCTV.' : ' The utility traces the pipe and confirms the fix.'}</p>}
              {active && (
                <ol className="recs">{view.recommendations.map((r, i) => (
                  <li key={r.check.key} className={i === 0 ? 'rec top' : 'rec'} onMouseEnter={() => setHover(r)} onMouseLeave={() => setHover(null)}
                    onFocus={() => setHover(r)} onBlur={() => setHover(null)}>
                    <h3 className="rec-title"><span className="rank" aria-hidden="true">{i + 1}</span><span>{r.label}</span></h3>
                    <p className="reason">{r.reason}</p>
                    <p className="rec-meta"><span>value {r.score.toFixed(3)}</span><span>effort {r.cost.toFixed(2)}</span>
                      <span>by a {r.check.role}</span>{r.delay_h > 0 && <span>{r.delay_h} h wait</span>}
                      {r.changes_decision && <span className="chip st-localized">may change the advisory</span>}</p>
                    {inspector && (
                      <div className="rec-buttons" role="group" aria-label={`Record the result of: ${r.label}`}>
                        <span className="muted small">Record result:</span>
                        <button className="small" disabled={busy} onClick={() => run(() => api.check(view.id, { ...r.check, positive: false }), (v) => `Recorded clean. ${summary(v)}`)}>Clean</button>
                        <button className="small warn" disabled={busy} onClick={() => run(() => api.check(view.id, { ...r.check, positive: true }), (v) => `Recorded polluted. ${summary(v)}`)}>Polluted</button>
                      </div>)}
                  </li>))}</ol>)}
              {!inspector && active && <p className="muted small">Investigators record check results. You can review the evidence and the advisory.</p>}
            </section>
          </div>

          <section className="panel ledger" aria-labelledby="ledger-h">
            <h2 id="ledger-h">Evidence ledger</h2>
            <div className="tablewrap" tabIndex={0} role="region" aria-label="Evidence ledger table">
              <table>
                <caption className="sr-only">Each piece of evidence and how it changed the estimate, newest first</caption>
                <thead><tr><th scope="col">#</th><th scope="col">Evidence</th><th scope="col">Data</th>
                  <th scope="col" className="num" title="log10 likelihood ratio for harmful point-source pollution">Evidence for harmful</th>
                  <th scope="col">Explanation shift</th><th scope="col" className="num">Location uncertainty (bits)</th><th scope="col">Leading entry after</th></tr></thead>
                <tbody>{[...view.ledger].reverse().map((e) => (
                  <tr key={e.index}><td className="num">{e.index}</td><td>{e.text}</td>
                    <td><span className={`tier ${e.tier}`}>{e.tier}</span></td>
                    <td className="num">{(e.harm_bans ?? 0) > 0 ? '+' : ''}{(e.harm_bans ?? 0).toFixed(2)}</td>
                    <td>{e.weight_for ? `${e.weight_for} ${e.weight_bans > 0 ? '+' : ''}${e.weight_bans.toFixed(2)}` : '·'}</td>
                    <td className="num">{e.entropy_before_bits.toFixed(2)} → {e.entropy_after_bits.toFixed(2)}</td>
                    <td>{view.sources.find((s) => s.id === e.top_source_after[0])?.label ?? 'upstream or unmapped'} {pct(e.top_source_after[1])}</td></tr>))}
                </tbody>
              </table>
            </div>
            <p className="muted small">{view.model.note}</p>
          </section>
        </div>)}

      {tab === 'advisory' && <AdvisoryPanel view={view} canApprove={publicHealth} busy={busy}
        onApprove={() => run(() => api.action(view.id, 'advisory'), () => 'Advisory published')}
        onLift={() => run(() => api.action(view.id, 'lift_advisory'), () => 'Advisory lifted and removed from the public map')} />}
      {tab === 'handoff' && <HandoffPanel view={view} canPush={inspector && !!config?.fhir_server} />}
      {tab === 'timeline' && <TimelinePanel view={view} />}
    </div>
  )
}

function AdvisoryPanel({ view, canApprove, busy, onApprove, onLift }:
  { view: CaseView; canApprove: boolean; busy: boolean; onApprove: () => void; onLift: () => void }) {
  const d = view.advisory_draft
  const published = [...view.actions].reverse().find((a) => a.type === 'advisory')
  const lifted = [...view.actions].reverse().find((a) => a.type === 'lift_advisory')
  const fixed = ['verified', 'fixed'].includes(view.status)
  const tiers: [string, string, string][] = [
    ['Observed', 'what people saw, smelled or measured', d.tiers.observed],
    ['Inferred', "the model's estimate, with its probability", d.tiers.inferred],
    ['Possible risk', 'what could happen to people, animals or the stream', d.tiers.possible_risk],
    ['Needs confirmation', 'what only a lab or clinician can confirm', d.tiers.needs_confirmation],
  ]
  return (
    <div role="tabpanel" id="panel-advisory" aria-labelledby="tab-advisory" className="page">
      <h2 className="section-h">Contact advisory</h2>
      <p className="muted lead">A person approves every public advisory. The wording keeps what was observed separate from what is inferred, and never claims a diagnosis.</p>
      <ol className="tiers">{tiers.map(([t, hint, text]) => (
        <li key={t} className="tier-card"><h3>{t} <span className="muted small">· {hint}</span></h3><p>{text}</p></li>))}</ol>
      <div className="grid2">
        {Object.entries(d.text).map(([l, text]) => (
          <section key={l} className="card" lang={l}><h3 lang="en">Public text · {LANG_NAME[l as Lang] ?? l}</h3><p>{text}</p></section>))}
      </div>
      {view.advisory_active && published ? (<>
        <p className="done">Published {new Date(published.at).toLocaleString()} by {published.approver}. <a href="#/public">See the public advisory map</a>.</p>
        {canApprove && <div className="row"><button disabled={busy} onClick={onLift}>Lift advisory</button>
          <span className="muted small">{fixed ? 'The fix has been reported. Lift the advisory once you are satisfied the water is safe.' : 'Removes it from the public map.'}</span></div>}
      </>) : lifted && published ? (
        <p className="done">Lifted {new Date(lifted.at).toLocaleString()} by {lifted.approver}. It is no longer on the public map.</p>
      ) : canApprove ? (
        <div className="row"><button className="primary" disabled={busy} onClick={onApprove}>Approve and publish advisory</button>
          <span className="muted small">{d.suggested ? 'The evidence supports an advisory.' : 'The evidence does not yet call for one; you may still publish.'}</span></div>
      ) : (
        <p className="muted">Waiting for a public-health officer to review and approve.{d.suggested && ' The evidence supports an advisory.'}</p>
      )}
    </div>
  )
}

function HandoffPanel({ view, canPush }: { view: CaseView; canPush: boolean }) {
  const [bundle, setBundle] = useState<any>(null)
  const [pushResult, setPushResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const announce = useAnnounce()
  useEffect(() => { api.fhir(view.id).then(setBundle).catch((e) => setError(e.message)) }, [view.id, view.actions.length, view.ledger.length])
  const counts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const e of bundle?.entry ?? []) m[e.resource.resourceType] = (m[e.resource.resourceType] ?? 0) + 1
    return Object.entries(m).sort((a, b) => b[1] - a[1])
  }, [bundle])
  const refsOk = useMemo(() => {
    if (!bundle) return null
    const ids = new Set(bundle.entry.map((e: any) => `${e.resource.resourceType}/${e.resource.id}`))
    const refs: string[] = []
    const walk = (x: any) => { if (x && typeof x === 'object') { if (typeof x.reference === 'string') refs.push(x.reference); Object.values(x).forEach(walk) } }
    bundle.entry.forEach((e: any) => walk(e.resource))
    return { total: refs.length, missing: refs.filter((r) => !ids.has(r)).length }
  }, [bundle])
  const find = (t: string) => bundle?.entry.find((e: any) => e.resource.resourceType === t)?.resource
  const confirm = (bundle?.entry ?? []).map((e: any) => e.resource).find((r: any) => r.resourceType === 'ServiceRequest' && r.code?.coding?.[0]?.code === 'confirm-entry')
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/fhir+json' }))
    const a = document.createElement('a'); a.href = url; a.download = `${view.id}.bundle.json`; a.click(); URL.revokeObjectURL(url)
  }
  const pushNow = async () => {
    setError(null)
    try { const r = await api.fhirPush(view.id); const m = `Sent ${r.resources} resources (${r.created} created, ${r.updated} updated) to ${r.server}`; setPushResult(m); announce(m) }
    catch (e: any) { setError(e.message) }
  }
  return (
    <div role="tabpanel" id="panel-handoff" aria-labelledby="tab-handoff" className="page">
      <h2 className="section-h">Hand-off package</h2>
      <p className="muted lead">HL7 FHIR R4, built on the OneAquaHealth implementation guide (LocationOah, GroupOah) plus Dipper response profiles. The example bundles validate with 0 errors in the official HL7 validator (<code>fhir/validate.sh</code>).</p>
      {error && <p className="error" role="alert">{error}</p>}
      {!bundle ? <p className="muted" role="status">Building bundle…</p> : <>
        <ul className="stat-row" aria-label="Bundle contents">{counts.map(([t, n]) => <li key={t}><strong>{n}</strong> {t}</li>)}</ul>
        {refsOk && <p className={refsOk.missing ? 'error' : 'done'}>{refsOk.missing ? `${refsOk.missing} of ${refsOk.total} references do not resolve.` : `All ${refsOk.total} internal references resolve.`}</p>}
        <div className="grid2">
          <section className="card"><h3>Source case · DetectedIssue</h3><p>{find('DetectedIssue')?.detail}</p></section>
          <section className="card"><h3>Exposure risk · RiskAssessment</h3><p>{find('RiskAssessment')?.prediction?.[0]?.rationale}</p>
            <p className="muted small">Subject: {find('RiskAssessment')?.subject?.reference} (people and animals using the reach)</p></section>
        </div>
        {confirm && <section className="card confirm-card">
          <h3>Confirm before repair · ServiceRequest {confirm.intent === 'order' ? '(sent to the utility)' : '(sent with the hand-off)'}</h3>
          <p>{confirm.reasonCode?.[0]?.text}</p>
          <p className="muted small">Dipper's localization is a probability, not proof. In the simulation benchmark about 1 in 7 localizations points at the wrong outfall.</p>
        </section>}
        <div className="row">
          <button onClick={download}>Download bundle (JSON)</button>
          {canPush && <button className="primary" onClick={pushNow}>Send to FHIR server</button>}
        </div>
        {pushResult && <p className="done" role="status">{pushResult}</p>}
        <details><summary>Show the full bundle</summary><pre className="json" tabIndex={0}>{JSON.stringify(bundle, null, 2)}</pre></details>
      </>}
    </div>
  )
}

function TimelinePanel({ view }: { view: CaseView }) {
  const events = useMemo(() => {
    const obs = view.observations.map((o, i) => ({ at: o.observed_at ?? view.opened_at, text: view.ledger[i]?.text ?? o.kind, kind: 'evidence', tier: o.tier }))
    const acts = view.actions.map((a) => ({ at: a.at, text: `${a.type.replace('_', ' ')} · ${a.approver ?? 'system'}${a.payload?.note ? ` · “${a.payload.note}”` : ''}`, kind: 'action', tier: 'observed' }))
    return [...obs, ...acts].sort((a, b) => a.at.localeCompare(b.at))
  }, [view])
  return (
    <div role="tabpanel" id="panel-timeline" aria-labelledby="tab-timeline" className="page">
      <h2 className="section-h">Timeline and audit trail</h2>
      <p className="muted lead">Every piece of evidence and every human decision, in order. Approvals carry the signed-in person's name, role and id.</p>
      <ol className="timeline">{events.map((e, i) => (
        <li key={i} className={`tl ${e.kind}`}><time dateTime={e.at}>{new Date(e.at).toLocaleString()}</time>
          <span>{e.text}</span>{e.tier === 'simulated' && <em className="tag">simulated</em>}</li>))}</ol>
    </div>
  )
}
