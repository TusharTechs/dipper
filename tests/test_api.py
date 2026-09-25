import importlib
import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DIPPER_DB", str(tmp_path / "test.sqlite3"))
    import dipper_api.main as main
    main = importlib.reload(main)
    with TestClient(main.app) as client:
        yield main, client


def test_scenario_flow_and_approval_gate(api):
    main, client = api
    v = client.post("/v1/scenarios/c014").json()
    cid = v["id"]
    assert v["hypotheses"][0]["id"] == "foul"
    for _ in range(3):
        r = client.post(f"/v1/scenarios/{cid}/autostep")
        assert r.status_code == 200
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "notify_utility"}).status_code == 403
    assert client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory", "approver": "ph-01"}).status_code == 200
    hist = client.get(f"/v1/cases/{cid}/history").json()
    assert [h["type"] for h in hist].count("observation") == 6 and hist[-1]["payload"]["approver"] == "ph-01"
    assert client.get(f"/v1/cases/{cid}/fhir").json()["resourceType"] == "Bundle"
    # Starting the scenario again gives a new id instead of overwriting.
    assert client.post("/v1/scenarios/c014").json()["id"] == f"{cid}-2"


def test_cases_survive_restart_with_identical_posterior(api):
    main, client = api
    cid = client.post("/v1/scenarios/c014").json()["id"]
    client.post(f"/v1/scenarios/{cid}/autostep")
    client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory", "approver": "ph-01"})
    before = main._cases[cid]
    reloaded, reach_of, truth = main.Store(Path(os.environ["DIPPER_DB"])).load_all(main.reach)
    after = reloaded[cid]
    assert np.allclose(before.belief.p, after.belief.p)
    assert [a.type for a in after.actions] == ["advisory"] and after.actions[0].at == before.actions[0].at
    assert truth[cid] == "O9" and reach_of[cid] == "coimbra-ribeira-de-coselhas"


def test_signal_snaps_to_stream_and_rejects_far_points(api):
    main, client = api
    g = main.reach("coimbra-ribeira-de-coselhas")
    nd = next(n for n in g.nodes.values() if n.access)
    ok = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                          "features": {"grey": True}, "observer": "cit-1"})
    assert ok.status_code == 200 and ok.json()["snap_distance_m"] < 1
    far = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": 40.3, "lon": -8.3, "features": {}})
    assert far.status_code == 422
    bad = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                           "features": {"glitter": True}})
    assert bad.status_code == 422
