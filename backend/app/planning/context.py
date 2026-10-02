"""PlanningContext: an immutable view of one snapshot, indexed for the planners (ARCHITECTURE
decision 1: planning is pure, with no DB or network access). Build it from a `ScenarioFile`
(stored or fused) and, optionally, the fusion metadata so stale statuses are treated cautiously."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.ingest.fusion import effective_aircraft_status
from app.ingest.models import RecordFusion
from app.models.entities import (
    Aircraft,
    AircraftType,
    Base,
    CrewMember,
    Loadout,
    Mission,
    WeatherRecord,
)
from app.models.enums import AircraftStatus, WeatherKind
from app.models.scenario import DutyRules, ScenarioFile
from app.planning.config import PlanningConfig
from app.planning.geometry import RouteProfile, build_profile
from app.sim.geo import haversine_km


@dataclass
class PlanningContext:
    scenario: ScenarioFile
    cfg: PlanningConfig = field(default_factory=PlanningConfig)
    fusion_meta: dict[str, dict[str, RecordFusion]] | None = None
    now_min: int = 0  # nothing may take off before this scenario time

    def __post_init__(self) -> None:
        s = self.scenario
        self.types: dict[str, AircraftType] = {t.id: t for t in s.aircraft_types}
        self.bases: dict[str, Base] = {b.id: b for b in s.bases}
        self.aircraft: dict[str, Aircraft] = {a.id: a for a in s.aircraft}
        self.crew: dict[str, CrewMember] = {c.id: c for c in s.crew}
        self.loadouts: dict[str, Loadout] = {item.id: item for item in s.loadouts}
        self.missions: dict[str, Mission] = {m.id: m for m in s.missions}
        self.rules: DutyRules = s.scenario.duty_rules
        self.horizon_min: int = s.scenario.horizon_min
        self.stock: dict[tuple[str, str], int] = {
            (w.base_id, w.item_type): w.qty_available for w in s.weapon_stocks
        }
        self._weather: dict[str, list[WeatherRecord]] = defaultdict(list)
        for w in s.weather:
            self._weather[w.base_id].append(w)
        for records in self._weather.values():  # at equal time the observation comes last
            records.sort(key=lambda w: (w.time_min, w.kind is WeatherKind.OBSERVATION))
        self._weather_times = {b: [w.time_min for w in recs] for b, recs in self._weather.items()}
        self._profiles: dict[tuple[Any, ...], RouteProfile] = {}
        self.crew_at_base: dict[str, list[CrewMember]] = defaultdict(list)
        for c in s.crew:
            self.crew_at_base[c.base_id].append(c)

    # ----------------------------------------------------------------------------------- lookups
    def effective_status(self, a: Aircraft) -> AircraftStatus:
        meta = (self.fusion_meta or {}).get("aircraft", {}).get(a.id)
        return effective_aircraft_status(a, meta)

    def weather_at(self, base_id: str, minute: float) -> WeatherRecord | None:
        """Latest record valid at `minute` (observation preferred at equal time); the first
        record is used before the series starts and the last after it ends."""
        records = self._weather.get(base_id)
        if not records:
            return None
        idx = bisect_right(self._weather_times[base_id], minute) - 1
        return records[max(idx, 0)]

    def nearest_base(self, lat: float, lon: float) -> Base:
        return min(
            self.bases.values(), key=lambda b: (haversine_km(lat, lon, b.lat, b.lon), b.id)
        )

    def turnaround_min(self, base_id: str, type_id: str) -> int:
        base = self.bases[base_id]
        return base.turnaround_min_by_type.get(type_id, self.types[type_id].turnaround_min)

    def profile(self, mission: Mission, base: Base, type_: AircraftType) -> RouteProfile:
        key = (mission.id, base.id, type_.cruise_kmh, mission.duration_min,
               mission.aoi.center.lat, mission.aoi.center.lon)
        found = self._profiles.get(key)
        if found is None:
            found = build_profile(
                (base.lat, base.lon), (mission.aoi.center.lat, mission.aoi.center.lon),
                type_.cruise_kmh, mission.duration_min, self.cfg.route_step_km,
                self.cfg.on_station_step_min,
            )
            self._profiles[key] = found
        return found
