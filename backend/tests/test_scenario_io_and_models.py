from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.entities import AOI, Event, GeoPoint, Mission, Provenance
from app.models.enums import EventType
from app.models.scenario import GeneratorParams, ScenarioFile
from app.sim.scenario_io import load_scenario, save_scenario


def test_save_load_round_trip_is_byte_stable(scenario42: ScenarioFile, tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    digest_a = save_scenario(scenario42, path)
    loaded = load_scenario(path)
    assert loaded.to_canonical_json().encode() == path.read_bytes()
    assert save_scenario(loaded, tmp_path / "again.json") == digest_a


def test_generator_params_reject_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        GeneratorParams(seed=1, n_bases=1)
    with pytest.raises(ValidationError):
        GeneratorParams(seed=1, weather_severity=1.5)
    with pytest.raises(ValidationError):
        GeneratorParams()  # seed is mandatory


def _prov() -> Provenance:
    t = "2026-01-01T00:00:00Z"
    return Provenance(
        source="SYNTHETIC", observed_at=t, ingested_at=t, confidence=1, data_label="synthetic"
    )


def test_provenance_confidence_and_timezone_are_enforced() -> None:
    with pytest.raises(ValidationError):
        Provenance(source="SYNTHETIC", observed_at="2026-01-01T00:00:00Z",
                   ingested_at="2026-01-01T00:00:00Z", confidence=1.5, data_label="synthetic")
    with pytest.raises(ValidationError):  # naive datetime is rejected: time is UTC internally
        Provenance(source="SYNTHETIC", observed_at="2026-01-01T00:00:00",
                   ingested_at="2026-01-01T00:00:00Z", confidence=1, data_label="synthetic")


def test_mission_priority_is_bounded_and_extra_fields_forbidden() -> None:
    base = dict(
        id="M-1", name="x", capability_required="AIRLIFT", priority=3, weight=35,
        window_start_min=0, window_end_min=100, duration_min=30,
        aoi=AOI(center=GeoPoint(lat=20, lon=78), radius_km=10), aircraft_required=1,
        loadout_category_required=None, min_crew_roles=["PILOT"], max_acceptable_risk=0.4,
        status="PENDING", provenance=_prov(),
    )
    assert Mission(**base).priority == 3
    with pytest.raises(ValidationError):
        Mission(**{**base, "priority": 6})
    with pytest.raises(ValidationError):
        Mission(**{**base, "surprise": 1})


def test_event_payload_must_have_the_documented_keys() -> None:
    ok = Event(id="E-1", type=EventType.AIRCRAFT_UNSERVICEABLE, time_min=10,
               payload={"aircraft_id": "A-001", "until_min": None}, source="SYNTHETIC",
               created_by="sim", provenance=_prov())
    assert ok.payload["until_min"] is None
    with pytest.raises(ValidationError):
        Event(id="E-2", type=EventType.AIRCRAFT_UNSERVICEABLE, time_min=10,
              payload={"aircraft_id": "A-001"}, source="SYNTHETIC", created_by="sim",
              provenance=_prov())
