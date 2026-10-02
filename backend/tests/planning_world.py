"""A tiny hand-built world for planning tests: one base, one fighter type, one aircraft, one
crew member, one mission, good weather, no threats or airspace. Geometry is easy to check by
hand: the AOI is 1.5 degrees of latitude north of the base (~166.8 km), the fighter cruises at
800 km/h, so transit = ceil(166.8 / 800 * 60) = 13 min and a 60 min patrol is a 86 min sortie.

With the default window T+100..T+400 the takeoff slots are 90, 105, ..., 315 (16 slots):
  lo = ceil((100 - 13) / 15) * 15 = 90,  hi = floor((400 - 60 - 13) / 15) * 15 = 315.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.entities import (
    AOI,
    Aircraft,
    AircraftType,
    AirspaceZone,
    Base,
    CrewMember,
    GeoJSONPolygon,
    GeoPoint,
    Loadout,
    Mission,
    Provenance,
    Threat,
    WeaponStock,
    WeatherMinima,
    WeatherRecord,
)
from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    Capability,
    ClimateZone,
    CrewStatus,
    LoadoutCategory,
    MissionStatus,
    Region,
    Role,
    SeasonPreset,
    ThreatType,
    WeatherKind,
)
from app.models.scenario import DutyRules, ScenarioFile, ScenarioMeta

T0 = datetime(2027, 7, 20, 2, 30, tzinfo=UTC)
PROV = Provenance(source="SYNTHETIC", observed_at=T0, ingested_at=T0, confidence=1.0,
                  data_label="synthetic")
BASE_LAT, BASE_LON = 20.0, 78.0


def base(id_: str = "B1", lat: float = BASE_LAT, lon: float = BASE_LON, runways: int = 2,
         elevation_m: float = 200.0, temp_c: float = 25.0) -> Base:
    return Base(
        id=id_, name=f"BASE-{id_}", region=Region.CENTRAL, elevation_m=elevation_m,
        climate_zone=ClimateZone.TROPICAL_PLATEAU, ref_temperature_c=temp_c, lat=lat, lon=lon,
        runways=runways, turnaround_min_by_type={"FTR-A": 60}, fuel_stock_kg=100000,
        weather_station_id=f"WX-{id_}", provenance=PROV,
    )


def ftr(**over: Any) -> AircraftType:
    data: dict[str, Any] = dict(
        id="FTR-A", role=[Capability.AIR_DEFENCE_PATROL], cruise_kmh=800, max_range_km=2000,
        combat_radius_km=500, endurance_min=180, min_crew=1, crew_roles=[Role.PILOT],
        hardpoints=6, compatible_loadouts=["L-AA"], turnaround_min=60,
        flight_hours_between_maintenance=100,
        weather_minima=WeatherMinima(min_visibility_km=1.5, min_ceiling_ft=500, max_wind_kmh=60),
        provenance=PROV,
    )
    return AircraftType(**{**data, **over})


def aircraft(id_: str = "A-1", **over: Any) -> Aircraft:
    data: dict[str, Any] = dict(
        id=id_, tail=f"T-{id_}", type_id="FTR-A", base_id="B1", status=AircraftStatus.SERVICEABLE,
        available_from_min=0, hours_since_maintenance=10.0, fuel_state_pct=90.0,
        current_loadout_id=None, provenance=PROV,
    )
    return Aircraft(**{**data, **over})


def crew(id_: str = "C-1", **over: Any) -> CrewMember:
    data: dict[str, Any] = dict(
        id=id_, name=f"CREW-{id_}", role=Role.PILOT, qualifications=["FTR-A"], base_id="B1",
        status=CrewStatus.AVAILABLE, duty_minutes_last_24h=0, last_duty_end_min=-1000,
        provenance=PROV,
    )
    return CrewMember(**{**data, **over})


def loadout(**over: Any) -> Loadout:
    data: dict[str, Any] = dict(
        id="L-AA", name="Air-to-air", category=LoadoutCategory.AIR_TO_AIR,
        items={"AA_STORE_T1": 4}, mass_kg=800, compatible_aircraft_types=["FTR-A"],
        provenance=PROV,
    )
    return Loadout(**{**data, **over})


def mission(id_: str = "M-1", **over: Any) -> Mission:
    data: dict[str, Any] = dict(
        id=id_, name=f"Patrol {id_}", capability_required=Capability.AIR_DEFENCE_PATROL,
        priority=1, weight=100.0, window_start_min=100, window_end_min=400, duration_min=60,
        aoi=AOI(center=GeoPoint(lat=BASE_LAT + 1.5, lon=BASE_LON), radius_km=20),
        aircraft_required=1, loadout_category_required=LoadoutCategory.AIR_TO_AIR,
        min_crew_roles=[Role.PILOT], max_acceptable_risk=0.5, status=MissionStatus.PENDING,
        provenance=PROV,
    )
    return Mission(**{**data, **over})


def weather(base_id: str = "B1", **over: Any) -> list[WeatherRecord]:
    data: dict[str, Any] = dict(
        visibility_km=10.0, ceiling_ft=8000.0, wind_kmh=10.0, wind_dir_deg=90.0,
        precip_mm_h=0.0, thunderstorm_prob=0.0,
    )
    data.update(over)
    return [
        WeatherRecord(kind=WeatherKind.FORECAST, base_id=base_id, lat=BASE_LAT, lon=BASE_LON,
                      time_min=t, provenance=PROV, **data)
        for t in range(0, 1440, 60)
    ]


def threat(**over: Any) -> Threat:
    data: dict[str, Any] = dict(
        id="T-1", type=ThreatType.GROUND_THREAT_ZONE,
        center=GeoPoint(lat=BASE_LAT + 1.5, lon=BASE_LON), radius_km=10, severity=0.95,
        active_from_min=0, active_to_min=1440, confidence=0.9, provenance=PROV,
    )
    return Threat(**{**data, **over})


def zone(kind: AirspaceKind, lat: float, lon: float, half_deg: float = 0.3, *,
         id_: str = "Z-1", start: int = 0, end: int = 1440) -> AirspaceZone:
    ring = [[lon - half_deg, lat - half_deg], [lon + half_deg, lat - half_deg],
            [lon + half_deg, lat + half_deg], [lon - half_deg, lat + half_deg],
            [lon - half_deg, lat - half_deg]]
    return AirspaceZone(id=id_, kind=kind, polygon=GeoJSONPolygon(coordinates=[ring]),
                        floor_ft=0, ceiling_ft=60000, active_from_min=start, active_to_min=end,
                        provenance=PROV)


def world(**over: Any) -> ScenarioFile:
    """Override any group by name, e.g. world(crew=[], missions=[mission(priority=2)])."""
    groups: dict[str, Any] = dict(
        bases=[base()], aircraft_types=[ftr()], aircraft=[aircraft()], crew=[crew()],
        loadouts=[loadout()],
        weapon_stocks=[WeaponStock(base_id="B1", item_type="AA_STORE_T1", qty_available=20,
                                   provenance=PROV)],
        missions=[mission()], threats=[], airspace=[], weather=weather(),
        alternate_airfields=[], maintenance_history=[], events=[],
    )
    groups.update(over)
    meta = ScenarioMeta(
        name="tiny", seed=0, t0=T0, horizon_min=1440, data_label="synthetic",
        season_preset=SeasonPreset.MONSOON, region_mix={"central": 1}, notes="test world",
        open_data_sources=[], params={}, duty_rules=DutyRules(), hard_cases=[],
    )
    return ScenarioFile(scenario=meta, **groups)
