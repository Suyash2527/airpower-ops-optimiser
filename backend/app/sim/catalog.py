"""Static catalogue for the generator: ALL NUMBERS ARE ILLUSTRATIVE PLACEHOLDERS (HONESTY.md).

Aircraft types are generic (FTR-A, TPT-B, HEL-C, ISR-D, TKR-E). Season/weather parameters are
configuration placeholders, not climatological statistics (INDIA_CONTEXT §3.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.enums import (
    Capability,
    ClimateZone,
    LoadoutCategory,
    Region,
    Role,
    SeasonPreset,
)

C = Capability
R = Role

RESERVE_FRACTION = 0.2  # fuel/endurance reserve (ALGORITHMS §2.3, configurable placeholder)
AOI_DISTANCE_CAP_KM = 700.0  # keeps generated AOIs near the bases
MAX_BASE_ELEVATION_M = 4500.0  # no real airfield is higher; sites above are not eligible
MIN_BASE_SEPARATION_KM = 150.0
AIRCRAFT_MIX: dict[str, float] = {
    "FTR-A": 0.45, "TPT-B": 0.20, "HEL-C": 0.15, "ISR-D": 0.10, "TKR-E": 0.10,
}
PRIORITY_WEIGHT: dict[int, float] = {1: 100.0, 2: 60.0, 3: 35.0, 4: 20.0, 5: 10.0}


@dataclass(frozen=True)
class TypeSpec:
    id: str
    capabilities: tuple[Capability, ...]
    cruise_kmh: float
    max_range_km: float
    combat_radius_km: float
    endurance_min: int
    crew_roles: tuple[Role, ...]
    hardpoints: int
    loadouts: tuple[str, ...]
    turnaround_min: int
    maint_interval_h: float
    min_visibility_km: float
    min_ceiling_ft: float
    max_wind_kmh: float


TYPES: tuple[TypeSpec, ...] = (
    TypeSpec("FTR-A", (C.AIR_DEFENCE_PATROL, C.STRIKE_SUPPORT_SORTIE, C.ESCORT), 850, 2400, 800,
             180, (R.PILOT,), 6, ("L-AA", "L-AG", "L-RECCE"), 60, 100, 1.5, 500, 60),
    TypeSpec("TPT-B", (C.AIRLIFT, C.HADR), 550, 4000, 1800, 480, (R.PILOT, R.LOADMASTER), 0,
             ("L-CARGO-L", "L-CARGO-H"), 90, 150, 2.0, 600, 55),
    TypeSpec("HEL-C", (C.SEARCH_AND_RESCUE, C.AIRLIFT, C.HADR), 230, 600, 250, 200,
             (R.PILOT, R.LOADMASTER), 0, ("L-CARGO-L",), 45, 80, 1.0, 300, 50),
    TypeSpec("ISR-D", (C.RECONNAISSANCE,), 600, 3000, 1200, 360, (R.PILOT, R.SENSOR_OP), 0,
             ("L-RECCE",), 75, 120, 2.0, 700, 55),
    TypeSpec("TKR-E", (C.AERIAL_REFUELLING,), 800, 3500, 1500, 420, (R.PILOT, R.LOADMASTER), 0,
             ("L-FUEL",), 90, 150, 3.0, 800, 55),
)
TYPE_BY_ID = {t.id: t for t in TYPES}


@dataclass(frozen=True)
class LoadoutSpec:
    id: str
    name: str
    category: LoadoutCategory
    items: dict[str, int]
    mass_kg: float
    compatible: tuple[str, ...]


# Resource attributes only: item type, count, mass, compatibility.
LOADOUTS: tuple[LoadoutSpec, ...] = (
    LoadoutSpec("L-AA", "Air-to-air configuration", LoadoutCategory.AIR_TO_AIR,
                {"AA_STORE_T1": 4}, 800, ("FTR-A",)),
    LoadoutSpec("L-AG", "Air-to-ground configuration", LoadoutCategory.AIR_TO_GROUND,
                {"AG_STORE_T1": 4}, 1600, ("FTR-A",)),
    LoadoutSpec("L-RECCE", "Reconnaissance pod", LoadoutCategory.RECCE_POD,
                {"RECCE_POD_T1": 1}, 300, ("FTR-A", "ISR-D")),
    LoadoutSpec("L-CARGO-L", "Light cargo (2 pallets)", LoadoutCategory.CARGO,
                {"CARGO_PALLET": 2}, 1500, ("HEL-C", "TPT-B")),
    LoadoutSpec("L-CARGO-H", "Heavy cargo (6 pallets)", LoadoutCategory.CARGO,
                {"CARGO_PALLET": 6}, 6000, ("TPT-B",)),
    LoadoutSpec("L-FUEL", "Tanker fuel tanks", LoadoutCategory.FUEL_TANKS,
                {"FUEL_TANK_T1": 2}, 2400, ("TKR-E",)),
)
LOADOUT_BY_ID = {item.id: item for item in LOADOUTS}

STOCK_RANGES: dict[str, tuple[int, int]] = {
    "AA_STORE_T1": (30, 90), "AG_STORE_T1": (30, 90), "RECCE_POD_T1": (4, 10),
    "CARGO_PALLET": (40, 120), "FUEL_TANK_T1": (10, 30),
}


@dataclass(frozen=True)
class MissionProfile:
    duration: tuple[int, int]
    aircraft_required: tuple[tuple[int, float], ...]  # (count, probability)
    crew_roles: tuple[Role, ...]
    loadout_category: LoadoutCategory | None


PROFILES: dict[Capability, MissionProfile] = {
    C.AIR_DEFENCE_PATROL: MissionProfile((60, 90), ((1, 0.8), (2, 0.2)), (R.PILOT,),
                                         LoadoutCategory.AIR_TO_AIR),
    C.STRIKE_SUPPORT_SORTIE: MissionProfile((30, 60), ((1, 0.7), (2, 0.3)), (R.PILOT,),
                                            LoadoutCategory.AIR_TO_GROUND),
    C.RECONNAISSANCE: MissionProfile((30, 60), ((1, 1.0),), (R.PILOT, R.SENSOR_OP),
                                     LoadoutCategory.RECCE_POD),
    C.AIRLIFT: MissionProfile((20, 40), ((1, 0.85), (2, 0.15)), (R.PILOT, R.LOADMASTER),
                              LoadoutCategory.CARGO),
    C.SEARCH_AND_RESCUE: MissionProfile((40, 90), ((1, 1.0),), (R.PILOT, R.LOADMASTER), None),
    C.AERIAL_REFUELLING: MissionProfile((40, 60), ((1, 1.0),), (R.PILOT, R.LOADMASTER),
                                        LoadoutCategory.FUEL_TANKS),
    C.ESCORT: MissionProfile((45, 90), ((1, 0.8), (2, 0.2)), (R.PILOT,),
                             LoadoutCategory.AIR_TO_AIR),
    C.HADR: MissionProfile((30, 60), ((1, 0.7), (2, 0.3)), (R.PILOT, R.LOADMASTER),
                           LoadoutCategory.CARGO),
}
CAPABILITY_LABEL: dict[Capability, str] = {
    C.AIR_DEFENCE_PATROL: "Air defence patrol", C.STRIKE_SUPPORT_SORTIE: "Strike support",
    C.RECONNAISSANCE: "Reconnaissance", C.AIRLIFT: "Airlift", C.SEARCH_AND_RESCUE: "SAR",
    C.AERIAL_REFUELLING: "Refuelling", C.ESCORT: "Escort", C.HADR: "HADR relief",
}

# Per-capability priority distributions (priority -> weight). Default skews to 3-4.
DEFAULT_PRIORITY_WEIGHTS = {1: 0.08, 2: 0.17, 3: 0.32, 4: 0.28, 5: 0.15}
PRIORITY_WEIGHTS: dict[Capability, dict[int, float]] = {
    C.HADR: {1: 0.40, 2: 0.40, 3: 0.20},
    C.SEARCH_AND_RESCUE: {1: 0.20, 2: 0.40, 3: 0.40},
}

# --- Regions (INDIA_CONTEXT §2): (lat_min, lat_max, lon_min, lon_max) ---
REGION_BOXES: dict[Region, tuple[float, float, float, float]] = {
    Region.NORTH: (30.0, 35.0, 74.0, 79.0),
    Region.WEST: (24.0, 29.0, 69.0, 75.0),
    Region.CENTRAL: (18.0, 24.0, 75.0, 82.0),
    Region.EAST_NE: (24.0, 28.0, 88.0, 96.0),
    Region.SOUTH: (8.0, 15.0, 72.0, 80.0),
}
REGION_ORDER = [Region.NORTH, Region.WEST, Region.CENTRAL, Region.EAST_NE, Region.SOUTH]


@dataclass(frozen=True)
class SeasonProfile:
    t0: datetime  # notional; 02:30 UTC = 08:00 IST (decision D-26)
    default_regions: tuple[Region, ...]
    mean_badness: dict[ClimateZone, float]
    w_vis: float
    w_ceil: float
    w_wind: float
    w_precip: float
    w_tstorm: float
    base_wind_kmh: float
    fog_diurnal: float  # extra badness amplitude peaking ~06:00 IST
    sea_level_temp_c: dict[Region, float]
    mission_weights: dict[Capability, float]
    disaster_kinds: tuple[str, ...]


Z = ClimateZone


def _t0(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 2, 30, tzinfo=UTC)


SEASONS: dict[SeasonPreset, SeasonProfile] = {
    SeasonPreset.PRE_MONSOON_HEAT_DUST: SeasonProfile(
        t0=_t0(2027, 5, 15),
        default_regions=(Region.WEST, Region.CENTRAL, Region.NORTH),
        mean_badness={Z.HIMALAYAN_HIGH_ALTITUDE: 0.15, Z.INDO_GANGETIC_PLAIN: 0.25,
                      Z.ARID_DESERT: 0.50, Z.TROPICAL_PLATEAU: 0.30, Z.HUMID_HILL_NE: 0.25,
                      Z.TROPICAL_COASTAL: 0.25},
        w_vis=1.0, w_ceil=0.3, w_wind=1.2, w_precip=0.3, w_tstorm=0.8, base_wind_kmh=15,
        fog_diurnal=0.0,
        sea_level_temp_c={Region.NORTH: 30, Region.WEST: 40, Region.CENTRAL: 38,
                          Region.EAST_NE: 32, Region.SOUTH: 33},
        mission_weights={C.AIR_DEFENCE_PATROL: .18, C.STRIKE_SUPPORT_SORTIE: .06,
                         C.RECONNAISSANCE: .18, C.AIRLIFT: .20, C.SEARCH_AND_RESCUE: .08,
                         C.AERIAL_REFUELLING: .10, C.ESCORT: .08, C.HADR: .12},
        disaster_kinds=("HEATWAVE", "WILDFIRE"),
    ),
    SeasonPreset.MONSOON: SeasonProfile(
        t0=_t0(2027, 7, 20),
        default_regions=(Region.CENTRAL, Region.EAST_NE, Region.SOUTH),
        mean_badness={Z.HIMALAYAN_HIGH_ALTITUDE: 0.35, Z.INDO_GANGETIC_PLAIN: 0.45,
                      Z.ARID_DESERT: 0.20, Z.TROPICAL_PLATEAU: 0.50, Z.HUMID_HILL_NE: 0.65,
                      Z.TROPICAL_COASTAL: 0.55},
        w_vis=0.6, w_ceil=1.1, w_wind=0.6, w_precip=1.2, w_tstorm=1.0, base_wind_kmh=12,
        fog_diurnal=0.0,
        sea_level_temp_c={Region.NORTH: 28, Region.WEST: 32, Region.CENTRAL: 29,
                          Region.EAST_NE: 29, Region.SOUTH: 29},
        mission_weights={C.AIR_DEFENCE_PATROL: .12, C.STRIKE_SUPPORT_SORTIE: .04,
                         C.RECONNAISSANCE: .10, C.AIRLIFT: .20, C.SEARCH_AND_RESCUE: .14,
                         C.AERIAL_REFUELLING: .06, C.ESCORT: .04, C.HADR: .30},
        disaster_kinds=("FLOOD", "LANDSLIDE"),
    ),
    SeasonPreset.POST_MONSOON_CYCLONE: SeasonProfile(
        t0=_t0(2026, 10, 28),
        default_regions=(Region.SOUTH, Region.EAST_NE, Region.CENTRAL),
        mean_badness={Z.HIMALAYAN_HIGH_ALTITUDE: 0.15, Z.INDO_GANGETIC_PLAIN: 0.15,
                      Z.ARID_DESERT: 0.10, Z.TROPICAL_PLATEAU: 0.25, Z.HUMID_HILL_NE: 0.40,
                      Z.TROPICAL_COASTAL: 0.55},
        w_vis=0.7, w_ceil=1.0, w_wind=1.5, w_precip=1.2, w_tstorm=0.7, base_wind_kmh=14,
        fog_diurnal=0.0,
        sea_level_temp_c={Region.NORTH: 24, Region.WEST: 31, Region.CENTRAL: 29,
                          Region.EAST_NE: 27, Region.SOUTH: 28},
        mission_weights={C.AIR_DEFENCE_PATROL: .12, C.STRIKE_SUPPORT_SORTIE: .04,
                         C.RECONNAISSANCE: .10, C.AIRLIFT: .18, C.SEARCH_AND_RESCUE: .16,
                         C.AERIAL_REFUELLING: .06, C.ESCORT: .04, C.HADR: .30},
        disaster_kinds=("CYCLONE", "FLOOD"),
    ),
    SeasonPreset.WINTER_FOG_NORTH: SeasonProfile(
        t0=_t0(2026, 12, 15),
        default_regions=(Region.NORTH, Region.WEST, Region.CENTRAL),
        mean_badness={Z.HIMALAYAN_HIGH_ALTITUDE: 0.45, Z.INDO_GANGETIC_PLAIN: 0.55,
                      Z.ARID_DESERT: 0.15, Z.TROPICAL_PLATEAU: 0.15, Z.HUMID_HILL_NE: 0.30,
                      Z.TROPICAL_COASTAL: 0.10},
        w_vis=1.2, w_ceil=0.8, w_wind=0.2, w_precip=0.1, w_tstorm=0.0, base_wind_kmh=6,
        fog_diurnal=0.35,
        sea_level_temp_c={Region.NORTH: 14, Region.WEST: 22, Region.CENTRAL: 22,
                          Region.EAST_NE: 20, Region.SOUTH: 27},
        mission_weights={C.AIR_DEFENCE_PATROL: .18, C.STRIKE_SUPPORT_SORTIE: .06,
                         C.RECONNAISSANCE: .16, C.AIRLIFT: .30, C.SEARCH_AND_RESCUE: .08,
                         C.AERIAL_REFUELLING: .08, C.ESCORT: .06, C.HADR: .08},
        disaster_kinds=("COLD_WAVE", "AVALANCHE"),
    ),
}

BASE_ITEM_TYPES = sorted(STOCK_RANGES)
