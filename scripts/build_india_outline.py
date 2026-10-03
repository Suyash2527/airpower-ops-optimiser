"""Build the small map outline used by the web map (frontend/public/geo/india_region.geojson).

Source: Natural Earth 1:10m "Admin 0 - Countries, India point of view"
(ne_10m_admin_0_countries_ind.geojson, public domain, naturalearthdata.com; GitHub
nvkelso/natural-earth-vector). This POV variant draws boundaries as India claims them.
See docs/DECISIONS.md D-64. Boundaries are not authoritative.

Usage: python scripts/build_india_outline.py <path to ne_10m_admin_0_countries_ind.geojson>
Needs shapely (installed with the backend).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import box, mapping, shape

BBOX = box(55.0, -2.0, 120.0, 42.0)  # India plus room for synthetic objects offshore
TOLERANCE_DEG = 0.03  # ~3 km; plenty for a theatre-scale view
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "geo" / "india_region.geojson"


def _round(coords, nd=3):
    if isinstance(coords[0], (int, float)):
        return [round(c, nd) for c in coords]
    return [_round(c, nd) for c in coords]


def main(src: str) -> None:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    features = []
    for f in data["features"]:
        geom = shape(f["geometry"])
        if not geom.intersects(BBOX):
            continue
        clipped = geom.intersection(BBOX).simplify(TOLERANCE_DEG, preserve_topology=True)
        if clipped.is_empty:
            continue
        g = mapping(clipped)
        features.append(
            {
                "type": "Feature",
                "properties": {"name": f["properties"]["NAME"], "iso": f["properties"]["ADM0_A3"]},
                "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"])},
            }
        )
    out = {
        "type": "FeatureCollection",
        "source": "Natural Earth 1:10m Admin 0 Countries, India point of view (public domain), simplified",
        "features": features,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{len(features)} features -> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
