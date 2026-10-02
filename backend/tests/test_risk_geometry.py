"""Risk formulas (Task 3.11) and the route geometry they rest on."""

from __future__ import annotations

import math

import numpy as np
import pytest
from planning_world import BASE_LAT, BASE_LON, aircraft, ftr, weather

from app.models.entities import WeatherMinima
from app.models.enums import AircraftStatus
from app.planning import risk
from app.planning.config import PlanningConfig
from app.planning.geometry import build_profile, great_circle, transit_minutes
from app.sim.geo import haversine_km

CFG = PlanningConfig()


def test_combine_is_one_minus_product_of_survivals() -> None:
    r = risk.combine(0.1, 0.2, 0.3)
    assert r.total == pytest.approx(1 - 0.9 * 0.8 * 0.7)  # 0.496
    assert risk.combine(0, 0, 0).total == 0 and risk.combine(1, 0, 0).total == 1


def test_combine_clips_inputs_and_keeps_components() -> None:
    r = risk.combine(1.5, -0.2, 0.0)
    assert (r.threat, r.weather, r.service, r.total) == (1.0, 0.0, 0.0, 1.0)


def test_service_risk_grows_with_wear_and_status() -> None:
    t = ftr()  # maintenance limit 100 h
    fresh = risk.service_risk(CFG, aircraft(hours_since_maintenance=0), t, AircraftStatus.SERVICEABLE)
    worn = risk.service_risk(CFG, aircraft(hours_since_maintenance=100), t, AircraftStatus.SERVICEABLE)
    degraded = risk.service_risk(CFG, aircraft(hours_since_maintenance=0), t, AircraftStatus.DEGRADED)
    assert fresh == pytest.approx(0.02) and worn == pytest.approx(0.10)
    assert degraded == pytest.approx(0.02 + 0.15)


def test_weather_margin_and_risk() -> None:
    minima = WeatherMinima(min_visibility_km=2.0, min_ceiling_ft=500, max_wind_kmh=60)
    clear = weather(visibility_km=10, ceiling_ft=8000, wind_kmh=10)[0]
    assert risk.weather_margin(clear, minima) == pytest.approx(min(5.0, 16.0, 6.0))
    assert risk.weather_risk(CFG, [clear], minima) == 0.0
    marginal = weather(visibility_km=2.0, ceiling_ft=8000, wind_kmh=10)[0]  # margin exactly 1
    assert risk.weather_risk(CFG, [marginal], minima) == pytest.approx(0.3)
    stormy = weather(visibility_km=10, thunderstorm_prob=0.5)[0]
    assert risk.weather_risk(CFG, [stormy], minima) == pytest.approx(0.3 * 0.5)
    assert risk.weather_risk(CFG, [clear, marginal], minima) == pytest.approx(0.3)  # worst point
    assert risk.weather_risk(CFG, [], minima) == 0.0


def test_transit_minutes_rounds_up() -> None:
    assert transit_minutes(100, 600) == 10
    assert transit_minutes(100.1, 600) == 11


def test_great_circle_endpoints_midpoint_and_equal_spacing() -> None:
    lat, lon = great_circle(10.0, 70.0, 20.0, 80.0, np.array([0.0, 0.5, 1.0]))
    assert (lat[0], lon[0]) == pytest.approx((10.0, 70.0), abs=1e-9)
    assert (lat[2], lon[2]) == pytest.approx((20.0, 80.0), abs=1e-9)
    total = haversine_km(10, 70, 20, 80)
    assert haversine_km(10, 70, lat[1], lon[1]) == pytest.approx(total / 2, rel=1e-6)


def test_great_circle_degenerate_same_point() -> None:
    lat, lon = great_circle(10.0, 70.0, 10.0, 70.0, np.array([0.25, 0.75]))
    assert list(lat) == [10.0, 10.0] and list(lon) == [70.0, 70.0]


def test_profile_time_shares_add_up_to_the_sortie_and_offsets_are_ordered() -> None:
    p = build_profile((BASE_LAT, BASE_LON), (BASE_LAT + 1.5, BASE_LON), 800, 60, 10.0, 15)
    assert p.transit_min == 13 and p.land_offset == 86 and p.total_min == 86
    assert p.dt.sum() == pytest.approx(86.0)
    assert np.all(np.diff(p.offset) >= 0) and p.offset[0] > 0 and p.offset[-1] < 86
    on_station = (p.offset > 13) & (p.offset < 73)
    assert p.dt[on_station].sum() == pytest.approx(60.0)
    # on-station samples sit at the AOI, others on the way
    assert np.allclose(p.lat[on_station], BASE_LAT + 1.5)
    assert math.isclose(p.dist_km, haversine_km(BASE_LAT, BASE_LON, BASE_LAT + 1.5, BASE_LON))


def test_profile_samples_are_at_most_the_step_apart() -> None:
    p = build_profile((10.0, 70.0), (15.0, 75.0), 800, 30, 10.0, 15)
    out = p.lat[: int(np.argmax(p.offset > p.transit_min))]
    lon = p.lon[: len(out)]
    gaps = [haversine_km(out[i], lon[i], out[i + 1], lon[i + 1]) for i in range(len(out) - 1)]
    assert max(gaps) <= 10.0 + 1e-6
