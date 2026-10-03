# AirPower demo video: voice-over script

Final narration, Indian English neural voice (Neerja or Prabhat via edge-tts). Each line is timed to its scene and finishes before the scene ends, so the voice never lags the video.
Video: `AirPower_SIH26250_demo_4K60.mp4`, 3840 × 2160, 60 fps, 3:07. The lines below are the source of truth for the narration.

| Time | Scene | Narration |
|---|---|---|
| 0:00–0:06 | Title | This is AirPower: AI decision support for air operations. |
| 0:06–0:17 | Problem | Planners juggle scarce aircraft and crews against shifting priorities, with data locked in separate systems. Re-planning is slow. |
| 0:17–0:26 | Solution | AirPower fuses the data, optimises the plan and proposes ranked re-plans, each explained, each approved by a person. |
| 0:26–0:36 | Home: the workflow | Here is the whole workflow on one screen. The two amber steps are always a human decision, never the machine's. |
| 0:36–0:48 | Scenario | We load a seeded scenario: real Indian geography and seasons, fictional bases and units. Same seed, same result, fully reproducible. |
| 0:48–0:56 | Fusion: two feeds | Two feeds describe one fleet. AirPower fuses them into one record, with source and age. |
| 0:56–1:05 | Fusion: conflicts | When feeds disagree, the fresher, more trusted value wins, and the other stays visible, with the rule. |
| 1:05–1:17 | Plan: optimiser | Now the optimiser: Google's CP-SAT assigns aircraft, crews and loads within duty, weather and threat limits. |
| 1:17–1:25 | Plan: explanations | Every assignment explains itself with a reason code and a plain sentence. No black box. |
| 1:25–1:35 | Approval | The AI only proposes. A planner reviews the draft and approves it. Nothing executes on its own. |
| 1:35–1:41 | Map | The operating picture: bases, missions, threats, airspace and sorties. |
| 1:41–1:52 | Map: time scrub | Scrub the clock and see what is active at any moment: which threats, which mission windows, which sorties are airborne. |
| 1:52–2:03 | Timeline | The timeline shows every sortie by aircraft. Locked sorties are already airborne, and no re-plan can ever change them. |
| 2:03–2:17 | Retasking: disruption | Now, something changes mid-operation. We simulate a disruption, and AirPower returns ranked options, each with its coverage, risk and stability trade-offs. |
| 2:17–2:31 | Retasking: options and decision | Each option shows exactly what it changes, before and after. The planner decides: approve one and it becomes the active plan. Reject, and nothing changes. |
| 2:31–2:40 | Audit log | Every plan, event and decision goes to an append-only audit log, so every recommendation can be audited. |
| 2:40–2:48 | Safe by design | Safe by design: advisory only, synthetic data labelled, and no targeting logic. |
| 2:48–3:00 | Under the hood: the AI | This AI is constraint optimisation with explained reasons, not a black box. A validator re-checks every plan, and people decide. |
| 3:00–3:07 | Close | AirPower proposes. A human approves. Thank you. |

## If a judge asks: how do you use AI, and how is it safe?

**How we use AI (be precise):**
- The decision engine is constraint optimisation (Google OR-Tools CP-SAT) over a feasibility check of every aircraft, crew, loadout and take-off slot. It is deterministic and seeded: the same inputs give the same plan.
- Every assignment and rejection carries a reason code and a plain sentence, so it is explainable.
- Machine-learning models (serviceability, weather impact) and a Gemini copilot that explains plans in plain words are designed but **not built yet**. Say "planned".

**How it stays safe:**
- Advisory only: a person approves every change; no code path applies a plan on its own.
- No targeting or weapon-employment logic: it only allocates aircraft, crews and loads.
- An independent validator re-checks every plan (0 violations in 60 benchmark plans).
- Airborne sorties are frozen, so a re-plan cannot change a flight under way.
- Append-only audit log of every plan, event and human decision.
- Data is synthetic and labelled; a solver fallback is labelled as a fallback.
- Runs fully offline; the planned copilot would get read-only tools, and its numbers would be checked against the API.
