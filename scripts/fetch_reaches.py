"""Fetch OneAquaHealth pilot-city streams from OpenStreetMap and cache them as reach GeoJSON.

Candidate outfalls are SYNTHETIC (OSM maps almost none) and are flagged as such in the output.
    uv run python scripts/fetch_reaches.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from dipper_engine.exposure import PLACE_WEIGHTS
from dipper_engine.graph import from_osm
from dipper_engine.osm import fetch_places, fetch_stream

OUT = Path(__file__).resolve().parents[1] / "data" / "reaches"

# (city, OSM name, bbox south,west,north,east, n_candidates or None for ~1 per 130 m)
STREAMS = [
    ("Coimbra", "Ribeira de Coselhas", (40.17, -8.47, 40.26, -8.38), 14),   # demo reach
    ("Coimbra", "Ribeira dos Covões", (40.15, -8.50, 40.24, -8.38), None),
    ("Oslo", "Hovinbekken", (59.85, 10.70, 59.98, 10.90), None),
    ("Oslo", "Ljanselva", (59.80, 10.70, 59.92, 10.95), None),
    ("Oslo", "Hoffselva", (59.90, 10.60, 59.99, 10.75), None),
    ("Ghent", "Zwalmbeek", (50.78, 3.65, 50.92, 3.85), None),
]


def slug(s: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in s.lower()).strip("-")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:]
    for city, name, bbox, n in STREAMS:
        if only and name not in only:
            continue
        try:
            elements = fetch_stream(name, bbox)
            if not any(e["type"] == "way" for e in elements):
                print(f"skip {name}: not found")
                continue
            g = from_osm(elements, name=name, city=city)
            k = n or max(6, min(20, round(g.total_length_m / 130)))
            g.place_synthetic_candidates(k, seed=14)
            time.sleep(2)
            places = fetch_places(name, bbox, around_m=300)
            for p in places:
                p["weight"] = PLACE_WEIGHTS.get(p["kind"], 0.5)
            g.attach_places(places)
            g.meta |= {"candidates": "synthetic, 1 per ~130 m unless set", "fetched": time.strftime("%Y-%m-%d")}
            path = OUT / f"{slug(city)}-{slug(name)}.geojson"
            path.write_text(json.dumps(g.to_geojson()))
            print(f"{name}: {len(g.nodes)} nodes, {g.total_length_m:.0f} m, {len(g.access_nodes)} access, "
                  f"{k} candidates, {len(g.places)} places, gaps bridged {g.meta['gaps_bridged']}, "
                  f"fragments dropped {g.meta['fragments_dropped']} -> {path.name}")
        except Exception as exc:  # network hiccups should not stop the batch
            print(f"skip {name}: {exc}")
        time.sleep(2)


if __name__ == "__main__":
    main()
