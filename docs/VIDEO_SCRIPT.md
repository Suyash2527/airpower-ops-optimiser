# AirPower demo video: voice-over script

Video: `AirPower_SIH26250_demo_4K60.mp4`, 3840 × 2160, 60 fps, 3:07 long, no audio track.
Record your voice over it with the lines below; each line fits its time slot at a calm pace (about 140 words a minute).
On-screen captions already carry the key point of each section, so the video also works muted.

| Time | On screen | Say |
|---|---|---|
| 0:00–0:06 | Title | This is AirPower, for problem SIH26250: air-operations planning and retasking. |
| 0:06–0:17 | Problem | Planners must match scarce aircraft and crews to changing priorities, with data scattered across systems. Re-planning after a fault is painful. |
| 0:17–0:26 | Solution | AirPower fuses the data, builds an optimised plan, and proposes ranked re-plans. Every decision has a reason; a human approves. |
| 0:26–0:36 | 1 · Home: The workflow on one screen | The home page shows the whole workflow. The two amber steps are always a human decision. |
| 0:36–0:48 | 2 · Scenario: Seeded, reproducible scenarios | We load a scenario: real Indian geography and seasons, fictional bases and units. The same seed always gives the same result. |
| 0:48–0:56 | 3 · Data fusion: Two feeds, one trusted record | Two feeds report on the same fleet. AirPower fuses them into one record, showing its source and age. |
| 0:56–1:05 | 3 · Data fusion: Conflicts resolved, not hidden | Where feeds disagree, the fresher, more trusted value is kept, and the other stays visible with the rule used. |
| 1:05–1:17 | 4 · Optimised plan: Generate a plan with the CP-SAT optimiser + Measured, not claimed | We generate a plan with the CP-SAT optimiser, within duty, weather and threat limits. Every figure is read from this run. |
| 1:17–1:25 | 4 · Optimised plan: Every assignment explains itself | Each assignment explains itself, with reason codes and a plain sentence. |
| 1:25–1:35 | 5 · Human approval: Nothing is final until a person approves | The AI only proposes. A planner reviews the draft and approves it, and that decision is recorded. |
| 1:35–1:41 | 6 · Operating picture: One fused map of the operation | The operating picture shows bases, missions by priority, threats, airspace and sorties. |
| 1:41–1:52 | 6 · Operating picture: Scrub through time | Scrubbing the clock shows what is active at any moment. |
| 1:52–2:03 | 7 · Timeline: Every sortie, by aircraft | The timeline shows every sortie by aircraft. Locked sorties are airborne and cannot be changed. |
| 2:03–2:17 | 8 · Dynamic retasking: Something changes mid-operation + Ranked options, never an automatic change | Now something changes. We simulate a disruption, and AirPower re-plans. It returns ranked options with their coverage, risk and stability trade-offs. |
| 2:17–2:31 | 8 · Dynamic retasking: A plan diff a planner can read + The planner decides | Each option shows exactly what it changes, before and after. The planner decides. Approving makes the option the active plan. |
| 2:31–2:40 | 10 · Audit log: Every action is on the record | Every plan, event and decision is logged, so the AI's advice can always be audited. |
| 2:40–2:48 | 11 · Honest by design: What is real and what is simulated | Safe by design: advisory only, synthetic data labelled as such, and no targeting logic at all. |
| 2:48–3:00 | Under the hood | The AI is constraint optimisation with explained reasons, not a black box. An independent validator re-checks every plan, and people decide. |
| 3:00–3:07 | Close | AirPower proposes. A human approves. Thank you. |

## If a judge asks: how do you use AI, and how is it safe?

Say this in your own words; every point is true of the prototype today.

**How we use AI (be precise):**
- The decision engine is constraint optimisation (Google OR-Tools CP-SAT) over a feasibility check of every aircraft, crew, loadout and take-off slot. It is deterministic and seeded, so the same inputs give the same plan.
- Explainability is built in: every assignment and rejection carries a reason code and a plain sentence.
- Machine-learning models (aircraft serviceability, weather impact) and a Gemini-based copilot that explains plans in plain words are designed but **not built yet**. Say "planned", not "done". Until real data exists they could only be trained on synthetic data, and we will label them that way.

**How it stays safe:**
- Advisory only: the system proposes and a person approves; no code path applies a plan change on its own.
- No targeting or weapon-employment logic: it only allocates and schedules aircraft, crews and loads.
- An independent validator re-checks every plan before it is shown (0 violations in 60 benchmark plans).
- Airborne sorties are frozen, so a re-plan can never change a flight that is already under way.
- Append-only audit log of every plan, event and human decision.
- Honest data: everything operational is synthetic and labelled so; open data is credited; a solver fallback is labelled as a fallback.
- Runs fully offline, with no data leaving the machine. The planned copilot would only get read-only tools, and its numbers would be checked against the API.

Notes
- Two waits are time-lapsed (the optimiser solve and the re-plan); a chip on screen says so. The real solver time is the figure shown on the Plan page.
- All operational data shown is synthetic, as the badge and the title card say. Do not describe it as real.
