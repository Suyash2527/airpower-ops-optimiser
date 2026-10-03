# Demo walkthrough (Phase 6 UI)

Every step below was run in a browser on 2026-10-03 on Windows 11, against the local API (port 5050) and web app
(port 3000), started with `scripts/dev.ps1`. All data is synthetic except the alternate airfields (OurAirports, open
data) and the map outline (Natural Earth, D-64). Numbers quoted are what that single run showed, not benchmarks.

## Start (Windows)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Two windows open (API and web). Open http://localhost:3000. If the script reports port 5050 in use, an old backend is
still running; close it first (D-63).

## Steps

1. **Scenario** (`/`). Click **Load demo scenario**. The page shows the scenario name, id, seed, horizon, season and
   data label, then summary cards read from the snapshot (this run: 3 bases, 40 aircraft with 33 serviceable, 60 crew
   with 45 available, 50 missions, 8 threat zones, 8 airspace zones), a bases table and status badges. The amber
   SYNTHETIC DATA badge is in the header on every page.
2. **Map** (`/map`). Opens on India (Natural Earth outline, India point of view) with neighbours in grey, and bases,
   mission areas, threat zones, airspace restrictions and the active plan's sorties drawn by lat/lon. Verified: the
   time slider (at T+04:00 it reported 3 threat zones active and 5 sorties airborne, drawn bold), clicking a base opens
   its details, **+**/**−** and the mouse wheel zoom around the cursor without scrolling the page, **India**/**All**
   refit the view. The note "Boundaries are not authoritative" is always shown.
3. **Plan** (`/plan`). Click **Generate plan** (CP-SAT, coverage first). This run returned draft v13, solver status
   OPTIMAL, solver time 20.6 s, 16 of 51 missions covered. Each assignment shows crew, loadout, times, risk and reason
   codes; **Why?** expands the explanation. Unassigned missions list their blocking reason codes. Click
   **Approve plan (human decision)**: the status changed to approved.
4. **Timeline** (`/timeline`). Gantt of the active plan's sorties by aircraft, coloured by risk. Clicking a bar shows
   that sortie's explanation.
5. **Fleet & crew** (`/resources`). Fusion summary cards (this run: 256 records fused, 91 open conflicts), then tabs:
   Fleet (40 rows), Crew (60), Missions (50), each with freshness, source-count and conflict badges, and Data conflicts
   (91 rows) showing the kept value, the other source's value, and the rule used.
6. **Proposals** (`/proposals`). With a plan approved, click **Inject simulated event**. This run injected NEW_THREAT
   and listed 3 ranked options, each with coverage/risk deltas, score components and a field-level diff table
   (removed / added / changed, before and after). Nothing is applied until a person clicks. **Approve** on option #1
   made it the active plan (v14) and expired the other two. In an earlier run **Reject** marked a proposal rejected.
   Decided and expired proposals are listed under a collapsed history section.
7. **Audit** (`/audit`). Newest first, in IST: the approval above appears as `proposal.approve` and `plan.supersede`,
   preceded by `retask.propose` and `event.inject`. The action filter narrows the list.

Browser console during steps 1–7 on a fresh tab: no errors. All API calls returned 200.

## Not verified / not built

- Live WebSocket updates are not used by the UI yet; pages refresh after each action.
- KPI comparison against baselines (`/benchmarks/latest`, `/plans/compare`) has no page yet.
- Pinning a fusion conflict from the UI is not built (the API supports it).
- `docker compose up` was not run in this session.
- Phone-width layouts were not checked.
- "Load demo scenario" reloads the same scenario id, so events and plans from earlier runs stay in its history
  (for example the mission count grows after NEW_MISSION events).
