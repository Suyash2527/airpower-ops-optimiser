"""Planning configuration. Every value is a placeholder chosen by us (HONESTY.md), not a doctrine
or an empirical figure. Defaults match the generator's own feasibility assumptions."""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.catalog import RESERVE_FRACTION

NO_LOADOUT = "NONE"  # Assignment.loadout_id for missions that need no external loadout


@dataclass(frozen=True)
class PlanningConfig:
    slot_min: int = 15  # takeoff times are multiples of this (ALGORITHMS §2)
    reserve_fraction: float = RESERVE_FRACTION  # share of endurance kept in reserve
    route_step_km: float = 10.0  # route sampling spacing for airspace / threat tests
    on_station_step_min: int = 15  # sampling spacing while loitering at the AOI
    allow_degraded: bool = True  # DEGRADED aircraft may fly; they carry extra service risk
    degraded_service_risk: float = 0.15
    base_service_risk: float = 0.02
    hours_service_risk: float = 0.08  # added at the maintenance limit, linear in between
    runway_ops_per_runway_per_slot: int = 2  # takeoffs + landings per runway per slot
    # Weather risk (placeholder until predict/weather_impact exists, Phase 7)
    weather_margin_span: float = 1.0  # margin ratio above minima at which weather risk reaches 0
    weather_margin_weight: float = 0.3
    weather_tstorm_weight: float = 0.3
