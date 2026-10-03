"""Parameters of the saved scenarios in scenarios/ (INDIA_CONTEXT §3.8).

Each saved file is fully determined by these params (tests/test_saved_scenarios.py checks it
byte for byte), so the API can rebuild a preset when the scenarios/ folder is not deployed
next to the backend, for example on Vercel where only backend/ is shipped (D-66).
"""

from __future__ import annotations

from functools import cache

from app.models.enums import Region, SeasonPreset
from app.models.scenario import GeneratorParams, ScenarioFile

PRESETS: dict[str, GeneratorParams] = {
    "demo": GeneratorParams(seed=42),
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
        regions=[Region.SOUTH, Region.EAST_COAST, Region.CENTRAL],
    ),
    "pre_monsoon_heat_dust": GeneratorParams(
        seed=404, season_preset=SeasonPreset.PRE_MONSOON_HEAT_DUST, weather_severity=0.4,
        regions=[Region.WEST, Region.CENTRAL, Region.NORTH],
    ),
}


@cache
def preset_by_id() -> dict[str, ScenarioFile]:
    """Scenario id -> rebuilt preset. Ids are content hashes, so they never change (D-70)."""
    from app.models.store import scenario_id_for  # local import: store must not import sim at load
    from app.sim.generate import generate_scenario

    built = [generate_scenario(p) for p in PRESETS.values()]
    return {scenario_id_for(s): s for s in built}
