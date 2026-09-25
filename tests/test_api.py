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
    cid, tok = r["case_id"], {"X-Report-Token": r["report_token"]}
    # the case summary and missions are only for the person who reported
    assert client.get(f"/v1/citizen/cases/{cid}").status_code == 403
    assert client.get(f"/v1/citizen/cases/{cid}", headers={"X-Report-Token": "0.forged"}).status_code == 403
    summary = client.get(f"/v1/citizen/cases/{cid}", headers=tok).json()
    assert "sources" not in summary and "ledger" not in summary and summary["mission"]["key"]
    assert "outfall" not in summary["mission"] and "where" not in summary["mission"]   # no outfall labels
    bad = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": "lab_ecoli:x:inspector", "positive": True},
                      headers=tok)
    assert bad.status_code == 409
    key = summary["mission"]["key"]
    assert client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": key, "positive": False}).status_code == 403
    ok = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": key, "positive": False}, headers=tok)
    assert ok.status_code == 200 and "search_narrowed_bits" in ok.json()
    again = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": key, "positive": True}, headers=tok)
    assert again.status_code == 409                                   # one answer per mission per report
    # a second report on the same reach joins the same open case
    r2 = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                          "features": {"foam": True}}).json()
    assert r2["case_id"] == cid


def test_offline_reports_keep_their_time_and_are_counted_once(api):
    from datetime import datetime, timedelta, timezone
    main, client = api
    nd = _node(main)
    seen = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    body = {"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon, "features": {"grey": True},
            "observed_at": seen, "client_id": "rep-0123456789"}
    first = client.post("/v1/signals", json=body).json()
    second = client.post("/v1/signals", json=body).json()               # the queue flushed twice
    assert first == second
    case = main._cases[first["case_id"]]
    assert len(case.belief.observations) == 1
    assert case.belief.observations[0].observed_at == datetime.fromisoformat(seen)
    old = dict(body, client_id="rep-abcdefghij", observed_at=(datetime.now(timezone.utc) - timedelta(days=9)).isoformat())
    assert client.post("/v1/signals", json=old).status_code == 422


def test_rate_limits_apply_under_the_single_origin_site(api):
    main, _ = api
    nd = _node(main)
    with TestClient(main.site) as site:
        codes = [site.post("/api/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat,
                                                     "lon": nd.lon, "features": {}}).status_code for _ in range(32)]
    assert codes[0] == 200 and 429 in codes


def test_demo_sign_in_never_issues_admin_tokens(api):
    _, client = api
    assert client.post("/v1/auth/demo", json={"role": "admin"}).status_code == 422


def test_citizen_mission_prefers_a_spot_within_walking_distance(api):
    main, client = api
    g = main.reach("coimbra-ribeira-de-coselhas")
    nd = sorted((n for n in g.nodes.values() if n.access), key=lambda n: n.dist_to_outlet_m)[len(g.nodes) // 20]
    r = client.post("/v1/signals", json={"reach_id": g_id(), "lat": nd.lat, "lon": nd.lon,
                                         "features": {"grey": True, "sewage_odour": True}}).json()
    cid, tok = r["case_id"], {"X-Report-Token": r["report_token"]}
    mission = client.get(f"/v1/citizen/cases/{cid}", headers=tok).json()["mission"]
    here = g.nodes[main._cases[cid].belief.observations[0].node_id]
    pool = main._missions(main._cases[cid])
    walk = lambda r: main.haversine_m(here.lat, here.lon, g.nodes[main._mission_node(g, r)].lat,
                                      g.nodes[main._mission_node(g, r)].lon)
    best = max(r.score - main.WALK_COST_PER_KM * walk(r) / 1000 for r in pool)
    chosen = next(r for r in pool if r.check.key() == mission["key"])
    assert chosen.score - main.WALK_COST_PER_KM * walk(chosen) / 1000 == pytest.approx(best)
    assert mission["walk_m"] <= walk(pool[0]) + 1                      # never further than the best check overall
    ok = client.post(f"/v1/citizen/cases/{cid}/checks", json={"mission_key": mission["key"], "positive": False},
                     headers=tok)
    assert ok.status_code == 200


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


def test_spoofed_forwarded_for_does_not_escape_the_rate_limit(api, monkeypatch):
    main, client = api
    nd = _node(main)
    body = {"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon, "features": {}}
    codes = [client.post("/v1/signals", json=body, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
             for i in range(32)]
    assert 429 in codes
    # behind one declared proxy, the proxy-appended entry identifies the client
    main._hits.clear()
    monkeypatch.setattr(main, "PROXY_HOPS", 1)
    codes = [client.post("/v1/signals", json=body, headers={"X-Forwarded-For": f"6.6.6.6, 10.0.0.{i}"}).status_code
             for i in range(32)]
    assert 429 not in codes


def test_single_origin_site_serves_api_and_sets_a_content_security_policy(api):
    main, _ = api
    with TestClient(main.site) as site:
        assert site.get("/api/health").status_code == 200
        if main.WEB_DIST.exists():
            page = site.get("/")
            assert "default-src 'self'" in page.headers["content-security-policy"]
            assert page.headers["x-frame-options"] == "DENY"


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


def test_old_photos_are_deleted_by_the_retention_policy(api, tmp_path):
    import time
    from dipper_api.retention import purge_media
    media = tmp_path / "m"
    media.mkdir()
    old, new = media / "old.jpg", media / "new.jpg"
    old.write_bytes(b"x"); new.write_bytes(b"x")
    past = time.time() - 31 * 86400
    os.utime(old, (past, past))
    assert purge_media(media, 30) == 1 and not old.exists() and new.exists()


def test_a_fix_is_verified_only_after_a_clean_follow_up_and_advisories_can_be_lifted(api):
    main, client = api
    inv, ph = token(client, "inspector"), token(client, "public_health")
    cid = client.post("/v1/scenarios/c014", headers=inv).json()["id"]
    for _ in range(6):
        client.post(f"/v1/scenarios/{cid}/autostep", headers=inv)
    act = lambda body, who=inv: client.post(f"/v1/cases/{cid}/actions", json=body, headers=who)
    assert act({"type": "advisory"}, ph).status_code == 200
    assert len(client.get("/v1/public/advisories").json()) == 1
    act({"type": "notify_utility"}); act({"type": "fixed"})
    assert act({"type": "verified"}).status_code == 409                       # no follow-up yet
    assert act({"type": "follow_up"}).status_code == 409                      # result is required
    assert act({"type": "follow_up", "clean": False}).json()["status"] == "handed_off"   # fix failed
    act({"type": "fixed"})
    assert act({"type": "follow_up", "clean": True}).status_code == 200
    assert act({"type": "verified"}).json()["status"] == "verified"
    # the advisory stays up until public health lifts it
    assert len(client.get("/v1/public/advisories").json()) == 1
    assert act({"type": "lift_advisory"}).status_code == 403                  # inspector may not
    assert act({"type": "lift_advisory"}, ph).status_code == 200
    assert client.get("/v1/public/advisories").json() == []
    tok = {"X-Report-Token": main._report_token(cid, 0)}           # the replay's first citizen report
    assert client.get(f"/v1/citizen/cases/{cid}", headers=tok).json()["advisory"] is None
    flag = [e["resource"] for e in client.get(f"/v1/cases/{cid}/fhir", headers=inv).json()["entry"]
            if e["resource"]["resourceType"] == "Flag"][0]
    assert flag["status"] == "inactive" and "end" in flag["period"]
    # the audit trail survives a restart with the same state
    reloaded, _, _ = main.Store(Path(os.environ["DIPPER_DB"])).load_all(main.reach)
    assert reloaded[cid].status == "verified" and not reloaded[cid].advisory_active


def test_weather_cache_that_cannot_be_written_does_not_break_a_case(tmp_path, monkeypatch):
    """In the container the bundled data directory is read-only; a new case must still get its weather."""
    from datetime import datetime, timezone
    import dipper_engine.weather as w
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    hourly = {"hourly": {"time": ["2026-09-24T12:00"], "precipitation": [0.0], "temperature_2m": [21.0]}}
    monkeypatch.setattr(w.httpx, "get", lambda *a, **k: type("R", (), {"raise_for_status": lambda s: None,
                                                                         "json": lambda s: hourly})())
    try:
        ctx = w.fetch_context(40.2, -8.4, datetime(2026, 9, 24, 12, tzinfo=timezone.utc), cache_dir=[ro / "cache", ro])
    finally:
        ro.chmod(0o700)
    assert ctx.rain_48h_mm == 0.0


def test_a_clean_report_is_negative_evidence_and_never_opens_a_case(api):
    main, client = api
    nd = _node(main)
    clean = {"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon, "features": {}}
    r = client.post("/v1/signals", json=clean).json()
    assert r["case_id"] is None and r["status"] == "no_open_case" and not main._cases
    polluted = client.post("/v1/signals", json=dict(clean, features={"grey": True})).json()
    case = main._cases[polluted["case_id"]]
    harm = case.belief.p_harmful()
    joined = client.post("/v1/signals", json=clean).json()
    assert joined["case_id"] == case.id
    last = case.belief.observations[-1]
    assert last.kind == "instream_look" and last.positive is False
    assert case.belief.p_harmful() <= harm                       # a clean look never raises the risk
    # the clean reporter can follow the case with their own token
    assert client.get(f"/v1/citizen/cases/{case.id}", headers={"X-Report-Token": joined["report_token"]}).status_code == 200


def test_a_report_without_a_device_id_still_answers_each_mission_once(api):
    main, client = api
    nd = _node(main)
    r = client.post("/v1/signals", json={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                                         "features": {"grey": True}}).json()               # no observer
    tok = {"X-Report-Token": r["report_token"]}
    key = client.get(f"/v1/citizen/cases/{r['case_id']}", headers=tok).json()["mission"]["key"]
    body = {"mission_key": key, "positive": False}
    assert client.post(f"/v1/citizen/cases/{r['case_id']}/checks", json=body, headers=tok).status_code == 200
    assert client.post(f"/v1/citizen/cases/{r['case_id']}/checks", json=body, headers=tok).status_code == 409
    assert client.get(f"/v1/citizen/cases/{r['case_id']}", headers={"X-Report-Token": "-1.x"}).status_code == 403


def test_fhir_advisory_uses_the_approved_wording_in_the_city_language(api):
    main, client = api
    inv, ph = token(client, "inspector"), token(client, "public_health")
    g = main.reach("oslo-hovinbekken")
    nd = [n for n in g.nodes.values() if n.access][2]
    cid = client.post("/v1/signals", json={"reach_id": "oslo-hovinbekken", "lat": nd.lat, "lon": nd.lon,
                                           "features": {"grey": True, "sewage_odour": True}}).json()["case_id"]
    client.post(f"/v1/cases/{cid}/actions", json={"type": "advisory"}, headers=ph)
    approved = main._cases[cid].actions[-1].payload["text"]
    assert set(approved) == {"en", "nb"}
    comm = [e["resource"] for e in client.get(f"/v1/cases/{cid}/fhir", headers=inv).json()["entry"]
            if e["resource"]["resourceType"] == "Communication"][0]
    assert [p["contentString"] for p in comm["payload"]] == [approved["nb"], approved["en"]]
    assert "Evite" not in str(comm)


def test_production_mode_hides_api_docs(tmp_path, monkeypatch):
    monkeypatch.setenv("DIPPER_DB", str(tmp_path / "prod.sqlite3"))
    monkeypatch.setenv("DIPPER_DEMO", "0")
    monkeypatch.delenv("DIPPER_DOCS", raising=False)
    import dipper_api.main as main
    main = importlib.reload(main)
    with TestClient(main.app) as client:
        assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200


def test_staff_tokens_can_be_revoked(api):
    main, client = api
    user, tok = main.users.create("A. Inspector", "inspector", ttl_s=3600)
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/v1/auth/me", headers=h).status_code == 200
    assert main.users.revoke(user.id)
    assert client.get("/v1/auth/me", headers=h).status_code == 401


def test_weather_endpoint_rejects_old_dates_and_far_away_points(api):
    from datetime import datetime, timedelta, timezone
    main, client = api
    nd = _node(main)
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert client.get("/v1/context/weather", params={"lat": nd.lat, "lon": nd.lon, "when": old}).status_code == 422
    now = datetime.now(timezone.utc).isoformat()
    assert client.get("/v1/context/weather", params={"lat": 0.0, "lon": 0.0, "when": now}).status_code == 422


def test_hsts_is_only_sent_over_https(api):
    main, _ = api
    with TestClient(main.site) as site:
        assert "strict-transport-security" not in site.get("/api/health").headers
    with TestClient(main.site, base_url="https://testserver") as site:
        assert "strict-transport-security" in site.get("/api/health").headers


def test_concurrent_traffic_across_cases_replays_to_the_same_posteriors(api):
    """Per-case locks let cases proceed in parallel; the event store must still replay every case exactly."""
    from concurrent.futures import ThreadPoolExecutor
    main, client = api
    inv = token(client, "inspector")
    reaches = ["coimbra-ribeira-de-coselhas", "oslo-hovinbekken", "oslo-hoffselva"]
    points = {r: [n for n in main.reach(r).nodes.values() if n.access][:6] for r in reaches}

    def citizen(i):
        r = reaches[i % 3]
        nd = points[r][i % 6]
        rep = client.post("/v1/signals", json={"reach_id": r, "lat": nd.lat, "lon": nd.lon,
                                               "features": {"grey": True}, "observer": f"dev-{i}"}).json()
        tok = {"X-Report-Token": rep["report_token"]}
        m = client.get(f"/v1/citizen/cases/{rep['case_id']}", headers=tok).json()["mission"]
        if m:
            client.post(f"/v1/citizen/cases/{rep['case_id']}/checks", json={"mission_key": m["key"], "positive": False},
                        headers=tok)
        client.post(f"/v1/cases/{rep['case_id']}/checks", headers=inv,
                    json={"check_type": "instream_look", "positive": i % 2 == 0, "node_id": points[r][(i + 1) % 6].id})
        return rep["case_id"]

    with ThreadPoolExecutor(8) as ex:
        cids = set(ex.map(citizen, range(24)))
    assert len(cids) == 3                                               # one open case per stream
    reloaded, _, _ = main.Store(Path(os.environ["DIPPER_DB"])).load_all(main.reach)
    for cid in cids:
        assert len(reloaded[cid].belief.observations) == len(main._cases[cid].belief.observations)
        assert np.allclose(reloaded[cid].belief.p, main._cases[cid].belief.p)
