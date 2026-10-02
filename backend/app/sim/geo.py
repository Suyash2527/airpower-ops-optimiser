"""Small spherical-geometry helpers for the generator (haversine; no pyproj needed here).

Planning-time geodesics use pyproj in Phase 3; the generator only needs ~0.5% accuracy.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEG = 111.195


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def destination_point(
    lat: float, lon: float, bearing_deg: float, distance_km: float
) -> tuple[float, float]:
    """Point reached from (lat, lon) travelling `distance_km` on an initial bearing."""
    delta = distance_km / EARTH_RADIUS_KM
    theta = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(
        math.sin(p1) * math.cos(delta) + math.cos(p1) * math.sin(delta) * math.cos(theta)
    )
    l2 = l1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(p1),
        math.cos(delta) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def offset_km(lat: float, lon: float, east_km: float, north_km: float) -> tuple[float, float]:
    """Local equirectangular offset (fine at the scales used for zone shapes)."""
    return (
        lat + north_km / KM_PER_DEG,
        lon + east_km / (KM_PER_DEG * math.cos(math.radians(lat))),
    )


def strip_polygon(
    lat1: float, lon1: float, lat2: float, lon2: float, width_km: float
) -> list[list[float]]:
    """Closed rectangular ring [[lon, lat], ...] of `width_km` centred on a segment."""
    mid_lat = (lat1 + lat2) / 2
    dx = (lon2 - lon1) * KM_PER_DEG * math.cos(math.radians(mid_lat))
    dy = (lat2 - lat1) * KM_PER_DEG
    length = math.hypot(dx, dy) or 1.0
    px, py = -dy / length * width_km / 2, dx / length * width_km / 2
    corners = []
    for lat, lon, sign in ((lat1, lon1, 1), (lat2, lon2, 1), (lat2, lon2, -1), (lat1, lon1, -1)):
        la, lo = offset_km(lat, lon, sign * px, sign * py)
        corners.append([round(lo, 4), round(la, 4)])
    corners.append(corners[0])
    return corners


def point_in_circle(
    lat: float, lon: float, c_lat: float, c_lon: float, radius_km: float
) -> bool:
    return haversine_km(lat, lon, c_lat, c_lon) <= radius_km
