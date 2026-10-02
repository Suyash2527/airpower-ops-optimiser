# BUILD_PLAN — phases and gates

Build in order. Each phase has a **Definition of Done (DoD)**; do not proceed until it passes. Items marked **[MVP]** form the minimum viable demo; everything else is stretch.

**MVP cut line = Phases 0–6.** Phases 7–8 only if time remains.

---

## Phase 0 — Scaffold [MVP]
Create repo layout from `CLAUDE.md`, backend (`pyproject.toml`, FastAPI hello, pytest, ruff), frontend (Next.js + Tailwind + MapLibre), `docker-compose.yml`, `.env.example`, `docs/DECISIONS.md` (empty log), CI-less Makefile or scripts.
**DoD:** `pytest` passes (one smoke test), `/api/v1/health` returns OK, frontend renders a page with a map and a "SYNTHETIC DATA" badge.

## Phase 1 — Models + synthetic scenario generator [MVP]
Implement SQLModel/Pydantic entities from `DATA_MODEL.md`, the seeded generator (`sim/generate.py`), scenario JSON save/load, `POST /scenarios/generate`, `GET /scenarios/{id}/snapshot`.
**DoD:** same seed → byte-identical scenario JSON (test); snapshot endpoint returns all entity groups with provenance; generated scenario has some intentionally infeasible missions.

## Phase 2 — Fusion layer [MVP]
Adapter interface; `SyntheticAdapter`; `FileAdapter` (CSV/JSON template); fusion rules (trust, staleness, conflicts); `fusion-report` endpoint. Inject a second noisy synthetic source for some fields to exercise conflicts.
**DoD:** unit tests for merge/staleness/conflict; UI-ready conflict list; fusion is deterministic.

## Phase 3 — Feasibility, risk, validator, baselines [MVP]
`planning/feasibility.py` (all checks + reason codes), `risk.py`, `validate.py`, `greedy.py` (greedy + fifo), `GET /feasibility`.
**DoD:** one unit test per hard constraint (pass and fail case); greedy plans on 20 seeded scenarios all pass `validate` with zero violations.

## Phase 4 — CP-SAT optimiser [MVP]
Model per `ALGORITHMS.md §3`; plan extraction; KPIs; `POST /plans/generate`; explanations for assigned and unassigned.
**DoD:** on small hand-built scenarios the optimiser result equals a hand-computed optimum (at least 3 cases, including a case where greedy is provably worse); on 20 seeded scenarios, every plan passes `validate`; time limit respected; deterministic with fixed seed/workers in tests.

## Phase 5 — Events + retasking [MVP]
Event model + injection + simulator; `retask.py` with frozen set, stability penalty, K variants, diff, ranking, greedy fallback; proposals + approve/reject; audit log; WebSocket hub.
**DoD:** tests — frozen assignments never change; unaffected assignments mostly preserved (assert changes ≤ affected + small slack in a controlled case); approving creates a new plan version and an audit row; proposals pass `validate`.

## Phase 6 — Frontend MVP [MVP]
Pages: Scenario (generate/load), COP map, Timeline (Gantt), Missions/Fleet/Crew/Weapons tables with freshness badges, Plan view with explanations, Alerts + Proposal diff + Approve/Reject, Audit log. WebSocket live updates. Persistent synthetic-data badge.
**DoD:** full demo flow works end-to-end in a browser (see end of `CLAUDE.md`); a short `docs/DEMO.md` records exact click-through steps that were verified.

## Phase 7 — Prediction + what-if + KPI/benchmarks
Serviceability model + model card; weather-impact + Open-Meteo adapter with offline cache; wire predictions into risk; what-if sandbox; `benchmarks/run_benchmarks.py` and auto-generated `benchmarks/RESULTS.md`; KPI dashboard reads real results only.
**DoD:** model card shows held-out synthetic metrics with the synthetic notice; benchmarks run reproducibly; dashboard shows "not measured" if no results file.

## Phase 8 — Hardening and polish
Performance tuning (candidate caps/decomposition), error handling, accessibility pass, README with architecture diagram and honest limitations section, Docker compose end-to-end check, a `docs/LIMITATIONS.md`.
**DoD:** `docker compose up` brings up working app; README commands verified; limitations documented.

## Phase 9 — AI layer (Gemini copilot, robustness, anomalies, preferences)
Follow `docs/AI_LAYER.md` §4 build order. Gemini runs through a swappable `LLMProvider` with read-only function-calling tools; the key and model come from env vars; the app works with no key.
**DoD:** as defined in `AI_LAYER.md` §4.

---

## Cross-cutting checklist for every phase
- [ ] Tests written and passing; `ruff` clean.
- [ ] No hard-coded claims or fabricated figures in UI/docs.
- [ ] Reason codes + explanation present for new decision logic.
- [ ] `docs/TASKS.md` ticked; any deviation logged in `docs/DECISIONS.md`.
- [ ] Commit with clear message.

## Suggested time split (adapt to your actual deadline)
Phases 0–2 ≈ 20%, 3–4 ≈ 30%, 5 ≈ 15%, 6 ≈ 20%, 7–8 ≈ 15%. The optimiser and retasking are the heart of the solution; protect time for them.
