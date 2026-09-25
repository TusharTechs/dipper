import { useEffect, useMemo, useState } from 'react'

interface Row {
  network: string; policy: string; trials: number; success_rate: number; wrong_localization_rate: number
  median_checks: number; median_checks_when_successful: number | null; mean_cost: number
}
interface Results { label: string; networks: string[]; summary: Row[]; args: { trials: number; misspec: number; seed: number } }

const ORDER = ['voi', 'entropy', 'bisect', 'walk', 'random']
const SHORT: Record<string, string> = { voi: 'Dipper', entropy: 'Greedy information', bisect: 'Bisect', walk: 'Bank walk', random: 'Random' }
const NAME: Record<string, string> = {
  voi: 'Dipper (value of information)', entropy: 'Greedy information, ignores cost', bisect: 'Bisect the stream',
  walk: 'Walk the bank, outfall by outfall', random: 'Random check',
}

function HBar({ rows, value, format, max, title, note }: {
  rows: Row[]; value: (r: Row) => number; format: (v: number) => string; max: number; title: string; note: string
}) {
  const [hover, setHover] = useState<string | null>(null)
  const W = 460, labelW = 128, band = 34, bar = 18, top = 6, H = top + rows.length * band
  const x = (v: number) => labelW + (v / max) * (W - labelW - 56)
  return (
    <figure className="bench-chart">
      <figcaption><strong>{title}</strong><span className="muted small">{note}</span></figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={title}>
        {[0.25, 0.5, 0.75, 1].map((t) => (
          <line key={t} x1={x(max * t)} x2={x(max * t)} y1={0} y2={H} className="grid" />
        ))}
        {rows.map((r, i) => {
          const y = top + i * band + (band - bar) / 2
          const w = Math.max(2, x(value(r)) - labelW)
          const hot = r.policy === 'voi'
          return (
            <g key={r.policy} onMouseEnter={() => setHover(r.policy)} onMouseLeave={() => setHover(null)}>
              <rect x={0} y={top + i * band} width={W} height={band} fill="transparent" />
              <text x={labelW - 10} y={y + bar / 2} dominantBaseline="central" textAnchor="end" className={hot ? 'cat hot' : 'cat'}>{SHORT[r.policy]}</text>
              <path className={hot ? 'mark hot' : 'mark'} opacity={hover && hover !== r.policy ? 0.45 : 1}
                d={`M${labelW},${y} h${w - 4} a4,4 0 0 1 4,4 v${bar - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z`} />
              <text x={labelW + w + 6} y={y + bar / 2} dominantBaseline="central" className={hot ? 'val hot' : 'val'}>{format(value(r))}</text>
            </g>
          )
        })}
      </svg>
      <div className="bench-tip" aria-live="polite">
        {hover ? (() => { const r = rows.find((x) => x.policy === hover)!; return (
          <span><b>{NAME[r.policy]}</b>: localized correctly {Math.round(r.success_rate * 100)}% · wrong {Math.round(r.wrong_localization_rate * 100)}% · median checks when found {r.median_checks_when_successful ?? '–'} · mean cost {r.mean_cost.toFixed(2)}</span>) })()
          : <span className="muted small">Hover a bar for details.</span>}
      </div>
    </figure>
  )
}

export default function Bench() {
  const [res, setRes] = useState<Results | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { fetch('/api/v1/sim/results').then((r) => r.ok ? r.json() : Promise.reject(r.statusText)).then(setRes).catch((e) => setErr(String(e))) }, [])
  const all = useMemo(() => ORDER.map((p) => res?.summary.find((r) => r.network === 'ALL' && r.policy === p)).filter(Boolean) as Row[], [res])
  if (err) return <div className="queue"><p className="error">Could not load results: {err}</p></div>
  if (!res) return <div className="queue"><p className="muted">Loading…</p></div>
  const nets = res.networks
  return (
    <div className="queue bench">
      <div className="banner">SIMULATION · synthetic incidents on real OneAquaHealth stream networks · not field performance</div>
      <h1>SourceBench: how fast does each strategy find the source?</h1>
      <p className="muted">{nets.length} networks ({nets.join(', ')}) · {res.args.trials} trials each · same true source for every strategy · budget 25 checks · simulated world {res.args.misspec}× noisier than the model, with bursty discharges.</p>
      <div className="bench-grid">
        <HBar rows={all} value={(r) => r.success_rate} max={1} format={(v) => `${Math.round(v * 100)}%`}
          title="Localized the correct outfall" note="higher is better" />
        <HBar rows={all} value={(r) => r.mean_cost} max={Math.max(...all.map((r) => r.mean_cost)) * 1.05} format={(v) => v.toFixed(2)}
          title="Mean cost per case" note="normalised effort; lower is better" />
      </div>
      <p className="bench-legend"><span><i className="sw hot" />Dipper</span><span><i className="sw" />baseline strategies</span>
        <span className="muted small">Greedy information maximizes bits learned per check and ignores cost. Bank walk checks every outfall from the downstream end.</span></p>
      <h2>By network</h2>
      <div className="tablewrap"><table>
        <thead><tr><th>Network</th>{ORDER.map((p) => <th key={p} className="num">{NAME[p].split(' (')[0].split(',')[0]}</th>)}</tr></thead>
        <tbody>{nets.map((n) => (
          <tr key={n}><td>{n}</td>{ORDER.map((p) => { const r = res.summary.find((x) => x.network === n && x.policy === p)
            return <td key={p} className={p === 'voi' ? 'num strong' : 'num'}>{r ? `${Math.round(r.success_rate * 100)}% · ${r.mean_cost.toFixed(2)}` : '–'}</td> })}</tr>))}
        </tbody>
      </table></div>
      <p className="muted small">Each cell: share localized correctly · mean cost. Reproduce with <code>uv run python -m dipper_engine.sim --trials {res.args.trials} --seed {res.args.seed} --misspec {res.args.misspec}</code>.</p>
    </div>
  )
}
