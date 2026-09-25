"""Dipper HTTP API.

    uv run uvicorn dipper_api.main:app --reload --port 8000   # API only, docs at /docs
    uv run uvicorn dipper_api.main:site --port 8000           # API under /api plus the built web app at /

Access model:
  * Citizens are anonymous. They can report, answer their own mission, and read a safe case summary.
  * Staff use bearer tokens (see auth.py). Full case views reveal suspected outfalls and are staff-only.
  * Every approval is attributed to the authenticated user: advisories need public_health, hand-offs need inspector.
  * DIPPER_DEMO=1 enables the labelled scenario replay and short-lived demo sign-in per role.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, Field, StrictBool

from dipper_engine import Case, Context, Observation, ReachGraph
from dipper_engine.fhir import FhirPushError, case_bundle, push
from dipper_engine.graph import haversine_m
from dipper_engine.model import CHECK_TYPES, FEATURES, NONE, OUTSIDE
from dipper_engine.oah import map_submission
from dipper_engine.photo import PhotoModelUnavailable, conflicts, extract, redact, to_observation, vision_provider
from dipper_engine.scenario import TRUE_SOURCE, build_case, truth_result
from dipper_engine.sim import load_networks, run_trial, summarise
from dipper_engine.voi import recommend
from dipper_engine.weather import fetch_context

from .auth import ROLES, User, Users, current_user, demo_enabled, require, require_staff
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")  # server-side secrets such as LLM_API_KEY; never sent to the browser
REACH_DIR = ROOT / "data" / "reaches"
CACHE_DIR = ROOT / "data" / "cache"
MEDIA_DIR = Path(os.getenv("DIPPER_MEDIA", str(ROOT / "data" / "media")))
WEB_DIST = ROOT / "web" / "dist"
MAX_PHOTO_BYTES = 10 * 1024 * 1024
CASE_WINDOW = timedelta(hours=72)  # a new report joins an open case on the same reach active within this window
DEMO_REACH = "coimbra-ribeira-de-coselhas"

log = logging.getLogger("dipper")
logging.basicConfig(level=os.getenv("DIPPER_LOG_LEVEL", "INFO"), format="%(message)s")

_lock = threading.RLock()          # guards cases, reaches and every store write
_reaches: dict[str, ReachGraph] = {}
_cases: dict[str, Case] = {}
_scenario_truth: dict[str, str] = {}
_reach_of: dict[str, str] = {}
store = Store(Path(os.getenv("DIPPER_DB", str(ROOT / "data" / "dipper.sqlite3"))))
users = Users(store.db, _lock)
TZ_BY_CITY = {"Coimbra": "Europe/Lisbon", "Oslo": "Europe/Oslo", "Ghent": "Europe/Brussels",
              "Toulouse": "Europe/Paris", "Benevento": "Europe/Rome", "Heraklion": "Europe/Athens"}


def _pepper() -> bytes:
    """Secret for pseudonymising observer ids. From DIPPER_PEPPER, else generated once and kept in the database."""
    env = os.getenv("DIPPER_PEPPER")
    if env:
        return env.encode()
    with _lock, store.db:
        store.db.execute("create table if not exists settings (k text primary key, v text not null)")
        row = store.db.execute("select v from settings where k = 'pepper'").fetchone()
        if row:
            return row[0].encode()
        value = uuid.uuid4().hex + uuid.uuid4().hex
        store.db.execute("insert into settings values ('pepper', ?)", (value,))
        return value.encode()


PEPPER = _pepper()


def pseudonym(raw: str | None) -> str | None:
    """Stable, non-reversible observer id. The client-side id never leaves the API."""
    if not raw:
        return None
    return "p_" + hmac.new(PEPPER, raw.encode(), hashlib.sha256).hexdigest()[:16]


@asynccontextmanager
async def lifespan(_: FastAPI):
    with _lock:
        cases, reach_of, truth = store.load_all(reach)
        _cases.update(cases)
        _reach_of.update(reach_of)
        _scenario_truth.update(truth)
        users.purge_expired()
    log.info(json.dumps({"event": "startup", "cases": len(_cases), "demo": demo_enabled()}))
    yield


app = FastAPI(lifespan=lifespan, title="Dipper API", version="0.2.0",
              description="Bayesian source hunting for sewage pollution in urban streams.")
app.state.users = users
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("DIPPER_CORS", "http://localhost:3000").split(",") if o],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])


# ---- middleware: request ids, security headers, logging, rate limits -------------------

RATE_LIMITS = {"/v1/signals": (30, 60), "/v1/signals/photo": (10, 60), "/v1/auth/demo": (20, 60),
               "/v1/context/weather": (30, 60)}
_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def _client_key(request: Request) -> str:
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip() or
          (request.client.host if request.client else "unknown"))
    return hashlib.sha256(ip.encode()).hexdigest()[:16]  # never keep raw IPs


@app.middleware("http")
async def _edge(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    path = request.url.path
    limit = RATE_LIMITS.get(path) if request.method == "POST" or path == "/v1/context/weather" else None
    if limit:
        n, window = limit
        q = _hits[(path, _client_key(request))]
        now = time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            return JSONResponse({"detail": "too many requests, try again in a minute"}, status_code=429,
                                headers={"Retry-After": str(window), "X-Request-ID": rid})
        q.append(now)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception(json.dumps({"event": "error", "rid": rid, "path": path}))
        return JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500, headers={"X-Request-ID": rid})
    response.headers.update({"X-Request-ID": rid, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                             "X-Frame-Options": "DENY", "Permissions-Policy": "geolocation=(self), camera=(self)"})
    log.info(json.dumps({"event": "request", "rid": rid, "method": request.method, "path": path,
                         "status": response.status_code, "ms": round((time.perf_counter() - t0) * 1000, 1)}))
    return response


# ---- helpers --------------------------------------------------------------------------

def reach(reach_id: str) -> ReachGraph:
    with _lock:
        if reach_id not in _reaches:
            if not reach_id.replace("-", "").replace("õ", "o").isalnum():
                raise HTTPException(404, "unknown reach")
            path = REACH_DIR / f"{reach_id}.geojson"
            if not path.exists() or path.resolve().parent != REACH_DIR.resolve():
                raise HTTPException(404, f"unknown reach {reach_id}")
            _reaches[reach_id] = ReachGraph.from_geojson(json.loads(path.read_text()))
        return _reaches[reach_id]


def get_case(case_id: str) -> Case:
    if case_id not in _cases:
        raise HTTPException(404, f"unknown case {case_id}")
    return _cases[case_id]


def _signed(user: User) -> str:
    return f"{user.name} ({user.role.replace('_', ' ')}, {user.id})" + (" [demo]" if user.demo else "")


def _last_activity(c: Case) -> datetime:
    return c.belief.clock or c.opened_at


def _new_case(reach_id: str, opened_at: datetime | None, weather: "WeatherIn | None") -> Case:
    g = reach(reach_id)
    tz = ZoneInfo(g.meta.get("tz") or TZ_BY_CITY.get(g.city, "UTC"))
    when = (opened_at or datetime.now(timezone.utc)).astimezone(tz)  # day/night activity uses local time
    if weather is not None:
        ctx = Context(rain_48h_mm=weather.rain_48h_mm, tmax_c=weather.tmax_c, dry_days=weather.dry_days, hour=when.hour)
    else:
        mid = next(iter(g.nodes.values()))
        ctx = fetch_context(mid.lat, mid.lon, when, cache_dir=CACHE_DIR)
    cid = f"C-{store.next_number():03d}"
    case = Case(cid, g, ctx, opened_at=when)
    _cases[cid], _reach_of[cid] = case, reach_id
    store.create(case, reach_id)
    log.info(json.dumps({"event": "case_opened", "case": cid, "reach": reach_id}))
    return case


def _case_for_signal(reach_id: str, when: datetime) -> Case:
    """Join the most recently active open case on this reach, or open a new one."""
    open_cases = [c for c in _cases.values() if _reach_of.get(c.id) == reach_id and c.id not in _scenario_truth
                  and c.status in ("open", "localizing", "localized") and when - _last_activity(c) <= CASE_WINDOW]
    return max(open_cases, key=_last_activity) if open_cases else _new_case(reach_id, when, None)


def _add(case: Case, obs: Observation) -> None:
    """Validate, persist, then apply. A rejected observation changes neither memory nor the database."""
    if case.status in Case.TERMINAL:
        raise HTTPException(409, f"case {case.id} is {case.status}; new evidence opens a new case")
    try:
        case.belief.validate(obs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    store.add_observation(case.id, obs)
    case.add(obs)


# ---- schemas --------------------------------------------------------------------------

class WeatherIn(BaseModel):
    rain_48h_mm: float | None = Field(None, ge=0, le=1000)
    tmax_c: float | None = Field(None, ge=-60, le=60)
    dry_days: int | None = Field(None, ge=0, le=365)


class CaseIn(BaseModel):
    reach_id: str
    opened_at: AwareDatetime | None = None
    weather: WeatherIn | None = Field(None, description="Omit to fetch from Open-Meteo")


class SignalIn(BaseModel):
    reach_id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    features: dict[str, StrictBool] = Field(default_factory=dict, max_length=len(FEATURES),
                                            description=f"Any of {', '.join(FEATURES)}")
    observer: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]*$",
                                 description="Device-local random id; pseudonymised on the server, never an email or name")


class CheckIn(BaseModel):
    check_type: Literal["instream_look", "outfall_look", "ammonium_strip", "lab_ecoli"]
    positive: bool
    node_id: str | None = Field(None, max_length=40)
    candidate_id: str | None = Field(None, max_length=40)
    observer: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]*$")


class CitizenCheckIn(BaseModel):
    mission_key: str = Field(max_length=120)
    positive: bool
    observer: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]*$")


class ActionIn(BaseModel):
    type: Literal["dispatch", "lab_request", "notify_utility", "advisory", "dismiss", "fixed", "verified", "close"]
    note: str | None = Field(None, max_length=500, description="Optional reason, stored in the audit trail")


class DemoIn(BaseModel):
    role: Literal["inspector", "public_health", "admin"]


class SimIn(BaseModel):
    trials: int = Field(20, ge=1, le=200)
    misspec: float = Field(1.3, ge=1.0, le=3.0)
    policies: list[Literal["walk", "bisect", "entropy", "voi", "random"]] = ["walk", "bisect", "entropy", "voi"]
    seed: int = 1


ACTION_ROLE = {"advisory": "public_health", "notify_utility": "inspector", "dispatch": "inspector",
               "lab_request": "inspector", "dismiss": "inspector", "fixed": "inspector", "verified": "inspector",
               "close": "inspector"}
CHECK_ROLE = {"instream_look": "citizen", "outfall_look": "citizen", "ammonium_strip": "trained", "lab_ecoli": "inspector"}


# ---- health, auth ------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/ready")
def ready() -> dict:
    with _lock:
        store.db.execute("select 1").fetchone()
    return {"ok": True, "cases": len(_cases), "demo": demo_enabled(), "vision_provider": vision_provider(),
            "fhir_server": bool(os.getenv("FHIR_BASE_URL"))}


@app.post("/v1/auth/demo")
def auth_demo(body: DemoIn) -> dict:
    """Short-lived demo sign-in for evaluators. Disabled unless DIPPER_DEMO=1."""
    if not demo_enabled():
        raise HTTPException(404, "demo sign-in is disabled")
    names = {"inspector": "Demo investigator", "public_health": "Demo public-health officer", "admin": "Demo admin"}
    user, token = users.create(names[body.role], body.role, ttl_s=4 * 3600, demo=True)
    return {"token": token, "user": user.__dict__}


@app.get("/v1/auth/me")
def auth_me(user: User = Depends(require_staff)) -> dict:
    return user.__dict__


@app.get("/v1/config")
def config() -> dict:
    return {"demo": demo_enabled(), "roles": ROLES, "demo_reach": DEMO_REACH if demo_enabled() else None,
            "fhir_server": bool(os.getenv("FHIR_BASE_URL"))}


# ---- reaches ------------------------------------------------------------------------------

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


# ---- citizen: report, photo, mission, safe summary ----------------------------------------

def _record_report(reach_id: str, lat: float, lon: float, features: dict[str, bool], observer: str | None,
                   observed_at: datetime, media: str | None = None) -> tuple[Case, str, float]:
    unknown = set(features) - set(FEATURES)
    if unknown:
        raise HTTPException(422, f"unknown features {sorted(unknown)}")
    g = reach(reach_id)
    node, dist = g.nearest_node(lat, lon)
    if dist > 150:
        raise HTTPException(422, f"location is {dist:.0f} m from the mapped stream; move closer to the water")
    case = _case_for_signal(reach_id, observed_at)
    _add(case, Observation("report", True, node_id=node, role="citizen", features=tuple(features.items()),
                           observed_at=observed_at, observer=pseudonym(observer), media=media))
    return case, node, dist


@app.post("/v1/signals")
def post_signal(body: SignalIn) -> dict:
    with _lock:
        case, node, dist = _record_report(body.reach_id, body.lat, body.lon, body.features, body.observer,
                                          datetime.now(timezone.utc))
        return {"case_id": case.id, "snap_distance_m": round(dist, 1), "status": case.status}


@app.post("/v1/signals/photo")
def post_signal_photo(
    photo: UploadFile = File(...), reach_id: str = Form(..., max_length=80), lat: float = Form(..., ge=-90, le=90),
    lon: float = Form(..., ge=-180, le=180),
    features: str = Form("{}", max_length=2000, description='JSON object of citizen answers, e.g. {"grey": true}'),
    observer: str | None = Form(None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]*$"),
) -> dict:
    """Citizen report with a photo. The answers are always recorded. The photo is redacted (EXIF stripped,
    faces blurred) and analysed only if face detection works; otherwise it is discarded, not stored.
    A plain `def`: FastAPI runs it in a worker thread, so image work and the model call never block the server."""
    try:
        parsed = json.loads(features)
        if not isinstance(parsed, dict) or not all(isinstance(v, bool) for v in parsed.values()):
            raise ValueError
        answers = {str(k): v for k, v in parsed.items()}
    except ValueError as exc:
        raise HTTPException(422, "features must be a JSON object of true/false answers") from exc
    raw = photo.file.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "photo larger than 10 MB")
    try:
        red = redact(raw)
    except ValueError as exc:
        raise HTTPException(422, "that file is not a readable photo") from exc
    now = datetime.now(timezone.utc)
    sha = hashlib.sha256(red.jpeg).hexdigest() if red.face_detection else None
    with _lock:
        case, node, dist = _record_report(reach_id, lat, lon, answers, observer, now, media=sha)
        first = len(case.belief.ledger) - 1
    photo_out: dict = {"exif_removed": True, "faces_blurred": red.faces_blurred}
    if not red.face_detection:
        photo_out |= {"status": "not_analysed", "reason": "face blurring is unavailable, so the photo was discarded"}
    else:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / f"{sha}.jpg").write_bytes(red.jpeg)
        try:
            pf = extract(red.jpeg)  # outside the lock: a slow model call must not block other requests
            pobs = to_observation(pf, node, observed_at=now + timedelta(seconds=1))
            with _lock:
                if pobs:
                    _add(case, Observation(pobs.kind, pobs.positive, node_id=pobs.node_id, role=pobs.role,
                                           features=pobs.features, observed_at=pobs.observed_at, media=sha))
            photo_out |= {"status": "analysed", "provider": vision_provider(), "note": pf.note,
                          "usable": pf.image_usable and pf.shows_stream_or_outfall,
                          "conflicts": [c.__dict__ for c in conflicts(answers, pf)]}
        except PhotoModelUnavailable as exc:
            photo_out |= {"status": "not_analysed", "reason": str(exc)}
        except Exception:  # noqa: BLE001 - any provider failure must not lose or duplicate the citizen's report
            log.exception(json.dumps({"event": "photo_model_error", "case": case.id}))
            photo_out |= {"status": "not_analysed", "reason": "the photo model failed; your report was still recorded"}
    with _lock:
        return {"case_id": case.id, "snap_distance_m": round(dist, 1), "status": case.status, "photo": photo_out,
                "ledger": [e.text for e in case.belief.ledger[first:]]}


MISSION_POOL = 12            # citizen checks considered for a mission
WALK_COST_PER_KM = 0.08      # score given up per km a volunteer must walk (same units as the check score)


def _missions(case: Case, k: int = MISSION_POOL) -> list:
    if case.status not in ("open", "localizing"):
        return []
    return recommend(case.belief, case.stakes, k=k, roles=("citizen",))


def _mission_node(g, r) -> str:
    return g.candidate(r.check.candidate_id).node_id if r.check.candidate_id else r.check.node_id


def _pick_mission(case: Case, lat: float | None, lon: float | None):
    """The most useful citizen check after charging for the walk from where the citizen is standing.
    Without a location, the most useful check overall."""
    pool = _missions(case)
    if not pool:
        return None, None
    if lat is None or lon is None:
        return pool[0], None
    g = case.graph
    walks = [haversine_m(lat, lon, g.nodes[_mission_node(g, r)].lat, g.nodes[_mission_node(g, r)].lon) for r in pool]
    i = max(range(len(pool)), key=lambda j: pool[j].score - WALK_COST_PER_KM * walks[j] / 1000)
    return pool[i], walks[i]


@app.get("/v1/citizen/cases/{case_id}")
def citizen_case(case_id: str, lat: float | None = Query(None, ge=-90, le=90),
                 lon: float | None = Query(None, ge=-180, le=180)) -> dict:
    """What a citizen may see: status, their mission, what happened, any published advisory. No outfall ranking.
    `lat`/`lon` (optional, never stored) let the mission favour a spot within a short walk."""
    with _lock:
        c = get_case(case_id)
        g = c.graph
        mission = None
        r, walk = _pick_mission(c, lat, lon)
        if r:
            nid = _mission_node(g, r)
            nd = g.nodes[nid]
            where = g.candidate(r.check.candidate_id).label if r.check.candidate_id else g.node_label(nid)
            mission = {"key": r.check.key(), "type": r.check.check_type, "where": where, "lat": nd.lat, "lon": nd.lon,
                       "km_above_outlet": round(nd.dist_to_outlet_m / 1000, 1),
                       "outfall": g.candidate(r.check.candidate_id).label if r.check.candidate_id else None,
                       "walk_m": round(walk) if walk is not None else None,
                       "if_clean": r.if_negative.zone, "if_polluted": r.if_positive.zone}
        advisories = [a for a in c.actions if a.type == "advisory"]
        return {"id": c.id, "reach": g.name, "status": c.status,
                "reports": sum(1 for o in c.belief.observations if o.kind == "report" and o.role == "citizen"),
                "checks": sum(1 for o in c.belief.observations if o.kind != "report"),
                "mission": mission,
                "advisory": c.advisory_draft()["text"] if advisories else None,
                "history": [{"at": a.at.isoformat(), "type": a.type} for a in c.actions]}


@app.post("/v1/citizen/cases/{case_id}/checks")
def citizen_check(case_id: str, body: CitizenCheckIn) -> dict:
    """A citizen answers one of the case's current citizen missions (and only those)."""
    with _lock:
        c = get_case(case_id)
        before = c.belief.location_entropy()
        mission = next((r for r in _missions(c) if r.check.key() == body.mission_key), None)
        if mission is None:
            raise HTTPException(409, "this mission is no longer open; refresh to get a new one")
        chk = mission.check
        _add(c, Observation(chk.check_type, body.positive, node_id=chk.node_id, candidate_id=chk.candidate_id,
                            role="citizen", observed_at=datetime.now(timezone.utc), observer=pseudonym(body.observer)))
        branch = mission.if_positive if body.positive else mission.if_negative
        return {"status": c.status, "search_narrowed_bits": round(before - c.belief.location_entropy(), 2),
                "now_most_likely_in": branch.zone}


@app.get("/v1/public/advisories")
def public_advisories() -> list[dict]:
    """Published advisories only: reach, affected stretch (downstream of the likely entry), wording. No outfalls."""
    out = []
    with _lock:
        for c in _cases.values():
            adv = [a for a in c.actions if a.type == "advisory"]
            if not adv or c.status in ("closed", "dismissed", "verified"):
                continue
            top, _ = c.belief.top_source()
            g = c.graph
            start = g.candidate(top).node_id if top not in (OUTSIDE, NONE) else min(
                g.nodes.values(), key=lambda n: -n.dist_to_outlet_m).id
            path = g.downstream_path(start)[1:]  # begin just below the entry point, never at it
            coords = [[round(g.nodes[n].lon, 5), round(g.nodes[n].lat, 5)] for n in path]
            out.append({"case": c.id, "reach": g.name, "city": g.city, "issued_at": adv[-1].at.isoformat(),
                        "text": c.advisory_draft()["text"], "stretch": {"type": "LineString", "coordinates": coords},
                        "simulated": c.id in _scenario_truth})
    return out


# ---- staff: cases, checks, actions, FHIR ----------------------------------------------------

@app.post("/v1/cases")
def create_case(body: CaseIn, user: User = Depends(require("inspector"))) -> dict:
    with _lock:
        return _new_case(body.reach_id, body.opened_at, body.weather).view()


@app.get("/v1/cases")
def list_cases(status: str | None = None, limit: int = Query(100, ge=1, le=500),
               user: User = Depends(require_staff)) -> list[dict]:
    out = []
    with _lock:
        for c in sorted(_cases.values(), key=_last_activity, reverse=True):
            if status and c.status != status:
                continue
            b = c.belief
            top = b.top_source()
            lead = b.hypothesis_table()[0]
            out.append({"id": c.id, "reach": c.graph.name, "city": c.graph.city, "status": c.status,
                        "opened_at": c.opened_at.isoformat(), "last_activity": _last_activity(c).isoformat(),
                        "leading_hypothesis": lead, "top_source": {"id": top[0], "label": b.labels()[top[0]], "p": top[1]},
                        "p_harmful": round(b.p_harmful(), 3), "signals": len(b.observations),
                        "simulated": c.id in _scenario_truth})
            if len(out) >= limit:
                break
    return out


@app.get("/v1/cases/{case_id}")
def case_view(case_id: str, k: int = Query(5, ge=1, le=20), user: User = Depends(require_staff)) -> dict:
    with _lock:
        return get_case(case_id).view(n_recommendations=k) | {"simulated": case_id in _scenario_truth}


@app.get("/v1/cases/{case_id}/history")
def case_history(case_id: str, user: User = Depends(require_staff)) -> list[dict]:
    """Append-only event history (observations and human actions): the audit trail."""
    with _lock:
        get_case(case_id)
        return store.history(case_id)


@app.get("/v1/cases/{case_id}/fhir")
def case_fhir(case_id: str, user: User = Depends(require_staff)) -> dict:
    """FHIR R4 Bundle (collection): OAH LocationOah/GroupOah plus Dipper response profiles."""
    with _lock:
        return case_bundle(get_case(case_id))


@app.post("/v1/cases/{case_id}/fhir/push")
def case_fhir_push(case_id: str, user: User = Depends(require("inspector"))) -> dict:
    """Send the case to the configured FHIR server (FHIR_BASE_URL) as an idempotent transaction."""
    base = os.getenv("FHIR_BASE_URL")
    if not base:
        raise HTTPException(409, "no FHIR server configured (set FHIR_BASE_URL)")
    with _lock:
        bundle = case_bundle(get_case(case_id))
    try:
        result = push(bundle, base, token=os.getenv("FHIR_TOKEN"))
    except FhirPushError as exc:
        raise HTTPException(502, str(exc)) from exc
    with _lock:
        a = get_case(case_id).act("fhir_push", _signed(user), result)
        store.add_action(case_id, a.type, a.approver, a.payload, a.at)
    return result


@app.get("/v1/cases/{case_id}/recommendations")
def recommendations(case_id: str, k: int = Query(5, ge=1, le=20), user: User = Depends(require_staff)) -> list[dict]:
    with _lock:
        c = get_case(case_id)
        return [r.as_dict() for r in recommend(c.belief, c.stakes, k=k)]


@app.post("/v1/cases/{case_id}/checks")
def post_check(case_id: str, body: CheckIn, user: User = Depends(require_staff)) -> dict:
    need = CHECK_ROLE[body.check_type]
    if need != "citizen" and not user.can(need):
        raise HTTPException(403, f"{body.check_type.replace('_', ' ')} needs the {need} role")
    role = "inspector" if user.can("inspector") else "trained"
    with _lock:
        c = get_case(case_id)
        try:
            _add(c, Observation(body.check_type, body.positive, node_id=body.node_id, candidate_id=body.candidate_id,
                                role=role, observed_at=datetime.now(timezone.utc), observer=body.observer or user.id))
        except (ValueError, KeyError) as exc:
            raise HTTPException(422, f"invalid check: {exc}") from exc
        return c.view()


@app.post("/v1/cases/{case_id}/actions")
def post_action(case_id: str, body: ActionIn, user: User = Depends(require_staff)) -> dict:
    need = ACTION_ROLE[body.type]
    if not user.can(need):
        raise HTTPException(403, f"{body.type.replace('_', ' ')} needs the {need.replace('_', ' ')} role")
    with _lock:
        c = get_case(case_id)
        if body.type == "notify_utility" and c.status != "localized":
            raise HTTPException(409, "hand-off is available once one entry point reaches the localization threshold")
        if body.type == "advisory" and any(a.type == "advisory" for a in c.actions):
            raise HTTPException(409, "an advisory is already published for this case")
        payload = ({"note": body.note} if body.note else {}) | (
            {"text": c.advisory_draft()["text"]} if body.type == "advisory" else {})
        try:
            a = c.act(body.type, _signed(user), payload)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        store.add_action(case_id, a.type, a.approver, a.payload, a.at)
        log.info(json.dumps({"event": "action", "case": case_id, "type": a.type, "user": user.id}))
        return c.view()


class OahImportIn(BaseModel):
    reach_id: str
    submissions: list[dict] = Field(max_length=500)


@app.post("/v1/import/oah")
def import_oah(body: OahImportIn, user: User = Depends(require("inspector"))) -> dict:
    """Import OneAquaHealth Citizen Science App submissions (see dipper_engine/oah.py for the mapping)."""
    g = reach(body.reach_id)
    results = []
    with _lock:
        seen = {o.observer for c in _cases.values() for o in c.belief.observations if o.observer}
        for sub in body.submissions:
            try:
                m = map_submission(sub)
            except ValueError as exc:
                results.append({"id": sub.get("id"), "status": "rejected", "reason": str(exc)})
                continue
            if f"oah:{m.submission_id}" in seen:
                results.append({"id": m.submission_id, "status": "duplicate"})
                continue
            node, dist = g.nearest_node(m.lat, m.lon)
            obs = m.to_observation(node) if dist <= 150 else None
            if obs is None:
                results.append({"id": m.submission_id, "status": "no_evidence",
                                "reason": "too far from the mapped stream" if dist > 150 else m.reason})
                continue
            case = _case_for_signal(body.reach_id, m.observed_at)
            _add(case, obs)
            seen.add(obs.observer)
            results.append({"id": m.submission_id, "status": "imported", "case_id": case.id, "evidence": m.reason,
                            "kind": obs.kind, "positive": obs.positive})
    return {"imported": sum(r["status"] == "imported" for r in results), "results": results}


# ---- demo scenario (labelled simulation) -----------------------------------------------------

def _demo_only() -> None:
    if not demo_enabled():
        raise HTTPException(404, "scenario replay is only available in demo mode")


@app.post("/v1/scenarios/c014")
def scenario_start(wet: bool = False, user: User = Depends(require("inspector"))) -> dict:
    _demo_only()
    with _lock:
        case, _ = build_case(wet=wet)
        base, n = case.id, 1
        while case.id in _cases:
            n += 1
            case.id = f"{base}-{n}"
        _cases[case.id], _reach_of[case.id] = case, DEMO_REACH
        _scenario_truth[case.id] = TRUE_SOURCE
        store.create(case, DEMO_REACH, scenario_truth=TRUE_SOURCE)
        return case.view() | {"simulated": True}


@app.post("/v1/scenarios/{case_id}/autostep")
def scenario_step(case_id: str, user: User = Depends(require("inspector"))) -> dict:
    """Perform the engine's top recommendation with a result derived from the simulated truth."""
    _demo_only()
    with _lock:
        if case_id not in _scenario_truth:
            raise HTTPException(404, "not a scenario case")
        c = get_case(case_id)
        if c.status not in ("open", "localizing"):
            raise HTTPException(409, "the search is complete")
        rec = recommend(c.belief, c.stakes, k=1)[0]
        positive = truth_result(c.graph, rec.check, _scenario_truth[case_id])
        _add(c, Observation(rec.check.check_type, positive, node_id=rec.check.node_id, candidate_id=rec.check.candidate_id,
                            role=rec.check.role, observed_at=_last_activity(c) + timedelta(minutes=25), tier="simulated"))
        return {"performed": rec.as_dict(), "result": "positive" if positive else "clean",
                "case": c.view() | {"simulated": True}}


# ---- context and benchmark -------------------------------------------------------------------

@app.get("/v1/context/weather")
def weather(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), when: AwareDatetime = Query()) -> dict:
    """Weather context, only near mapped reaches (this is not a general weather proxy)."""
    near = any(reach(p.stem).nearest_node(lat, lon)[1] < 5000 for p in REACH_DIR.glob("*.geojson"))
    if not near:
        raise HTTPException(422, "weather is only available near a mapped stream")
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
def sim_run(body: SimIn, user: User = Depends(require("admin"))) -> dict:
    nets = load_networks(REACH_DIR)
    results = [run_trial(n, pol, random.Random(f"{body.seed}-{n.name}-{k}"), misspec=body.misspec)
               for n in nets for k in range(body.trials) for pol in body.policies]
    return {"label": "SIMULATION", "networks": [n.name for n in nets], "summary": summarise(results)}


# ---- single-origin deployment: API under /api, web app at / -----------------------------------

site = FastAPI(title="Dipper", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
site.mount("/api", app)
if WEB_DIST.exists():
    site.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @site.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
