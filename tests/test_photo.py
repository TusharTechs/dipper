import importlib
import io
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dipper_engine import Belief, Context, Observation, synthetic_tree
from dipper_engine.photo import PhotoFeatures, PhotoModelUnavailable, conflicts, extract_features, redact, to_observation

DRY = Context(rain_48h_mm=0.0, tmax_c=24, hour=10, dry_days=8)


def jpeg_with_exif(size=(4000, 3000)) -> bytes:
    img = Image.new("RGB", size, (90, 110, 100))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"          # Make
    exif[0x9003] = "2026:09:18 08:10:00"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def features_json(**over) -> str:
    base = {f: {"present": False, "confidence": 0.9} for f in
            ("grey", "sewage_fungus", "foam", "brown_turbid", "green", "pipe_flowing", "dead_fish")}
    base.update(over)
    return json.dumps({"shows_stream_or_outfall": True, "image_usable": True, "note": "Grey plume below a pipe.", **base})


class FakeClient:
    def __init__(self, text: str | None, stop_reason: str = "end_turn"):
        self.calls = []
        content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        resp = SimpleNamespace(stop_reason=stop_reason, content=content)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: (self.calls.append(kw), resp)[1]))


def test_redact_strips_metadata_and_downscales():
    raw = jpeg_with_exif()
    assert len(Image.open(io.BytesIO(raw)).getexif()) > 0
    red = redact(raw)
    out = Image.open(io.BytesIO(red.jpeg))
    assert len(out.getexif()) == 0
    assert max(out.size) == 1568 and red.face_detection
    with pytest.raises(ValueError):
        redact(b"not an image")


def test_redact_refuses_decompression_bombs():
    buf = io.BytesIO()
    Image.new("1", (9000, 9000)).save(buf, format="PNG")  # ~81 M pixels in a tiny file
    assert len(buf.getvalue()) < 200_000
    with pytest.raises(ValueError):
        redact(buf.getvalue())


def test_extract_sends_redacted_image_with_schema_and_fallbacks():
    fake = FakeClient(features_json(grey={"present": True, "confidence": 0.85}))
    pf = extract_features(redact(jpeg_with_exif()).jpeg, client=fake)
    assert pf.grey.present and pf.grey.confidence == 0.85
    kw = fake.calls[0]
    assert kw["model"] == "claude-opus-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    img = kw["messages"][0]["content"][0]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/jpeg"


@pytest.mark.parametrize("fake", [FakeClient(None, stop_reason="refusal"), FakeClient("{not json"), FakeClient('{"image_usable": true}')])
def test_extract_failures_are_reported_not_raised_as_crashes(fake):
    with pytest.raises(PhotoModelUnavailable):
        extract_features(b"x", client=fake)


def test_photo_observation_is_weaker_than_a_citizen_report():
    g = synthetic_tree(seed=2)
    g.place_synthetic_candidates(8, seed=2)
    node = min(g.access_nodes, key=lambda n: g.nodes[n].dist_to_outlet_m)
    pf = PhotoFeatures.model_validate_json(features_json(grey={"present": True, "confidence": 0.9}))
    pobs = to_observation(pf, node)
    assert pobs.role == "photo_model" and pobs.positive and ("grey", True) in pobs.features
    a, b = Belief(g, DRY), Belief(g, DRY)
    photo_w = a.update(pobs).harm_bans
    citizen_w = b.update(Observation("report", True, node_id=node, features=(("grey", True),))).harm_bans
    assert 0 < photo_w < citizen_w


def test_unusable_photo_adds_no_evidence_and_conflicts_prompt_the_citizen():
    unusable = PhotoFeatures.model_validate({**json.loads(features_json()), "image_usable": False})
    assert to_observation(unusable, "m1") is None
    pf = PhotoFeatures.model_validate_json(features_json(grey={"present": True, "confidence": 0.9}))
    cs = conflicts({"grey": False, "foam": False}, pf)
    assert [c.feature for c in cs] == ["grey"] and "Keep your answer" in cs[0].prompt


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("DIPPER_DB", str(tmp_path / "t.sqlite3"))
    import dipper_api.main as main
    main = importlib.reload(main)
    monkeypatch.setattr(main, "MEDIA_DIR", tmp_path / "media")
    main._hits.clear()
    with TestClient(main.app) as client:
        yield main, client


def _post(client, main, answers):
    g = main.reach("coimbra-ribeira-de-coselhas")
    nd = next(n for n in g.nodes.values() if n.access)
    return client.post("/v1/signals/photo", files={"photo": ("p.jpg", jpeg_with_exif((800, 600)), "image/jpeg")},
                       data={"reach_id": "coimbra-ribeira-de-coselhas", "lat": nd.lat, "lon": nd.lon,
                             "features": json.dumps(answers), "observer": "cit-7"})


def test_photo_endpoint_records_both_observers(api, monkeypatch):
    main, client = api
    pf = PhotoFeatures.model_validate_json(features_json(grey={"present": True, "confidence": 0.9}))
    monkeypatch.setattr(main, "extract", lambda jpeg: pf)
    r = _post(client, main, {"grey": False, "sewage_odour": True}).json()
    assert r["photo"]["status"] == "analysed" and r["photo"]["conflicts"][0]["feature"] == "grey"
    roles = [o.role for o in main._cases[r["case_id"]].belief.observations]
    assert roles == ["citizen", "photo_model"]
    assert "ledger" not in r                     # only the citizen's own results; never other people's evidence
    assert r["report_token"]
    media = {o.media for o in main._cases[r["case_id"]].belief.observations}
    assert len(media) == 1 and (main.MEDIA_DIR / f"{media.pop()}.jpg").exists()   # both observations link the photo


def test_photo_endpoint_keeps_the_report_when_model_unavailable(api, monkeypatch):
    main, client = api

    def boom(jpeg):
        raise PhotoModelUnavailable("no credentials")
    monkeypatch.setattr(main, "extract", boom)
    r = _post(client, main, {"grey": True}).json()
    assert r["photo"]["status"] == "not_analysed" and "no credentials" in r["photo"]["reason"]
    assert [o.role for o in main._cases[r["case_id"]].belief.observations] == ["citizen"]


def test_missing_credentials_become_unavailable_without_network(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent-dipper-test")
    with pytest.raises(PhotoModelUnavailable, match="credentials"):
        extract_features(redact(jpeg_with_exif((64, 48))).jpeg)


def test_request_time_auth_error_becomes_unavailable():
    class NoAuth(FakeClient):
        def __init__(self):
            def create(**kw):
                raise TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token"')
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))
    with pytest.raises(PhotoModelUnavailable, match="credentials"):
        extract_features(b"x", client=NoAuth())


class FakeGemini:
    def __init__(self, text, block=None):
        self.calls = []
        resp = SimpleNamespace(text=text, prompt_feedback=SimpleNamespace(block_reason=block) if block else None)
        self.models = SimpleNamespace(generate_content=lambda **kw: (self.calls.append(kw), resp)[1])


def test_gemini_backend_uses_json_schema_and_the_redacted_image():
    from dipper_engine.photo import extract_features_gemini
    fake = FakeGemini(features_json(foam={"present": True, "confidence": 0.8}))
    jpeg = redact(jpeg_with_exif((200, 150))).jpeg
    pf = extract_features_gemini(jpeg, client=fake)
    assert pf.foam.present
    kw = fake.calls[0]
    assert kw["config"].response_json_schema["additionalProperties"] is False
    assert kw["contents"][0].inline_data.data == jpeg
    with pytest.raises(PhotoModelUnavailable, match="declined"):
        extract_features_gemini(jpeg, client=FakeGemini(None, block="SAFETY"))


def test_provider_selection(monkeypatch):
    from dipper_engine.photo import vision_provider
    for v in ("DIPPER_VISION_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert vision_provider() == "none"
    monkeypatch.setenv("LLM_API_KEY", "x")  # a generic key alone never selects (or reaches) Google
    assert vision_provider() == "none"
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert vision_provider() == "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    assert vision_provider() == "anthropic"
    monkeypatch.setenv("DIPPER_VISION_PROVIDER", "gemini")
    assert vision_provider() == "gemini"


def test_gemini_network_failure_becomes_unavailable():
    import httpx
    from dipper_engine.photo import extract_features_gemini

    def down(**kw):
        raise httpx.ConnectError("certificate verify failed")
    client = SimpleNamespace(models=SimpleNamespace(generate_content=down))
    with pytest.raises(PhotoModelUnavailable, match="unreachable"):
        extract_features_gemini(b"x", client=client)


def test_blur_box_accepts_opencv_numpy_coordinates_and_changes_pixels():
    import numpy as np
    from dipper_engine.photo import blur_box
    img = Image.new("RGB", (200, 200), "white")
    for i in range(0, 200, 4):  # high-frequency stripes so a blur is measurable
        img.paste((0, 0, 0), (i, 60, i + 2, 140))
    before = np.asarray(img).astype(int).copy()
    blur_box(img, *np.array([70, 70, 50, 50], dtype=np.int32))
    after = np.asarray(img).astype(int)
    assert np.abs(after[90:110, 90:110] - before[90:110, 90:110]).mean() > 20  # region blurred
    assert (after[:40, :40] == before[:40, :40]).all()                       # outside untouched


def test_photo_observer_does_not_report_excluded_brown_turbid():
    pf = PhotoFeatures.model_validate_json(features_json(brown_turbid={"present": True, "confidence": 0.95},
                                                         grey={"present": True, "confidence": 0.9}))
    obs = to_observation(pf, "n1")
    assert "brown_turbid" not in dict(obs.features) and dict(obs.features)["grey"] is True
    assert conflicts({"brown_turbid": False}, pf) == []
