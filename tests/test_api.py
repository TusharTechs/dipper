import importlib
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DIPPER_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("DIPPER_MEDIA", str(tmp_path / "media"))
    monkeypatch.setenv("DIPPER_DEMO", "1")
    import dipper_api.main as main
    main = importlib.reload(main)
    with TestClient(main.app) as client:
        yield main, client


def token(client, role):
    r = client.post("/v1/auth/demo", json={"role": role})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_staff_endpoints_require_sign_in_and_the_right_role(api):
    main, client = api
    assert client.get("/v1/cases").status_code == 401
    assert client.post("/v1/scenarios/c014").status_code == 401
    inv, ph = token(client, "inspector"), token(client, "public_health")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    # public health may not hand off; an inspector may not publish an advisory
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "notify_utility"}, headers=ph).status_code == 403
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory"}, headers=inv).status_code == 403
    # a hand-off before localization is refused
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "notify_utility"}, headers=inv).status_code == 409
    for _ in range(6):
        client.post(f"/v1/scenarios/{cid}/autostep", headers=inv)
    v = client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory"}, headers=ph).json()
    assert v["actions"][-1]["approver"].startswith("Demo public-health officer (public health")
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory"}, headers=ph).status_code == 409
    v = client.post(f"/v1/cases/{cid}/actions", json={"type": "notify_utility"}, headers=inv).json()
    assert v["status"] == "handed_off"
    hist = client.get(f"/v1/cases/{cid}/history", headers=inv).json()
    assert [h["payload"]["type"] for h in hist if h["type"] == "action"] == ["advisory", "notify_utility"]
    assert client.get(f"/v1/cases/{cid}/fhir", headers=inv).json()["resourceType"] == "Bundle"


def test_demo_sign_in_is_disabled_outside_demo_mode(api, monkeypatch):
    main, client = api
    monkeypatch.setenv("DIPPER_DEMO", "0")
    assert client.post("/v1/auth/demo", json={"role": "inspector"}).status_code == 404


def test_cases_survive_restart_with_identical_posterior(api):
    main, client = api
    inv, ph = token(client, "inspector"), token(client, "public_health")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    client.post(f"/v1/scenarios/{cid}/autostep", headers=inv)
    client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory"}, headers=ph)
    before = main._cases[cid]
    reloaded, reach_of, truth = main.Store(Path(os.environ["DIPPER_DB"])).load_all(main.reach)
    after = reloaded[cid]
    assert np.allclose(before.belief.p, after.belief.p)
    assert [a.type for a in after.actions] == ["advisory"] and after.actions[0].at == before.actions[0].at
    assert truth[cid] == "O9" and reach_of[cid] == "coimbra-ribeira-de-coselhas"


def _node(main, i=0):
    g = main.reach("coimbra-ribeira-de-coselhas")
    return [n for n in g.nodes.values() if n.access][i]


def test_citizen_flow_uses_safe_endpoints_and_missions_only(api):
    main, client = api
    nd = _node(main)
    r = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                         "features": {"grey": True}, "observer": "cit-1"}).json()
    cid = r["case_id"]
    summary = client.get(f"/v1/citizen/cases/{cid}").json()
    assert "sources" not in summary and "ledger" not in summary and summary["mission"]["key"]
    bad = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": "lab_ecoli:x:inspector", "positive": True})
    assert bad.status_code == 409
    ok = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": summary["mission"]["key"], "positive": False})
    assert ok.status_code == 200 and "now_most_likely_in" in ok.json()
    # a second report on the same reach joins the same open case
    r2 = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                          "features": {"foam": True}}).json()
    assert r2["case_id"] == cid


def test_citizen_mission_prefers_a_spot_within_walking_distance(api):
    main, client = api
    g = main.reach("coimbra-ribeira-de-coselhas")
    nd = sorted((n for n in g.nodes.values() if n.access), key=lambda n: n.dist_to_outlet_m)[len(g.nodes) // 20]
    cid = client.post("/v1/signals", json={"reach_id": g_id(), "lat": nd.lat, "lon": nd.lon,
                                           "features": {"grey": True, "sewage_odour": True}}).json()["case_id"]
    far = client.get(f"/v1/citizen/cases/{cid}").json()["mission"]
    near = client.get(f"/v1/citizen/cases/{cid}", params={"lat": nd.lat, "lon": nd.lon}).json()["mission"]
    assert far["walk_m"] is None and near["walk_m"] is not None
    pool = main._missions(main._cases[cid])
    walk = lambda r: main.haversine_m(nd.lat, nd.lon, g.nodes[main._mission_node(g, r)].lat, g.nodes[main._mission_node(g, r)].lon)
    best = max(r.score - main.WALK_COST_PER_KM * walk(r) / 1000 for r in pool)
    chosen = next(r for r in pool if r.check.key() == near["key"])
    assert chosen.score - main.WALK_COST_PER_KM * walk(chosen) / 1000 == pytest.approx(best)
    assert near["walk_m"] <= far_walk(main, g, nd, pool, far["key"]) + 1
    # the nearby mission is still one the citizen may answer
    ok = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": near["key"], "positive": False})
    assert ok.status_code == 200


def far_walk(main, g, nd, pool, key):
    r = next(r for r in pool if r.check.key() == key)
    n = g.nodes[main._mission_node(g, r)]
    return main.haversine_m(nd.lat, nd.lon, n.lat, n.lon)


def g_id():
    return "coimbra-ribeira-de-coselhas"


def test_signal_validation(api):
    main, client = api
    nd = _node(main)
    far = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": 40.3, "lon": -8.3, "features": {}})
    assert far.status_code == 422 and "move closer" in far.json()["detail"]
    bad = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                           "features": {"glitter": True}})
    assert bad.status_code == 422
    assert client.post("/v1/signals", json={"reach_id": "../../etc/passwd", "lat": 0, "lon": 0}).status_code == 404
    pii = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                           "observer": "jane.doe@example.com"})
    assert pii.status_code == 422  # observer ids must be pseudonymous tokens, not emails


def test_published_advisory_is_public_but_hides_the_entry_point(api):
    main, client = api
    inv, ph = token(client, "inspector"), token(client, "public_health")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    for _ in range(6):
        client.post(f"/v1/scenarios/{cid}/autostep", headers=inv)
    assert client.get("/v1/public/advisories").json() == []
    client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory"}, headers=ph)
    adv = client.get("/v1/public/advisories").json()
    assert len(adv) == 1 and adv[0]["simulated"] and "Evite o contacto" in adv[0]["text"]["pt"]
    c = main._cases[cid]
    src = c.graph.nodes[c.graph.candidate(c.belief.top_source()[0]).node_id]
    assert [round(src.lon, 5), round(src.lat, 5)] not in adv[0]["stretch"]["coordinates"]


def test_oah_import_maps_dedupes_and_requires_role(api):
    main, client = api
    nd = _node(main, 3)
    subs = [{"id": "s1", "latitude": nd.lat, "longitude": nd.lon, "water_aspect": "Has foam (C)", "draining_pipes": "Yes"},
            {"id": "s2", "latitude": nd.lat, "longitude": nd.lon, "water_aspect": "Clear/transparent (A)",
             "draining_pipes": "No", "sewage_discharge": "No"},
            {"id": "s3", "latitude": 41.0, "longitude": -8.0, "water_aspect": "Has foam (C)"},
            {"id": "s4"}]
    body = {"reach_id": "coimbra-ribeira-de-coselhas", "submissions": subs}
    assert client.post("/v1/import/oah", json=body).status_code == 401
    inv = token(client, "inspector")
    r = client.post("/v1/import/oah", json=body, headers=inv).json()
    status = {x["id"]: x["status"] for x in r["results"]}
    assert status == {"s1": "imported", "s2": "imported", "s3": "no_evidence", "s4": "rejected"}
    again = client.post("/v1/import/oah", json=body, headers=inv).json()
    assert {x["id"]: x["status"] for x in again["results"]}["s1"] == "duplicate"


def test_rate_limit_on_public_reports(api):
    main, client = api
    nd = _node(main)
    codes = [client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                              "features": {}}).status_code for _ in range(32)]
    assert codes.count(429) >= 1 and codes[0] == 200


def test_security_headers_and_request_id(api):
    main, client = api
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert len(r.headers["x-request-id"]) >= 8


def test_rejected_checks_leave_the_case_intact(api):
    main, client = api
    inv = token(client, "inspector")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    n = len(main._cases[cid].belief.observations)
    bad = client.post(f"/v1/cases/{cid}/checks", json={"check_type": "outfall_look", "positive": True,
                                                       "candidate_id": "O999"}, headers=inv)
    assert bad.status_code == 422
    assert client.get(f"/v1/cases/{cid}", headers=inv).status_code == 200      # not bricked
    assert len(main._cases[cid].belief.observations) == n
    assert len([h for h in client.get(f"/v1/cases/{cid}/history", headers=inv).json() if h["type"] == "observation"]) == n


def test_lifecycle_rejects_out_of_order_actions_and_evidence_after_closure(api):
    main, client = api
    inv = token(client, "inspector")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "verified"}, headers=inv).status_code == 409
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "dismiss", "note": "natural foam"}, headers=inv).status_code == 200
    late = client.post(f"/v1/cases/{cid}/checks", json={"check_type": "instream_look", "positive": True,
                                                        "node_id": next(iter(main._cases[cid].graph.nodes))}, headers=inv)
    assert late.status_code == 409


def test_string_false_is_not_true_and_naive_times_are_rejected(api):
    main, client = api
    nd = _node(main)
    r = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                         "features": {"grey": "false"}})
    assert r.status_code == 422
    inv = token(client, "inspector")
    r = client.post("/v1/cases", json={"reach_id": "coimbra-ribeira-de-coselhas", "opened_at": "2026-09-20T11:00:00",
                                       "weather": {"rain_48h_mm": 0}}, headers=inv)
    assert r.status_code == 422


def test_observer_ids_are_pseudonymised_on_the_server(api):
    main, client = api
    nd = _node(main)
    cid = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                           "features": {"grey": True}, "observer": "device-123"}).json()["case_id"]
    stored = main._cases[cid].belief.observations[-1].observer
    assert stored.startswith("p_") and "device-123" not in stored
    assert stored == main.pseudonym("device-123")  # stable, so repeat reports from one device can be linked


def test_parallel_writes_keep_memory_and_database_consistent(api):
    from concurrent.futures import ThreadPoolExecutor
    main, client = api
    inv = token(client, "inspector")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    nodes = [n.id for n in main._cases[cid].graph.nodes.values() if n.access][:10]

    def post(i):
        return client.post(f"/v1/cases/{cid}/checks", json={"check_type": "instream_look", "positive": i % 2 == 0,
                                                            "node_id": nodes[i % len(nodes)]}, headers=inv).status_code
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(post, range(40)))
    assert codes.count(200) == 40
    mem = len(main._cases[cid].belief.observations)
    db = len([h for h in client.get(f"/v1/cases/{cid}/history", headers=inv).json() if h["type"] == "observation"])
    assert mem == db == 3 + 40
