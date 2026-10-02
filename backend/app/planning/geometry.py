"""Route geometry for planning (decision D-35: haversine + shapely, no pyproj).

A sortie flies base -> AOI centre -> loiter -> AOI -> base along great circles. For the airspace
and threat tests the route is *sampled*: ~every `route_step_km` along each leg and every
`on_station_step_min` while loitering. Each sample carries its offset (minutes after takeoff) and
the time share `dt` it represents, so a zone is only counted while it is active at that moment.
Approximations (documented): spherical Earth (error well under 1%), zones tested at sample points
(zones narrower than the step can be missed), zone altitude bands ignored (conservative), the
AOI is its centre point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import shapely

from app.models.entities import AirspaceZone
from app.sim.geo import EARTH_RADIUS_KM, haversine_km


@dataclass
class RouteProfile:
    lat: np.ndarray
    lon: np.ndarray
    offset: np.ndarray  # minutes after takeoff
    dt: np.ndarray  # minutes of flight each sample stands for
    total_min: float
    dist_km: float
    transit_min: int
    duration_min: int
    _threat_inside: dict[str, np.ndarray] = field(default_factory=dict)
    _zone_inside: dict[str, np.ndarray] = field(default_factory=dict)
    _slot_cache: dict[tuple[str, int], object] = field(default_factory=dict)

    @property
    def land_offset(self) -> int:
        return 2 * self.transit_min + self.duration_min


def transit_minutes(dist_km: float, cruise_kmh: float) -> int:
    """Whole minutes, rounded up (the generator uses the same convention)."""
    return math.ceil(dist_km / cruise_kmh * 60)


def _unit(lat: np.ndarray | float, lon: np.ndarray | float) -> np.ndarray:
    phi, lam = np.radians(lat), np.radians(lon)
    return np.stack(
        [np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)], axis=-1
    )


def great_circle(
    lat1: float, lon1: float, lat2: float, lon2: float, fractions: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Points at the given fractions (0..1) of the great circle from point 1 to point 2."""
    a, b = _unit(lat1, lon1), _unit(lat2, lon2)
    omega = math.acos(max(-1.0, min(1.0, float(np.dot(a, b)))))
    if omega < 1e-9:
        same = np.ones_like(fractions, dtype=float)
        return same * lat1, same * lon1
    s = math.sin(omega)
    w1 = np.sin((1 - fractions) * omega) / s
    w2 = np.sin(fractions * omega) / s
    pts = w1[:, None] * a + w2[:, None] * b
    lat = np.degrees(np.arcsin(np.clip(pts[:, 2], -1, 1)))
    lon = np.degrees(np.arctan2(pts[:, 1], pts[:, 0]))
    return lat, lon


def haversine_vec(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> np.ndarray:
    p1, p2 = np.radians(lat), math.radians(lat0)
    dphi, dlmb = p2 - p1, math.radians(lon0) - np.radians(lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * math.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def build_profile(
    base: tuple[float, float], aoi: tuple[float, float], cruise_kmh: float, duration_min: int,
    step_km: float, on_station_step_min: int,
) -> RouteProfile:
    dist = haversine_km(base[0], base[1], aoi[0], aoi[1])
    transit = transit_minutes(dist, cruise_kmh)
    n = max(1, math.ceil(dist / step_km))
    frac = (np.arange(n) + 0.5) / n
    out_lat, out_lon = great_circle(base[0], base[1], aoi[0], aoi[1], frac)
    back_lat, back_lon = out_lat[::-1], out_lon[::-1]
    m = max(1, math.ceil(duration_min / on_station_step_min))
    loiter = (np.arange(m) + 0.5) / m
    lat = np.concatenate([out_lat, np.full(m, aoi[0]), back_lat])
    lon = np.concatenate([out_lon, np.full(m, aoi[1]), back_lon])
    offset = np.concatenate([
        transit * frac, transit + duration_min * loiter, transit + duration_min + transit * frac,
    ])
    dt = np.concatenate([
        np.full(n, transit / n), np.full(m, duration_min / m), np.full(n, transit / n),
    ])
    return RouteProfile(
        lat=lat, lon=lon, offset=offset, dt=dt, total_min=float(2 * transit + duration_min),
        dist_km=dist, transit_min=transit, duration_min=duration_min,
    )


def inside_threat(profile: RouteProfile, threat_id: str, lat: float, lon: float, radius_km: float):
    cached = profile._threat_inside.get(threat_id)
    if cached is None:
        cached = haversine_vec(profile.lat, profile.lon, lat, lon) <= radius_km
        profile._threat_inside[threat_id] = cached
    return cached


def inside_zone(profile: RouteProfile, zone: AirspaceZone) -> np.ndarray:
    cached = profile._zone_inside.get(zone.id)
    if cached is None:
        rings = zone.polygon.coordinates
        poly = shapely.Polygon(rings[0], holes=rings[1:] or None)
        cached = np.asarray(shapely.contains_xy(poly, profile.lon, profile.lat), dtype=bool)
        profile._zone_inside[zone.id] = cached
    return cached
