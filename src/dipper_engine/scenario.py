"""Case C-014 scenario replay on Ribeira de Coselhas, Coimbra.

REAL: stream geometry and culverts (OpenStreetMap), weather on the replay date (Open-Meteo archive),
places near the stream (OpenStreetMap).
SIMULATED (tier="simulated"): candidate outfalls, the true source, citizen reports, and every check result.

At each step the engine's top recommendation is performed and its result is derived from the
simulated truth, so the replay shows the engine's own choices rather than a fixed script.

    uv run python -m dipper_engine.scenario            # dry-weather replay (18 Sep 2026)
    uv run python -m dipper_engine.scenario --wet      # contrast replay (24 Aug 2026, 20 mm rain)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from .belief import Observation
from .case import Case
from .graph import ReachGraph
from .model import Context
from .voi import ProposedCheck, recommend
from .weather import fetch_context

ROOT = Path(__file__).resolve().parents[2]
REACH_FILE = ROOT / "data" / "reaches" / "coimbra-ribeira-de-coselhas.geojson"
CACHE = ROOT / "data" / "cache"
LISBON = timezone(timedelta(hours=1))  # WEST (summer time)

DRY = datetime(2026, 9, 18, 8, 10, tzinfo=LISBON)
WET = datetime(2026, 8, 24, 18, 10, tzinfo=LISBON)
TRUE_SOURCE = "O9"
REPORT_FEATURES = [
    (("grey", True), ("sewage_odour", True)),
    (("grey", True), ("pipe_flowing", True)),
    (("sewage_odour", True), ("foam", False)),
]


def load_reach(path: Path = REACH_FILE) -> ReachGraph:
    return ReachGraph.from_geojson(json.loads(path.read_text(encoding="utf-8")))


def truth_result(graph: ReachGraph, check: ProposedCheck, source: str = TRUE_SOURCE) -> bool:
    """Idealised simulated result: positive iff the true (active) source is visible from this check."""
    src_node = graph.candidate(source).node_id
    if check.check_type == "outfall_look":
        return check.candidate_id == source
    return src_node in graph.upstream_or_self(check.node_id)


def report_nodes(graph: ReachGraph, source: str = TRUE_SOURCE, n: int = 3) -> list[str]:
    """The n access points just downstream of the true source, nearest first."""
    src_node = graph.candidate(source).node_id
    path = graph.downstream_path(src_node)[1:]
    access = [x for x in path if graph.nodes[x].access and graph.nodes[x].observable] or path
    picks = access[1:1 + n] if len(access) > n else access[:n]
    return picks or [path[-1]]


def build_case(wet: bool = False, ctx: Context | None = None) -> tuple[Case, datetime]:
    graph = load_reach()
    when = WET if wet else DRY
    mid = graph.nodes[graph.candidate(TRUE_SOURCE).node_id]
    ctx = ctx or fetch_context(mid.lat, mid.lon, when, cache_dir=CACHE)
    case = Case("C-014" + ("-wet" if wet else ""), graph, ctx, opened_at=when)
    case.freeze_clock()  # a replay: "now" is the replay's own time, not today
    for i, (nid, feats) in enumerate(zip(report_nodes(graph), REPORT_FEATURES)):
        case.add(Observation("report", True, node_id=nid, role="citizen", features=feats,
                             observed_at=when + timedelta(minutes=[0, 30, 55][i]), observer=f"cit-{i + 1:03d}",
                             tier="simulated"))
    return case, when


def replay(wet: bool = False, max_steps: int = 10, roles: tuple[str, ...] = ("citizen", "trained", "inspector"),
           ctx: Context | None = None) -> Iterator[dict[str, Any]]:
    case, when = build_case(wet, ctx)
    b = case.belief
    yield {"step": 0, "event": "reports", "context": case.ctx.describe(), "hypotheses": b.hypothesis_table()[:3],
           "top_source": b.top_source(), "entropy_bits": round(b.location_entropy(), 2), "ledger": [e.text for e in b.ledger],
           "case": case}
    t = when + timedelta(hours=1)
    for step in range(1, max_steps + 1):
        if case.status == "localized":
            break
        rec = recommend(b, case.stakes, k=1, roles=roles)[0]
        positive = truth_result(case.graph, rec.check)
        obs = Observation(rec.check.check_type, positive, node_id=rec.check.node_id, candidate_id=rec.check.candidate_id,
                          role=rec.check.role, observed_at=t, observer=f"vol-{step:03d}", tier="simulated")
        case.add(obs)
        t += timedelta(minutes=25)
        yield {"step": step, "event": "check", "recommended": rec.label, "reason": rec.reason, "score": rec.score,
               "result": "positive" if positive else "clean", "top_source": b.top_source(),
               "entropy_bits": round(b.location_entropy(), 2), "p_harmful": round(b.p_harmful(), 3), "status": case.status,
               "case": case}


def main() -> None:
    ap = argparse.ArgumentParser(description="C-014 scenario replay (simulated reports and results)")
    ap.add_argument("--wet", action="store_true")
    args = ap.parse_args()
    labels = None
    print("SCENARIO REPLAY: real stream and weather, simulated reports and results\n")
    for ev in replay(wet=args.wet):
        case: Case = ev["case"]
        labels = labels or case.belief.labels()
        top = f"{labels[ev['top_source'][0]]} {ev['top_source'][1]:.0%}"
        if ev["event"] == "reports":
            print(f"Case {case.id} · {case.graph.name}, {case.graph.city} · {ev['context']}")
            for line in ev["ledger"]:
                print(f"  · {line}")
            print("  Hypotheses: " + ", ".join(f"{h['id']} {h['p']:.0%}" for h in ev["hypotheses"]))
            print(f"  Top source {top} · entropy {ev['entropy_bits']} bits\n")
        else:
            print(f"Step {ev['step']}: {ev['recommended']}  →  {ev['result'].upper()}")
            print(f"  why: {ev['reason']}")
            print(f"  now: top source {top} · entropy {ev['entropy_bits']} bits · P(harmful) {ev['p_harmful']:.0%} · {ev['status']}\n")
    view = case.view(n_recommendations=1)
    print(f"Status: {view['status']} · advisory suggested: {view['advisory_suggested']}")
    for u in view["unknowns"]:
        print(f"  unknown: {u}")
    for pl in view["exposure"][:3]:
        print(f"  exposure: {pl['label']} ({pl['kind']}) P(affected) {pl['p_affected']:.0%}, "
              f"~{pl['minutes_from_likely_source']} min from likely source")


if __name__ == "__main__":
    main()
