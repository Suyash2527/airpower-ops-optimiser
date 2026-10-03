// Plain-English labels for codes the API returns. Sentences paraphrase backend/app/planning/explain.py
// and docs/DECISIONS.md; they describe what the code means, never a measured result.

export const REASONS: Record<string, { label: string; sentence: string }> = {
  NO_CAPABLE_AIRCRAFT: { label: "No capable aircraft", sentence: "The fleet has fewer aircraft able to fly this mission type than the mission needs." },
  OUT_OF_RANGE: { label: "Out of range", sentence: "The mission area is beyond the aircraft's radius from its base, with the 20% fuel reserve kept." },
  INSUFFICIENT_FUEL_ENDURANCE: { label: "Not enough endurance", sentence: "Transit plus time on station is longer than the aircraft can stay airborne with its reserve." },
  LOADOUT_INCOMPATIBLE: { label: "Loadout incompatible", sentence: "No suitable loadout fits this aircraft, or it is too heavy for the base's density altitude." },
  NO_LOADOUT_STOCK: { label: "No loadout stock", sentence: "The base has no stock left of the loadout this mission needs." },
  NO_QUALIFIED_CREW: { label: "No qualified crew", sentence: "No available crew at the base is qualified on this aircraft type for every required seat." },
  CREW_DUTY_LIMIT: { label: "Crew duty limit", sentence: "Flying this sortie would take the crew past the 720-minute duty limit in a rolling 24 hours." },
  CREW_REST_VIOLATION: { label: "Crew rest", sentence: "The crew would not have had the 600-minute minimum rest before take-off." },
  AIRCRAFT_UNSERVICEABLE: { label: "Aircraft unavailable", sentence: "The aircraft is unserviceable or in maintenance, or not back in service before the window closes." },
  MAINTENANCE_DUE: { label: "Maintenance due", sentence: "The sortie would take the aircraft past its maintenance interval." },
  AIRSPACE_CONFLICT: { label: "Airspace conflict", sentence: "The route crosses an airspace restriction that is active at that time." },
  WEATHER_BELOW_MINIMA_BASE: { label: "Weather at base", sentence: "Forecast visibility, cloud ceiling or wind at the base is below the aircraft's minima." },
  WEATHER_BELOW_MINIMA_TARGET: { label: "Weather at target", sentence: "Forecast weather near the mission area is below the aircraft's minima." },
  THREAT_RISK_EXCEEDS_LIMIT: { label: "Threat risk too high", sentence: "Time-weighted exposure to active threat zones is above this mission's acceptable limit." },
  TIME_WINDOW_UNREACHABLE: { label: "Window unreachable", sentence: "No take-off slot lets the aircraft reach the area and stay for the full duration inside the window." },
  TURNAROUND_CONFLICT: { label: "Aircraft committed", sentence: "The aircraft is already flying, or turning around after another sortie, at that time." },
  BASE_RUNWAY_CAPACITY: { label: "Runway capacity", sentence: "The base's runways are full for that 15-minute slot (2 movements per runway, placeholder)." },
  ASSIGNED_BEST_SCORE: { label: "Best option", sentence: "This aircraft, crew and loadout gave the best objective score among the feasible options." },
  DROPPED_LOWER_PRIORITY: { label: "Dropped for priority", sentence: "Feasible on its own, but the resources it needed went to higher-priority missions." },
  PRESERVED_EXISTING: { label: "Kept from plan", sentence: "Unchanged from the active plan: retasking keeps sorties that are still valid." },
  CHANGED_DUE_TO_EVENT: { label: "Changed by event", sentence: "This sortie was changed because the latest event made the previous version invalid." },
  FROZEN_AIRBORNE: { label: "Frozen", sentence: "The sortie has already taken off, so it cannot be changed by a re-plan." },
};

export const reason = (code: string) =>
  REASONS[code] ?? { label: code.replaceAll("_", " ").toLowerCase(), sentence: "Reason code reported by the planner." };

export const EVENTS: Record<string, string> = {
  AIRCRAFT_UNSERVICEABLE: "Aircraft unserviceable",
  CREW_UNAVAILABLE: "Crew unavailable",
  WEATHER_CHANGE: "Weather change",
  NEW_THREAT: "New threat",
  THREAT_UPDATE: "Threat update",
  AIRSPACE_CHANGE: "Airspace change",
  PRIORITY_CHANGE: "Priority change",
  NEW_MISSION: "New mission",
  MISSION_CANCELLED: "Mission cancelled",
};

export const PRESETS: Record<string, { label: string; sentence: string }> = {
  coverage_first: { label: "Coverage first", sentence: "Cover as many high-priority missions as possible." },
  risk_averse: { label: "Risk averse", sentence: "Prefer lower-risk sorties, even at some cost in coverage." },
  stability_first: { label: "Stability first", sentence: "Change as few existing sorties as possible." },
  greedy_repair: { label: "Greedy repair", sentence: "Keep valid sorties and re-place the rest in priority order." },
};
export const preset = (k: string) => PRESETS[k] ?? { label: k.replaceAll("_", " "), sentence: "" };

export const PLANNERS: Record<string, string> = {
  cpsat: "Optimiser (CP-SAT)",
  greedy: "Greedy baseline",
  fifo: "First-in first-out baseline",
};

export const FIELD_LABELS: Record<string, string> = {
  aircraft_id: "Aircraft",
  crew_ids: "Crew",
  loadout_id: "Loadout",
  takeoff_min: "Take-off",
  land_min: "Landing",
  base_from: "Base",
  base_to: "Recovery base",
};

export const CAPABILITIES: Record<string, string> = {
  AIR_DEFENCE_PATROL: "Air defence patrol",
  STRIKE_SUPPORT_SORTIE: "Strike support",
  RECONNAISSANCE: "Reconnaissance",
  AIRLIFT: "Airlift",
  SEARCH_AND_RESCUE: "Search and rescue",
  AERIAL_REFUELLING: "Aerial refuelling",
  ESCORT: "Escort",
  HADR: "Disaster relief (HADR)",
};

export const SEASONS: Record<string, string> = {
  monsoon: "Monsoon",
  pre_monsoon_heat_dust: "Pre-monsoon heat and dust",
  post_monsoon_cyclone: "Post-monsoon cyclone",
  winter_fog_north: "Winter fog (north)",
};

export const REGIONS: Record<string, string> = {
  north: "North",
  west: "West",
  central: "Central",
  east_ne: "East and North-East",
  south: "South",
  east_coast: "East coast",
};
