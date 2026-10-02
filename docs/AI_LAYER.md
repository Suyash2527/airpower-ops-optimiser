# AI_LAYER.md — AI components of AirPower

AirPower uses AI in two kinds of ways: **decision AI**, which does the planning, prediction and checks and runs offline, and **assistant AI**, a Gemini-powered copilot that explains and answers questions. Every AI output is advisory, and a human approves every plan change.

## 1. Component map

| # | Component | Technique / library | Module | Phase |
|---|---|---|---|---|
| A1 | Plan optimiser | OR-Tools CP-SAT | `planning/optimiser.py` | 4 (exists in plan) |
| A2 | Serviceability prediction | scikit-learn gradient boosting + calibration; trained on synthetic history, optionally pre-trained on NASA's public turbofan degradation data (verify licence) | `predict/serviceability.py` | 7 |
| A3 | Weather risk | Real open forecasts + rule/logistic risk model | `predict/weather_impact.py` | 7 |
| A4 | Data anomaly detection | scikit-learn IsolationForest + rule checks (e.g. duty hours > limit, impossible positions) | `ingest/anomaly.py` | 9 |
| A5 | Plan robustness score | Monte Carlo simulation (NumPy): sample failures/weather from predicted probabilities, re-check plan, report % of futures where each mission survives | `planning/robustness.py` | 9 |
| A6 | Planner preference learning | Logistic regression on proposal score components (coverage, risk, stability) from approve/reject history → suggested weight preset | `planning/preferences.py` | 9 |
| A7 | **Gemini copilot** | Gemini API via the official Google Gen AI Python SDK, with function calling | `assistant/` | 9 |

## 2. Gemini copilot (A7) — design

### What it does
1. **Ask the system:** "Which P1 missions are at risk if fog closes BASE-N1 after 0600 IST?" Gemini answers by calling AirPower tools, not from its own knowledge.
2. **Explain:** turns computed explanations (reason codes, diffs, KPIs) into a short briefing for the planner or commander.
3. **Structured intake:** converts a free-text request ("need 2 transports for flood relief near BASE-C1 by 1400") into a draft `Mission` JSON. The draft is shown in a form, and a human must confirm it before it becomes a `NEW_MISSION` event.
4. **What-if in words:** "What if A-017 goes down?" maps to the `/whatif` endpoint and summarises the result.

### Grounding rules (MUST)
- Gemini gets **tools only** (function calling) that wrap existing read-only API functions: `get_snapshot_summary`, `list_missions`, `get_plan`, `explain_assignment`, `get_feasibility`, `run_whatif`, `get_predictions`, `get_proposals`.
- It **never** calls approve/reject or any state-changing endpoint. Mission intake returns a draft only.
- Every number in an answer must come from a tool result. The system prompt says: "If the tools do not return it, say you don't know." The backend checks that numbers in the answer appear in the tool outputs and adds a warning badge if not.
- Answers show the tool calls used ("Sources: get_plan(p_12), get_predictions"), and the UI labels them "AI-generated summary — verify before acting".
- Inputs to Gemini contain synthetic scenario data only. Never send real or sensitive data.

### Configuration
- `GEMINI_API_KEY` and `GEMINI_MODEL` come from environment variables (placeholders in `.env.example`; never commit keys). Do not hard-code a model name. Check Google's current model list and SDK docs at build time and log the choice and date in `DECISIONS.md`.
- Set a low temperature (≈0.2) for factual answers, with a timeout and retry with backoff.
- **Swappable provider:** `assistant/llm.py` defines an `LLMProvider` interface with a `GeminiProvider`. Leave a stub for an offline provider (e.g. a local open model via Ollama) to show an air-gapped deployment path. If no key is configured, the copilot panel shows "Assistant not configured" and the rest of the app works normally.

### UI
- Right-side "Ask AirPower" panel with chat history, suggested questions, tool-call sources, an AI-generated label and a copy-briefing button.
- "Explain in plain words" button on plans and proposals.
- Mission intake: text box → draft form → human confirms.

## 3. Evaluation (honest)

- A2: hold-out AUC/Brier on synthetic data (and NASA data if used), labelled with its data source.
- A4: precision/recall on deliberately injected anomalies in synthetic data.
- A5: report robustness distribution; compare CP-SAT vs greedy plans on robustness across seeds.
- A6: show the weights recovered from a simulated planner with known preferences (a sanity test).
- A7: a fixed set of 20+ test questions with expected tool calls; measure the % of answers where every number traces to a tool output. Report the measured figure only.
- All results go through `benchmarks/` and `RESULTS.md`, per `HONESTY.md`.

## 4. Build order (Phase 9, after the MVP and Phase 7)
1. `assistant/llm.py` interface + GeminiProvider + no-key fallback
2. Tool wrappers (read-only) + function-calling loop + number-grounding check
3. Copilot UI panel + "Explain in plain words"
4. Mission intake draft → confirm flow
5. A4 anomaly detection → fusion report flags
6. A5 robustness score → shown per plan and per proposal
7. A6 preference learning → "suggested weights" card (planner chooses to apply)
8. Evaluation scripts for A4–A7

**DoD:** the copilot answers the test question set using tools only, with zero state-changing calls; the app works with no API key; robustness and anomaly outputs appear in the UI; all evaluation numbers come from scripts.
