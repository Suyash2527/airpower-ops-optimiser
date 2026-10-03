# AirPower demo video v2: narration script

Voice: Sarvam AI Bulbul v3, speaker **Ritu**, English (India), pace 1.08. The video is built narration-first: every sentence is generated, measured, and the matching scene is rendered to last exactly as long as it, so voice and picture never drift. Subtitles show the same words on screen.

Every figure spoken comes from `benchmarks/results/results.csv` (see `benchmarks/RESULTS.md`).

## Title  ·  card

- (7.0 s) This is AirPower: decision support that helps air-operations planners plan better, and re-plan the moment things change.

## The problem  ·  card

- (5.4 s) Planners must match scarce aircraft, crews and weapon loads to missions with competing priorities.
- (6.2 s) But the data is scattered: fleet status, crew rosters, weather, airspace and threats all live in separate systems.
- (4.8 s) Plans take hours, aircraft are under-used, and every disruption means re-planning from scratch.

## Our solution  ·  card

- (8.8 s) AirPower fuses every source into one trusted picture, checks every possible sortie against real constraints, and lets an optimiser build the best plan.
- (5.1 s) When something changes, it proposes ranked repairs, and a human stays in command at every step.

## Live demo  ·  live app

- (6.6 s) Here is the working prototype. The home page lays out the whole workflow, and the two amber steps are always a human decision.

## Live demo · Scenario  ·  live app

- (5.8 s) We start by loading a scenario: real Indian geography and seasons, with fictional bases and units.
- (7.8 s) Everything is seeded, so the same scenario always produces the same result. Forty aircraft, sixty crew and fifty missions are now loaded.

## Live demo · Data fusion  ·  live app

- (4.3 s) Next, data fusion. Two independent feeds report on the same fleet and crews.
- (6.5 s) AirPower merges them into one record per asset, and shows where every value came from, and how old it is.
- (8.5 s) When the feeds disagree, nothing is hidden. The fresher, more trusted value is kept, and the other stays visible beside it, with the rule that decided.

## Live demo · Optimised plan  ·  live app

- (2.1 s) Now, the core of the system: planning.
- (10.3 s) Google's CP-SAT optimiser assigns aircraft, crews and loadouts, respecting range, fuel, crew duty and rest, weather, airspace and threat limits.
- (7.8 s) Every number on this screen comes from this run: missions covered, priority-weighted coverage, risk, and how long the solver took.
- (7.3 s) And every assignment explains itself, with reason codes and a plain-English sentence. Planners see why, not just what.

## Live demo · Human approval  ·  live app

- (4.5 s) Crucially, this plan is only a draft. Nothing is committed until a planner approves it.
- (3.2 s) That decision is recorded, and the plan becomes active.

## Live demo · Operating picture  ·  live app

- (6.7 s) The operating picture puts bases, missions by priority, threat zones, airspace and planned sorties on one map.
- (6.6 s) Scrub the clock, and the picture updates: which threats are active, which mission windows are open, which aircraft are airborne.
- (5.2 s) Hover over any mission to see its window, its requirements, and whether the plan covers it.

## Live demo · Timeline  ·  live app

- (4.1 s) The timeline shows every sortie by aircraft, coloured by mission priority.
- (6.7 s) Open any sortie to see its crew, timing and risk. Locked sorties are already airborne, and no re-plan can touch them.

## Live demo · Dynamic retasking  ·  live app

- (5.2 s) Now, the real test. Mid-operation, an aircraft suddenly goes unserviceable.
- (4.7 s) AirPower checks the active plan, finds every affected sortie, and solves for repairs.
- (4.6 s) It returns ranked options, each showing its trade-off in coverage, risk and stability.
- (5.9 s) Each option shows exactly what would change: sorties added, removed or modified, field by field.
- (5.6 s) The planner decides. Approve one, and it becomes the active plan. Reject, and nothing changes at all.

## Live demo · Audit trail  ·  live app

- (5.4 s) Every plan, every event and every human decision is written to an append-only audit log.
- (6.6 s) And the prototype is honest about itself: what is real, what is simulated, and what a real deployment would still need.

## How we use AI  ·  card

- (2.1 s) So, how does AirPower use AI?
- (6.0 s) Its core is constraint optimisation, the same family of methods airlines use to schedule fleets and crews.
- (7.1 s) It is deterministic and explainable, never a black box. Machine-learning forecasts and a plain-language copilot are next on our roadmap.

## Safe by design  ·  card

- (1.4 s) And how do we keep it safe?
- (5.2 s) It is advisory only: it proposes, people decide, and it contains no targeting logic.
- (5.9 s) A validator re-checks every plan, airborne sorties are frozen, and every decision is audited.

## Measured results  ·  card

- (2.4 s) We measured it, rather than claiming it.
- (10.8 s) Across 20 seeded scenarios, it beat a greedy planner by 8 percent in priority-weighted coverage, and first-in, first-out planning by almost 30 percent, with zero constraint violations.

## Close  ·  card

- (5.4 s) AirPower: one trusted picture, one optimised plan, and explainable re-plans.
- (3.1 s) The system proposes. A human approves. Thank you.

## If a judge asks: how do you use AI, and how is it safe?

- **AI today:** constraint optimisation (Google OR-Tools CP-SAT) over a feasibility check of every aircraft, crew, loadout and slot; deterministic and seeded; every decision carries a reason code and a sentence.
- **Roadmap, not built:** machine-learning forecasts (serviceability, weather impact) and a read-only plain-language copilot. Say "planned".
- **Safety:** advisory only (a person approves every change); no targeting or weapon-employment logic; an independent validator re-checks every plan (0 violations in 60 benchmark plans); airborne sorties are frozen; append-only audit log; synthetic data labelled; runs offline.
