import pytest

from dipper_engine.oah import map_submission

BASE = {"id": "s-1", "latitude": 40.21, "longitude": -8.41, "created_at": "2026-09-18T08:10:00+01:00"}


def test_pollution_answers_become_a_positive_report():
    m = map_submission(BASE | {"water_flow": "Slow (B)", "water_aspect": ["Has foam (C)", "Has colors/altered color (D)"],
                               "draining_pipes": "Yes", "sewage_discharge": "I am not sure"})
    assert m.observation_kind == "report" and m.positive
    assert ("foam", True) in m.features and ("pipe_flowing", True) in m.features
    assert "altered colour" in m.reason
    obs = m.to_observation("n1")
    assert obs.role == "citizen" and obs.observer == "oah:s-1" and obs.observed_at.utcoffset().total_seconds() == 3600


def test_greek_option_codes_and_sewage_only_are_understood():
    m = map_submission(BASE | {"water_aspect": "Muddy/turbid (Β)", "sewage_discharge": "Ναι"})
    assert m.positive and ("brown_turbid", True) in m.features and "sewage discharge" in m.reason


def test_clear_water_is_clean_evidence_and_unsure_or_dry_is_none():
    clear = map_submission(BASE | {"water_aspect": "Clear/transparent (A)", "draining_pipes": "No", "sewage_discharge": "No"})
    assert clear.observation_kind == "instream_look" and not clear.positive
    unsure = map_submission(BASE | {"water_aspect": "I am not sure"})
    assert unsure.observation_kind is None and unsure.to_observation("n1") is None
    dry = map_submission(BASE | {"water_flow": "Dry (D)", "water_aspect": "Has foam (C)"})
    assert dry.observation_kind is None and dry.reason == "stream reported dry"


def test_missing_location_is_rejected():
    with pytest.raises(ValueError):
        map_submission({"id": "x", "water_aspect": "Has foam (C)"})
