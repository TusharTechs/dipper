"""Dipper HTTP API. In-memory store for the prototype (PostGIS persistence is the next step).

    uv run uvicorn dipper_api.main:app --reload --port 8000     # docs at http://localhost:8000/docs
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import hashlib

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from dipper_engine import Case, Context, Observation, ReachGraph
from dipper_engine.fhir import case_bundle
from dipper_engine.photo import PhotoModelUnavailable, conflicts, extract, redact, to_observation, vision_provider
from dipper_engine.model import CHECK_TYPES, FEATURES, ROLES
from dipper_engine.scenario import TRUE_SOURCE, build_case, truth_result
from dipper_engine.sim import load_networks, run_trial, summarise
from dipper_engine.voi import recommend
from dipper_engine.weather import fetch_context

from .store import Store

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")  # server-side secrets such as LLM_API_KEY; never sent to the browser
REACH_DIR = ROOT / "data" / "reaches"
CACHE_DIR = ROOT / "data" / "cache"

@asynccontextmanager
async def lifespan(_: FastAPI):
    cases, reach_of, truth = store.load_all(reach)
    _cases.update(cases)
    _reach_of.update(reach_of)
    _scenario_truth.update(truth)
    yield


app = FastAPI(lifespan=lifespan, title="Dipper API", version="0.1.0",
              description="Bayesian source hunting for sewage pollution in urban streams. Prototype; in-memory store.")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("DIPPER_CORS", "http://localhost:3000").split(","),
                   allow_methods=["*"], allow_headers=["*"])

_reaches: dict[str, ReachGraph] = {}
_cases: dict[str, Case] = {}
_scenario_truth: dict[str, str] = {}
_reach_of: dict[str, str] = {}
store = Store(Path(os.getenv("DIPPER_DB", str(ROOT / "data" / "dipper.sqlite3"))))


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
    cid = f"C-{store.next_number():03d}"
    case = Case(cid, g, ctx, opened_at=when)
    _cases[cid], _reach_of[cid] = case, reach_id
    store.create(case, reach_id)
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


@app.get("/v1/cases/{case_id}/history")
def case_history(case_id: str) -> list[dict]:
    """Append-only event history (observations and human actions), the audit trail."""
    get_case(case_id)
    return store.history(case_id)


@app.get("/v1/cases/{case_id}/fhir")
def case_fhir(case_id: str) -> dict:
    """FHIR R4 Bundle (collection) using OAH LocationOah/GroupOah plus Dipper response profiles."""
    return case_bundle(get_case(case_id))


def _record_report(reach_id: str, lat: float, lon: float, features: dict[str, bool], role: str,
                   observer: str | None, observed_at: datetime | None, case_id: str | None) -> tuple[Case, str, float]:
    unknown = set(features) - set(FEATURES)
    if unknown:
        raise HTTPException(422, f"unknown features {sorted(unknown)}")
    g = reach(reach_id)
    node, dist = g.nearest_node(lat, lon)
    if dist > 150:
        raise HTTPException(422, f"location is {dist:.0f} m from the mapped stream")
    case = get_case(case_id) if case_id else next(
        (c for c in _cases.values() if _reach_of.get(c.id) == reach_id and c.status in ("open", "localizing", "localized")),
        None) or _new_case(reach_id, observed_at, None)
    obs = Observation("report", True, node_id=node, role=role, features=tuple(features.items()),
                      observed_at=observed_at or datetime.now(timezone.utc), observer=observer)
    case.add(obs)
    store.add_observation(case.id, obs)
    return case, node, dist


@app.post("/v1/signals")
def post_signal(body: SignalIn) -> dict:
    case, node, dist = _record_report(body.reach_id, body.lat, body.lon, body.features, body.role, body.observer,
                                      body.observed_at, body.case_id)
    return {"case_id": case.id, "snapped_node": node, "snap_distance_m": round(dist, 1),
            "ledger_entry": case.belief.ledger[-1].as_dict(), "status": case.status}


MEDIA_DIR = ROOT / "data" / "media"


@app.post("/v1/signals/photo")
async def post_signal_photo(
    photo: UploadFile = File(...), reach_id: str = Form(...), lat: float = Form(...), lon: float = Form(...),
    features: str = Form("{}", description="JSON object of citizen answers, e.g. {\"grey\": true}"),
    observer: str | None = Form(None), case_id: str | None = Form(None),
) -> dict:
    """Citizen report with a photo. The citizen's answers are always recorded. The photo is redacted
    (EXIF stripped, faces blurred) before it is sent to the vision model, and only if face detection works."""
    try:
        answers = {k: bool(v) for k, v in json.loads(features).items()}
    except (json.JSONDecodeError, AttributeError) as exc:
        raise HTTPException(422, "features must be a JSON object") from exc
    raw = await photo.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(413, "photo larger than 15 MB")
    try:
        red = redact(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = datetime.now(timezone.utc)
    case, node, dist = _record_report(reach_id, lat, lon, answers, "citizen", observer, now, case_id)
    first = len(case.belief.ledger) - 1  # ledger entries created by this request start here
    sha = hashlib.sha256(red.jpeg).hexdigest()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    (MEDIA_DIR / f"{sha}.jpg").write_bytes(red.jpeg)
    photo_out: dict = {"sha256": sha, "faces_blurred": red.faces_blurred, "exif_removed": red.exif_removed}
    if not red.face_detection:
        photo_out |= {"status": "not_analysed", "reason": "face detection unavailable, so the photo was not sent"}
    else:
        try:
            pf = extract(red.jpeg)
            pobs = to_observation(pf, node, observed_at=now + timedelta(seconds=1))
            if pobs:
                case.add(pobs)
                store.add_observation(case.id, pobs)
            photo_out |= {"status": "analysed", "provider": vision_provider(), "note": pf.note, "usable": pf.image_usable and pf.shows_stream_or_outfall,
                          "features": {f: c.model_dump() for f, c in pf.calls().items()},
                          "conflicts": [c.__dict__ for c in conflicts(answers, pf)]}
        except PhotoModelUnavailable as exc:
            photo_out |= {"status": "not_analysed", "reason": str(exc)}
    return {"case_id": case.id, "snapped_node": node, "snap_distance_m": round(dist, 1), "status": case.status,
            "photo": photo_out, "ledger": [e.as_dict() for e in case.belief.ledger[first:]]}


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
        store.add_observation(case_id, obs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return c.view()


@app.post("/v1/cases/{case_id}/actions")
def post_action(case_id: str, body: ActionIn) -> dict:
    c = get_case(case_id)
    try:
        a = c.act(body.type, body.approver, body.payload)
        store.add_action(case_id, a.type, a.approver, a.payload, a.at)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    return c.view()


# ---- demo scenario (simulated reports and results, labelled) --------------------------

@app.post("/v1/scenarios/c014")
def scenario_start(wet: bool = False) -> dict:
    case, _ = build_case(wet=wet)
    base, n = case.id, 1
    while case.id in _cases:
        n += 1
        case.id = f"{base}-{n}"
    _cases[case.id], _reach_of[case.id] = case, "coimbra-ribeira-de-coselhas"
    _scenario_truth[case.id] = TRUE_SOURCE
    store.create(case, "coimbra-ribeira-de-coselhas", scenario_truth=TRUE_SOURCE)
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
    obs = Observation(rec.check.check_type, positive, node_id=rec.check.node_id, candidate_id=rec.check.candidate_id,
                      role=rec.check.role, observed_at=last + timedelta(minutes=25), tier="simulated")
    c.add(obs)
    store.add_observation(case_id, obs)
    return {"performed": rec.as_dict(), "result": "positive" if positive else "clean", "case": c.view()}


# ---- context and benchmark -----------------------------------------------------------

@app.get("/v1/context/weather")
def weather(lat: float, lon: float, when: datetime) -> dict:
    ctx = fetch_context(lat, lon, when, cache_dir=CACHE_DIR)
    return {"regime": ctx.regime, "summary": ctx.describe(), **ctx.__dict__, "source": "Open-Meteo (CC BY 4.0)"}


@app.get("/v1/sim/results")
def sim_results() -> dict:
    """Pre-computed SourceBench results (SIMULATION). Regenerate with `python -m dipper_engine.sim`."""
    path = ROOT / "data" / "sourcebench" / "results.json"
    if not path.exists():
        raise HTTPException(404, "no SourceBench results yet")
    return json.loads(path.read_text())


@app.post("/v1/sim/runs")
def sim_run(body: SimIn) -> dict:
    import random
    nets = load_networks(REACH_DIR)
    results = [run_trial(n, pol, random.Random(f"{body.seed}-{n.name}-{k}"), misspec=body.misspec)
               for n in nets for k in range(body.trials) for pol in body.policies]
    return {"label": "SIMULATION", "networks": [n.name for n in nets], "summary": summarise(results)}
