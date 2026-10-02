# DATA_MODEL

All entities carry the **provenance block**:

```python
class Provenance(BaseModel):
    source: str            # "SYNTHETIC" | "OPEN_METEO" | "FILE:<name>" ...
    observed_at: datetime  # when the source says it was true
    ingested_at: datetime
    confidence: float      # 0..1
    data_label: Literal["synthetic", "open", "external"]
```

Time inside planning = integer **minutes from scenario t0** (`t0` is stored on the `Scenario`).
Units: km, ft, km/h, kg, minutes.

> All numeric values in the generator are **illustrative placeholders** (see `HONESTY.md`).

## 1. Entities

### Scenario
`id, name, seed, t0 (UTC), horizon_min, data_label`

### Base
`id, name (fictional), lat, lon, runways: int, turnaround_min_by_type: dict[type_id,int], fuel_stock_kg, weather_station_id`

### AircraftType
`id (e.g. "FTR-A"), role: set[Capability], cruise_kmh, max_range_km, combat_radius_km, endurance_min, min_crew, crew_roles: list[Role], hardpoints: int, compatible_loadouts: list[LoadoutId], turnaround_min, flight_hours_between_maintenance`

`Capability` enum (abstract mission categories): `AIR_DEFENCE_PATROL, STRIKE_SUPPORT_SORTIE, RECONNAISSANCE, AIRLIFT, SEARCH_AND_RESCUE, AERIAL_REFUELLING, ESCORT`. These are logistics-level categories; we model *who can do what*, not how.

### Aircraft
`id, tail (synthetic code e.g. "A-017"), type_id, base_id, status: {SERVICEABLE, DEGRADED, UNSERVICEABLE, IN_MAINTENANCE}, available_from_min, hours_since_maintenance, fuel_state_pct, current_loadout_id | null, provenance`

### Role / Qualification / CrewMember
`Role: PILOT, WSO, LOADMASTER, SENSOR_OP, ...`
`CrewMember: id, name (synthetic code), role, qualifications: set[type_id or Capability], base_id, status: {AVAILABLE, ON_REST, SICK, ON_DUTY}, duty_minutes_last_24h, last_duty_end_min, provenance`
Crew duty rules (configurable, defaults illustrative): max duty minutes per rolling 24 h, min rest between duties.

### Loadout and WeaponStock (resource attributes only)
`Loadout: id, name, category (e.g. "AIR_TO_AIR", "AIR_TO_GROUND", "RECCE_POD", "CARGO", "FUEL_TANKS"), items: dict[item_type, qty], mass_kg, compatible_aircraft_types`
`WeaponStock: base_id, item_type, qty_available, provenance`
Consumption: assigning a loadout reserves its items from the base stock for that sortie.

### Mission
`id, name, capability_required, priority: int (1 = highest .. 5), weight: float (derived from priority, configurable), window_start_min, window_end_min, duration_min (on-station), aoi: GeoPoint+radius_km, aircraft_required: int, loadout_category_required | null, min_crew_roles, max_acceptable_risk: float, status: {PENDING, PLANNED, ACTIVE, DONE, CANCELLED}, provenance`

### Threat (abstract threat zone)
`id, type: str (generic: "GROUND_THREAT_ZONE", "AIR_THREAT_ZONE"), center, radius_km, severity 0..1, active_from_min, active_to_min, confidence, provenance`

### AirspaceZone
`id, kind: {RESTRICTED, DANGER, CORRIDOR, NO_FLY}, polygon (GeoJSON), floor_ft, ceiling_ft, active_from_min, active_to_min, provenance`

### WeatherObservation / WeatherForecast
`location (base_id or lat/lon), time_min, visibility_km, ceiling_ft, wind_kmh, wind_dir_deg, precip_mm_h, thunderstorm_prob, provenance`
`WeatherMinima` per aircraft type and per mission capability: min visibility, min ceiling, max crosswind/wind.

### Event
`id, type, time_min, payload (typed per event), source, created_by: {sim, user, adapter}`
Types: `AIRCRAFT_UNSERVICEABLE{aircraft_id,until_min|null}, CREW_UNAVAILABLE{crew_id,until_min}, WEATHER_CHANGE{base_id|region,new_forecast_ref}, NEW_THREAT{threat}, THREAT_UPDATE{threat_id,...}, AIRSPACE_CHANGE{zone}, PRIORITY_CHANGE{mission_id,new_priority}, NEW_MISSION{mission}, MISSION_CANCELLED{mission_id}`

### Plan
`id, scenario_id, version, parent_plan_id | null, status: {draft, proposed, approved, superseded}, created_at, created_by, assignments: list[Assignment], unassigned: list[UnassignedMission], kpis: PlanKPIs, solver: {name, status, wall_ms, objective, gap}, data_label`

### Assignment (one sortie)
`id, mission_id, aircraft_id, crew_ids: list[str], loadout_id, takeoff_min, land_min, base_from, base_to, route: list[GeoPoint], risk: RiskBreakdown, frozen: bool, reasons: list[ReasonCode], explanation: str`

### UnassignedMission
`mission_id, blocking_reasons: list[{code, count, example}], explanation`

### Proposal (retasking)
`id, event_id, base_plan_id, rank, plan: Plan, diff: PlanDiff, score_breakdown, explanation, status: {open, approved, rejected, expired}`
`PlanDiff: added[], removed[], changed[{assignment_id, field, from, to}], n_changes, coverage_delta, risk_delta`

### AuditEntry
`id, ts, actor, action, object_type, object_id, details_json` — append-only.

### PlanKPIs
`priority_weighted_coverage (0..1), missions_covered/total, by_priority: dict, aircraft_utilisation, crew_utilisation, mean_risk, max_risk, total_flight_minutes, changes_vs_parent`

## 2. Reason codes (enum `ReasonCode`)

Feasibility: `NO_CAPABLE_AIRCRAFT, OUT_OF_RANGE, INSUFFICIENT_FUEL_ENDURANCE, LOADOUT_INCOMPATIBLE, NO_LOADOUT_STOCK, NO_QUALIFIED_CREW, CREW_DUTY_LIMIT, CREW_REST_VIOLATION, AIRCRAFT_UNSERVICEABLE, MAINTENANCE_DUE, AIRSPACE_CONFLICT, WEATHER_BELOW_MINIMA_BASE, WEATHER_BELOW_MINIMA_TARGET, THREAT_RISK_EXCEEDS_LIMIT, TIME_WINDOW_UNREACHABLE, TURNAROUND_CONFLICT, BASE_RUNWAY_CAPACITY`
Planning outcomes: `ASSIGNED_BEST_SCORE, DROPPED_LOWER_PRIORITY, PRESERVED_EXISTING, CHANGED_DUE_TO_EVENT, FROZEN_AIRBORNE`

## 3. Persistence

Tables for every entity above via SQLModel; JSON columns for polygons/payloads. Snapshots are rebuilt from tables at call time. Keep a `state_version` counter incremented on every fusion write for cache keys.

## 4. Scenario file format (`scenarios/*.json`)

```json
{
  "scenario": {"name": "...", "seed": 42, "t0": "2026-01-01T00:00:00Z", "horizon_min": 1440, "data_label": "synthetic"},
  "bases": [], "aircraft_types": [], "aircraft": [], "crew": [], "loadouts": [], "weapon_stocks": [],
  "missions": [], "threats": [], "airspace": [], "weather": [], "maintenance_history": [], "events": []
}
```

## 5. Synthetic generator spec (`sim/generate.py`)

Parameters: `seed, n_bases=3, n_aircraft=40, n_crew=60, n_missions=50, horizon_min=1440, threat_density, weather_severity, disruption_rate`.
Rules:
- Bases: fictional names, placed within a bounding box on a neutral map region; 2–3 bases, 1–3 runways.
- Aircraft: type mix e.g. 45% FTR-A, 20% TPT-B, 15% HEL-C, 10% ISR-D, 10% TKR-E; ~80–90% serviceable at t0 (parameter), rest degraded/maintenance.
- Crew: roles matched to types; ~75% available; random duty history within limits.
- Missions: priority distribution skewed to 3–4; windows spread over horizon; AOIs within range of at least one base (ensure some are intentionally hard/infeasible so the optimiser has to choose).
- Threat zones: 3–8 circles with severity and time windows.
- Maintenance history: for each aircraft, a history of flight-hours and failure events drawn from a **documented hazard function** (e.g. Weibull with shape>1 + extra hazard for hours since maintenance). This is the ground truth the serviceability model learns — it is synthetic by construction.
- Everything reproducible from `seed`.
