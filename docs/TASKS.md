# TASKS — checklist for Claude Code

Tick `[x]` as you complete. IDs map to `PRD.md` requirements. Do tasks in order within a phase.

## Phase 0 — Scaffold
- [x] 0.1 Create folder layout (see CLAUDE.md), `.gitignore`, `.env.example`
- [x] 0.2 Backend `pyproject.toml` (fastapi, uvicorn, pydantic, sqlmodel, ortools, shapely, pyproj, scikit-learn, httpx, pytest, ruff), `app/main.py`, `/api/v1/health`
- [x] 0.3 Frontend Next.js + TS + Tailwind + MapLibre; layout with SYNTHETIC DATA badge (U-8)
- [ ] 0.4 `docker-compose.yml` (api, web, db)
- [ ] 0.5 `docs/DECISIONS.md` created; smoke test passes

## Phase 1 — Models & generator
- [ ] 1.1 SQLModel tables + Pydantic schemas for all entities in DATA_MODEL.md
- [ ] 1.2 Provenance block on all ingested entities
- [ ] 1.3 `sim/generate.py` with seed + parameters; maintenance-history hazard function documented in code docstring
- [ ] 1.4 Save/load scenario JSON; `scenarios/demo.json` (seed 42)
- [ ] 1.5 Endpoints: generate, load, list, snapshot
- [ ] 1.6 Test: same seed → identical JSON; intentionally infeasible missions present

## Phase 2 — Fusion (F-1…F-5)
- [ ] 2.1 `Adapter` protocol + `SyntheticAdapter`
- [ ] 2.2 `FileAdapter` for CSV/JSON (documented as the template for real feeds)
- [ ] 2.3 Secondary noisy synthetic source for conflicts
- [ ] 2.4 Fusion rules: trust × confidence × time-decay; staleness; conflict list
- [ ] 2.5 `GET fusion-report`, `POST conflicts/{id}/pin` (audited)
- [ ] 2.6 Tests: merge, staleness, conflict, determinism

## Phase 3 — Feasibility & baselines (P-1, P-4, P-5 partial)
- [ ] 3.1 Capability check + test
- [ ] 3.2 Serviceability/availability check + test
- [ ] 3.3 Range/endurance (pyproj geodesic) + test
- [ ] 3.4 Loadout compatibility + stock + test
- [ ] 3.5 Crew qualification, duty limit, rest + tests
- [ ] 3.6 Time-window/transit + test
- [ ] 3.7 Airspace route intersection (shapely) + test
- [ ] 3.8 Weather minima (base + target) + test
- [ ] 3.9 Threat risk limit + test
- [ ] 3.10 Feasibility matrix builder with slot discretisation and reason-code aggregation
- [ ] 3.11 `risk.py` breakdown (threat, weather, service, combined)
- [ ] 3.12 `validate.py` independent validator
- [ ] 3.13 `greedy.py` greedy_priority + fifo; all pass validator on 20 seeds
- [ ] 3.14 `GET /feasibility`

## Phase 4 — Optimiser (P-2, P-3, P-6)
- [ ] 4.1 CP-SAT model: options, z[m], intervals, aircraft NoOverlap
- [ ] 4.2 Crew assignment variables + NoOverlap + duty/rest
- [ ] 4.3 Weapon stock and runway capacity constraints
- [ ] 4.4 Objective with weight presets from `config/weights.yaml`
- [ ] 4.5 Hints from greedy; time limit; seed/workers config; status/gap reporting
- [ ] 4.6 Plan extraction → `Plan`, KPIs, versioning
- [ ] 4.7 `explain.py` for assignments and unassigned missions
- [ ] 4.8 `POST /plans/generate`, `GET /plans/{id}`, `POST /plans/{id}/validate`, `GET /plans/compare`
- [ ] 4.9 Hand-computed optimum tests (≥3), including a greedy-suboptimal case
- [ ] 4.10 Property test: 20 seeds → zero validator violations

## Phase 5 — Retasking (R-1…R-5)
- [ ] 5.1 Event types + payload schemas + `POST /events`
- [ ] 5.2 Event applied to snapshot copy; affected-set detection via validator
- [ ] 5.3 Frozen set (airborne/started)
- [ ] 5.4 Stability penalty + parent hints
- [ ] 5.5 K weight-preset variants, dedupe, diff, ranked proposals with score breakdown
- [ ] 5.6 Greedy repair fallback with `fallback=true`
- [ ] 5.7 Proposal approve/reject → new plan version + audit
- [ ] 5.8 Event simulator (`/events/simulate`, seeded)
- [ ] 5.9 WebSocket hub and message types
- [ ] 5.10 Tests: frozen unchanged; stability; approval creates version/audit; proposals valid

## Phase 6 — Frontend MVP (U-1…U-4, U-7, U-8)
- [ ] 6.1 API client + WebSocket hook
- [ ] 6.2 Scenario page (generate/load, seed input)
- [ ] 6.3 COP map (bases, threat circles, airspace polygons, mission AOIs, planned routes)
- [ ] 6.4 Timeline/Gantt (aircraft × time, priority colours, frozen marker)
- [ ] 6.5 Tables: missions, fleet, crew, weapons — freshness/staleness badges, conflict flags
- [ ] 6.6 Plan view: generate button, KPIs, assignment explanation drawer, unassigned list with reasons
- [ ] 6.7 Alerts + proposal list + diff view + Approve/Reject
- [ ] 6.8 Audit log page
- [ ] 6.9 `docs/DEMO.md` with verified click-through script

## Phase 7 — Prediction, what-if, KPIs (D-1…D-4, U-5, U-6, G7)
- [ ] 7.1 Serviceability training + calibration + persisted model + model card
- [ ] 7.2 Weather synthetic generator + `OpenWeatherAdapter` with cache + offline fallback
- [ ] 7.3 `weather_impact.py`; wire predictions into `risk.py`
- [ ] 7.4 `/predict/*` endpoints; UI predictions panel with synthetic-trained notice
- [ ] 7.5 What-if endpoint + UI sandbox + KPI comparison
- [ ] 7.6 `benchmarks/run_benchmarks.py`, CSV + auto-generated `RESULTS.md`
- [ ] 7.7 KPI dashboard reading only real benchmark output

## Phase 8 — Hardening
- [ ] 8.1 Performance: candidate caps/decomposition if needed; log measured times
- [ ] 8.2 Error handling, input validation, loading/empty states
- [ ] 8.3 README (architecture diagram, run steps, honest limitations)
- [ ] 8.4 `docs/LIMITATIONS.md`
- [ ] 8.5 `docker compose up` verified end-to-end
- [ ] 8.6 Final pass: grep UI/docs for any unmeasured numeric claim
