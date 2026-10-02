"""Events (Task 5.1, 5.8): validation, application to a state copy, and the seeded simulator."""

from __future__ import annotations

import pytest
from planning_world import (
    BASE_LAT,
    BASE_LON,
    PROV,
    mission,
    threat,
    world,
    zone,
)

from app.models.entities import Event
from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    EventOrigin,
    EventType,
    MissionStatus,
)
from app.models.scenario import GeneratorParams, ScenarioFile
from app.planning.context import PlanningContext
from app.planning.feasibility import build_mission
from app.sim.events import EventError, apply_event, simulate_events, validate_event
from app.sim.generate import generate_scenario

T = EventType


def ev(type_: EventType, payload: dict, time_min: int = 100, id_: str = "EV-001") -> Event:
    return Event(id=id_, type=type_, time_min=time_min, payload=payload, source="USER",
                 created_by=EventOrigin.USER, provenance=PROV)


# --------------------------------------------------------------------------------- apply
def test_aircraft_unserviceable_with_and_without_a_return_time() -> None:
    scn = world()
    back = apply_event(scn, ev(T.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1", "until_min": 500}))
    a = back.aircraft[0]
    assert a.status is AircraftStatus.UNSERVICEABLE and a.available_from_min == 500
    gone = apply_event(scn, ev(T.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1", "until_min": None}))
    assert gone.aircraft[0].available_from_min == scn.scenario.horizon_min + 1
    assert scn.aircraft[0].status is AircraftStatus.SERVICEABLE  # the original is untouched


def test_unserviceable_aircraft_is_blocked_until_it_returns() -> None:
    scn = apply_event(world(), ev(T.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1",
                                                             "until_min": 200}))
    ctx = PlanningContext(scn, now_min=100)
    feas = build_mission(ctx, ctx.missions["M-1"])
    assert feas.options[0].slots[0].takeoff_min == 210  # first slot at/after its return at T+200


def test_crew_unavailable_blocks_takeoffs_before_until() -> None:
    scn = apply_event(world(), ev(T.CREW_UNAVAILABLE, {"crew_id": "C-1", "until_min": 250}))
    ctx = PlanningContext(scn, now_min=100)
    feas = build_mission(ctx, ctx.missions["M-1"])
    # last_duty_end = 250 - 600 -> takeoff - last_end >= 600 -> takeoff >= 250 -> first slot 255
    assert feas.options[0].slots[0].takeoff_min == 255


def test_weather_change_degrades_the_forecast_in_the_window_only() -> None:
    scn = world()
    new = apply_event(scn, ev(T.WEATHER_CHANGE, {"base_id": "B1", "new_forecast_ref": "x"},
                              time_min=120))
    before = {w.time_min: w for w in scn.weather}
    after = {w.time_min: w for w in new.weather}
    assert after[60].visibility_km == before[60].visibility_km  # before the window
    assert after[120].visibility_km == pytest.approx(before[120].visibility_km * 0.3, abs=0.06)
    assert after[240].wind_kmh == pytest.approx(before[240].wind_kmh * 1.6, abs=0.06)
    assert after[600].visibility_km == before[600].visibility_km  # after +360 min
    explicit = apply_event(scn, ev(T.WEATHER_CHANGE, {
        "base_id": "B1", "new_forecast_ref": "x", "visibility_km": 0.5, "until_min": 200},
        time_min=100))
    assert {w.time_min: w.visibility_km for w in explicit.weather}[120] == 0.5
    assert {w.time_min: w.visibility_km for w in explicit.weather}[240] == 10.0


def test_weather_change_can_close_a_base() -> None:
    new = apply_event(world(), ev(T.WEATHER_CHANGE, {
        "base_id": "B1", "new_forecast_ref": "x", "visibility_km": 0.5, "until_min": 1400},
        time_min=0))
    ctx = PlanningContext(new)
    assert not build_mission(ctx, ctx.missions["M-1"]).coverable


def test_new_threat_threat_update_and_airspace_change() -> None:
    scn = world()
    t = threat(id="T-9")
    with_threat = apply_event(scn, ev(T.NEW_THREAT, {"threat": t.model_dump(mode="json")}))
    assert [x.id for x in with_threat.threats] == ["T-9"]
    ctx = PlanningContext(with_threat)
    assert not build_mission(ctx, ctx.missions["M-1"]).coverable  # sits on the AOI
    softer = apply_event(with_threat, ev(T.THREAT_UPDATE, {"threat_id": "T-9", "severity": 0.1}))
    assert softer.threats[0].severity == 0.1 and softer.threats[0].radius_km == t.radius_km
    z = zone(AirspaceKind.NO_FLY, BASE_LAT + 0.75, BASE_LON, 0.2, id_="Z-9")
    with_zone = apply_event(scn, ev(T.AIRSPACE_CHANGE, {"zone": z.model_dump(mode="json")}))
    assert [x.id for x in with_zone.airspace] == ["Z-9"]
    replaced = apply_event(with_zone, ev(T.AIRSPACE_CHANGE, {"zone": z.model_dump(mode="json")}))
    assert len(replaced.airspace) == 1  # same id replaces


def test_priority_change_updates_weight_and_cancel_and_new_mission() -> None:
    scn = world()
    up = apply_event(scn, ev(T.PRIORITY_CHANGE, {"mission_id": "M-1", "new_priority": 5}))
    assert (up.missions[0].priority, up.missions[0].weight) == (5, 10.0)
    gone = apply_event(scn, ev(T.MISSION_CANCELLED, {"mission_id": "M-1"}))
    assert gone.missions[0].status is MissionStatus.CANCELLED
    new = apply_event(scn, ev(T.NEW_MISSION, {"mission": mission("M-7").model_dump(mode="json")}))
    assert [m.id for m in new.missions] == ["M-1", "M-7"]


# ------------------------------------------------------------------------------ validation
@pytest.mark.parametrize(("type_", "payload", "needle"), [
    (T.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-404", "until_min": None}, "unknown aircraft"),
    (T.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1", "until_min": 50}, "after time_min"),
    (T.CREW_UNAVAILABLE, {"crew_id": "C-404", "until_min": 300}, "unknown crew"),
    (T.CREW_UNAVAILABLE, {"crew_id": "C-1", "until_min": None}, "integer after"),
    (T.WEATHER_CHANGE, {"base_id": "NOPE", "new_forecast_ref": "x"}, "unknown base"),
    (T.NEW_THREAT, {"threat": {"id": "T-1"}}, "invalid payload for NEW_THREAT"),
    (T.THREAT_UPDATE, {"threat_id": "T-404"}, "unknown threat"),
    (T.PRIORITY_CHANGE, {"mission_id": "M-1", "new_priority": 9}, "1..5"),
    (T.PRIORITY_CHANGE, {"mission_id": "M-404", "new_priority": 2}, "unknown mission"),
    (T.NEW_MISSION, {"mission": mission("M-1").model_dump(mode="json")}, "already exists"),
    (T.MISSION_CANCELLED, {"mission_id": "M-404"}, "unknown mission"),
    (T.AIRSPACE_CHANGE, {"zone": {"id": "Z"}}, "invalid payload for AIRSPACE_CHANGE"),
])
def test_invalid_events_are_rejected_with_a_reason(type_, payload, needle) -> None:
    with pytest.raises(EventError, match=needle):
        validate_event(world(), ev(type_, payload))


def test_threat_update_rejects_unknown_fields_and_negative_time() -> None:
    scn = world(threats=[threat()])
    with pytest.raises(EventError, match="cannot update"):
        validate_event(scn, ev(T.THREAT_UPDATE, {"threat_id": "T-1", "type": "x"}))
    with pytest.raises(EventError, match="time_min"):
        validate_event(scn, ev(T.MISSION_CANCELLED, {"mission_id": "M-1"}, time_min=-1))


def test_event_model_requires_its_payload_keys() -> None:
    with pytest.raises(ValueError, match="missing keys"):
        ev(T.AIRCRAFT_UNSERVICEABLE, {"aircraft_id": "A-1"})


# ----------------------------------------------------------------------------- simulator
def test_simulator_is_deterministic_and_valid_against_the_state() -> None:
    scn = generate_scenario(GeneratorParams(seed=7))
    a = simulate_events(scn, seed=1, count=30, from_min=60, to_min=1000)
    b = simulate_events(scn, seed=1, count=30, from_min=60, to_min=1000)
    assert a == b and len(a) == 30
    assert a != simulate_events(scn, seed=2, count=30, from_min=60, to_min=1000)
    assert [t for t, _, _ in a] == sorted(t for t, _, _ in a)
    assert all(60 <= t <= 1000 for t, _, _ in a)
    cur: ScenarioFile = scn
    for i, (t, ty, p) in enumerate(a):
        cur = apply_event(cur, ev(ty, p, time_min=t, id_=f"EV-{i + 1:03d}"))  # none raises
    assert {ty for _, ty, _ in a} >= {T.AIRCRAFT_UNSERVICEABLE, T.CREW_UNAVAILABLE}


def test_simulator_serial_keeps_new_ids_unique_across_calls() -> None:
    scn = generate_scenario(GeneratorParams(seed=7))
    ids: set[str] = set()
    for serial in (0, 1):
        for _, ty, p in simulate_events(scn, seed=3, count=60, from_min=0, to_min=1000, serial=serial):
            key = {T.NEW_MISSION: lambda p: p["mission"]["id"], T.NEW_THREAT: lambda p: p["threat"]["id"],
                   T.AIRSPACE_CHANGE: lambda p: p["zone"]["id"]}.get(ty)
            if key:
                assert key(p) not in ids
                ids.add(key(p))
