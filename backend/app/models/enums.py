"""Enumerations from docs/DATA_MODEL.md."""

from enum import StrEnum


class Capability(StrEnum):
    """Abstract mission categories: who can do what (logistics level only)."""

    AIR_DEFENCE_PATROL = "AIR_DEFENCE_PATROL"
    STRIKE_SUPPORT_SORTIE = "STRIKE_SUPPORT_SORTIE"
    RECONNAISSANCE = "RECONNAISSANCE"
    AIRLIFT = "AIRLIFT"
    SEARCH_AND_RESCUE = "SEARCH_AND_RESCUE"
    AERIAL_REFUELLING = "AERIAL_REFUELLING"
    ESCORT = "ESCORT"
    HADR = "HADR"  # humanitarian assistance and disaster relief (logistics-level)


class Role(StrEnum):
    PILOT = "PILOT"
    WSO = "WSO"
    LOADMASTER = "LOADMASTER"
    SENSOR_OP = "SENSOR_OP"


class AircraftStatus(StrEnum):
    SERVICEABLE = "SERVICEABLE"
    DEGRADED = "DEGRADED"
    UNSERVICEABLE = "UNSERVICEABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"


class CrewStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    ON_REST = "ON_REST"
    SICK = "SICK"
    ON_DUTY = "ON_DUTY"


class LoadoutCategory(StrEnum):
    AIR_TO_AIR = "AIR_TO_AIR"
    AIR_TO_GROUND = "AIR_TO_GROUND"
    RECCE_POD = "RECCE_POD"
    CARGO = "CARGO"
    FUEL_TANKS = "FUEL_TANKS"


class MissionStatus(StrEnum):
    PENDING = "PENDING"
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ThreatType(StrEnum):
    GROUND_THREAT_ZONE = "GROUND_THREAT_ZONE"
    AIR_THREAT_ZONE = "AIR_THREAT_ZONE"


class AirspaceKind(StrEnum):
    RESTRICTED = "RESTRICTED"
    DANGER = "DANGER"
    CORRIDOR = "CORRIDOR"
    NO_FLY = "NO_FLY"


class WeatherKind(StrEnum):
    OBSERVATION = "OBSERVATION"
    FORECAST = "FORECAST"


class EventType(StrEnum):
    AIRCRAFT_UNSERVICEABLE = "AIRCRAFT_UNSERVICEABLE"
    CREW_UNAVAILABLE = "CREW_UNAVAILABLE"
    WEATHER_CHANGE = "WEATHER_CHANGE"
    NEW_THREAT = "NEW_THREAT"
    THREAT_UPDATE = "THREAT_UPDATE"
    AIRSPACE_CHANGE = "AIRSPACE_CHANGE"
    PRIORITY_CHANGE = "PRIORITY_CHANGE"
    NEW_MISSION = "NEW_MISSION"
    MISSION_CANCELLED = "MISSION_CANCELLED"


class EventOrigin(StrEnum):
    SIM = "sim"
    USER = "user"
    ADAPTER = "adapter"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class ProposalStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ReasonCode(StrEnum):
    # Feasibility
    NO_CAPABLE_AIRCRAFT = "NO_CAPABLE_AIRCRAFT"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    INSUFFICIENT_FUEL_ENDURANCE = "INSUFFICIENT_FUEL_ENDURANCE"
    LOADOUT_INCOMPATIBLE = "LOADOUT_INCOMPATIBLE"
    NO_LOADOUT_STOCK = "NO_LOADOUT_STOCK"
    NO_QUALIFIED_CREW = "NO_QUALIFIED_CREW"
    CREW_DUTY_LIMIT = "CREW_DUTY_LIMIT"
    CREW_REST_VIOLATION = "CREW_REST_VIOLATION"
    AIRCRAFT_UNSERVICEABLE = "AIRCRAFT_UNSERVICEABLE"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    AIRSPACE_CONFLICT = "AIRSPACE_CONFLICT"
    WEATHER_BELOW_MINIMA_BASE = "WEATHER_BELOW_MINIMA_BASE"
    WEATHER_BELOW_MINIMA_TARGET = "WEATHER_BELOW_MINIMA_TARGET"
    THREAT_RISK_EXCEEDS_LIMIT = "THREAT_RISK_EXCEEDS_LIMIT"
    TIME_WINDOW_UNREACHABLE = "TIME_WINDOW_UNREACHABLE"
    TURNAROUND_CONFLICT = "TURNAROUND_CONFLICT"
    BASE_RUNWAY_CAPACITY = "BASE_RUNWAY_CAPACITY"
    # Planning outcomes
    ASSIGNED_BEST_SCORE = "ASSIGNED_BEST_SCORE"
    DROPPED_LOWER_PRIORITY = "DROPPED_LOWER_PRIORITY"
    PRESERVED_EXISTING = "PRESERVED_EXISTING"
    CHANGED_DUE_TO_EVENT = "CHANGED_DUE_TO_EVENT"
    FROZEN_AIRBORNE = "FROZEN_AIRBORNE"


class Region(StrEnum):
    """Operating regions from docs/INDIA_CONTEXT.md §2."""

    NORTH = "north"
    WEST = "west"
    CENTRAL = "central"
    EAST_NE = "east_ne"
    SOUTH = "south"


class ClimateZone(StrEnum):
    HIMALAYAN_HIGH_ALTITUDE = "himalayan_high_altitude"
    INDO_GANGETIC_PLAIN = "indo_gangetic_plain"
    ARID_DESERT = "arid_desert"
    TROPICAL_PLATEAU = "tropical_plateau"
    HUMID_HILL_NE = "humid_hill_ne"
    TROPICAL_COASTAL = "tropical_coastal"


class SeasonPreset(StrEnum):
    PRE_MONSOON_HEAT_DUST = "pre_monsoon_heat_dust"
    MONSOON = "monsoon"
    POST_MONSOON_CYCLONE = "post_monsoon_cyclone"
    WINTER_FOG_NORTH = "winter_fog_north"
