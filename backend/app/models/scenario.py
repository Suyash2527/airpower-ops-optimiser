"""Scenario metadata, generator parameters and the scenario file format (DATA_MODEL §4, §5;
INDIA_CONTEXT §6)."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.models.entities import (
    Aircraft,
    AircraftType,
    Airfield,
    AirspaceZone,
    Base,
    CrewMember,
    Event,
    Loadout,
    MaintenanceRecord,
    Mission,
    Model,
    Threat,
    WeaponStock,
    WeatherRecord,
)
from app.models.enums import ReasonCode, Region, SeasonPreset


class GeneratorParams(Model):
    """Every stochastic choice in the generator derives from `seed`."""

    seed: int
    season_preset: SeasonPreset = SeasonPreset.MONSOON
    regions: list[Region] | None = None  # None -> the season preset's default region mix
    n_bases: int = Field(3, ge=2, le=6)
    n_aircraft: int = Field(40, ge=5, le=200)
    n_crew: int = Field(60, ge=5, le=400)
    n_missions: int = Field(50, ge=4, le=300)
    horizon_min: int = Field(1440, ge=240, le=10080)
    threat_density: float = Field(0.5, ge=0, le=1)
    weather_severity: float = Field(0.3, ge=0, le=1)  # extra on top of the season preset
    disruption_rate: float = Field(0.15, ge=0, le=2)  # scheduled events per hour
    serviceable_fraction: float = Field(0.85, ge=0.5, le=1)
    crew_available_fraction: float = Field(0.75, ge=0.3, le=1)
    infeasible_fraction: float = Field(0.1, ge=0, le=0.5)  # intentionally infeasible missions
    history_days: int = Field(30, ge=1, le=365)  # synthetic maintenance history length


class DutyRules(Model):
    """Crew duty rules; illustrative placeholders (configurable)."""

    max_duty_min_24h: int = 720
    min_rest_min: int = 600


class HardCase(Model):
    """Generator ground truth: a mission made infeasible on purpose, and why."""

    mission_id: str
    intended_reason: ReasonCode


class ScenarioMeta(Model):
    name: str
    seed: int
    t0: AwareDatetime
    horizon_min: int = Field(gt=0)
    data_label: Literal["synthetic", "open", "mixed"]
    source: str = "SYNTHETIC"
    season_preset: SeasonPreset
    region_mix: dict[str, int]  # region -> number of bases
    notes: str
    open_data_sources: list[str]  # attribution for any real/open data included
    params: dict[str, Any]
    duty_rules: DutyRules
    hard_cases: list[HardCase]


# Group name -> model class, in file order. Used by file I/O, storage and the API.
GROUPS: dict[str, type[Model]] = {
    "bases": Base,
    "aircraft_types": AircraftType,
    "aircraft": Aircraft,
    "crew": CrewMember,
    "loadouts": Loadout,
    "weapon_stocks": WeaponStock,
    "missions": Mission,
    "threats": Threat,
    "airspace": AirspaceZone,
    "weather": WeatherRecord,
    "alternate_airfields": Airfield,
    "maintenance_history": MaintenanceRecord,
    "events": Event,
}


class ScenarioFile(Model):
    scenario: ScenarioMeta
    bases: list[Base]
    aircraft_types: list[AircraftType]
    aircraft: list[Aircraft]
    crew: list[CrewMember]
    loadouts: list[Loadout]
    weapon_stocks: list[WeaponStock]
    missions: list[Mission]
    threats: list[Threat]
    airspace: list[AirspaceZone]
    weather: list[WeatherRecord]
    alternate_airfields: list[Airfield]
    maintenance_history: list[MaintenanceRecord]
    events: list[Event]

    def counts(self) -> dict[str, int]:
        return {name: len(getattr(self, name)) for name in GROUPS}

    def to_canonical_json(self) -> str:
        """Canonical, byte-stable JSON: sorted keys, 2-space indent, ASCII, LF, trailing newline."""
        data = self.model_dump(mode="json", by_alias=True)
        return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
