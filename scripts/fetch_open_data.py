"""One-time fetch of the two open datasets the generator ships as small static files.

Run (needs network):  backend/.venv/Scripts/python scripts/fetch_open_data.py

Outputs (committed, so the generator stays offline and deterministic):
  backend/app/sim/data/sites.json          fictional base SITES with real terrain elevation
  backend/app/sim/data/india_airports.json real public civil airports (divert candidates)

Sources and licences (verified 2026-10-02, recorded in docs/DECISIONS.md):
  - Open-Meteo elevation API: data under CC BY 4.0; free for non-commercial use.
  - OurAirports airports.csv: public domain ("released to the Public Domain, no guarantee").

The SITES below are arbitrary points inside the INDIA_CONTEXT region boxes. They are NOT real
installations; every base built on them is a fictional codename.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path
from urllib.request import urlopen

OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "sim" / "data"
FETCHED_ON = date.today().isoformat()

# region -> (code prefix, [(lat, lon), ...]); boxes from docs/INDIA_CONTEXT.md §2
SITES: dict[str, tuple[str, list[tuple[float, float]]]] = {
    "north": ("N", [(33.6, 76.4), (32.4, 77.2), (31.2, 76.1), (30.6, 75.2),
                    (34.1, 74.4), (32.9, 75.6), (33.1, 78.1), (31.9, 78.4)]),
    "west": ("W", [(26.1, 70.9), (27.6, 72.3), (25.3, 71.8), (28.4, 73.5),
                   (24.8, 73.2), (26.9, 74.1), (27.9, 70.4), (28.9, 74.7)]),
    "central": ("C", [(21.2, 79.6), (22.6, 77.9), (19.7, 78.8), (20.4, 76.2),
                      (23.3, 80.4), (18.9, 80.7), (21.9, 81.5), (19.1, 76.7)]),
    "east_ne": ("NE", [(26.3, 92.6), (25.6, 93.6), (27.6, 88.7), (26.7, 89.9),
                       (24.9, 91.9), (27.9, 93.8), (26.0, 95.1), (27.2, 94.6)]),
    "south": ("S", [(12.1, 76.9), (13.6, 79.2), (10.6, 77.4), (9.4, 78.4),
                    (11.2, 75.9), (14.4, 77.3), (8.6, 76.9), (10.6, 72.6)]),
}


def climate_zone(region: str, elevation_m: float) -> str:
    if region == "north":
        return "himalayan_high_altitude" if elevation_m >= 1500 else "indo_gangetic_plain"
    if region == "west":
        return "arid_desert"
    if region == "central":
        return "tropical_plateau"
    if region == "east_ne":
        return "humid_hill_ne"
    return "tropical_coastal" if elevation_m < 100 else "tropical_plateau"


def fetch_elevations(points: list[tuple[float, float]]) -> list[float]:
    lats = ",".join(str(p[0]) for p in points)
    lons = ",".join(str(p[1]) for p in points)
    url = f"https://api.open-meteo.com/v1/elevation?latitude={lats}&longitude={lons}"
    with urlopen(url, timeout=60) as r:  # noqa: S310 (fixed https URL)
        return json.load(r)["elevation"]


def build_sites() -> None:
    sites = []
    for region, (prefix, points) in SITES.items():
        elevations = fetch_elevations(points)
        for i, ((lat, lon), elev) in enumerate(zip(points, elevations, strict=True), start=1):
            sites.append({
                "code": f"BASE-{prefix}{i}", "region": region, "lat": lat, "lon": lon,
                "elevation_m": round(float(elev), 1),
                "climate_zone": climate_zone(region, float(elev)),
            })
    doc = {
        "note": "Fictional base SITES (arbitrary points in the INDIA_CONTEXT region boxes). "
                "Elevation: Open-Meteo elevation API (CC BY 4.0), https://open-meteo.com/",
        "fetched_on": FETCHED_ON,
        "sites": sites,
    }
    (OUT / "sites.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("sites:", len(sites))


def build_airports() -> None:
    url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    with urlopen(url, timeout=120) as r:  # noqa: S310
        text = r.read().decode("utf-8")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        if row["iso_country"] != "IN" or row["scheduled_service"] != "yes":
            continue
        if row["type"] not in ("large_airport", "medium_airport", "small_airport"):
            continue
        if not row["elevation_ft"]:
            continue
        rows.append({
            "id": row["ident"], "name": row["name"], "iata": row["iata_code"] or None,
            "type": row["type"], "lat": round(float(row["latitude_deg"]), 4),
            "lon": round(float(row["longitude_deg"]), 4),
            "elevation_m": round(float(row["elevation_ft"]) * 0.3048, 1),
        })
    rows.sort(key=lambda a: a["id"])
    doc = {
        "note": "Public civil airports with scheduled service (divert candidates). "
                "Source: OurAirports, public domain, https://ourairports.com/data/",
        "fetched_on": FETCHED_ON,
        "airports": rows,
    }
    (OUT / "india_airports.json").write_text(
        json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("airports:", len(rows))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build_sites()
    build_airports()
