from datetime import datetime, timedelta, timezone

from dipper_engine import Case, Context, Observation, synthetic_tree
from dipper_engine.fhir import case_bundle

T0 = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)


def make_case(simulated: bool) -> Case:
    g = synthetic_tree(seed=5)
    g.place_synthetic_candidates(10, seed=5)
    case = Case("T-9", g, Context(rain_48h_mm=0.0, tmax_c=25, hour=9, dry_days=6), opened_at=T0)
    low = min(g.access_nodes, key=lambda n: g.nodes[n].dist_to_outlet_m)
    tier = "simulated" if simulated else "observed"
    case.add(Observation("report", True, node_id=low, features=(("grey", True), ("foam", True)), observed_at=T0, tier=tier))
    case.add(Observation("ammonium_strip", True, node_id=low, role="trained", observed_at=T0 + timedelta(minutes=30), tier=tier))
    return case


def test_bundle_structure_and_references_resolve():
    b = case_bundle(make_case(simulated=False), T0)
    ids = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in b["entry"]}
    types = {e["resource"]["resourceType"] for e in b["entry"]}
    assert {"Location", "Observation", "DetectedIssue", "RiskAssessment", "Group", "ServiceRequest", "Task", "Provenance"} <= types

    def refs(x):
        if isinstance(x, dict):
            if "reference" in x:
                yield x["reference"]
            for v in x.values():
                yield from refs(v)
        elif isinstance(x, list):
            for v in x:
                yield from refs(v)
    dangling = [r for e in b["entry"] for r in refs(e["resource"]) if r not in ids]
    assert dangling == []
    ra = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "RiskAssessment")
    assert ra["subject"]["reference"].startswith("Group/")
    assert "no pathogen confirmed" in ra["prediction"][0]["rationale"]
    assert all("text" in e["resource"] for e in b["entry"])


def test_simulated_content_is_tagged_htest():
    b = case_bundle(make_case(simulated=True), T0)
    for e in b["entry"]:
        r = e["resource"]
        assert r["id"].startswith("SIM-")
        if "meta" in r and r["resourceType"] != "Device":
            assert any(s["code"] == "HTEST" for s in r["meta"].get("security", []))


def test_observation_codes_do_not_clash_with_components():
    b = case_bundle(make_case(simulated=False), T0)
    for e in b["entry"]:
        r = e["resource"]
        if r["resourceType"] == "Observation":
            main = {(c["system"], c["code"]) for c in r["code"]["coding"]}
            for comp in r.get("component", []):
                assert not main & {(c["system"], c["code"]) for c in comp["code"]["coding"]}  # obs-7
