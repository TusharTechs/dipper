# web

Vite + React + TypeScript + MapLibre GL (OpenFreeMap tiles, no key). Node.js 22 LTS or newer.

```bash
uv run uvicorn dipper_api.main:app --reload --port 8000   # API, from the repo root (.env turns on demo mode)
npm --prefix web ci && npm --prefix web run dev            # http://localhost:3000, /api is proxied to :8000
npm --prefix web run build                                 # web/dist, served at / by dipper_api.main:site
```

| Route | Screen |
|---|---|
| `#/citizen` | Citizen PWA in four languages (English, Portuguese, Norwegian, Dutch): report (tap the map or pick the nearest point, toggle signs, optional photo), then a nearby mission and "what your check changed". Reports queue offline. |
| `#/public` | Public advisory map: approved advisories only, never suspected pipes or addresses |
| `#/ops` | Staff sign-in and case queue; in demo mode, start the C-014 replay (dry 18 Sep or wet 24 Aug 2026) |
| `#/ops/C-014` | Case workspace: probability along the real stream, explanations, "where it enters", unknowns, contact places, ranked next checks with both outcomes, evidence ledger, approvals, advisory, FHIR hand-off, timeline |
| `#/bench` | SourceBench results (simulation): success rate and cost per strategy, per-network table |
| `#/about` | How it works |

Simulated items are labelled on screen: a replay banner, a SYNTHETIC tag on outfalls, and a tier column in the ledger.

`npm run a11y -- <url>` runs the axe audit (WCAG 2.2 AA) at desktop, phone and 320 px widths; `npm run screenshots` refreshes the README screenshots.

MapLibre v6 is excluded from Vite pre-bundling (`vite.config.ts`) so its module worker loads.
