"""Regenerate the seasonal preset scenarios in scenarios/ (INDIA_CONTEXT §3.8).

Run from the repo root:  backend/.venv/Scripts/python scripts/generate_presets.py
Each file is fully determined by the params below; the seed is also stored in the file.
demo.json is produced separately by the documented CLI:
    cd backend && python -m app.sim.generate --seed 42 --out ../scenarios/demo.json
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.enums import Region, SeasonPreset  # noqa: E402
from app.models.scenario import GeneratorParams  # noqa: E402
from app.sim.generate import generate_scenario  # noqa: E402
from app.sim.scenario_io import save_scenario  # noqa: E402

PRESETS: dict[str, GeneratorParams] = {
    "monsoon_flood_hadr": GeneratorParams(
        seed=101, season_preset=SeasonPreset.MONSOON, weather_severity=0.5,
        regions=[Region.CENTRAL, Region.EAST_NE, Region.SOUTH],
    ),
    "winter_fog_north": GeneratorParams(
        seed=202, season_preset=SeasonPreset.WINTER_FOG_NORTH, weather_severity=0.4,
        regions=[Region.NORTH, Region.WEST, Region.CENTRAL],
    ),
    "cyclone_east_coast": GeneratorParams(
        seed=303, season_preset=SeasonPreset.POST_MONSOON_CYCLONE, weather_severity=0.6,
        regions=[Region.SOUTH, Region.EAST_NE, Region.CENTRAL],
    ),
    "pre_monsoon_heat_dust": GeneratorParams(
        seed=404, season_preset=SeasonPreset.PRE_MONSOON_HEAT_DUST, weather_severity=0.4,
        regions=[Region.WEST, Region.CENTRAL, Region.NORTH],
    ),
}

if __name__ == "__main__":
    for name, params in PRESETS.items():
        digest = save_scenario(generate_scenario(params), ROOT / "scenarios" / f"{name}.json")
        print(f"{name}.json seed={params.seed} sha256={digest[:16]}")
