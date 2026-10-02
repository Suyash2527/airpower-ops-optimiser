# PRD — AirPower: Dynamic Air Operations & Resource Optimisation

## 1. Source problem (SIH26250)

> Complexity in planning and dynamically retasking air operations in a contested and rapidly changing operational environment. Information on aircraft availability, crew status, weapon loads, airspace, weather, threats and mission priorities is generated across multiple systems but is not always available through a common, real-time decision-support framework, leading to increased planning timelines and sub-optimal allocation of scarce airpower resources.
>
> Technology opportunity: AI-enabled decision-support, multi-source data fusion, predictive analytics and optimisation algorithms.

## 2. Product vision

A single decision-support workspace that (a) fuses the scattered data into one live picture, (b) generates a feasible, optimised air tasking plan in seconds, (c) predicts what is likely to go wrong soon, and (d) when something changes, proposes ranked, explainable retasking options with a minimal-disruption plan diff — leaving the decision to the human planner.

## 3. Users

| Persona | Need |
|---|---|
| Air operations planner | Build/adjust the tasking plan fast; understand why |
| Duty/ops controller | See live status; get alerts and retasking options when things change |
| Commander (viewer) | Summary KPIs: coverage of priorities, utilisation, risk |
| Evaluator/demo viewer | See scenarios, what-ifs, and baseline comparisons |

## 4. Goals and non-goals

**Goals**
- G1 Common operating picture from heterogeneous sources, with provenance, freshness and conflict flags.
- G2 Constraint-correct plan generation: aircraft capability, range/fuel, weapon-load compatibility, crew qualification and duty limits, maintenance state, airspace windows, weather minima, threat exposure.
- G3 Optimisation of priority-weighted mission coverage with risk and effort trade-offs.
- G4 Dynamic retasking on events with stability (few changes) and explanation.
- G5 Predictive analytics: aircraft serviceability for the planning horizon; weather impact on missions.
- G6 Explainability + audit trail; what-if sandbox.
- G7 Measured comparison against naive baselines.

**Non-goals**
- Targeting, weapon employment, kill-chain, real-time flight control.
- Real classified integration, accreditation, hardware/avionics.
- Full 3D trajectory planning or realistic flight dynamics.
- Autonomous execution of plans.

## 5. Functional requirements

IDs are referenced from `TASKS.md`.

### Data fusion (F-xx)
- F-1 Ingest adapters for: fleet status, crew roster, weapon stocks, mission requests, airspace restrictions, threat reports, weather. Each adapter outputs the **canonical schema** (`DATA_MODEL.md`).
- F-2 Each fused record keeps `source`, `observed_at`, `confidence` (0–1), `staleness_min`.
- F-3 Conflict handling: if two sources disagree on the same field, apply the documented rule (`ALGORITHMS.md §1`), store both, flag the conflict in the UI.
- F-4 Staleness: records older than a per-type threshold are shown as stale and down-weighted in planning.
- F-5 Weather adapter fetches real forecast from an open API for a configurable lat/lon, with a cached offline fallback.

### Planning (P-xx)
- P-1 Feasibility engine: for every (mission, aircraft, crew, loadout, time) decide feasible/infeasible with reason codes.
- P-2 Optimiser: CP-SAT model assigning aircraft+crew+loadout and sortie times to missions; objective in `ALGORITHMS.md §3`.
- P-3 Multi-sortie scheduling with turnaround times and no overlap per aircraft and per crew.
- P-4 Risk scoring per assignment (threat exposure along route, weather at target/base, serviceability probability).
- P-5 Unassigned missions listed with the dominant blocking reasons.
- P-6 Plan versioning; baseline vs current plan.

### Retasking (R-xx)
- R-1 Event types: aircraft_unserviceable, crew_unavailable, weather_change, new_threat, airspace_change, priority_change, new_mission, mission_cancelled.
- R-2 On event, the system identifies affected assignments and generates up to N (default 3) alternative plans ranked by score, each with a diff (what changes, what it costs).
- R-3 Stability penalty so retasking changes as few assignments as possible, and never changes sorties already airborne/started.
- R-4 Human approves/rejects; approval creates a new plan version and an audit entry.
- R-5 Fallback greedy repair if the optimiser exceeds its time budget.

### Prediction (D-xx)
- D-1 Serviceability model: probability each aircraft is mission-capable over the next H hours.
- D-2 Weather impact: per-mission/per-base go/no-go risk from forecast vs minima.
- D-3 Predictions feed the optimiser as risk terms and feed the alerts panel.
- D-4 UI labels the models as trained on synthetic data.

### Experience (U-xx)
- U-1 Map: bases, aircraft positions (planned), mission targets as abstract "areas of interest", threat zones, airspace zones, weather overlay.
- U-2 Timeline (Gantt): aircraft rows × time; sorties coloured by mission priority; conflicts highlighted.
- U-3 Mission board, fleet/crew/weapons status tables with freshness badges.
- U-4 Alerts + retasking proposal panel with side-by-side diff and Approve / Reject.
- U-5 What-if sandbox: change inputs on a copy; compare KPIs; never touches the live plan.
- U-6 KPI dashboard and baseline comparison (from measured benchmark results).
- U-7 Audit log viewer.
- U-8 Persistent "SYNTHETIC DATA" badge.

## 6. Non-functional requirements

- N-1 Initial plan for the demo scenario (~40 aircraft, ~60 crews, ~50 missions, 24 h horizon) should solve within a configurable time limit (default 20 s); retasking within 5 s or return best-so-far/greedy repair. These are targets; report actual measured values only.
- N-2 Deterministic runs given a seed.
- N-3 Every API response includes `data_label` indicating synthetic/open source.
- N-4 Role-based access is out of scope for MVP; include a simple role header stub only if time permits.
- N-5 Test coverage of planning code: unit tests for each constraint.

## 7. Success metrics (all measured, none assumed)

| Metric | How measured |
|---|---|
| Priority-weighted mission coverage vs greedy and FIFO baselines | `benchmarks/run_benchmarks.py` over N seeded scenarios |
| Constraint violations in produced plans | validator must report 0 on all scenarios |
| Retasking: assignments changed per event, solve time | benchmark script, simulated disruptions |
| Planning time vs manual | **Do not claim** a manual-time figure unless measured with a real user; present only machine solve time |
| Serviceability model quality | metrics on held-out **synthetic** data, labelled as such |

## 8. Risks

- Scope creep → follow the phase gates in `BUILD_PLAN.md`; MVP cut line defined there.
- CP-SAT model too slow → time limit + greedy fallback + decomposition by base/time window.
- Over-claiming → `HONESTY.md`.

## 9. Glossary

- **Sortie**: one flight of one aircraft from takeoff to landing, assigned to a mission.
- **Mission**: a tasking request with priority, time window, required capability, number of aircraft, and an area of interest.
- **Loadout**: a configuration of stores/payload on an aircraft (treated as a resource attribute).
- **Retasking**: changing assignments in response to an event.
- **COP**: common operating picture.
