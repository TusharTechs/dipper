"""Dipper HTTP API. In-memory store for the prototype (PostGIS persistence is the next step).

    uv run uvicorn dipper_api.main:app --reload --port 8000     # docs at http://localhost:8000/docs
"""

from __future__ import annotations

import itertools
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from dipper_engine import Case, Context, Observation, ReachGraph
from dipper_engine.model import CHECK_TYPES, FEATURES, ROLES
from dipper_engine.scenario import TRUE_SOURCE, build_case, truth_result
from dipper_engine.sim import load_networks, run_trial, summarise
from dipper_engine.voi import recommend
from dipper_engine.weather import fetch_context

ROOT = Path(__file__).resolve().parents[2]
REACH_DIR = ROOT / "data" / "reaches"
CACHE_DIR = ROOT / "data" / "cache"

app = FastAPI(title="Dipper API", version="0.1.0",
              description="Bayesian source hunting for sewage pollution in urban streams. Prototype; in-memory store.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("DIPPER_CORS", "http://localhost:3000").split(","),
                   allow_methods=["*"], allow_headers=["*"])

_reaches: dict[str, ReachGraph] = {}
_cases: dict[str, Case] = {}
_scenario_truth: dict[str, str] = {}
_ids = itertools.count(1)


def reach(reach_id: str) -> ReachGraph:
    if reach_id not in _reaches:
        path = REACH_DIR / f"{reach_id}.geojson"
        if not path.exists():
            raise HTTPException(404, f"unknown reach {reach_id}")
        _reaches[reach_id] = ReachGraph.from_geojson(json.loads(path.read_text()))
    return _reaches[reach_id]


def get_case(case_id: str) -> Case:
    if case_id not in _cases:
        raise HTTPException(404, f"unknown case {case_id}")
    return _cases[case_id]


# ---- schemas -----------------------------------------------------------------------

class WeatherIn(BaseModel):
    rain_48h_mm: float | None = None
    tmax_c: float | None = None
    dry_days: int | None = None


class CaseIn(BaseModel):
    reach_id: str
    opened_at: datetime | None = None
    weather: WeatherIn | None = Field(None, description="Omit to fetch from Open-Meteo")


class SignalIn(BaseModel):
    reach_id: str
    lat: float
    lon: float
    observed_at: datetime | None = None
    features: dict[str, bool] = Field(default_factory=dict, description=f"Any of {', '.join(FEATURES)}")
    role: Literal["citizen", "trained", "inspector"] = "citizen"
    observer: str | None = Field(None, description="Pseudonymous id; never an email or name")
    case_id: str | None = None


class CheckIn(BaseModel):
    check_type: Literal["instream_look", "outfall_look", "ammonium_strip", "lab_ecoli"]
    positive: bool
    node_id: str | None = None
    candidate_id: str | None = None
    role: Literal["citizen", "trained", "inspector"] = "citizen"
    observed_at: datetime | None = None
    observer: str | None = None


class ActionIn(BaseModel):
    type: Literal["dispatch", "lab_request", "notify_utility", "advisory", "dismiss", "fixed", "verified", "close"]
    approver: str | None = None
    payload: dict = Field(default_factory=dict)


class SimIn(BaseModel):
    trials: int = Field(20, le=200)
    misspec: float = 1.3
    policies: list[str] = ["walk", "bisect", "entropy", "voi"]
    seed: int = 1


# ---- endpoints ---------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"ok": True, "cases": len(_cases)}


@app.get("/v1/reaches")
def list_reaches() -> list[dict]:
    out = []
    for p in sorted(REACH_DIR.glob("*.geojson")):
        g = reach(p.stem)
        out.append({"id": p.stem, "name": g.name, "city": g.city, "length_m": round(g.total_length_m),
                    "candidates": len(g.candidates), "places": len(g.places)})
    return out


@app.get("/v1/reaches/{reach_id}")
def get_reach(reach_id: str) -> dict:
    return reach(reach_id).to_geojson()


def _new_case(reach_id: str, opened_at: datetime | None, weather: WeatherIn | None) -> Case:
    g = reach(reach_id)
    when = opened_at or datetime.now(timezone.utc)
    if weather is not None:
        ctx = Context(rain_48h_mm=weather.rain_48h_mm, tmax_c=weather.tmax_c, dry_days=weather.dry_days, hour=when.hour)
    else:
        mid = next(iter(g.nodes.values()))
        ctx = fetch_context(mid.lat, mid.lon, when, cache_dir=CACHE_DIR)
    cid = f"C-{next(_ids):03d}"
    case = Case(cid, g, ctx, opened_at=when)
    case.reach_id = reach_id  # type: ignore[attr-defined]
    _cases[cid] = case
    return case


@app.post("/v1/cases")
def create_case(body: CaseIn) -> dict:
    return _new_case(body.reach_id, body.opened_at, body.weather).view()


@app.get("/v1/cases")
def list_cases(status: str | None = None) -> list[dict]:
    out = []
    for c in _cases.values():
        if status and c.status != status:
            continue
        b = c.belief
        top = b.top_source()
        lead = b.hypothesis_table()[0]
        out.append({"id": c.id, "reach": c.graph.name, "city": c.graph.city, "status": c.status,
                    "opened_at": c.opened_at.isoformat(), "leading_hypothesis": lead,
                    "top_source": {"id": top[0], "label": b.labels()[top[0]], "p": top[1]},
                    "p_harmful": round(b.p_harmful(), 3), "signals": len(b.observations)})
    return out


@app.get("/v1/cases/{case_id}")
def case_view(case_id: str, k: int = 5) -> dict:
    return get_case(case_id).view(n_recommendations=k)


@app.post("/v1/signals")
def post_signal(body: SignalIn) -> dict:
    unknown = set(body.features) - set(FEATURES)
    if unknown:
        raise HTTPException(422, f"unknown features {sorted(unknown)}")
    g = reach(body.reach_id)
    node, dist = g.nearest_node(body.lat, body.lon)
    if dist > 150:
        raise HTTPException(422, f"location is {dist:.0f} m from the mapped stream")
    case = get_case(body.case_id) if body.case_id else next(
        (c for c in _cases.values() if getattr(c, "reach_id", None) == body.reach_id and c.status in ("open", "localizing", "localized")),
        None) or _new_case(body.reach_id, body.observed_at, None)
    obs = Observation("report", True, node_id=node, role=body.role, features=tuple(body.features.items()),
                      observed_at=body.observed_at or datetime.now(timezone.utc), observer=body.observer)
    case.add(obs)
    return {"case_id": case.id, "snapped_node": node, "snap_distance_m": round(dist, 1),
            "ledger_entry": case.belief.ledger[-1].as_dict(), "status": case.status}


@app.get("/v1/cases/{case_id}/recommendations")
def recommendations(case_id: str, k: int = 5, roles: str = Query(",".join(ROLES))) -> list[dict]:
    c = get_case(case_id)
    return [r.as_dict() for r in recommend(c.belief, c.stakes, k=k, roles=tuple(roles.split(",")))]


@app.post("/v1/cases/{case_id}/checks")
def post_check(case_id: str, body: CheckIn) -> dict:
    c = get_case(case_id)
    if body.role not in CHECK_TYPES[body.check_type].roles:
        raise HTTPException(422, f"{body.role} cannot perform {body.check_type}")
    try:
        obs = Observation(body.check_type, body.positive, node_id=body.node_id, candidate_id=body.candidate_id,
                          role=body.role, observed_at=body.observed_at or datetime.now(timezone.utc), observer=body.observer)
        c.add(obs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return c.view()


@app.post("/v1/cases/{case_id}/actions")
def post_action(case_id: str, body: ActionIn) -> dict:
    c = get_case(case_id)
    try:
        c.act(body.type, body.approver, body.payload)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return c.view()


# ---- demo scenario (simulated reports and results, labelled) --------------------------

@app.post("/v1/scenarios/c014")
def scenario_start(wet: bool = False) -> dict:
    case, _ = build_case(wet=wet)
    case.reach_id = "coimbra-ribeira-de-coselhas"  # type: ignore[attr-defined]
    _cases[case.id] = case
    _scenario_truth[case.id] = TRUE_SOURCE
    return case.view() | {"scenario": {"label": "Scenario replay: real stream and weather, simulated reports and results"}}


@app.post("/v1/scenarios/{case_id}/autostep")
def scenario_step(case_id: str) -> dict:
    """Perform the engine's top recommendation with a result derived from the simulated truth."""
    if case_id not in _scenario_truth:
        raise HTTPException(404, "not a scenario case")
    c = get_case(case_id)
    rec = recommend(c.belief, c.stakes, k=1)[0]
    positive = truth_result(c.graph, rec.check, _scenario_truth[case_id])
    last = c.belief.clock or c.opened_at
    c.add(Observation(rec.check.check_type, positive, node_id=rec.check.node_id, candidate_id=rec.check.candidate_id,
                      role=rec.check.role, observed_at=last + timedelta(minutes=25), tier="simulated"))
    return {"performed": rec.as_dict(), "result": "positive" if positive else "clean", "case": c.view()}


# ---- context and benchmark -----------------------------------------------------------

@app.get("/v1/context/weather")
def weather(lat: float, lon: float, when: datetime) -> dict:
    ctx = fetch_context(lat, lon, when, cache_dir=CACHE_DIR)
    return {"regime": ctx.regime, "summary": ctx.describe(), **ctx.__dict__, "source": "Open-Meteo (CC BY 4.0)"}


@app.post("/v1/sim/runs")
def sim_run(body: SimIn) -> dict:
    import random
    nets = load_networks(REACH_DIR)
    results = [run_trial(n, pol, random.Random(f"{body.seed}-{n.name}-{k}"), misspec=body.misspec)
               for n in nets for k in range(body.trials) for pol in body.policies]
    return {"label": "SIMULATION", "networks": [n.name for n in nets], "summary": summarise(results)}
