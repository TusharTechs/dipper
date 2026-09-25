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

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import re
import threading
import time
import uuid
from collections import OrderedDict, defaultdict, deque
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, Field, StrictBool

from dipper_engine import Case, Context, Observation, ReachGraph, __version__
from dipper_engine.fhir import FhirPushError, case_bundle, push
from dipper_engine.graph import haversine_m
from dipper_engine.model import CHECK_TYPES, FEATURES, NONE, OUTSIDE
from dipper_engine.oah import map_submission
from dipper_engine.photo import PhotoModelUnavailable, conflicts, extract, redact, to_observation, vision_provider
from dipper_engine.scenario import TRUE_SOURCE, build_case, truth_result
from dipper_engine.sim import load_networks, run_trial, summarise
from dipper_engine.weather import fetch_context

from .auth import ROLES, User, Users, current_user, demo_enabled, require, require_staff
from .retention import maybe_purge
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")  # server-side secrets such as LLM_API_KEY; never sent to the browser
REACH_DIR = ROOT / "data" / "reaches"
BUNDLED_CACHE = ROOT / "data" / "cache"  # weather for the scenario replay ships with the code (read-only in Docker)
CACHE_DIRS = list(dict.fromkeys([Path(os.getenv("DIPPER_CACHE", str(BUNDLED_CACHE))), BUNDLED_CACHE]))
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
        for cid in truth:
            if cid in _cases:
                _cases[cid].freeze_clock()
        users.purge_expired()
    maybe_purge(MEDIA_DIR, every_s=0)
    log.info(json.dumps({"event": "startup", "cases": len(_cases), "demo": demo_enabled()}))

    async def retention() -> None:  # photos past retention are deleted even when no new photo arrives
        while True:
            await asyncio.sleep(3600)
            await asyncio.to_thread(maybe_purge, MEDIA_DIR, 0)
            with _lock:
                users.purge_expired()
    task = asyncio.create_task(retention())
    try:
        yield
    finally:
        task.cancel()


_DOCS = demo_enabled() or os.getenv("DIPPER_DOCS", "").lower() in ("1", "true", "yes")  # off in production
app = FastAPI(lifespan=lifespan, title="Dipper API", version=__version__,
              docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
              openapi_url="/openapi.json" if _DOCS else None,
              description="Bayesian source hunting for sewage pollution in urban streams.")
app.state.users = users
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("DIPPER_CORS", "http://localhost:3000").split(",") if o],
                   allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Report-Token"])


# ---- middleware: request ids, security headers, logging, rate limits -------------------

RATE_LIMITS = {"/v1/signals": (30, 60), "/v1/signals/photo": (10, 60), "/v1/auth/demo": (20, 60),
               "/v1/context/weather": (30, 60), "/v1/citizen/checks": (20, 60)}
_CITIZEN_CHECK = re.compile(r"^/v1/citizen/cases/[^/]+/checks$")


def _route_path(request: Request) -> str:
    """The path inside this app. Under the single-origin site the app is mounted at /api, so strip the mount
    prefix; otherwise limits keyed on /v1/... would silently never match in production."""
    path, root = request.url.path, request.scope.get("root_path", "")
    if root and path.startswith(root):
        path = path[len(root):] or "/"
    return path


def _limit_for(method: str, path: str) -> tuple[str, tuple[int, int]] | None:
    if method == "POST" and _CITIZEN_CHECK.match(path):
        return "/v1/citizen/checks", RATE_LIMITS["/v1/citizen/checks"]
    if method == "POST" or path == "/v1/context/weather":
        lim = RATE_LIMITS.get(path)
        return (path, lim) if lim else None
    return None
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
# Number of reverse proxies in front of the app. X-Forwarded-For is client-controlled, so it is only used
# when a proxy is declared, and then only the entry that proxy appended (counted from the right).
PROXY_HOPS = int(os.getenv("DIPPER_PROXY_HOPS", "0"))


def _client_key(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if PROXY_HOPS and xff:
        ip = xff[-PROXY_HOPS] if len(xff) >= PROXY_HOPS else xff[0]
    return hashlib.sha256(ip.encode()).hexdigest()[:16]  # never keep raw IPs


def _prune_hits(now: float) -> None:
    """Drop idle rate-limit buckets so memory stays bounded however many clients call."""
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > 120]:
        del _hits[key]


@app.middleware("http")
async def _edge(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    path = _route_path(request)
    rule = _limit_for(request.method, path)
    if rule:
        bucket, (n, window) = rule
        now = time.monotonic()
        if len(_hits) > 5000:
            _prune_hits(now)
        q = _hits[(bucket, _client_key(request))]
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


# Locking: `_lock` guards the case registry and the database connection and is held only briefly. Each case
# has its own lock for reading and updating its belief (ranking checks is the slow part), so cases proceed in
# parallel. Order is always case lock, then `_lock`; never the reverse.
_case_locks: dict[str, threading.RLock] = {}
_import_lock = threading.Lock()


def _case_lock(case_id: str) -> threading.RLock:
    with _lock:
        return _case_locks.setdefault(case_id, threading.RLock())


@contextmanager
def _locked_case(case_id: str):
    with _lock:
        c = get_case(case_id)
    with _case_lock(c.id):
        yield c


def _last_activity(c: Case) -> datetime:
    return c.belief.clock or c.opened_at


def _context_for(reach_id: str, opened_at: datetime | None, weather: "WeatherIn | None") -> tuple[Context, datetime]:
    """Weather context for a new case. May call Open-Meteo, so it runs without any lock held."""
    g = reach(reach_id)
    tz = ZoneInfo(g.meta.get("tz") or TZ_BY_CITY.get(g.city, "UTC"))
    when = (opened_at or datetime.now(timezone.utc)).astimezone(tz)  # day/night activity uses local time
    if weather is not None:
        return Context(rain_48h_mm=weather.rain_48h_mm, tmax_c=weather.tmax_c, dry_days=weather.dry_days,
                       hour=when.hour), when
    mid = next(iter(g.nodes.values()))
    return fetch_context(mid.lat, mid.lon, when, cache_dir=CACHE_DIRS), when


def _new_case(reach_id: str, ctx: Context, when: datetime) -> Case:
    """Register and persist a case. Call with `_lock` held."""
    g = reach(reach_id)
    cid = f"C-{store.next_number():03d}"
    case = Case(cid, g, ctx, opened_at=when)
    _cases[cid], _reach_of[cid] = case, reach_id
    store.create(case, reach_id)
    log.info(json.dumps({"event": "case_opened", "case": cid, "reach": reach_id}))
    return case


def _open_case_on(reach_id: str, when: datetime) -> Case | None:
    open_cases = [c for c in _cases.values() if _reach_of.get(c.id) == reach_id and c.id not in _scenario_truth
                  and c.status in ("open", "localizing", "localized") and when - _last_activity(c) <= CASE_WINDOW]
    return max(open_cases, key=_last_activity) if open_cases else None


def _case_for_signal(reach_id: str, when: datetime, create: bool = True) -> Case | None:
    """Join the most recently active open case on this reach, or (if `create`) open a new one."""
    with _lock:
        c = _open_case_on(reach_id, when)
    if c is not None or not create:
        return c
    ctx, local = _context_for(reach_id, when, None)   # network, outside the lock
    with _lock:                                        # someone may have opened one in the meantime
        return _open_case_on(reach_id, when) or _new_case(reach_id, ctx, local)


def _add(case: Case, obs: Observation) -> None:
    """Validate, persist, then apply. A rejected observation changes neither memory nor the database.
    Call with the case's lock held."""
    if case.status in Case.TERMINAL:
        raise HTTPException(409, f"case {case.id} is {case.status}; new evidence opens a new case")
    try:
        case.belief.validate(obs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with _lock:
        store.add_observation(case.id, obs)
    case.add(obs)


def _record_action(case: Case, a) -> None:
    with _lock:
        store.add_action(case.id, a.type, a.approver, a.payload, a.at)


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
    observed_at: AwareDatetime | None = Field(None, description="When it was seen, for reports queued offline "
                                              "(at most 7 days ago); defaults to now")
    client_id: str | None = Field(None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$",
                                  description="Random id per report; a repeated id returns the first result")


class CheckIn(BaseModel):
    check_type: Literal["instream_look", "outfall_look", "ammonium_strip", "lab_ecoli"]
    positive: bool
    node_id: str | None = Field(None, max_length=40)
    candidate_id: str | None = Field(None, max_length=40)
    observer: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]*$")


class CitizenCheckIn(BaseModel):
    mission_key: str = Field(max_length=120)
    positive: StrictBool


class ActionIn(BaseModel):
    type: Literal["dispatch", "lab_request", "notify_utility", "advisory", "lift_advisory", "dismiss", "fixed",
                  "follow_up", "verified", "close"]
    note: str | None = Field(None, max_length=500, description="Optional reason, stored in the audit trail")
    clean: StrictBool | None = Field(None, description="follow_up only: was the source clean after the fix?")


class DemoIn(BaseModel):
    role: Literal["inspector", "public_health"]  # never admin: demo tokens are handed to anyone who asks


class SimIn(BaseModel):
    trials: int = Field(20, ge=1, le=200)
    misspec: float = Field(1.3, ge=1.0, le=3.0)
    policies: list[Literal["walk", "bisect", "entropy", "voi", "random"]] = ["walk", "bisect", "entropy", "voi"]
    seed: int = 1


ACTION_ROLE = {"advisory": "public_health", "lift_advisory": "public_health", "follow_up": "inspector",
               "notify_utility": "inspector", "dispatch": "inspector",
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
    names = {"inspector": "Demo investigator", "public_health": "Demo public-health officer"}
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
                   observed_at: datetime, media: str | None = None) -> tuple[Case | None, str, float, int]:
    unknown = set(features) - set(FEATURES)
    if unknown:
        raise HTTPException(422, f"unknown features {sorted(unknown)}")
    g = reach(reach_id)
    node, dist = g.nearest_node(lat, lon)
    if dist > 150:
        raise HTTPException(422, f"location is {dist:.0f} m from the mapped stream; move closer to the water")
    polluted = any(features.values())
    # "The water looks clean" is evidence too: a clean look at that spot for an open case. It never opens a
    # pollution case on its own.
    case = _case_for_signal(reach_id, observed_at, create=polluted)
    if case is None:
        return None, node, dist, -1
    obs = (Observation("report", True, node_id=node, role="citizen", features=tuple(features.items()),
                       observed_at=observed_at, observer=pseudonym(observer), media=media) if polluted else
           Observation("instream_look", False, node_id=node, role="citizen", observed_at=observed_at,
                       observer=pseudonym(observer), media=media))
    with _case_lock(case.id):
        _add(case, obs)
        return case, node, dist, len(case.belief.observations) - 1


_seen_reports: "OrderedDict[str, dict | None]" = OrderedDict()   # client_id -> first response (None: pending)


def _report_token(case_id: str, index: int) -> str:
    """Capability for the citizen who made report `index` of a case: read their case summary and answer its
    missions. Stateless (keyed hash) and never logged; case ids alone are guessable, this is not."""
    mac = hmac.new(PEPPER, f"report:{case_id}:{index}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{index}.{mac}"


def _report_for(case: Case, token: str | None) -> tuple[int, Observation]:
    """The citizen report (or clean look) a token was issued for, with its index, or 403."""
    ok, obs, idx = False, None, -1
    try:
        idx_s, mac = (token or "").split(".", 1)
        idx = int(idx_s)
        if 0 <= idx < len(case.belief.observations):
            ok = hmac.compare_digest(_report_token(case.id, idx), f"{idx}.{mac}")
            obs = case.belief.observations[idx]
    except ValueError:
        ok = False
    if not ok or obs is None or obs.role != "citizen" or obs.kind not in ("report", "instream_look"):
        raise HTTPException(403, "this link is only for the person who sent the report")
    return idx, obs


def _answerer(case: Case, idx: int, report: Observation) -> str:
    """Who answers a mission: the reporter's pseudonym, or one derived from the report itself, so each report
    answers each mission at most once even when the phone sent no device id."""
    return report.observer or pseudonym(f"report:{case.id}:{idx}")


@app.post("/v1/signals")
def post_signal(body: SignalIn) -> dict:
    now = datetime.now(timezone.utc)
    seen = body.observed_at or now
    if seen > now + timedelta(minutes=5) or seen < now - timedelta(days=7):
        raise HTTPException(422, "observed_at must be within the last 7 days")
    if body.client_id:
        with _lock:
            if body.client_id in _seen_reports:  # a retried or twice-flushed offline report
                if _seen_reports[body.client_id] is None:
                    raise HTTPException(409, "this report is already being recorded")
                return _seen_reports[body.client_id]
            _seen_reports[body.client_id] = None  # pending
    try:
        case, node, dist, idx = _record_report(body.reach_id, body.lat, body.lon, body.features, body.observer, seen)
    except BaseException:
        if body.client_id:
            with _lock:
                _seen_reports.pop(body.client_id, None)
        raise
    out = ({"case_id": None, "snap_distance_m": round(dist, 1), "status": "no_open_case", "report_token": None}
           if case is None else
           {"case_id": case.id, "snap_distance_m": round(dist, 1), "status": case.status,
            "report_token": _report_token(case.id, idx)})
    if body.client_id:
        with _lock:
            _seen_reports[body.client_id] = out
            while len(_seen_reports) > 20000:
                _seen_reports.popitem(last=False)
    return out


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
    case, node, dist, index = _record_report(reach_id, lat, lon, answers, observer, now, media=sha)
    if case is None:  # a clean report with no open case: thank the citizen, keep nothing
        return {"case_id": None, "snap_distance_m": round(dist, 1), "status": "no_open_case", "report_token": None,
                "photo": {"status": "not_analysed", "exif_removed": True, "faces_blurred": red.faces_blurred,
                          "reason": "there is no open investigation on this stream, so the photo was not kept"}}
    photo_out: dict = {"exif_removed": True, "faces_blurred": red.faces_blurred}
    if not red.face_detection:
        photo_out |= {"status": "not_analysed", "reason": "face blurring is unavailable, so the photo was discarded"}
    else:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / f"{sha}.jpg").write_bytes(red.jpeg)
        maybe_purge(MEDIA_DIR)
        try:
            pf = extract(red.jpeg)  # outside the lock: a slow model call must not block other requests
            pobs = to_observation(pf, node, observed_at=now + timedelta(seconds=1))
            with _case_lock(case.id):
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
    with _case_lock(case.id):  # only this citizen's own results: other evidence may have arrived meanwhile
        return {"case_id": case.id, "snap_distance_m": round(dist, 1), "status": case.status, "photo": photo_out,
                "report_token": _report_token(case.id, index)}


MISSION_POOL = 12            # citizen checks considered for a mission
WALK_COST_PER_KM = 0.08      # score given up per km a volunteer must walk (same units as the check score)


def _missions(case: Case, k: int = MISSION_POOL) -> list:
    if case.status not in ("open", "localizing"):
        return []
    return case.ranked(k, ("citizen",))


def _mission_node(g, r) -> str:
    return g.candidate(r.check.candidate_id).node_id if r.check.candidate_id else r.check.node_id


def _pick_mission(case: Case, report: Observation):
    """The most useful citizen check after charging for the walk from where this citizen reported.
    The location comes from their stored report, so the client never has to send it again."""
    pool = _missions(case)
    if not pool:
        return None, None
    g = case.graph
    here = g.nodes[report.node_id]
    walks = [haversine_m(here.lat, here.lon, g.nodes[_mission_node(g, r)].lat, g.nodes[_mission_node(g, r)].lon)
             for r in pool]
    i = max(range(len(pool)), key=lambda j: pool[j].score - WALK_COST_PER_KM * walks[j] / 1000)
    return pool[i], walks[i]


def _answered(case: Case, answerer: str, key: str) -> bool:
    return any(o.observer == answerer and o.kind != "report" and f"{o.kind}:{o.candidate_id or o.node_id}:citizen" == key
               for o in case.belief.observations)


@app.get("/v1/citizen/cases/{case_id}")
def citizen_case(case_id: str, x_report_token: str | None = Header(None)) -> dict:
    """What the reporting citizen may see: status, one mission near where they reported, what happened, any
    published advisory. Never the outfall ranking. Needs the token returned with their report."""
    with _locked_case(case_id) as c:
        idx, report = _report_for(c, x_report_token)
        g = c.graph
        mission = None
        r, walk = _pick_mission(c, report)
        if r and not _answered(c, _answerer(c, idx, report), r.check.key()):
            nd = g.nodes[_mission_node(g, r)]
            mission = {"key": r.check.key(), "type": r.check.check_type, "lat": nd.lat, "lon": nd.lon,
                       "kind": "outfall" if r.check.candidate_id else "stream",
                       "km_above_outlet": round(nd.dist_to_outlet_m / 1000, 1),
                       "walk_m": round(walk) if walk is not None else None}
        return {"id": c.id, "reach": g.name, "status": c.status,
                "reports": sum(1 for o in c.belief.observations if o.kind == "report" and o.role == "citizen"),
                "checks": sum(1 for o in c.belief.observations if o.kind != "report"),
                "mission": mission,
                "advisory": c.published_advisory_text,
                "history": [{"at": a.at.isoformat(), "type": a.type} for a in c.actions]}


@app.post("/v1/citizen/cases/{case_id}/checks")
def citizen_check(case_id: str, body: CitizenCheckIn, x_report_token: str | None = Header(None)) -> dict:
    """The reporting citizen answers one of the case's current citizen missions, once."""
    with _locked_case(case_id) as c:
        idx, report = _report_for(c, x_report_token)
        answerer = _answerer(c, idx, report)
        before = c.belief.location_entropy()
        mission = next((r for r in _missions(c) if r.check.key() == body.mission_key), None)
        if mission is None:
            raise HTTPException(409, "this mission is no longer open; refresh to get a new one")
        if _answered(c, answerer, body.mission_key):
            raise HTTPException(409, "you already answered this mission")
        chk = mission.check
        _add(c, Observation(chk.check_type, body.positive, node_id=chk.node_id, candidate_id=chk.candidate_id,
                            role="citizen", observed_at=datetime.now(timezone.utc), observer=answerer))
        return {"status": c.status, "search_narrowed_bits": round(before - c.belief.location_entropy(), 2)}


@app.get("/v1/public/advisories")
def public_advisories() -> list[dict]:
    """Published advisories only: reach, affected stretch (downstream of the likely entry), wording. No outfalls."""
    out = []
    with _lock:
        for c in _cases.values():
            adv = [a for a in c.actions if a.type == "advisory"]
            if not c.advisory_active:
                continue
            top, _ = c.belief.top_source()
            g = c.graph
            start = g.candidate(top).node_id if top not in (OUTSIDE, NONE) else min(
                g.nodes.values(), key=lambda n: -n.dist_to_outlet_m).id
            path = g.downstream_path(start)[1:]  # begin just below the entry point, never at it
            coords = [[round(g.nodes[n].lon, 5), round(g.nodes[n].lat, 5)] for n in path]
            out.append({"case": c.id, "reach": g.name, "city": g.city, "issued_at": adv[-1].at.isoformat(),
                        "text": c.published_advisory_text, "stretch": {"type": "LineString", "coordinates": coords},
                        "simulated": c.id in _scenario_truth})
    return out


# ---- staff: cases, checks, actions, FHIR ----------------------------------------------------

@app.post("/v1/cases")
def create_case(body: CaseIn, user: User = Depends(require("inspector"))) -> dict:
    ctx, when = _context_for(body.reach_id, body.opened_at, body.weather)
    with _lock:
        c = _new_case(body.reach_id, ctx, when)
    with _case_lock(c.id):
        return c.view()


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
    with _locked_case(case_id) as c:
        return c.view(n_recommendations=k) | {"simulated": case_id in _scenario_truth}


@app.get("/v1/cases/{case_id}/history")
def case_history(case_id: str, user: User = Depends(require_staff)) -> list[dict]:
    """Append-only event history (observations and human actions): the audit trail."""
    with _lock:
        get_case(case_id)
        return store.history(case_id)


@app.get("/v1/cases/{case_id}/fhir")
def case_fhir(case_id: str, user: User = Depends(require_staff)) -> dict:
    """FHIR R4 Bundle (collection): OAH LocationOah/GroupOah plus Dipper response profiles."""
    with _locked_case(case_id) as c:
        return case_bundle(c)


@app.post("/v1/cases/{case_id}/fhir/push")
def case_fhir_push(case_id: str, user: User = Depends(require("inspector"))) -> dict:
    """Send the case to the configured FHIR server (FHIR_BASE_URL) as an idempotent transaction."""
    base = os.getenv("FHIR_BASE_URL")
    if not base:
        raise HTTPException(409, "no FHIR server configured (set FHIR_BASE_URL)")
    with _locked_case(case_id) as c:
        bundle = case_bundle(c)
    try:
        result = push(bundle, base, token=os.getenv("FHIR_TOKEN"))
    except FhirPushError as exc:
        raise HTTPException(502, str(exc)) from exc
    with _locked_case(case_id) as c:
        _record_action(c, c.act("fhir_push", _signed(user), result))
    return result


@app.get("/v1/cases/{case_id}/recommendations")
def recommendations(case_id: str, k: int = Query(5, ge=1, le=20), user: User = Depends(require_staff)) -> list[dict]:
    with _locked_case(case_id) as c:
        return [r.as_dict() for r in c.ranked(k, distinct=True)]


@app.post("/v1/cases/{case_id}/checks")
def post_check(case_id: str, body: CheckIn, user: User = Depends(require_staff)) -> dict:
    need = CHECK_ROLE[body.check_type]
    if need != "citizen" and not user.can(need):
        raise HTTPException(403, f"{body.check_type.replace('_', ' ')} needs the {need} role")
    role = "inspector" if user.can("inspector") else "trained"
    with _locked_case(case_id) as c:
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
    with _locked_case(case_id) as c:
        if body.type == "notify_utility" and c.status != "localized":
            raise HTTPException(409, "hand-off is available once one entry point reaches the localization threshold")
        payload = ({"note": body.note} if body.note else {}) | (
            {"text": c.advisory_draft()["text"]} if body.type == "advisory" else {}) | (
            {"clean": body.clean} if body.type == "follow_up" else {})
        try:
            a = c.act(body.type, _signed(user), payload)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        _record_action(c, a)
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
    with _import_lock:  # imports run one at a time, so the duplicate check below holds
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
            with _case_lock(case.id):
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
    with _case_lock(case.id):
        return case.view() | {"simulated": True}


@app.post("/v1/scenarios/{case_id}/autostep")
def scenario_step(case_id: str, user: User = Depends(require("inspector"))) -> dict:
    """Perform the engine's top recommendation with a result derived from the simulated truth."""
    _demo_only()
    if case_id not in _scenario_truth:
        raise HTTPException(404, "not a scenario case")
    with _locked_case(case_id) as c:
        if c.status not in ("open", "localizing"):
            raise HTTPException(409, "the search is complete")
        rec = c.ranked(1)[0]  # the same top check the workspace shows
        positive = truth_result(c.graph, rec.check, _scenario_truth[case_id])
        _add(c, Observation(rec.check.check_type, positive, node_id=rec.check.node_id, candidate_id=rec.check.candidate_id,
                            role=rec.check.role, observed_at=_last_activity(c) + timedelta(minutes=25), tier="simulated"))
        return {"performed": rec.as_dict(), "result": "positive" if positive else "clean",
                "case": c.view() | {"simulated": True}}


# ---- context and benchmark -------------------------------------------------------------------

@app.get("/v1/context/weather")
def weather(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180), when: AwareDatetime = Query()) -> dict:
    """Weather context for a mapped stream (not a general weather proxy). The point is snapped to the nearest
    stream's reference point and the date to the day, within the last 60 days, so callers cannot make the
    server fetch or cache arbitrary places and times."""
    now = datetime.now(timezone.utc)
    if when > now + timedelta(hours=1) or when < now - timedelta(days=60):
        raise HTTPException(422, "weather is available for the last 60 days only")
    dist, g = min(((reach(p.stem).nearest_node(lat, lon)[1], reach(p.stem)) for p in REACH_DIR.glob("*.geojson")),
                  key=lambda x: x[0])
    if dist >= 5000:
        raise HTTPException(422, "weather is only available near a mapped stream")
    ref = next(iter(g.nodes.values()))  # the same point cases on this stream use
    day = when.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    ctx = fetch_context(ref.lat, ref.lon, day, cache_dir=CACHE_DIRS)
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
TILES = "https://tiles.openfreemap.org"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       f"img-src 'self' data: blob: {TILES}; connect-src 'self' {TILES}; worker-src 'self' blob:; child-src blob:; "
       "font-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'")


@site.middleware("http")
async def _site_headers(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers.update({"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff",
                                 "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                                 "Permissions-Policy": "geolocation=(self), camera=(self)"})
    proto = request.headers.get("x-forwarded-proto", "") if PROXY_HOPS else ""
    if request.url.scheme == "https" or proto.split(",")[-1].strip() == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response

if WEB_DIST.exists():
    site.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @site.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (WEB_DIST / path).resolve()
        if path and target.is_file() and WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})
