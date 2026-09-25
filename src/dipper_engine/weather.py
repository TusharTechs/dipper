"""Weather context from Open-Meteo (CC BY 4.0). Cached on disk so demos run offline."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from .model import Context

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"


def _fetch_hourly(lat: float, lon: float, start: datetime, end: datetime, cache_dir: Path | None) -> dict:
    key = f"openmeteo_{lat:.3f}_{lon:.3f}_{start:%Y%m%d}_{end:%Y%m%d}.json"
    if cache_dir and (cache_dir / key).exists():
        return json.loads((cache_dir / key).read_text())
    recent = (datetime.now(timezone.utc).date() - end.date()).days < 6
    params = {"latitude": lat, "longitude": lon, "hourly": "precipitation,temperature_2m", "timezone": "UTC"}
    if recent:
        url = FORECAST
        params["past_days"] = min(92, (datetime.now(timezone.utc).date() - start.date()).days + 1)
        params["forecast_days"] = 1
    else:
        url = ARCHIVE
        params |= {"start_date": f"{start:%Y-%m-%d}", "end_date": f"{end:%Y-%m-%d}"}
    r = httpx.get(url, params=params, timeout=30, headers={"User-Agent": "dipper-hackathon/0.1"})
    r.raise_for_status()
    data = r.json()
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / key).write_text(json.dumps(data))
    return data


def context_from_hourly(data: dict, when: datetime) -> Context:
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in data["hourly"]["time"]]
    rain = data["hourly"]["precipitation"]
    temp = data["hourly"]["temperature_2m"]
    w = when.astimezone(timezone.utc)
    r48 = [r for t, r in zip(times, rain) if w - timedelta(hours=48) <= t <= w and r is not None]
    day_t = [x for t, x in zip(times, temp) if t.date() == w.date() and x is not None]
    daily: dict = {}
    for t, r in zip(times, rain):
        if r is not None and t <= w:
            daily[t.date()] = daily.get(t.date(), 0.0) + r
    dry = 0
    d = w.date() - timedelta(days=1)
    while d in daily and daily[d] < 0.2:
        dry += 1
        d -= timedelta(days=1)
    if w.date() in daily and daily[w.date()] >= 0.2:
        dry = 0
    return Context(rain_48h_mm=round(sum(r48), 1) if r48 else None,
                   tmax_c=max(day_t) if day_t else None, hour=when.hour, dry_days=dry)


def fetch_context(lat: float, lon: float, when: datetime, cache_dir: Path | None = None) -> Context:
    """Context for a case at `when` (timezone-aware). Falls back to 'weather unknown' on failure."""
    try:
        data = _fetch_hourly(lat, lon, when - timedelta(days=30), when, cache_dir)
        return context_from_hourly(data, when)
    except (httpx.HTTPError, KeyError, ValueError):
        return Context(hour=when.hour)
