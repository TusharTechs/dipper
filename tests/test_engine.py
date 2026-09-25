import json
import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from dipper_engine import Belief, Case, Context, Observation, ReachGraph, from_osm, synthetic_tree
from dipper_engine.model import HYPOTHESES, OUTSIDE, ModelParams, hypothesis_prior
from dipper_engine.voi import enumerate_checks, evaluate, recommend

DRY = Context(rain_48h_mm=0.0, tmax_c=24, hour=10, dry_days=8)
WET = Context(rain_48h_mm=22.0, tmax_c=18, hour=10, dry_days=0)
T0 = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def graph() -> ReachGraph:
    g = synthetic_tree(main_len_m=1500, n_branches=2, branch_len_m=400, seed=3)
    g.place_synthetic_candidates(12, seed=3)
    return g


def lowest_access(g: ReachGraph) -> str:
    return min(g.access_nodes, key=lambda n: g.nodes[n].dist_to_outlet_m)


def seeded_belief(g: ReachGraph, ctx: Context = DRY) -> Belief:
    b = Belief(g, ctx)
    b.update(Observation("report", True, node_id=lowest_access(g), features=(("grey", True), ("sewage_odour", True)),
                         observed_at=T0))
    return b


def test_posterior_and_marginals_sum_to_one(graph):
    b = seeded_belief(graph)
    assert b.p.sum() == pytest.approx(1.0)
    assert sum(b.marginal_h().values()) == pytest.approx(1.0)
    assert sum(b.marginal_s().values()) == pytest.approx(1.0)


def test_wet_weather_raises_overflow_prior():
    prm = ModelParams()
    assert hypothesis_prior(prm, WET)["overflow"] > 5 * hypothesis_prior(prm, DRY)["overflow"]
    assert hypothesis_prior(prm, DRY)["foul"] > hypothesis_prior(prm, WET)["foul"]


@pytest.mark.parametrize("seed", range(8))
def test_clean_instream_check_never_raises_upstream_mass(graph, seed):
    rng = random.Random(seed)
    b = seeded_belief(graph)
    x = rng.choice(graph.access_nodes)
    up = {c.id for c in graph.candidates_upstream_of(x)}
    before = sum(v for k, v in b.marginal_s().items() if k in up)
    b.update(Observation("instream_look", False, node_id=x, observed_at=T0 + timedelta(minutes=30)))
    after = sum(v for k, v in b.marginal_s().items() if k in up)
    assert after <= before + 1e-12


def test_positive_outfall_look_raises_that_candidate(graph):
    b = seeded_belief(graph)
    cid = graph.candidates[len(graph.candidates) // 2].id
    before = b.marginal_s()[cid]
    b.update(Observation("outfall_look", True, candidate_id=cid, observed_at=T0 + timedelta(minutes=20)))
    assert b.marginal_s()[cid] > 3 * before


def test_nearby_reports_are_tempered(graph):
    node = lowest_access(graph)
    one, three = Belief(graph, DRY), Belief(graph, DRY)
    obs = Observation("report", True, node_id=node, features=(("grey", True),))
    one.update(obs)
    for _ in range(3):
        three.update(obs)
    lo = lambda b: np.log(b.marginal_h()["foul"] / (1 - b.marginal_h()["foul"]))  # noqa: E731
    prior = np.log(hypothesis_prior(ModelParams(), DRY)["foul"] / (1 - hypothesis_prior(ModelParams(), DRY)["foul"]))
    assert (lo(three) - prior) < 3 * (lo(one) - prior)


def test_voi_terms_are_non_negative_and_ranked(graph):
    b = seeded_belief(graph)
    recs = [evaluate(b, c, 0.8) for c in enumerate_checks(b)]
    assert all(r.evsi >= 0 and r.search_bits >= 0 for r in recs)
    top = recommend(b, 0.8, k=5)
    assert [r.score for r in top] == sorted((r.score for r in top), reverse=True)
    assert all(abs(r.if_positive.probability + r.if_negative.probability - 1) < 1e-6 for r in top)


def test_evidence_ledger_explains_each_update(graph):
    b = seeded_belief(graph)
    b.update(Observation("ammonium_strip", True, node_id=lowest_access(graph), role="trained"))
    assert len(b.ledger) == 2
    assert b.ledger[0].weight_for == "foul" and b.ledger[0].weight_bans > 0
    assert b.ledger[0].harm_bans > 0 and b.ledger[1].harm_bans > 0
    assert b.ledger[1].text.startswith("Ammonium strip")


def test_search_localizes_true_source_with_ideal_observer(graph):
    truth = graph.candidates[7]
    src_node = truth.node_id
    b = Belief(graph, DRY)
    below = graph.downstream_path(src_node)[2]
    t = T0
    b.update(Observation("report", True, node_id=below, features=(("grey", True), ("sewage_odour", True)), observed_at=t))
    for _ in range(20):
        if b.status() == "localized":
            break
        rec = recommend(b, 0.8, k=1)[0]
        c = rec.check
        pos = c.candidate_id == truth.id if c.check_type == "outfall_look" else src_node in graph.upstream_or_self(c.node_id)
        t += timedelta(minutes=20)
        b.update(Observation(c.check_type, pos, node_id=c.node_id, candidate_id=c.candidate_id, role=c.role, observed_at=t))
    assert b.status() == "localized"
    assert b.top_source()[0] == truth.id


def test_geojson_roundtrip(graph):
    g2 = ReachGraph.from_geojson(json.loads(json.dumps(graph.to_geojson())))
    assert set(g2.nodes) == set(graph.nodes)
    assert set(g2.g.edges) == set(graph.g.edges)
    assert [c.label for c in g2.candidates] == [c.label for c in graph.candidates]


def test_from_osm_bridges_gaps_and_marks_culverts():
    nodes = [{"type": "node", "id": i, "lat": 40.20 - i * 0.0005, "lon": -8.42} for i in range(1, 9)]
    ways = [
        {"type": "way", "id": 1, "nodes": [1, 2, 3], "tags": {"waterway": "stream"}},
        {"type": "way", "id": 2, "nodes": [3, 4, 5], "tags": {"waterway": "stream", "tunnel": "culvert"}},
        {"type": "way", "id": 3, "nodes": [5, 6], "tags": {"waterway": "stream"}},
        {"type": "way", "id": 4, "nodes": [7, 8], "tags": {"waterway": "stream"}},  # 55 m gap after node 6
    ]
    g = from_osm(nodes + ways, name="toy", city="test", max_gap_m=80)
    assert g.meta["gaps_bridged"] == 1
    assert len(g.nodes) == 8
    assert not g.nodes["4"].observable          # inside the culvert
    assert g.nodes["3"].observable              # culvert portal
    assert "1" in g.upstream_or_self("8")


def test_case_requires_human_for_advisory(graph):
    case = Case("T-1", graph, DRY)
    with pytest.raises(PermissionError):
        case.act("advisory", approver=None)
    case.act("advisory", approver="ph-officer-1")
    view = case.view(n_recommendations=2)
    assert view["actions"][0]["approver"] == "ph-officer-1"
    assert len(view["recommendations"]) == 2
    assert {h["id"] for h in view["hypotheses"]} == set(HYPOTHESES)


def test_unknown_weather_widens_priors(graph):
    b = Belief(graph, Context(hour=12))
    mh = b.marginal_h()
    assert 0.05 < mh["overflow"] < 0.3
    assert OUTSIDE in b.marginal_s()
