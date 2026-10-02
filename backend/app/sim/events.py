"""Disruption events (PRD R-1): validate a payload, apply an event to a scenario copy, and a seeded
simulator. `apply_event` is pure: it returns a new `ScenarioFile`.

How each event changes the state (interpretations logged in DECISIONS D-57):
- AIRCRAFT_UNSERVICEABLE {aircraft_id, until_min}: status UNSERVICEABLE; it returns at `until_min`
  (`available_from_min`), or never within the horizon when `until_min` is null.
- CREW_UNAVAILABLE {crew_id, until_min}: the crew member cannot start a sortie before `until_min`
  (modelled as `last_duty_end_min = until_min - min_rest`, so the normal rest rule gives exactly
  that earliest takeoff). Status is left as reported.
- WEATHER_CHANGE {base_id, new_forecast_ref, ...}: the base's forecast is degraded from the event
  time until `until_min` (default +360 min). Optional payload keys `visibility_km`, `ceiling_ft`,
  `wind_kmh`, `thunderstorm_prob` set explicit values; otherwise visibility and ceiling x0.3, wind
  x1.6 (placeholders).
- NEW_THREAT {threat}: added. THREAT_UPDATE {threat_id, ...fields}: those fields are replaced.
- AIRSPACE_CHANGE {zone}: added, replacing a zone with the same id.
- PRIORITY_CHANGE {mission_id, new_priority}: priority and weight (from the priority table).
- NEW_MISSION {mission}: added as PENDING.   MISSION_CANCELLED {mission_id}: status CANCELLED.
"""

from __future__ import annotations

import random
from typing import Any

from pydantic import ValidationError

from app.models.entities import AirspaceZone, Event, Mission, Threat, WeatherRecord
from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    Capability,
    EventType,
    MissionStatus,
    ThreatType,
)
from app.models.scenario import GeneratorParams, ScenarioFile
from app.sim import catalog as cat
from app.sim.generate import _blob, _build_mission, _build_world, _prov, _region_point, _zone
from app.sim.geo import offset_km

WEATHER_WINDOW_MIN = 360
WEATHER_VIS_FACTOR, WEATHER_CEIL_FACTOR, WEATHER_WIND_FACTOR = 0.3, 0.3, 1.6
THREAT_UPDATE_FIELDS = {"severity", "radius_km", "center", "active_from_min", "active_to_min",
                        "confidence"}


class EventError(ValueError):
    """The event does not make sense for this scenario (unknown id, bad value, ...)."""


# ------------------------------------------------------------------------------ validation
def _find(items: list[Any], key: str, value: str, what: str) -> Any:
    for item in items:
        if getattr(item, key) == value:
            return item
    raise EventError(f"unknown {what}: {value}")


def validate_event(scenario: ScenarioFile, event: Event) -> None:
    """Raise EventError if the payload refers to things that do not exist or is malformed."""
    p, t = event.payload, event.type
    if event.time_min < 0:
        raise EventError("time_min must be >= 0")
    try:
        if t is EventType.AIRCRAFT_UNSERVICEABLE:
            _find(scenario.aircraft, "id", p["aircraft_id"], "aircraft")
            if p["until_min"] is not None and (
                not isinstance(p["until_min"], int) or p["until_min"] <= event.time_min
            ):
                raise EventError("until_min must be null or an integer after time_min")
        elif t is EventType.CREW_UNAVAILABLE:
            _find(scenario.crew, "id", p["crew_id"], "crew member")
            if not isinstance(p["until_min"], int) or p["until_min"] <= event.time_min:
                raise EventError("until_min must be an integer after time_min")
        elif t is EventType.WEATHER_CHANGE:
            _find(scenario.bases, "id", p["base_id"], "base")
            if p.get("until_min") is not None and p["until_min"] <= event.time_min:
                raise EventError("until_min must be after time_min")
        elif t is EventType.NEW_THREAT:
            th = Threat.model_validate(p["threat"])
            if any(x.id == th.id for x in scenario.threats):
                raise EventError(f"threat {th.id} already exists")
        elif t is EventType.THREAT_UPDATE:
            _find(scenario.threats, "id", p["threat_id"], "threat")
            extra = set(p) - {"threat_id"} - THREAT_UPDATE_FIELDS
            if extra:
                raise EventError(f"cannot update threat fields: {sorted(extra)}")
            _updated_threat(scenario, p)
        elif t is EventType.AIRSPACE_CHANGE:
            AirspaceZone.model_validate(p["zone"])
        elif t is EventType.PRIORITY_CHANGE:
            _find(scenario.missions, "id", p["mission_id"], "mission")
            if p["new_priority"] not in cat.PRIORITY_WEIGHT:
                raise EventError("new_priority must be 1..5")
        elif t is EventType.NEW_MISSION:
            m = Mission.model_validate(p["mission"])
            if any(x.id == m.id for x in scenario.missions):
                raise EventError(f"mission {m.id} already exists")
        elif t is EventType.MISSION_CANCELLED:
            _find(scenario.missions, "id", p["mission_id"], "mission")
    except ValidationError as exc:
        err = exc.errors()[0]
        where = ".".join(str(x) for x in err["loc"])
        raise EventError(f"invalid payload for {t.value}: {where}: {err['msg']}") from exc


def _updated_threat(scenario: ScenarioFile, p: dict[str, Any]) -> Threat:
    old = _find(scenario.threats, "id", p["threat_id"], "threat")
    data = old.model_dump(mode="json")
    data.update({k: v for k, v in p.items() if k in THREAT_UPDATE_FIELDS})
    return Threat.model_validate(data)


# -------------------------------------------------------------------------------- applying
def apply_event(scenario: ScenarioFile, event: Event) -> ScenarioFile:
    validate_event(scenario, event)
    p, t = event.payload, event.type
    upd: dict[str, Any] = {}
    if t is EventType.AIRCRAFT_UNSERVICEABLE:
        until = p["until_min"] if p["until_min"] is not None else scenario.scenario.horizon_min + 1
        upd["aircraft"] = [
            a.model_copy(update={"status": AircraftStatus.UNSERVICEABLE,
                                 "available_from_min": until})
            if a.id == p["aircraft_id"] else a for a in scenario.aircraft
        ]
    elif t is EventType.CREW_UNAVAILABLE:
        rest = scenario.scenario.duty_rules.min_rest_min
        upd["crew"] = [
            c.model_copy(update={"last_duty_end_min": p["until_min"] - rest})
            if c.id == p["crew_id"] else c for c in scenario.crew
        ]
    elif t is EventType.WEATHER_CHANGE:
        upd["weather"] = _degrade_weather(scenario, event)
    elif t is EventType.NEW_THREAT:
        upd["threats"] = [*scenario.threats, Threat.model_validate(p["threat"])]
    elif t is EventType.THREAT_UPDATE:
        new = _updated_threat(scenario, p)
        upd["threats"] = [new if x.id == new.id else x for x in scenario.threats]
    elif t is EventType.AIRSPACE_CHANGE:
        zone = AirspaceZone.model_validate(p["zone"])
        upd["airspace"] = [x for x in scenario.airspace if x.id != zone.id] + [zone]
    elif t is EventType.PRIORITY_CHANGE:
        prio = p["new_priority"]
        upd["missions"] = [
            m.model_copy(update={"priority": prio, "weight": cat.PRIORITY_WEIGHT[prio]})
            if m.id == p["mission_id"] else m for m in scenario.missions
        ]
    elif t is EventType.NEW_MISSION:
        upd["missions"] = [*scenario.missions, Mission.model_validate(p["mission"])]
    elif t is EventType.MISSION_CANCELLED:
        upd["missions"] = [
            m.model_copy(update={"status": MissionStatus.CANCELLED})
            if m.id == p["mission_id"] else m for m in scenario.missions
        ]
    return scenario.model_copy(update=upd)


def _degrade_weather(scenario: ScenarioFile, event: Event) -> list[WeatherRecord]:
    p = event.payload
    end = p.get("until_min") or event.time_min + WEATHER_WINDOW_MIN
    explicit = {k: p[k] for k in ("visibility_km", "ceiling_ft", "wind_kmh", "thunderstorm_prob")
                if k in p}
    out = []
    for w in scenario.weather:
        if w.base_id == p["base_id"] and event.time_min - 59 <= w.time_min <= end:
            change = explicit or {
                "visibility_km": round(w.visibility_km * WEATHER_VIS_FACTOR, 1),
                "ceiling_ft": round(w.ceiling_ft * WEATHER_CEIL_FACTOR, -1),
                "wind_kmh": round(w.wind_kmh * WEATHER_WIND_FACTOR, 1),
                "thunderstorm_prob": min(1.0, round(w.thunderstorm_prob + 0.3, 2)),
            }
            w = WeatherRecord.model_validate({**w.model_dump(mode="json"), **change})
        out.append(w)
    return out


# ------------------------------------------------------------------------------- simulator
SIM_TYPES: list[tuple[EventType, float]] = [
    (EventType.AIRCRAFT_UNSERVICEABLE, 0.30), (EventType.CREW_UNAVAILABLE, 0.15),
    (EventType.WEATHER_CHANGE, 0.15), (EventType.NEW_THREAT, 0.10),
    (EventType.PRIORITY_CHANGE, 0.10), (EventType.MISSION_CANCELLED, 0.05),
    (EventType.AIRSPACE_CHANGE, 0.05), (EventType.NEW_MISSION, 0.10),
]


def simulate_events(
    scenario: ScenarioFile, seed: int, count: int, from_min: int, to_min: int, serial: int = 0,
) -> list[tuple[int, EventType, dict[str, Any]]]:
    """`count` seeded disruptions with times in [from_min, to_min], built against `scenario` (the
    current state). Same scenario, seed and arguments give the same events. `serial` keeps new
    mission / threat / zone ids unique across several calls."""
    rng = random.Random(f"airpower:{seed}:events-sim:{serial}")
    params = GeneratorParams.model_validate(scenario.scenario.params)
    season = cat.SEASONS[params.season_preset]
    world = _build_world(params, season, scenario.bases, scenario.aircraft)
    horizon = scenario.scenario.horizon_min
    t0 = scenario.scenario.t0
    flyable = [a for a in scenario.aircraft if a.status is AircraftStatus.SERVICEABLE]
    plannable = [m for m in scenario.missions if m.status in (MissionStatus.PENDING,
                                                              MissionStatus.PLANNED)]
    types = [t for t, _ in SIM_TYPES]
    weights = [w for _, w in SIM_TYPES]
    next_mission = len(scenario.missions) + 1 + serial * 100
    next_threat = len(scenario.threats) + 1 + serial * 100
    out: list[tuple[int, EventType, dict[str, Any]]] = []
    for k in range(count):
        t = rng.randint(from_min, max(from_min, to_min))
        etype = rng.choices(types, weights=weights)[0]
        if etype is EventType.AIRCRAFT_UNSERVICEABLE and flyable:
            payload: dict[str, Any] = {
                "aircraft_id": rng.choice(flyable).id,
                "until_min": None if rng.random() < 0.3 else t + rng.randint(120, 720),
            }
        elif etype is EventType.CREW_UNAVAILABLE:
            payload = {"crew_id": rng.choice(scenario.crew).id,
                       "until_min": t + rng.randint(120, 600)}
        elif etype is EventType.WEATHER_CHANGE:
            base = rng.choice(scenario.bases)
            payload = {"base_id": base.id, "new_forecast_ref": f"{base.id}:FORECAST:{t // 60 * 60}"}
        elif etype is EventType.NEW_THREAT:
            regions = list(dict.fromkeys(b.region for b in scenario.bases))
            lat, lon = _region_point(rng, rng.choice(regions))
            payload = {"threat": Threat(
                id=f"T-{next_threat:02d}", type=rng.choice(list(ThreatType)),
                center={"lat": round(lat, 4), "lon": round(lon, 4)},  # type: ignore[arg-type]
                radius_km=round(rng.uniform(30, 120), 1), severity=round(rng.uniform(0.3, 0.9), 2),
                active_from_min=t, active_to_min=min(horizon, t + rng.randint(180, 600)),
                confidence=round(rng.uniform(0.5, 0.9), 2), provenance=_prov(rng, t0),
            ).model_dump(mode="json")}
            next_threat += 1
        elif etype is EventType.PRIORITY_CHANGE and plannable:
            m = rng.choice(plannable)
            payload = {"mission_id": m.id,
                       "new_priority": rng.choice([p for p in (1, 2, 3) if p != m.priority])}
        elif etype is EventType.MISSION_CANCELLED and plannable:
            payload = {"mission_id": rng.choice(plannable).id}
        elif etype is EventType.AIRSPACE_CHANGE:
            b = rng.choice(scenario.bases)
            lat, lon = offset_km(b.lat, b.lon, rng.uniform(-100, 100), rng.uniform(-100, 100))
            zone = _zone(
                f"Z-EV-{serial * 100 + k + 1:02d}", AirspaceKind.RESTRICTED,
                _blob(rng, lat, lon, 60), 0, 30000, t, min(horizon, t + rng.randint(180, 600)),
                _prov(rng, t0),
            )
            payload = {"zone": zone.model_dump(mode="json")}
        elif Capability.HADR in world.candidates:  # NEW_MISSION, or the fallback for empty pools
            etype = EventType.NEW_MISSION
            mission = _build_mission(
                world, rng, next_mission, Capability.HADR, min_start=t + 30,
                disaster_event=f"DE-SIM-{serial * 100 + k + 1:02d}", priority=rng.choice([1, 1, 2]),
            )
            next_mission += 1
            payload = {"mission": mission.model_dump(mode="json")}
        else:
            etype = EventType.WEATHER_CHANGE
            base = rng.choice(scenario.bases)
            payload = {"base_id": base.id, "new_forecast_ref": f"{base.id}:FORECAST:{t // 60 * 60}"}
        out.append((t, etype, payload))
    out.sort(key=lambda item: (item[0], item[1].value))
    return out
