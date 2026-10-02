# CLAUDE.md — AirPower (SIH26250)

You are building **AirPower**: an AI-enabled, human-in-the-loop decision-support system for planning and dynamically retasking air operations. This is a Smart India Hackathon 2026 project (problem SIH26250, Ministry of Defence / MIC, Software, Transportation & Logistics bucket).

Read this file fully, then read the docs in this order before writing code:

1. `docs/PRD.md` — what and why
2. `docs/HONESTY.md` — non-negotiable rules about data and claims
3. `docs/ARCHITECTURE.md` — how the system is shaped
4. `docs/DATA_MODEL.md` — entities and schemas
5. `docs/ALGORITHMS.md` — fusion, feasibility, optimisation, retasking, prediction
6. `docs/API_SPEC.md` — REST + WebSocket contract
7. `docs/BUILD_PLAN.md` and `docs/TASKS.md` — the order of work and the checklist
8. `docs/INDIA_CONTEXT.md` — India-specific realism (regions, seasons, elevation, HADR, airspace). Its rules override generic defaults in DATA_MODEL §5 and ALGORITHMS §7.2. Real geography/climate, fictional bases and units.

## Problem in one paragraph

Air-ops planners must assign scarce aircraft, crews and weapon loads to prioritised missions under constraints (airspace, weather, threats, crew duty limits, maintenance). Data lives in separate systems and is not available in one real-time picture, so planning is slow and allocation is sub-optimal, and re-planning when something changes (aircraft breaks, weather closes, new threat, priority change) is painful. AirPower fuses multi-source data into one operating picture, computes feasible and optimised plans, predicts near-term readiness/weather risk, and proposes explainable retasking options that a human approves.

## Hard rules (never break)

1. **Advisory only.** The system proposes; a human approves. No code path may auto-execute a plan change. No weapon-employment or targeting logic. We do allocation/scheduling of resources, nothing more.
2. **All data is synthetic or open, and is labelled so.** Never present synthetic data as real. Never invent real-world military facts, unit names, serial numbers, or performance figures. See `docs/HONESTY.md`.
3. **No fabricated results.** Any number shown in the UI, README or slides (solve time, % improvement, accuracy) must come from a script in `benchmarks/` that actually ran. If it hasn't run, say "not measured".
4. **Explain every decision.** Every assignment, rejection and retasking proposal carries machine-readable reason codes plus a human-readable sentence.
5. **Do not guess missing requirements.** If a spec is ambiguous, pick the simplest reasonable option, write it in `docs/DECISIONS.md` with a one-line rationale, and continue. Do not silently expand scope.

## Stack (fixed unless a decision is logged)

- Backend: Python 3.11+, FastAPI, Pydantic v2, SQLModel (SQLite in dev, PostgreSQL in compose), Google OR-Tools (CP-SAT), shapely + pyproj (geometry), scikit-learn (predictive models), httpx (open weather API), pytest, ruff.
- Frontend: Next.js (App Router) + TypeScript + Tailwind, MapLibre GL JS for the map, a Gantt/timeline component (build simply with SVG/div; do not add heavy libs without logging a decision).
- Realtime: FastAPI WebSocket for events and plan updates.
- Packaging: Docker Compose (api, web, db).

## Repository layout to create

```
airpower/
├─ CLAUDE.md
├─ README.md
├─ docs/                  (already provided)
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/            config, db, logging, time utils
│  │  ├─ models/          SQLModel tables + Pydantic schemas
│  │  ├─ ingest/          adapters + fusion (provenance, staleness, conflicts)
│  │  ├─ sim/             synthetic scenario generator + event simulator
│  │  ├─ planning/        feasibility, risk, optimiser, retasking, explain
│  │  ├─ predict/         serviceability + weather-impact models
│  │  ├─ api/             routers (REST) + websocket
│  │  └─ audit/           audit log
│  ├─ tests/
│  └─ pyproject.toml
├─ frontend/
├─ benchmarks/            scripts that produce every reported number
├─ scenarios/             saved scenario JSON (seeded, reproducible)
└─ docker-compose.yml
```

## Working agreement

- Work **one phase at a time** from `docs/BUILD_PLAN.md`. Do not start phase N+1 until phase N's "Definition of Done" passes.
- Tick items in `docs/TASKS.md` as you finish them.
- Write tests alongside code. Planning code (feasibility, optimiser, retasking) needs unit tests with small hand-checkable cases.
- Everything stochastic takes a `seed`. Same seed ⇒ same scenario ⇒ same result (CP-SAT: set `random_seed`, fixed `num_workers` in tests).
- Commit after each task with a clear message.
- Keep functions small and typed. Run `ruff` and `pytest` before declaring a task done.
- Time is UTC internally; show local (IST) only in UI formatting.
- Distances in km, altitudes in ft, speeds in km/h, weights in kg, time in minutes from scenario start unless noted.

## Commands (create these as you scaffold)

```
# backend
cd backend && pip install -e ".[dev]" && uvicorn app.main:app --reload
cd backend && pytest -q && ruff check .
python -m app.sim.generate --seed 42 --out ../scenarios/demo.json
python benchmarks/run_benchmarks.py --scenarios 30 --seed 1

# frontend
cd frontend && npm install && npm run dev

# all
docker compose up --build
```

## Definition of "done" for the whole project

A user opens the web app, loads a synthetic scenario, sees a fused map + timeline, clicks "Generate plan", gets an optimised plan with explanations, triggers a simulated disruption (e.g. aircraft unserviceable), receives ranked retasking proposals with a plan diff, approves one, and sees the audit log and KPI comparison against baselines — with every figure traceable to a real run.
