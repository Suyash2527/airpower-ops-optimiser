"""Risk model (ALGORITHMS §4): transparent formulas, each component reported separately.

- threat   = sum over threat zones active during the sortie of
             severity * confidence * (flight time spent inside the zone / total flight time),
             clipped to 0..1. Time-weighted (refines §4's "fraction of route"): time on station
             at the AOI counts, so a zone sitting on the AOI cannot hide behind a long transit.
- weather  = PLACEHOLDER until predict/weather_impact exists (Phase 7): from the margin above
             the type's minima and the thunderstorm probability at the worst point of the sortie.
- service  = PLACEHOLDER until predict/serviceability exists (Phase 7): a small base risk that
             grows with hours since maintenance, plus extra for a DEGRADED aircraft.
- total    = 1 - (1-threat)(1-weather)(1-service), assuming the three risks are independent.
"""

from __future__ import annotations

import numpy as np

from app.models.entities import Aircraft, AircraftType, WeatherMinima, WeatherRecord
from app.models.enums import AircraftStatus
from app.models.plans import RiskBreakdown
from app.planning.config import PlanningConfig
from app.planning.context import PlanningContext
from app.planning.geometry import RouteProfile, inside_threat


def combine(threat: float, weather: float, service: float) -> RiskBreakdown:
    t, w, s = (min(1.0, max(0.0, x)) for x in (threat, weather, service))
    return RiskBreakdown(
        threat=round(t, 4), weather=round(w, 4), service=round(s, 4),
        total=round(1 - (1 - t) * (1 - w) * (1 - s), 4),
    )


def threat_exposure(ctx: PlanningContext, profile: RouteProfile, takeoff_min: int) -> float:
    """Time-weighted exposure of a sortie taking off at `takeoff_min`."""
    times = takeoff_min + profile.offset
    exposure = 0.0
    for th in ctx.scenario.threats:
        inside = inside_threat(profile, th.id, th.center.lat, th.center.lon, th.radius_km)
        active = (times >= th.active_from_min) & (times <= th.active_to_min)
        minutes = float(profile.dt[inside & active].sum())
        exposure += th.severity * th.confidence * minutes / profile.total_min
    return min(1.0, exposure)


def weather_margin(rec: WeatherRecord, minima: WeatherMinima) -> float:
    """Smallest ratio of the forecast to the minimum (>= 1 means every minimum is met)."""
    ratios = [
        rec.visibility_km / minima.min_visibility_km if minima.min_visibility_km else 99.0,
        rec.ceiling_ft / minima.min_ceiling_ft if minima.min_ceiling_ft else 99.0,
        minima.max_wind_kmh / rec.wind_kmh if rec.wind_kmh else 99.0,
    ]
    return min(ratios)


def weather_risk(
    cfg: PlanningConfig, records: list[WeatherRecord], minima: WeatherMinima
) -> float:
    """Worst point of the sortie. Records below minima are rejected elsewhere (hard check)."""
    worst = 0.0
    for rec in records:
        margin = weather_margin(rec, minima)
        thin = float(np.clip(1.0 - (margin - 1.0) / cfg.weather_margin_span, 0.0, 1.0))
        worst = max(
            worst,
            cfg.weather_margin_weight * thin + cfg.weather_tstorm_weight * rec.thunderstorm_prob,
        )
    return min(1.0, worst)


def service_risk(
    cfg: PlanningConfig, aircraft: Aircraft, type_: AircraftType, status: AircraftStatus
) -> float:
    wear = min(1.0, aircraft.hours_since_maintenance / type_.flight_hours_between_maintenance)
    risk = cfg.base_service_risk + cfg.hours_service_risk * wear
    if status is AircraftStatus.DEGRADED:
        risk += cfg.degraded_service_risk
    return min(1.0, risk)
