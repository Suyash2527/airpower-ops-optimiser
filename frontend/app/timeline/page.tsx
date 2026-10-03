"use client";

import { useState } from "react";
import { useApi, useScenarioId } from "@/lib/api";
import type { Assignment, Plan, Snapshot } from "@/lib/types";
import { Badge, Card, Empty, ErrorBox, Loading, NeedScenario, PageHeader, pickPlan, riskTone, statusTone, tmin } from "@/components/ui";

const BAR: Record<string, string> = {
  green: "bg-emerald-500 hover:bg-emerald-600",
  amber: "bg-amber-500 hover:bg-amber-600",
  red: "bg-red-500 hover:bg-red-600",
};

export default function TimelinePage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const [picked, setPicked] = useState<Assignment | null>(null);

  const plan = plans.data ? pickPlan(plans.data) : null;
  const err = snap.error ?? plans.error;

  return (
    <>
      <PageHeader
        title="Timeline"
        subtitle="Sorties of the active plan (or the newest draft) by aircraft, from take-off to landing. Bar colour shows total risk; hatched bars are frozen (already under way)."
      />
      {!scenarioId ? (
        <NeedScenario />
      ) : err ? (
        <ErrorBox message={err} onRetry={() => { snap.reload(); plans.reload(); }} />
      ) : !snap.data || !plans.data ? (
        <Loading what="timeline" />
      ) : !plan ? (
        <Empty>No plan yet. Generate one on the Plan page.</Empty>
      ) : plan.assignments.length === 0 ? (
        <Empty>Plan v{plan.version} has no sorties.</Empty>
      ) : (
        <Gantt plan={plan} horizon={snap.data.scenario.horizon_min} picked={picked} onPick={setPicked} />
      )}
    </>
  );
}

function Gantt({ plan, horizon, picked, onPick }: { plan: Plan; horizon: number; picked: Assignment | null; onPick: (a: Assignment) => void }) {
  const byAircraft = new Map<string, Assignment[]>();
  for (const a of plan.assignments) byAircraft.set(a.aircraft_id, [...(byAircraft.get(a.aircraft_id) ?? []), a]);
  const rows = [...byAircraft.entries()].sort(([a], [b]) => a.localeCompare(b));
  const end = Math.max(horizon, ...plan.assignments.map((a) => a.land_min));
  const pct = (m: number) => `${(Math.max(0, m) / end) * 100}%`;
  const ticks: number[] = [];
  for (let m = 0; m <= end; m += 120) ticks.push(m);

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold">Plan {plan.id}</span>
        <Badge>v{plan.version}</Badge>
        <Badge tone={statusTone(plan.status)}>{plan.status}</Badge>
        <Badge>{plan.assignments.length} sorties · {rows.length} aircraft</Badge>
        <span className="ml-auto flex items-center gap-3 text-xs text-slate-600">
          <Legend cls="bg-emerald-500" label="risk < 0.20" />
          <Legend cls="bg-amber-500" label="0.20–0.40" />
          <Legend cls="bg-red-500" label="≥ 0.40" />
        </span>
      </div>
      <Card>
        <div className="overflow-x-auto">
          <div className="min-w-[760px] pr-8">
            <div className="relative ml-24 h-6 border-b border-slate-200 text-xs text-slate-500">
              {ticks.map((m) => (
                <span key={m} className="absolute -translate-x-1/2 font-mono" style={{ left: pct(m) }}>{tmin(m)}</span>
              ))}
            </div>
            {rows.map(([aircraft, sorties]) => (
              <div key={aircraft} className="flex items-center border-b border-slate-100 last:border-0">
                <div className="w-24 shrink-0 py-1.5 pr-2 text-sm font-medium text-slate-700">{aircraft}</div>
                <div className="relative h-8 flex-1">
                  {ticks.map((m) => (
                    <div key={m} className="absolute inset-y-0 border-l border-slate-100" style={{ left: pct(m) }} />
                  ))}
                  {sorties.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => onPick(a)}
                      title={`${a.mission_id} · ${tmin(a.takeoff_min)} → ${tmin(a.land_min)} · risk ${a.risk.total.toFixed(2)}`}
                      className={`absolute top-1 bottom-1 overflow-hidden whitespace-nowrap rounded px-1 text-left text-xs font-medium text-white shadow-sm ${BAR[riskTone(a.risk.total)]} ${picked?.id === a.id ? "ring-2 ring-slate-900 ring-offset-1" : ""}`}
                      style={{
                        left: pct(a.takeoff_min),
                        width: `max(6px, calc(${pct(a.land_min)} - ${pct(a.takeoff_min)}))`,
                        backgroundImage: a.frozen ? "repeating-linear-gradient(45deg, transparent 0 4px, rgb(255 255 255 / 0.35) 4px 8px)" : undefined,
                      }}
                    >
                      {a.mission_id}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Card>
      <Card title="Selected sortie">
        {picked ? (
          <div className="flex flex-col gap-2 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge>{picked.mission_id}</Badge>
              <Badge>{picked.aircraft_id}</Badge>
              <Badge>{picked.base_from}</Badge>
              <Badge>{tmin(picked.takeoff_min)} → {tmin(picked.land_min)}</Badge>
              <Badge tone={riskTone(picked.risk.total)}>risk {picked.risk.total.toFixed(2)}</Badge>
              {picked.frozen && <Badge tone="blue">FROZEN</Badge>}
            </div>
            <p className="text-slate-700">{picked.explanation}</p>
          </div>
        ) : (
          <p className="text-sm text-slate-600">Click a bar to see why that sortie was planned.</p>
        )}
      </Card>
    </>
  );
}

const Legend = ({ cls, label }: { cls: string; label: string }) => (
  <span className="flex items-center gap-1"><span className={`inline-block h-2.5 w-4 rounded-sm ${cls}`} />{label}</span>
);
