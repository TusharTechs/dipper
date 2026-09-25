"""OpenStreetMap (ODbL) access through the Overpass API."""

from __future__ import annotations

from typing import Any

import httpx

OVERPASS = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "dipper-hackathon/0.1 (OneAquaHealth hackathon prototype)"}

PLACE_KIND = {"playground": "playground", "park": "park", "dog_park": "dog_park",
              "school": "school", "kindergarten": "kindergarten"}


def _query(q: str) -> list[dict[str, Any]]:
    r = httpx.post(OVERPASS, data={"data": q}, headers=HEADERS, timeout=120)
    r.raise_for_status()
    return r.json()["elements"]


def _bbox(b: tuple[float, float, float, float]) -> str:
    s, w, n, e = b
    return f"{s},{w},{n},{e}"


def fetch_stream(name: str, bbox: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    """Waterway ways with this exact name inside bbox (south, west, north, east), plus their nodes."""
    return _query(f'[out:json][timeout:90];way["waterway"]["name"="{name}"]({_bbox(bbox)});(._;>;);out body;')


def fetch_places(name: str, bbox: tuple[float, float, float, float], around_m: int = 120) -> list[dict[str, Any]]:
    """Places near the named stream where people or dogs may contact the water."""
    q = (f'[out:json][timeout:90];way["waterway"]["name"="{name}"]({_bbox(bbox)})->.w;'
         f'(nwr(around.w:{around_m})["leisure"~"^(playground|park|dog_park)$"];'
         f'nwr(around.w:{around_m})["amenity"~"^(school|kindergarten)$"];);out center tags;')
    out = []
    for e in _query(q):
        tags = e.get("tags", {})
        kind = PLACE_KIND.get(tags.get("leisure") or tags.get("amenity"))
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if kind and lat is not None:
            out.append({"id": f"osm-{e['type'][0]}{e['id']}", "kind": kind,
                        "label": tags.get("name") or kind.replace("_", " "), "lat": lat, "lon": lon})
    return out
