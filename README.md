# Dipper

**Find urban stream pollution at its source.** Citizens see sewage first. Dipper turns their reports
into a search that locates the polluting outfall in a few checks, and tells health systems in FHIR.

Built for the OneAquaHealth IEEE Global Hackathon 2026 (Track 3, AI-Supported Assessment).

> **Data honesty.** The stream geometry, culverts, nearby places (OpenStreetMap) and weather (Open-Meteo)
> are real. Candidate outfalls, citizen reports and check results in the demo are **simulated** and tagged
> as such. SourceBench is a **simulation**. See [DATA.md](DATA.md).

## How it works

1. **Reports become evidence.** A citizen report ("grey water, sewage smell") is snapped to a stream network
   built from OpenStreetMap, with flow direction, culverts and bridged gaps.
2. **Belief over what and where.** The engine keeps an exact joint probability over six explanations
   (foul sewage, overflow, chemical, sediment, bloom, benign) and every candidate entry point. Weather sets
   the priors: dry weather favours misconnections, rain favours overflows.
3. **Clean results count.** A clean look at the stream lowers the probability of every source upstream of
   that point. Intermittent discharges are handled: clean never means impossible.
4. **Next-best check.** Each possible check (a citizen look, an outfall look, an ammonium strip, a lab
   sample) at each location is scored as follows:

   `EVSI for the advisory decision + 1.2 × bits of source entropy removed − cost − delay`

   Each recommendation comes with both outcome branches in plain language.
5. **Photos help, people decide.** A citizen photo is redacted on the server (EXIF including GPS removed,
   faces blurred) and only then read by a vision model for visual indicators: Claude (`claude-opus-5`) or
   Google Gemini (`gemini-flash-latest`), chosen by `DIPPER_VISION_PROVIDER` or by whichever key is set. Those enter the ledger as a separate,
   weaker observer. A disagreement with the citizen's answer becomes a prompt to them and never overwrites
   what they said. Without a key the report is still recorded, and the photo is kept but not
   analysed.
6. **People decide.** Advisories, utility handoffs and dismissals require a named approver. Every update is
   explained in an evidence ledger.

## Quickstart

```bash
uv sync
uv run pytest                                   # 19 tests
uv run python -m dipper_engine.scenario         # C-014 replay on Ribeira de Coselhas, Coimbra (dry, 18 Sep 2026)
uv run python -m dipper_engine.scenario --wet   # same reports on 24 Aug 2026 after 24 mm of rain
uv run python -m dipper_engine.sim --trials 40  # SourceBench (simulation)
uv run uvicorn dipper_api.main:app --reload     # API docs at http://localhost:8000/docs
npm --prefix web install && npm --prefix web run dev   # UI at http://localhost:3000
uv run python scripts/export_fhir_examples.py && ./fhir/validate.sh   # FHIR bundles + HL7 validator
```

Demo through the API:

```bash
curl -X POST localhost:8000/v1/scenarios/c014
curl -X POST localhost:8000/v1/scenarios/C-014/autostep     # repeat until status = localized
curl -X POST localhost:8000/v1/cases/C-014/actions -H 'content-type: application/json' \
     -d '{"type":"notify_utility","approver":"tech-01"}'
```

## SourceBench results (SIMULATION)

**Setup:**
- 7 networks: 5 real OAH streams (Coimbra ×2, Oslo ×3) and 2 synthetic.
- 40 trials per network, identical truths for every strategy.
- Budget of 25 checks.
- The simulated world is noisier than the model (`--misspec 1.3`) and its discharges come in bursts.

| Strategy | Localized correctly | Wrong localization | Median checks (successes) | Mean cost |
|---|---|---|---|---|
| Walk the bank, outfall by outfall | 26% | 7% | 19 | 1.48 |
| Bisect (look at the stream at the 50% point) | 43% | 14% | 13 | 0.95 |
| **Dipper (value of information)** | **57%** | 9% | 9 | 1.26 |
| Greedy information gain, ignoring cost | 75% | 9% | 8 | 4.78 |
| Random check | 6% | 0% | 10 | 4.76 |

**Reading:**
- Dipper roughly doubles the success rate of a bank walk at lower cost.
- Pure information gain succeeds more often, but spends about 3.8× more, mostly on lab samples.
- `search_weight` moves along this trade-off: a higher value means faster but costlier.

These are simulated results under stated assumptions, not field performance. Reproduce with
`uv run python -m dipper_engine.sim --trials 40 --seed 1 --misspec 1.3`; the full output is in
`data/sourcebench/results.json`.

## Repository layout

```
src/dipper_engine/
  model.py      hypotheses, priors, likelihood tables, check types (the model card in code)
  graph.py      stream graph: OSM builder (gaps, culverts), synthetic trees, GeoJSON I/O, labels
  belief.py     joint Bayesian belief over (hypothesis, source); evidence ledger; safeguards
  voi.py        next-best check: EVSI + search value − cost; plain-language reasons
  exposure.py   contact places downstream and travel time (proximity, not dose-response)
  case.py       case lifecycle, human approval gates, API view (ribbon, unknowns, recommendations)
  weather.py    Open-Meteo context with on-disk cache
  osm.py        Overpass queries for streams and places
  scenario.py   C-014 replay (real stream and weather, simulated reports and results)
  sim.py        SourceBench: walk vs bisect vs entropy vs value-of-information strategies
src/dipper_api/main.py   FastAPI (in-memory store)
scripts/fetch_reaches.py fetch OAH pilot streams into data/reaches
data/reaches/            cached reach GeoJSON (Coimbra, Oslo, Ghent)
docs/model-card.md       every parameter and its rationale
web/                     Vite + React + MapLibre UI (see web/README.md)
fhir/ig/                 Dipper FSH profiles on the OAH IG; fhir/examples/ bundles; fhir/validate.sh
```

## Status

| Built | Next |
|---|---|
| Engine, value-of-information recommender, SourceBench, scenario replay, API, 36 tests | Live evaluation of photo features on labelled outfall photos (needs an API key) |
| Web UI: case workspace with probability ribbon, queue, SourceBench screen, citizen report, photo and mission flow (PT and EN) | PostGIS for multi-user deployments (SQLite event store today) |
| FHIR: 8 Dipper response profiles on the OAH IG; bundle export; **0 errors** in the HL7 validator | Offline PWA, notifications, ENORA API import |
| Real OSM reaches for 6 OAH streams; real weather context; human approval gates; evidence ledger | Expert review of likelihoods; lab calibration |
| SQLite event store (cases survive restarts; `/history` audit trail) | Number-plate redaction |
| Photo pipeline: EXIF stripped, faces blurred, then Claude (`claude-opus-5`, structured output, refusal fallbacks) reads visual indicators as a down-weighted observer | |

## Licence and attribution

Code: Apache-2.0. Map data © OpenStreetMap contributors (ODbL). Weather data by Open-Meteo (CC BY 4.0).
Not affiliated with or endorsed by the OneAquaHealth consortium.
