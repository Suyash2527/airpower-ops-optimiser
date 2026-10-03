// Response shapes used by the UI (subset of docs/API_SPEC.md; fields not shown are ignored).

export interface LatLon {
  lat: number;
  lon: number;
}
export interface Provenance {
  source: string;
  observed_at: string;
  confidence: number;
  data_label: string;
}

export interface ScenarioSummary {
  scenario_id: string;
  name: string;
  seed: number;
  horizon_min: number;
  season_preset: string;
  counts: Record<string, number>;
  data_label: string;
}

export interface Base {
  id: string;
  name: string;
  region: string;
  elevation_m: number;
  lat: number;
  lon: number;
  runways: number;
}
export interface Aircraft {
  id: string;
  tail: string;
  type_id: string;
  base_id: string;
  status: string;
  available_from_min: number;
  hours_since_maintenance: number;
  fuel_state_pct: number;
  provenance: Provenance;
}
export interface Crew {
  id: string;
  name: string;
  role: string;
  qualifications: string[];
  base_id: string;
  status: string;
  duty_minutes_last_24h: number;
  provenance: Provenance;
}
export interface Mission {
  id: string;
  name: string;
  capability_required: string;
  priority: number;
  window_start_min: number;
  window_end_min: number;
  duration_min: number;
  aoi: { center: LatLon; radius_km: number };
  aircraft_required: number;
  status: string;
  provenance: Provenance;
}
export interface Threat {
  id: string;
  type: string;
  center: LatLon;
  radius_km: number;
  severity: number;
  active_from_min: number;
  active_to_min: number;
}
export interface Airspace {
  id: string;
  kind: string;
  polygon: { type: string; coordinates: number[][][] };
  active_from_min: number;
  active_to_min: number;
}
export interface Airfield {
  id: string;
  name: string;
  lat: number;
  lon: number;
  provenance: Provenance;
}
export interface FusionMeta {
  source: string;
  sources: string[];
  staleness_min: number;
  stale: boolean;
  stale_fields: Record<string, unknown>;
  conflict_fields: string[];
  pinned_fields: string[];
}

export interface Snapshot {
  scenario: { name: string; seed: number; horizon_min: number; season_preset: string; t0: string };
  scenario_id: string;
  data_label: string;
  state_version: number;
  bases: Base[];
  aircraft: Aircraft[];
  crew: Crew[];
  missions: Mission[];
  threats: Threat[];
  airspace: Airspace[];
  alternate_airfields: Airfield[];
  fusion_meta: Record<string, Record<string, FusionMeta>>;
}

export interface Candidate {
  source: string;
  value: unknown;
  age_min: number;
  score: number;
  selected: boolean;
  stale: boolean;
}
export interface Conflict {
  id: string;
  group: string;
  entity_id: string;
  field: string;
  status: string;
  reason: string;
  resolved_value: unknown;
  resolved_source: string;
  candidates: Candidate[];
  explanation: string;
}
export interface FusionReport {
  counts: Record<string, number>;
  conflicts: Conflict[];
  config: { notice: string };
}

export interface Risk {
  threat: number;
  weather: number;
  service: number;
  total: number;
}
export interface Assignment {
  id: string;
  mission_id: string;
  aircraft_id: string;
  crew_ids: string[];
  loadout_id: string;
  takeoff_min: number;
  land_min: number;
  base_from: string;
  risk: Risk;
  frozen: boolean;
  reasons: string[];
  explanation: string;
}
export interface Unassigned {
  mission_id: string;
  blocking_reasons: { code: string; count: number }[];
  explanation: string;
}
export interface Plan {
  id: string;
  version: number;
  status: string;
  parent_plan_id: string | null;
  created_at: string;
  created_by: string;
  data_label: string;
  assignments: Assignment[];
  unassigned: Unassigned[];
  kpis: Record<string, number>;
  solver: { name?: string; status?: string; wall_ms?: number };
}

export interface DiffChange {
  assignment_id: string;
  field: string;
  from: unknown;
  to: unknown;
}
export interface Proposal {
  id: string;
  event_id: string;
  base_plan_id: string;
  rank: number;
  fallback: boolean;
  status: string;
  preset: string;
  explanation: string;
  event_description: string;
  score_breakdown: Record<string, number>;
  affected_assignment_ids: string[];
  diff: {
    added: string[];
    removed: string[];
    changed: DiffChange[];
    n_changes: number;
    coverage_delta: number;
    risk_delta: number;
  };
}

export interface AuditEntry {
  id: string;
  ts: string;
  actor: string;
  action: string;
  object_type: string;
  object_id: string;
  details: Record<string, unknown>;
}
