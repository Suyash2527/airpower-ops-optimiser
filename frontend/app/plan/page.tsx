"use client";

import { useState } from "react";
import { api, useApi, useScenarioId } from "@/lib/api";
import type { Plan } from "@/lib/types";
import { Badge, Button, Card, Empty, ErrorBox, Loading, NeedScenario, PageHeader, Stat, Table, Td, pickPlan, riskTone, statusTone, tmin } from "@/components/ui";

const ACTOR = "planner-ui";
const PLANNERS = [["cpsat", "Optimiser (CP-SAT)"], ["greedy", "Greedy baseline"], ["fifo", "First-in first-out baseline"]] as const;
const PRESETS = [["coverage_first", "Coverage first"], ["risk_averse", "Risk averse"], ["stability_first", "Stability first"]] as const;

export default function PlanPage() {
  const scenarioId = useScenarioId();
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const [selected, setSelected] = useState<string | null>(null);
  const [planner, setPlanner] = useState("cpsat");
  const [preset, setPreset] = useState("coverage_first");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const list = plans.data ?? [];
  const plan = list.find((p) => p.id === selected) ?? pickPlan(list);

  async function act(label: string, fn: () => Promise<Plan>) {
    setBusy(label);
    setError(null);
    try {
      const p = await fn();
      setSelected(p.id);
      plans.reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const generate = () =>
    act("gen", () => api<Plan>("/plans/generate", { method: "POST", body: { scenario_id: scenarioId, planner, weight_preset: preset } }));
  const approve = (id: string) =>
    act("approve", () => api<Plan>(`/plans/${id}/approve`, { method: "POST", body: { actor: ACTOR } }));

  const select = "rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm";

  return (
    <>
      <PageHeader
        title="Plan"
        subtitle="Generate an allocation of aircraft, crew and loadouts to missions. A generated plan is a draft proposal; it becomes active only when a person approves it."
        actions={
          scenarioId && (
            <>
              <select aria-label="Planner" className={select} value={planner} onChange={(e) => setPlanner(e.target.value)}>
                {PLANNERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <select aria-label="Weight preset" className={select} value={preset} onChange={(e) => setPreset(e.target.value)}>
                {PRESETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <Button variant="primary" disabled={busy !== null} onClick={generate}>
                {busy === "gen" ? "Solving (up to 20 s)…" : "Generate plan"}
              </Button>
            </>
          )
        }
      />
      {error && <ErrorBox message={error} />}

      {!scenarioId ? (
        <NeedScenario />
      ) : plans.error ? (
        <ErrorBox message={plans.error} onRetry={plans.reload} />
      ) : !plans.data ? (
        <Loading what="plans" />
      ) : !plan ? (
        <Empty>No plan yet for this scenario. Click <b>Generate plan</b>.</Empty>
      ) : (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-semibold">Plan {plan.id}</span>
              <Badge>v{plan.version}</Badge>
              <Badge tone={statusTone(plan.status)}>{plan.status}</Badge>
              <Badge>by {plan.created_by}</Badge>
              {plan.solver.status && <Badge title="Solver status reported by the API">solver: {plan.solver.status}</Badge>}
              <Badge tone="amber">data: {plan.data_label}</Badge>
              <label className="ml-auto flex items-center gap-2 text-sm text-slate-600">
                Version
                <select className={select} value={plan.id} onChange={(e) => setSelected(e.target.value)}>
                  {[...list].reverse().map((p) => (
                    <option key={p.id} value={p.id}>v{p.version} · {p.status}</option>
                  ))}
                </select>
              </label>
              {plan.status === "draft" && (
                <Button variant="primary" disabled={busy !== null} onClick={() => approve(plan.id)}>
                  {busy === "approve" ? "Approving…" : "Approve plan (human decision)"}
                </Button>
              )}
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Missions covered" value={`${plan.kpis.missions_covered ?? "—"} / ${plan.kpis.missions_total ?? "—"}`} />
            <Stat
              label="Priority-weighted coverage"
              value={plan.kpis.priority_weighted_coverage !== undefined ? plan.kpis.priority_weighted_coverage.toFixed(2) : "not measured"}
            />
            <Stat label="Sorties" value={plan.assignments.length} hint={`${plan.unassigned.length} missions unassigned`} />
            <Stat
              label="Solver time"
              value={plan.solver.wall_ms !== undefined ? `${(plan.solver.wall_ms / 1000).toFixed(1)} s` : "not measured"}
              hint="This run, this machine"
            />
          </div>

          <Card title={`Assignments (${plan.assignments.length})`}>
            {plan.assignments.length === 0 ? (
              <Empty>No sorties could be placed. See the unassigned missions below.</Empty>
            ) : (
              <Table head={["Mission", "Aircraft", "Crew", "Loadout", "Base", "Take-off → land", "Risk", "Reason codes", ""]}>
                {plan.assignments.map((a) => (
                  <FragmentRow key={a.id} expanded={open === a.id} explanation={a.explanation}>
                    <Td className="font-medium">{a.mission_id}</Td>
                    <Td>{a.aircraft_id}</Td>
                    <Td className="text-xs">{a.crew_ids.join(", ")}</Td>
                    <Td>{a.loadout_id}</Td>
                    <Td>{a.base_from}</Td>
                    <Td className="whitespace-nowrap tabular-nums">{tmin(a.takeoff_min)} → {tmin(a.land_min)}</Td>
                    <Td>
                      <Badge tone={riskTone(a.risk.total)} title={`threat ${a.risk.threat.toFixed(2)} · weather ${a.risk.weather.toFixed(2)} · service ${a.risk.service.toFixed(2)}`}>
                        {a.risk.total.toFixed(2)}
                      </Badge>
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {a.frozen && <Badge tone="blue">FROZEN</Badge>}
                        {a.reasons.map((c) => <Badge key={c}>{c}</Badge>)}
                      </div>
                    </Td>
                    <Td>
                      <button className="text-sm font-medium text-sky-700 hover:underline" onClick={() => setOpen(open === a.id ? null : a.id)}>
                        {open === a.id ? "Hide" : "Why?"}
                      </button>
                    </Td>
                  </FragmentRow>
                ))}
              </Table>
            )}
          </Card>

          <Card title={`Unassigned missions (${plan.unassigned.length})`}>
            {plan.unassigned.length === 0 ? (
              <p className="text-sm text-slate-600">Every mission is covered.</p>
            ) : (
              <Table head={["Mission", "Blocking reasons (count of aircraft options)", "Explanation"]}>
                {plan.unassigned.map((u) => (
                  <tr key={u.mission_id}>
                    <Td className="font-medium">{u.mission_id}</Td>
                    <Td>
                      <div className="flex flex-wrap gap-1">
                        {u.blocking_reasons.map((b) => <Badge key={b.code} tone="amber">{b.code} × {b.count}</Badge>)}
                      </div>
                    </Td>
                    <Td className="text-slate-700">{u.explanation}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}

function FragmentRow({ children, expanded, explanation }: { children: React.ReactNode; expanded: boolean; explanation: string }) {
  return (
    <>
      <tr className="hover:bg-slate-50">{children}</tr>
      {expanded && (
        <tr className="bg-sky-50/60">
          <td colSpan={9} className="px-3 py-2 text-sm text-slate-700">{explanation}</td>
        </tr>
      )}
    </>
  );
}
