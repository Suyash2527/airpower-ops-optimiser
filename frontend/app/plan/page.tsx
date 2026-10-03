"use client";

import { Fragment, useState } from "react";
import { api, useApi, useScenarioId } from "@/lib/api";
import type { Plan, Snapshot } from "@/lib/types";
import { PLANNERS, PRESETS, preset } from "@/lib/labels";
import { dur, pct, pickPlan, riskTone, riskWord, statusTone, tmin } from "@/lib/format";
import {
  Badge, Button, Callout, Card, EmptyState, Icon, KpiCard, Modal, PageHeader, PageSkeleton, PriorityChip,
  ReasonChip, Select, Table, Tabs, Td, Tooltip, Tr,
} from "@/components/ui";
import { Gate, useAction } from "@/components/shell/states";

const ACTOR = "planner-ui";

export default function PlanPage() {
  const scenarioId = useScenarioId();
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const [selected, setSelected] = useState<string | null>(null);
  const [planner, setPlanner] = useState("cpsat");
  const [weights, setWeights] = useState("coverage_first");
  const [confirm, setConfirm] = useState(false);
  const { busy, run } = useAction();

  const list = plans.data ?? [];
  const plan = list.find((p) => p.id === selected) ?? pickPlan(list);

  const generate = () =>
    run(
      "gen",
      () => api<Plan>("/plans/generate", { method: "POST", body: { scenario_id: scenarioId, planner, weight_preset: weights } }),
      (p) => {
        setSelected(p.id);
        plans.reload();
        return [`Draft plan v${p.version} generated`, `${p.kpis.missions_covered ?? 0} of ${p.kpis.missions_total ?? 0} missions covered. Review it, then approve.`];
      },
      "Plan generation failed",
    );
  const approve = (id: string) =>
    run(
      "approve",
      () => api<Plan>(`/plans/${id}/approve`, { method: "POST", body: { actor: ACTOR } }),
      (p) => {
        setConfirm(false);
        plans.reload();
        return [`Plan v${p.version} approved`, "It is now the active plan. The approval is in the audit log."];
      },
      "Approval failed",
    );

  return (
    <>
      <PageHeader
        title="Plan"
        purpose="Assign aircraft, crew and loadouts to the requested missions. A generated plan is a draft until a person approves it."
        actions={
          scenarioId && (
            <>
              <Select label="Planner" value={planner} onChange={(e) => setPlanner(e.target.value)} className="w-56">
                {Object.entries(PLANNERS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </Select>
              <Select label="Objective" value={weights} onChange={(e) => setWeights(e.target.value)} className="w-44">
                {Object.entries(PRESETS).filter(([k]) => k !== "greedy_repair").map(([v, l]) => <option key={v} value={v}>{l.label}</option>)}
              </Select>
              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-transparent select-none" aria-hidden>Run</span>
                <Button variant="primary" icon="zap" loading={busy === "gen"} disabled={busy !== null} onClick={generate}>
                  {busy === "gen" ? "Solving, up to 20 s" : "Generate plan"}
                </Button>
              </div>
            </>
          )
        }
      />

      <Gate scenarioId={scenarioId} error={plans.error} ready={!!plans.data} onRetry={plans.reload} skeleton={<PageSkeleton kpis={4} />}>
        {() =>
          !plan ? (
            <EmptyState icon="clipboard" title="No plan yet" action={<Button variant="primary" icon="zap" loading={busy === "gen"} onClick={generate}>Generate plan</Button>}>
              Generate a first plan for this scenario. The optimiser has up to 20 seconds; the result is a draft for you to review.
            </EmptyState>
          ) : (
            <PlanBody
              plan={plan}
              plans={list}
              snapshot={snap.data}
              onSelect={setSelected}
              onApprove={() => setConfirm(true)}
              approving={busy === "approve"}
            />
          )
        }
      </Gate>

      {plan && (
        <Modal
          open={confirm}
          onClose={() => setConfirm(false)}
          icon="shield"
          tone="green"
          title={`Approve plan v${plan.version}?`}
          actions={
            <>
              <Button onClick={() => setConfirm(false)}>Cancel</Button>
              <Button variant="success" icon="check" loading={busy === "approve"} onClick={() => approve(plan.id)}>Approve plan</Button>
            </>
          }
        >
          It becomes the active plan for this scenario ({plan.assignments.length} sorties, {plan.kpis.missions_covered ?? 0} missions covered). Any
          earlier approved plan is superseded. Your decision is recorded in the audit log as <b className="text-ink">{ACTOR}</b>.
        </Modal>
      )}
    </>
  );
}

function PlanBody({
  plan,
  plans,
  snapshot,
  onSelect,
  onApprove,
  approving,
}: {
  plan: Plan;
  plans: Plan[];
  snapshot: Snapshot | null;
  onSelect: (id: string) => void;
  onApprove: () => void;
  approving: boolean;
}) {
  const [tab, setTab] = useState<"assigned" | "unassigned">("assigned");
  const [open, setOpen] = useState<string | null>(null);
  const k = plan.kpis;
  const missions = new Map((snapshot?.missions ?? []).map((m) => [m.id, m]));
  const solverS = plan.solver.wall_ms !== undefined ? plan.solver.wall_ms / 1000 : undefined;

  return (
    <>
      <Card className="!p-5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-700"><Icon name="clipboard" size={20} /></span>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-semibold text-ink">Plan v{plan.version}</span>
                <Badge tone={statusTone(plan.status)} dot>{plan.status === "approved" ? "Approved, active" : plan.status}</Badge>
              </div>
              <div className="mt-0.5 text-[13px] text-ink-3">
                {PLANNERS[plan.inputs?.planner ?? ""] ?? plan.created_by}
                {plan.inputs?.weight_preset && ` · ${preset(plan.inputs.weight_preset).label}`}
                {plan.parent_plan_id && " · re-plan of an earlier version"}
                <span className="font-mono"> · {plan.id}</span>
              </div>
            </div>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            {plan.solver.status && (
              <Tooltip content="Solver status reported by the API for this run. OPTIMAL means optimal over the candidate set the model considers (D-53); FALLBACK means the greedy plan was used.">
                <span tabIndex={0}><Badge tone={plan.solver.status.startsWith("FALLBACK") ? "amber" : "grey"} icon="gauge">Solver: {plan.solver.status}</Badge></span>
              </Tooltip>
            )}
            <Select label="" aria-label="Plan version" value={plan.id} onChange={(e) => onSelect(e.target.value)} className="w-52">
              {[...plans].reverse().map((p) => <option key={p.id} value={p.id}>Version {p.version} · {p.status}</option>)}
            </Select>
            {plan.status === "draft" && (
              <Button variant="success" icon="check" loading={approving} onClick={onApprove}>Approve plan</Button>
            )}
          </div>
        </div>
        {plan.status === "draft" && (
          <div className="mt-4">
            <Callout tone="blue" icon="shield">This plan is a draft. Nothing is committed until you approve it.</Callout>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-4 gap-6">
        <KpiCard
          icon="target"
          tone="blue"
          label="Missions covered"
          value={k.missions_covered ?? "—"}
          unit={k.missions_total !== undefined ? `of ${k.missions_total}` : undefined}
          meaning="Missions that get every aircraft they asked for."
        />
        <KpiCard
          icon="gauge"
          tone="violet"
          label="Priority-weighted coverage"
          value={k.priority_weighted_coverage !== undefined ? (k.priority_weighted_coverage * 100).toFixed(1) : "not measured"}
          unit={k.priority_weighted_coverage !== undefined ? "%" : undefined}
          meaning="Coverage where high-priority missions count for more."
          footer={k.by_priority && <PriorityBars by={k.by_priority} />}
        />
        <KpiCard
          icon="alert"
          tone={k.mean_risk !== undefined ? riskTone(k.mean_risk) : "grey"}
          label="Mean sortie risk"
          value={k.mean_risk !== undefined ? k.mean_risk.toFixed(2) : "not measured"}
          unit={k.mean_risk !== undefined ? riskWord(k.mean_risk).toLowerCase() : undefined}
          meaning={k.max_risk !== undefined ? `0 is no risk, 1 the highest. Highest single sortie: ${k.max_risk.toFixed(2)}.` : "0 is no risk, 1 the highest."}
        />
        <KpiCard
          icon="clock"
          label="Solver time"
          value={solverS !== undefined ? solverS.toFixed(1) : "not measured"}
          unit={solverS !== undefined ? "s" : undefined}
          meaning={`Measured for this run on this machine. ${plan.assignments.length} sorties, ${k.total_flight_minutes !== undefined ? dur(k.total_flight_minutes) : "—"} flying.`}
        />
      </div>

      <div className="flex flex-col gap-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "assigned", label: "Planned sorties", count: plan.assignments.length, icon: "plane" },
            { key: "unassigned", label: "Not covered", count: plan.unassigned.length, icon: "alert" },
          ]}
        />
        {tab === "assigned" ? (
          plan.assignments.length === 0 ? (
            <EmptyState icon="plane" title="No sorties could be placed">See the missions that are not covered for the reasons.</EmptyState>
          ) : (
            <Table head={["Mission", "Aircraft", "Base", "Take-off → landing", "Crew", "Loadout", "Risk", "Reasons", ""]}>
              {plan.assignments.map((a) => {
                const m = missions.get(a.mission_id);
                const isOpen = open === a.id;
                return (
                  <Fragment key={a.id}>
                    <Tr onClick={() => setOpen(isOpen ? null : a.id)} selected={isOpen} className="border-b-0">
                      <Td>
                        <div className="flex items-center gap-2.5">
                          {m && <PriorityChip p={m.priority} compact />}
                          <div>
                            <div className="font-medium text-ink">{a.mission_id}</div>
                            {m && <div className="max-w-56 truncate text-xs text-ink-3">{m.name}</div>}
                          </div>
                        </div>
                      </Td>
                      <Td className="whitespace-nowrap font-medium text-ink">{a.aircraft_id}</Td>
                      <Td className="whitespace-nowrap">{a.base_from}</Td>
                      <Td className="whitespace-nowrap tnum">{tmin(a.takeoff_min)} <span className="text-ink-4">→</span> {tmin(a.land_min)}</Td>
                      <Td className="whitespace-nowrap text-xs">{a.crew_ids.join(", ")}</Td>
                      <Td className="whitespace-nowrap font-mono text-xs">{a.loadout_id}</Td>
                      <Td>
                        <Tooltip content={`Threat ${a.risk.threat.toFixed(2)} · weather ${a.risk.weather.toFixed(2)} · service ${a.risk.service.toFixed(2)}. Combined assuming the three are independent.`}>
                          <span tabIndex={0}><Badge tone={riskTone(a.risk.total)} dot>{a.risk.total.toFixed(2)}</Badge></span>
                        </Tooltip>
                      </Td>
                      <Td>
                        <div className="flex flex-wrap gap-1">
                          {a.reasons.map((c) => <ReasonChip key={c} code={c} tone={c === "FROZEN_AIRBORNE" ? "blue" : "grey"} />)}
                        </div>
                      </Td>
                      <Td className="text-right">
                        <span className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-700">
                          Why?
                          <Icon name="chevronDown" size={15} className={`transition-transform ${isOpen ? "rotate-180" : ""}`} />
                        </span>
                      </Td>
                    </Tr>
                    <tr>
                      <td colSpan={9} className="p-0">
                        <div className="collapsible" data-open={isOpen}>
                          <div>
                            <div className="mx-5 mb-4 flex gap-3 rounded-lg border border-brand-100 bg-brand-50/50 p-4 text-sm leading-6 text-ink-2">
                              <Icon name="info" size={17} className="mt-0.5 text-brand-600" />
                              <p>{a.explanation}</p>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </Table>
          )
        ) : plan.unassigned.length === 0 ? (
          <EmptyState icon="checkCircle" title="Every mission is covered" />
        ) : (
          <Table head={["Mission", "Why it is not covered", "Explanation"]}>
            {plan.unassigned.map((u) => {
              const m = missions.get(u.mission_id);
              return (
                <Tr key={u.mission_id}>
                  <Td className="w-64">
                    <div className="flex items-center gap-2.5">
                      {m && <PriorityChip p={m.priority} compact />}
                      <div>
                        <div className="font-medium text-ink">{u.mission_id}</div>
                        {m && <div className="max-w-48 truncate text-xs text-ink-3">{m.name}</div>}
                      </div>
                    </div>
                  </Td>
                  <Td className="w-[420px]">
                    <div className="flex flex-wrap gap-1">
                      {u.blocking_reasons.map((b) => <ReasonChip key={b.code} code={b.code} count={b.count} tone="amber" />)}
                    </div>
                  </Td>
                  <Td className="text-[13px] leading-5 text-ink-3">{u.explanation}</Td>
                </Tr>
              );
            })}
          </Table>
        )}
      </div>
    </>
  );
}

function PriorityBars({ by }: { by: Record<string, number> }) {
  return (
    <div className="flex items-end gap-2">
      {[1, 2, 3, 4, 5].map((p) => {
        const v = by[String(p)] ?? 0;
        return (
          <Tooltip key={p} content={`Priority ${p}: ${pct(v)} covered`}>
            <span className="flex flex-1 flex-col items-center gap-1">
              <span className="flex h-10 w-full items-end overflow-hidden rounded-sm bg-slate-100">
                <span className="w-full rounded-sm" style={{ height: `${Math.max(v * 100, v > 0 ? 6 : 0)}%`, background: `var(--color-p${p})` }} />
              </span>
              <span className="text-[11px] font-medium text-ink-3">P{p}</span>
            </span>
          </Tooltip>
        );
      })}
    </div>
  );
}
