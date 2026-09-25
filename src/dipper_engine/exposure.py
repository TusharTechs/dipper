"""Who might be in contact with the water downstream. A proximity estimate, not a disease-risk model."""

from __future__ import annotations

from typing import Any

from .belief import Belief
from .graph import ReachGraph
from .model import NONE, OUTSIDE

PLACE_WEIGHTS = {"playground": 1.0, "kindergarten": 0.9, "school": 0.8, "dog_park": 0.8, "park": 0.6, "path": 0.5}


def stakes(graph: ReachGraph) -> float:
    """Static exposure stakes for the advisory decision (0..1): more contact places, higher stakes."""
    if not graph.places:
        return 0.5
    return min(1.0, 0.25 + 0.15 * sum(p.weight for p in graph.places))


def exposure_report(belief: Belief, velocity_m_s: float | None = None) -> list[dict[str, Any]]:
    velocity = velocity_m_s or (0.5 if belief.ctx.regime == "wet" else 0.2)
    top, p_top = belief.top_source()
    src_node = belief.graph.candidate(top).node_id if top not in (OUTSIDE, NONE) else None
    out = []
    for pl in belief.graph.places:
        p_aff = belief.p_polluted_at(pl.node_id)
        travel = None
        if src_node:
            d = belief.graph.along_distance_m(src_node, pl.node_id)
            if d is not None:
                travel = round(d / velocity / 60)
        out.append({"id": pl.id, "kind": pl.kind, "label": pl.label, "lat": pl.lat, "lon": pl.lon,
                    "p_affected": round(p_aff, 3), "minutes_from_likely_source": travel})
    out.sort(key=lambda r: -r["p_affected"])
    return out
