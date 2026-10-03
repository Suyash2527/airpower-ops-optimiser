# AirPower — Dynamic Air Operations & Resource Optimisation

SIH 2026 · Problem SIH26250 · Ministry of Defence / MIC · Software · Transportation & Logistics

An AI-enabled, **human-in-the-loop decision-support prototype** that fuses multi-source operational data, generates optimised air tasking plans, predicts near-term readiness risk, and proposes explainable retasking options when conditions change.

> **Honest scope:** All fleet, crew, mission, threat and maintenance data in this project is **synthetic** and labelled as such. It demonstrates architecture and algorithms with a pluggable adapter layer; it is not validated on real operations and is advisory only.

## Documents (read in this order)
1. `CLAUDE.md` — instructions for Claude Code
2. `docs/PRD.md` — requirements
3. `docs/HONESTY.md` — data/claims rules
4. `docs/ARCHITECTURE.md`
5. `docs/DATA_MODEL.md`
6. `docs/ALGORITHMS.md`
7. `docs/API_SPEC.md`
8. `docs/BUILD_PLAN.md`, `docs/TASKS.md`

## How to start the build with Claude Code (Sonnet 5.5)

1. Create a new folder, copy this whole `airpower/` folder into it, `git init`.
2. Open the folder in Claude Code and use a first prompt like:

```
Read CLAUDE.md and every file in docs/ in the order CLAUDE.md lists.
Summarise the plan back to me in under 15 lines, list any ambiguities,
then begin Phase 0 of docs/BUILD_PLAN.md. Work one phase at a time,
tick docs/TASKS.md, run tests, and commit after each task.
Stop at the end of each phase and show me the Definition of Done evidence.
```

3. After each phase, review, then say: `Proceed to Phase N+1.`
4. Tips: keep sessions per phase; if context gets long, start a new session and say "Read CLAUDE.md and docs/TASKS.md, continue from the first unchecked task."

## Running the backend on Windows (setup note)

Some Windows machines apply an Application Control policy that blocks unsigned compiled wheels
(`scikit-learn`, `pyproj`, `ruff` via `python -m`). Phases 0-6 avoid those two libraries. From
Phase 7 (scikit-learn) and for exact geodesics, run the backend under **WSL2** or **Docker**
(Linux), where they install normally. The policy is not bypassed (docs/DECISIONS.md D-11, D-35).

## Run on Windows

One-time setup:

```powershell
cd backend; pip install --user -e ".[dev]"; cd ..
cd frontend; npm install; cd ..
```

Then, from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

This opens two windows: the API on `http://localhost:5050` (docs at `/docs`) and the web app on
`http://localhost:3000`. The web app reads the API URL from `frontend/.env.local`
(`NEXT_PUBLIC_API_URL`, copied from `frontend/.env.local.example`). `uvicorn` is started with
`python -m uvicorn` because the `--user` install does not put it on PATH. If the script says port
5050 is in use, an older backend is still running; close that window (or `Stop-Process -Id <pid>`).

## Status
Phases 0–5 built (scaffold, synthetic scenarios, fusion, feasibility, risk, validator, greedy/FIFO baselines, CP-SAT optimiser, events and advisory retasking with approve/reject, audit log, WebSocket hub). See `docs/TASKS.md` for the checklist.
