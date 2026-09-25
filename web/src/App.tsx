import { useEffect, useState } from 'react'
import Bench from './Bench'
import Citizen from './Citizen'
import Workspace from './Workspace'
import { api, type CaseSummary } from './api'

type Route = { page: 'ops' | 'queue' | 'citizen' | 'bench'; caseId: string | null }

function parse(): Route {
  const h = window.location.hash.replace(/^#\/?/, '')
  const [page, id] = h.split('/')
  if (page === 'citizen') return { page: 'citizen', caseId: null }
  if (page === 'queue') return { page: 'queue', caseId: null }
  if (page === 'bench') return { page: 'bench', caseId: null }
  return { page: 'ops', caseId: id || null }
}

function Queue() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  useEffect(() => { api.cases().then(setCases).catch(() => setCases([])) }, [])
  return (
    <div className="queue">
      <h1>Case queue</h1>
      {!cases ? <p className="muted">Loading…</p> : cases.length === 0 ? <p className="muted">No cases yet. Start the scenario from Operations.</p> : (
        <div className="tablewrap"><table>
          <thead><tr><th>Case</th><th>Stream</th><th>Status</th><th>Leading explanation</th><th>Likely entry</th><th className="num">P(harmful)</th><th className="num">Signals</th></tr></thead>
          <tbody>{cases.map((c) => (
            <tr key={c.id} onClick={() => { window.location.hash = `#/ops/${c.id}` }} className="clickable">
              <td><a href={`#/ops/${c.id}`}>{c.id}</a></td><td>{c.reach}, {c.city}</td>
              <td><span className={`chip st-${c.status}`}>{c.status.replace('_', ' ')}</span></td>
              <td>{c.leading_hypothesis.label} ({Math.round(c.leading_hypothesis.p * 100)}%)</td>
              <td>{c.top_source.label} ({Math.round(c.top_source.p * 100)}%)</td>
              <td className="num">{Math.round(c.p_harmful * 100)}%</td><td className="num">{c.signals}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  )
}

export default function App() {
  const [route, setRoute] = useState<Route>(parse)
  useEffect(() => {
    const on = () => setRoute(parse())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return (
    <div className="app">
      <nav className="top">
        <a className="brand" href="#/ops">Dipper</a>
        <a className={route.page === 'ops' ? 'on' : ''} href={route.caseId ? `#/ops/${route.caseId}` : '#/ops'}>Operations</a>
        <a className={route.page === 'queue' ? 'on' : ''} href="#/queue">Queue</a>
        <a className={route.page === 'citizen' ? 'on' : ''} href="#/citizen">Citizen</a>
        <a className={route.page === 'bench' ? 'on' : ''} href="#/bench">SourceBench</a>
        <span className="spacer" />
        <span className="muted small">Prototype · OneAquaHealth IEEE Hackathon 2026</span>
      </nav>
      {route.page === 'ops' && <Workspace caseId={route.caseId} onCase={(id) => { window.location.hash = `#/ops/${id}` }} />}
      {route.page === 'queue' && <Queue />}
      {route.page === 'citizen' && <Citizen />}
      {route.page === 'bench' && <Bench />}
    </div>
  )
}
