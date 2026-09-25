# web (to build)

Next.js + MapLibre GL (OpenFreeMap tiles, no key). Screens from the spec:

| Area | Screens |
|---|---|
| Citizen PWA | C1 report · C2 mission · C3 outcomes |
| Operations | O1 queue · O2 case workspace (probability ribbon, hypotheses, ledger, ranked checks) · O3 advisory · O4 handoff and FHIR · O5 SourceBench |
| Public | P1 advisory map |

The API already serves everything the O2 workspace needs:
- `GET /v1/cases/{id}` returns the `ribbon` (per-node P(polluted)), the `sources` with coordinates, `hypotheses`, `ledger`, `unknowns`, `exposure` and `recommendations`.
- `GET /v1/reaches/{id}` returns the stream GeoJSON.
- `POST /v1/scenarios/c014` then `POST /v1/scenarios/C-014/autostep` drives the demo.
