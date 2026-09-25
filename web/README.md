# web

Vite + React + TypeScript + MapLibre GL (OpenFreeMap tiles, no key).

```bash
uv run uvicorn dipper_api.main:app --port 8000   # from the repo root
npm --prefix web install && npm --prefix web run dev   # http://localhost:3000
```

| Route | Screen |
|---|---|
| `#/ops` | Start the C-014 replay (dry 18 Sep or wet 24 Aug 2026) |
| `#/ops/C-014` | Case workspace: probability ribbon on the real stream, candidate outfalls, reports and check pins, hypotheses, "where it enters", unknowns, contact places, ranked next checks with both outcome branches, evidence ledger, approval-gated actions (notify utility, approve advisory), FHIR bundle |
| `#/queue` | Case queue |
| `#/bench` | SourceBench results (simulation): success rate and cost per strategy, per-network table |
| `#/citizen` | Citizen PWA flow in PT and EN: report (tap map, toggle signs), mission (the engine's best citizen check nearby), outcome ("your check changed the search") |

Simulated items are labelled on screen: a replay banner, a SYNTHETIC tag on outfalls, and a tier column in the ledger.

MapLibre v6 is excluded from Vite pre-bundling (`vite.config.ts`) so its module worker loads.
