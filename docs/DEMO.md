# Demo walkthrough (Phase 6 minimal slice)

Every step below was run in a browser on 2026-10-03 against the local API and web app. All data is synthetic.
Not covered (not built): Gantt timeline, entity tables, WebSocket live updates, audit page, KPI comparison.
Timings and solve-time figures: **not measured**.

## Start

```bash
cd backend && pip install -e ".[dev]" && python -m uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev
```

Open http://localhost:3000.

## Steps

1. **Scenario** (`/`). Click "Load saved demo scenario", then "Generate (seed 42)". The page shows the scenario id, seed,
   horizon (1440 min), season preset and entity counts (40 aircraft, 60 crew, 50 missions in the run). The amber
   SYNTHETIC DATA badge is in the header on every page. The map is a plain background with no boundaries,
   with the note "Boundaries are not authoritative" (D-22).
2. **Plan** (`/plan`). Click "Generate plan". The page lists 19 assigned and 32 unassigned missions for this run, each
   assignment with its explanation. The plan is a draft; click "Approve plan (human decision)" to make it active.
3. **Proposals** (`/proposals`). Click "Inject one simulated event". The run injected a PRIORITY_CHANGE and listed
   3 open proposals with explanations and score breakdowns. Nothing is applied until you click. Reject on #3 set it to
   rejected. Approve on #1 set it to approved and expired #2.

## Known gaps

- Proposal explanations show the event type next to a different affected-assignment reason
  (a PRIORITY_CHANGE event listed "AIRCRAFT_UNSERVICEABLE"). Not investigated; wording comes from the backend.
- The first Approve click in one run did not register; a second click worked. Cause not investigated.
