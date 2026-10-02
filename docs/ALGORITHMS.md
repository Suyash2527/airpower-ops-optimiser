# ALGORITHMS

Design principle: use well-understood, explainable methods. No claim beyond what the code does.

## 1. Multi-source data fusion

**Goal:** one consistent `Snapshot` from many feeds.

1. Each adapter yields canonical records with `Provenance`.
2. **Entity resolution:** records match by stable id (`aircraft.id`, `crew.id`, `mission.id`). For feeds lacking ids, a documented key (tail number / name+base) is used.
3. **Field-level merge.** For each field with multiple observations:
   - Discard observations older than `max_age[type]` (configurable; default e.g. aircraft status 60 min, weather 180 min, threats 30 min — placeholders).
   - Score = `source_trust[source] * confidence * exp(-age / tau[type])`.
   - Highest score wins; keep losers in `conflicts[]` if values differ materially.
4. **Staleness flag:** `staleness_min = now - observed_at`; stale if over threshold; the planner uses a conservative value (e.g. stale "SERVICEABLE" is treated as `DEGRADED` risk-wise).
5. **Conflict surfaced to UI** with both values and sources. A human can pin a value (audit-logged).
6. Output: `Snapshot` (immutable) + `FusionReport` (counts of merged/conflicts/stale).

`source_trust` is a config table of numbers we choose; document that they are configuration, not empirical.

## 2. Feasibility engine (`planning/feasibility.py`)

For mission `m`, aircraft `a`, crew set `C`, loadout `l`, base `b`, candidate takeoff `t`:

Hard checks (each returns a `ReasonCode` on failure):
1. **Capability:** `m.capability ∈ type(a).roles`.
2. **Serviceability:** `a.status ∈ {SERVICEABLE, DEGRADED(if allowed for priority)}` and `t ≥ a.available_from`; `hours_since_maintenance + est_flight_hours ≤ limit`.
3. **Range/endurance:** `dist(b, aoi) ≤ combat_radius`; `2*dist/cruise + duration + reserve ≤ endurance`. Reserve fraction configurable.
4. **Loadout:** `l.category` satisfies `m.loadout_category_required`; `l ∈ compatible`; `stock(b, l.items) ≥ qty` for the sortie interval (checked in the optimiser as a cumulative resource).
5. **Crew:** each required role filled by a qualified, `AVAILABLE` crew member at base `b`; duty limit: `duty_last_24h + sortie_duty ≤ max_duty`; rest: `t - last_duty_end ≥ min_rest`.
6. **Time window:** `window_start ≤ arrive_on_station` and `arrive + duration ≤ window_end` (+ transit time).
7. **Airspace:** route polyline does not intersect `NO_FLY/RESTRICTED` active during transit unless the sortie is in a `CORRIDOR`.
8. **Weather minima:** forecast at `b` (takeoff and landing) and at the AOI at the relevant times meets type minima.
9. **Threat limit:** route+AOI `risk ≤ m.max_acceptable_risk`.

Output: boolean + list of reasons. The **matrix** is built over (mission × aircraft × loadout × base-time-slot). To keep it small, time is discretised into slots (e.g. 15 min) for candidate takeoff times.

## 3. Optimiser (`planning/optimiser.py`) — OR-Tools CP-SAT

### 3.1 Decision variables
For each feasible option `o = (m, a, l, t_slot)` (crew handled below):
- `x[o] ∈ {0,1}` option chosen (a sortie).
- Optional interval `I[o]` with start = takeoff, duration = flight time + turnaround, present iff `x[o]`.

Crew: for each required role of the mission and each qualified crew member `c`, `y[o,c] ∈ {0,1}`, with `Σ_c y[o,c] = x[o]` per role.

### 3.2 Constraints
- Each mission `m` gets at most `aircraft_required` sorties, and (if partial coverage is not allowed) either 0 or exactly `aircraft_required`: introduce `z[m] ∈ {0,1}` with `Σ_o x[o] = aircraft_required * z[m]`.
- Each aircraft: `NoOverlap` over its intervals (includes turnaround).
- Each crew member: `NoOverlap` over intervals of options they are assigned to, plus rest gaps; cumulative duty minutes ≤ remaining duty budget.
- Weapon stock: for each base and item type, cumulative consumption (cumulative constraint over time or simple total ≤ stock for horizon in MVP).
- Runway capacity per base per slot: number of takeoffs/landings ≤ capacity (use `Cumulative` or per-slot sums).
- Frozen assignments (retasking): fixed `x = 1`.
- Airspace/threat/weather already filtered by feasibility; time-varying effects encoded by candidate-slot filtering.

### 3.3 Objective (maximise)
```
 Σ_m  W_cov * weight(m) * z[m]
 − Σ_o W_risk * risk(o) * x[o]
 − Σ_o W_cost * cost(o) * x[o]            # flight minutes, loadout cost proxy
 − Σ_a W_bal * utilisation_imbalance(a)    # optional, MVP can skip
 − Σ_o W_stab * 1[o differs from parent plan] * x[o]   # retasking only
```
Integer-scale all coefficients (CP-SAT needs integers). `weight(m)` from priority: e.g. `{1:100, 2:60, 3:35, 4:20, 5:10}` (configurable placeholders). Weights `W_*` live in `config/weights.yaml`; presets: `coverage_first`, `risk_averse`, `stability_first`.

### 3.4 Solver settings
`max_time_in_seconds` configurable, `num_workers` fixed in tests, `random_seed`, hints from parent/greedy plan, report status (OPTIMAL/FEASIBLE), objective, best bound → gap.

### 3.5 Size control
- Prune options dominated by cheaper identical-capability options only if safe; otherwise rely on slot discretisation (15 min) and candidate cap per mission (top-K by cost, K configurable) — document the cap since it can cost optimality.
- If the model exceeds a size threshold, decompose: solve by base cluster or by time-window chunk with frozen earlier chunks.

## 4. Risk model (`planning/risk.py`)

Transparent formula, not a black box:
- **Threat exposure** = Σ over threat zones active during the sortie of `severity × fraction_of_route_inside_zone × confidence`, clipped 0..1 (route = straight segments base→AOI→base; geometry via shapely).
- **Weather risk** = from `predict/weather_impact` (margin above minima mapped to 0..1).
- **Serviceability risk** = `1 − P(mission_capable)` from `predict/serviceability`.
- **Total** = `1 − (1−threat)(1−weather)(1−service)` (independent-risks combination; state this assumption).
`RiskBreakdown` stores each component so the UI can show why.

## 5. Retasking (`planning/retask.py`)

Input: snapshot, active plan, event.
1. Apply event to snapshot copy (e.g. mark aircraft UNSERVICEABLE).
2. **Frozen set:** assignments with `takeoff ≤ now` (airborne/started) are frozen.
3. **Affected set:** assignments invalidated by the event (validator re-check) plus assignments whose mission priority changed.
4. **Variants** (K, default 3): re-solve with different weight presets — `stability_first`, `coverage_first`, `risk_averse` — with parent plan as hint and `W_stab` penalty. Dedupe identical plans.
5. **Diff** vs parent: added/removed/changed assignments, coverage delta, risk delta, number of changes.
6. **Rank** by a documented score (coverage_delta, risk_delta, n_changes); show components, never an opaque score.
7. **Time budget:** if no solution within budget, run `greedy.repair` (reassign affected missions by best available option in priority order) and mark proposal `fallback=true`.
8. Never auto-apply; create `Proposal`s only.

## 6. Baselines (for honest comparison)

- `greedy_priority`: sort missions by priority then window; for each, pick the lowest-cost feasible option; no look-ahead.
- `fifo`: missions in request order, first feasible option.
Both use the same feasibility engine and must pass `validate`.

## 7. Predictive analytics

### 7.1 Serviceability (`predict/serviceability.py`)
- Training data: synthetic maintenance history from the generator (documented hazard function).
- Features: `hours_since_maintenance, aircraft_age_proxy, type, recent_fault_count, planned_flight_hours_next_H`.
- Model: logistic regression (baseline) and gradient-boosted trees (`sklearn`); keep the simpler if no gain. Calibrate probabilities (`CalibratedClassifierCV` or isotonic).
- Output: `P(mission_capable at t)` for t in horizon.
- Evaluation: time-split hold-out on synthetic data; report AUC, Brier score, calibration plot **labelled synthetic**. Include a sanity test: model recovers the monotone effect of hours-since-maintenance defined in the generator.

### 7.2 Weather impact (`predict/weather_impact.py`)
- Rule-based margin: `margin = min over (vis, ceiling, wind) of (forecast − minima)/scale`; map to risk via logistic.
- Real forecast from Open-Meteo (free, no key; verify its terms before demo and record in `DECISIONS.md`); cache responses to a JSON file for offline mode; map the real forecast onto the base's synthetic location only if the fictional base is placed at a chosen real lat/lon, otherwise use a synthetic weather generator and keep the real API as a demonstrated adapter.

## 8. Explainability (`planning/explain.py`)

- Every assignment: why this aircraft/crew/loadout (cost + risk + availability), and top rejected alternative with reason codes.
- Every unassigned mission: dominant blocking `ReasonCode`s with counts from the feasibility matrix (e.g. "No qualified crew in window: 12 of 14 aircraft options blocked by CREW_DUTY_LIMIT").
- Every proposal: what changed, why, and what it costs.
- Templates with filled values only; never LLM-generated claims about facts. (An optional LLM narrator may rephrase *already-computed* explanations; if used, it receives only structured outputs and its text is labelled "AI-generated summary".)

## 9. Validator (`planning/validate.py`)

Independent re-implementation of all hard constraints over a finished `Plan`: capability, range, loadout/stock, crew qualification/duty/rest, aircraft non-overlap, crew non-overlap, time windows, airspace, weather, runway capacity, frozen assignments. Returns a list of violations. **Every plan from any planner must produce an empty list**; tests and benchmarks enforce this.

## 10. Benchmark protocol (`benchmarks/run_benchmarks.py`)

- Generate N scenarios across seeds and difficulty settings (load factor, disruption rate).
- For each: run greedy, fifo, cp-sat; record coverage, weighted coverage, mean/max risk, utilisation, solve ms, violations (must be 0).
- Retasking: inject M seeded disruptions per scenario; record changes made, coverage retained, solve ms, fallback rate.
- Output CSV + `benchmarks/RESULTS.md` (auto-generated with machine info, seeds, N). Docs/UI quote only this file.
