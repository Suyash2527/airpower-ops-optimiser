"""Pydantic entities from docs/DATA_MODEL.md §1.

Conventions
- Planning time is integer minutes from scenario t0; units are km, ft, km/h, kg, minutes.
- `set[...]` fields in the spec are stored as *sorted lists* so JSON output is deterministic
  (string hashing is randomised per process, so set order would not be stable).
- Every record carries a `Provenance` block (`source="SYNTHETIC"` for generated data).
- All numeric values produced by the generator are illustrative placeholders (HONESTY.md).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    AircraftStatus,
    AirspaceKind,
    Capability,
    ClimateZone,
    CrewStatus,
    EventOrigin,
    EventType,
    LoadoutCategory,
    MissionStatus,
    Region,
    Role,
    ThreatType,
    WeatherKind,
)

DataLabel = Literal["synthetic", "open", "external"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(Model):
    source: str  # "SYNTHETIC" | "OPEN_METEO" | "FILE:<name>" ...
    observed_at: AwareDatetime  # when the source says it was true
    ingested_at: AwareDatetime
    confidence: float = Field(ge=0, le=1)
    data_label: DataLabel


class GeoPoint(Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class AOI(Model):
    """Abstract area of interest: a point and a radius. Not a target."""

    center: GeoPoint
    radius_km: float = Field(gt=0)


class GeoJSONPolygon(Model):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[list[float]]]  # [ring][vertex][lon, lat]


class WeatherMinima(Model):
    min_visibility_km: float = Field(ge=0)
    min_ceiling_ft: float = Field(ge=0)
    max_wind_kmh: float = Field(ge=0)


class Base(Model):
    id: str
    name: str  # fictional codename, e.g. BASE-N1
    region: Region
    elevation_m: float  # from open elevation data (see sim/data/README.md)
    climate_zone: ClimateZone
    ref_temperature_c: float  # scenario-start air temperature; season preset + climate zone + lapse
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    runways: int = Field(ge=1)
    turnaround_min_by_type: dict[str, int]
    fuel_stock_kg: int = Field(ge=0)
    weather_station_id: str
    provenance: Provenance


class AircraftType(Model):
    id: str  # generic: FTR-A, TPT-B, HEL-C, ISR-D, TKR-E
    role: list[Capability]  # spec: set[Capability]
    cruise_kmh: float = Field(gt=0)
    max_range_km: float = Field(gt=0)
    combat_radius_km: float = Field(gt=0)
    endurance_min: int = Field(gt=0)
    min_crew: int = Field(ge=1)
    crew_roles: list[Role]
    hardpoints: int = Field(ge=0)
    compatible_loadouts: list[str]
    turnaround_min: int = Field(ge=0)
    flight_hours_between_maintenance: float = Field(gt=0)
    weather_minima: WeatherMinima
    provenance: Provenance


class Aircraft(Model):
    id: str
    tail: str  # synthetic code
    type_id: str
    base_id: str
    status: AircraftStatus
    available_from_min: int = Field(ge=0)
    hours_since_maintenance: float = Field(ge=0)
    fuel_state_pct: float = Field(ge=0, le=100)
    current_loadout_id: str | None
    provenance: Provenance


class CrewMember(Model):
    id: str
    name: str  # synthetic code
    role: Role
    qualifications: list[str]  # aircraft type ids
    base_id: str
    status: CrewStatus
    duty_minutes_last_24h: int = Field(ge=0)
    last_duty_end_min: int  # minutes from t0 (negative = before t0)
    provenance: Provenance


class Loadout(Model):
    """A resource attribute only (type, count, compatibility)."""

    id: str
    name: str
    category: LoadoutCategory
    items: dict[str, int]
    mass_kg: float = Field(ge=0)
    compatible_aircraft_types: list[str]
    provenance: Provenance


class WeaponStock(Model):
    base_id: str
    item_type: str
    qty_available: int = Field(ge=0)
    provenance: Provenance


class Mission(Model):
    id: str
    name: str
    capability_required: Capability
    priority: int = Field(ge=1, le=5)  # 1 = highest
    weight: float = Field(gt=0)
    window_start_min: int
    window_end_min: int
    duration_min: int = Field(gt=0)  # on-station
    aoi: AOI
    aircraft_required: int = Field(ge=1)
    loadout_category_required: LoadoutCategory | None
    min_crew_roles: list[Role]
    max_acceptable_risk: float = Field(ge=0, le=1)
    status: MissionStatus
    disaster_event: str | None = None  # HADR missions reference a (synthetic) disaster event id
    provenance: Provenance


class Threat(Model):
    id: str
    type: ThreatType
    center: GeoPoint
    radius_km: float = Field(gt=0)
    severity: float = Field(ge=0, le=1)
    active_from_min: int
    active_to_min: int
    confidence: float = Field(ge=0, le=1)
    provenance: Provenance


class AirspaceZone(Model):
    id: str
    kind: AirspaceKind
    polygon: GeoJSONPolygon
    floor_ft: int = Field(ge=0)
    ceiling_ft: int = Field(ge=0)
    active_from_min: int
    active_to_min: int
    provenance: Provenance


class WeatherRecord(Model):
    """WeatherObservation / WeatherForecast for a base location."""

    kind: WeatherKind
    base_id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    time_min: int
    visibility_km: float = Field(ge=0)
    ceiling_ft: float = Field(ge=0)
    wind_kmh: float = Field(ge=0)
    wind_dir_deg: float = Field(ge=0, lt=360)
    precip_mm_h: float = Field(ge=0)
    thunderstorm_prob: float = Field(ge=0, le=1)
    provenance: Provenance


class Airfield(Model):
    """Real public civil airport used as a divert/alternate (open data, not a base)."""

    id: str  # ICAO-style ident from the open dataset
    name: str
    iata: str | None
    type: str  # "large_airport" | "medium_airport" | "small_airport"
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    elevation_m: float
    provenance: Provenance


class MaintenanceRecord(Model):
    """One aircraft-day of synthetic history: ground truth for the serviceability model."""

    id: str
    aircraft_id: str
    type_id: str
    day_offset: int  # negative = days before t0
    hours_since_maintenance: float = Field(ge=0)  # at start of that day
    flight_hours: float = Field(ge=0)
    recent_fault_count: int = Field(ge=0)  # faults in the previous 7 days
    failure: bool
    event: Literal["NONE", "FAULT", "SCHEDULED_MAINTENANCE"]
    provenance: Provenance


_PAYLOAD_KEYS: dict[EventType, set[str]] = {
    EventType.AIRCRAFT_UNSERVICEABLE: {"aircraft_id", "until_min"},
    EventType.CREW_UNAVAILABLE: {"crew_id", "until_min"},
    EventType.WEATHER_CHANGE: {"base_id", "new_forecast_ref"},
    EventType.NEW_THREAT: {"threat"},
    EventType.THREAT_UPDATE: {"threat_id"},
    EventType.AIRSPACE_CHANGE: {"zone"},
    EventType.PRIORITY_CHANGE: {"mission_id", "new_priority"},
    EventType.NEW_MISSION: {"mission"},
    EventType.MISSION_CANCELLED: {"mission_id"},
}


class Event(Model):
    id: str
    type: EventType
    time_min: int
    payload: dict[str, Any]
    source: str
    created_by: EventOrigin
    provenance: Provenance

    @model_validator(mode="after")
    def _payload_has_required_keys(self) -> Event:
        missing = _PAYLOAD_KEYS[self.type] - self.payload.keys()
        if missing:
            raise ValueError(f"{self.type} payload missing keys: {sorted(missing)}")
        return self
