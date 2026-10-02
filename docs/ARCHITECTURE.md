# ARCHITECTURE

## 1. Overview

```
 ┌───────────── Sources (synthetic or open) ─────────────┐
 │ fleet │ crew │ weapons │ missions │ airspace │ threats │ weather(API) │
 └───┬───────┬───────┬────────┬─────────┬─────────┬──────────┬──────────┘
     ▼       ▼       ▼        ▼         ▼         ▼          ▼
   [ Adapter layer ]  one adapter per source → canonical schema
                │
                ▼
   [ Fusion service ]  provenance · confidence · staleness · conflict rules
                │ writes fused state
                ▼
   [ State store (DB) ]  current state + history + plans + audit
        │                 │                      │
        ▼                 ▼                      ▼
 [ Prediction ]   [ Planning core ]        [ Event engine ]
  serviceability   feasibility → risk →     sim events / API events
  weather impact   CP-SAT optimiser →            │
        │          retasking → explain           │
        └────────────────┬──────────────────────┘
                         ▼
                [ FastAPI: REST + WebSocket ]
                         ▼
                [ Next.js web app ]
        map · timeline · boards · alerts · what-if · KPI · audit
```

## 2. Modules and responsibilities

| Module | Responsibility | Depends on |
|---|---|---|
| `ingest/adapters/*` | Parse a source into canonical records. Adapters are pluggable: `SyntheticAdapter`, `OpenWeatherAdapter`, and a documented `FileAdapter` (CSV/JSON) as the template for real feeds | models |
| `ingest/fusion.py` | Merge records, apply conflict + staleness rules, emit `FusedState` snapshot | adapters |
| `sim/generate.py` | Seeded scenario generator (fleet, crews, missions, threats, bases, airspace, maintenance history) | models |
| `sim/events.py` | Seeded disruption generator + manual injection | models |
| `planning/feasibility.py` | Pure functions: is (mission, aircraft, crew, loadout, time-window) feasible? returns reasons | models |
| `planning/risk.py` | Route-threat exposure, weather risk, serviceability risk | shapely, predict |
| `planning/optimiser.py` | Build + solve CP-SAT model; extract plan | feasibility, risk |
| `planning/retask.py` | Event → affected set → re-solve with stability → ranked proposals + diff | optimiser |
| `planning/greedy.py` | Baseline and fallback planner | feasibility |
| `planning/validate.py` | Independent constraint validator for any plan (used in tests and benchmarks) | models |
| `planning/explain.py` | Reason codes → human sentences | all planning |
| `predict/serviceability.py` | Train/load model, predict P(mission-capable over horizon) | scikit-learn |
| `predict/weather_impact.py` | Compare forecast to minima → go/no-go risk | weather |
| `api/*` | REST routers, WebSocket hub | all |
| `audit/` | Append-only log of plan versions, proposals, approvals, injected events | db |

## 3. Key design decisions

1. **Planning core is pure and deterministic.** Functions take a `Snapshot` (immutable fused state) and return a `Plan`. No DB or network access inside `planning/`. This makes it testable and benchmarkable.
2. **Independent validator.** `validate.py` re-checks every constraint without using the optimiser's variables. Any plan (CP-SAT, greedy, human-edited) must pass it. This is our guard against model bugs.
3. **Two-stage planning.** Stage A: build the feasibility matrix with reason codes (cheap, explainable). Stage B: CP-SAT optimises only over feasible options, which also shrinks the model.
4. **Retasking = re-optimise with memory.** Freeze started/airborne sorties; add a penalty for changing each existing assignment; hint the solver with the current plan.
5. **Human in the loop.** `Plan.status` ∈ {draft, proposed, approved, superseded}. Only an explicit approve call changes the active plan.
6. **Pluggable data layer.** Adapters implement `fetch() -> list[CanonicalRecord]`. Swapping synthetic for real feeds changes only adapters.
7. **Time model.** Scenario time = integer minutes from `t0`. CP-SAT uses integer minutes; map layer converts to UTC.
8. **Geometry.** Great-circle distance via pyproj/geod for range; shapely for route–threat/airspace intersection in a local equirectangular projection (fine for prototype scale; note this approximation in docs).

## 4. Data flow for the two main use cases

**Generate plan**
1. UI → `POST /plans/generate` (scenario id, optional params).
2. API takes snapshot from state store (fused).
3. `feasibility.build_matrix` → `risk.score` → `optimiser.solve` (time limit) → `validate` → `explain`.
4. Plan saved as `draft`; response returns plan + KPIs; WebSocket pushes `plan.created`.

**Retask on event**
1. Event arrives (sim engine / `POST /events`). Fusion updates state. Event stored.
2. `retask.propose(snapshot, active_plan, event)` → affected assignments → re-solve K variants (e.g. weights favouring stability / coverage / risk) → dedupe → rank.
3. Proposals saved with diffs; WebSocket pushes `proposal.created`; UI shows alert.
4. Human approves one → `POST /proposals/{id}/approve` → new plan version active; audit entry.

## 5. Deployment

Docker Compose: `api` (uvicorn), `web` (next), `db` (postgres). Dev mode uses SQLite and no Docker. Environment variables in `.env.example` (DB URL, solver time limit, weather lat/lon, API base URL).

## 6. Testing strategy

- Unit: each feasibility rule with minimal cases (one aircraft, one mission).
- Property-style: random seeded scenarios → every produced plan passes `validate`.
- Retasking: after an event, no frozen assignment changes; unaffected assignments mostly stay.
- API: FastAPI TestClient for each route.
- Frontend: smoke test that main pages render against a mocked API (keep light).
- Benchmarks are not tests but must be reproducible.
