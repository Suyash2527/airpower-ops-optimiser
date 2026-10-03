"use client";

import { useMemo, useState } from "react";
import { useApi, useScenarioId } from "@/lib/api";
import type { Assignment, Plan, SimEvent, Snapshot } from "@/lib/types";
import { CAPABILITIES, EVENTS } from "@/lib/labels";
import { dur, istAt, pickPlan, riskTone, riskWord, statusTone, tmin } from "@/lib/format";
import { Badge, Card, DetailRows, Drawer, EmptyState, Icon, Meter, PageHeader, PriorityChip, ReasonChip, Skeleton, Tooltip } from "@/components/ui";
import { Gate } from "@/components/shell/states";

const LABEL_W = 208;
const ROW_H = 44;
const RISK_DOT = { green: "bg-emerald-500", amber: "bg-amber-400", red: "bg-red-500", blue: "", grey: "", violet: "" };

export default function TimelinePage() {
  const scenarioId = useScenarioId();
  const snap = useApi<Snapshot>(scenarioId ? `/scenarios/${scenarioId}/snapshot` : null);
  const plans = useApi<Plan[]>(scenarioId ? `/plans?scenario_id=${scenarioId}` : null);
  const events = useApi<SimEvent[]>(scenarioId ? `/events?scenario_id=${scenarioId}` : null);
  const [picked, setPicked] = useState<Assignment | null>(null);
  const plan = plans.data ? pickPlan(plans.data) : null;
  const err = snap.error ?? plans.error ?? events.error;
  const last = events.data?.[events.data.length - 1];

  return (
    <>
      <PageHeader
        title="Timeline"
        purpose="Every planned sortie, by aircraft, from take-off to landing. Colour shows mission priority; a lock marks sorties already airborne that a re-plan cannot change."
      />
      <Gate
        scenarioId={scenarioId}
        error={err}
        ready={!!snap.data && !!plans.data && !!events.data}
        onRetry={() => { snap.reload(); plans.reload(); events.reload(); }}
        skeleton={<GanttSkeleton />}
      >
        {() =>
          !plan ? (
            <EmptyState icon="gantt" title="No plan to show yet">Generate a plan on the Plan page and its sorties appear here.</EmptyState>
          ) : plan.assignments.length === 0 ? (
            <EmptyState icon="gantt" title={`Plan v${plan.version} has no sorties`}>See the Plan page for the missions that could not be covered and why.</EmptyState>
          ) : (
            <Gantt plan={plan} snap={snap.data!} now={last?.time_min ?? plan.inputs?.now_min ?? 0} nowEvent={last} onPick={setPicked} picked={picked} />
          )
        }
      </Gate>
      {picked && snap.data && <SortieDrawer a={picked} snap={snap.data} onClose={() => setPicked(null)} />}
    </>
  );
}

function Gantt({ plan, snap, now, nowEvent, onPick, picked }: { plan: Plan; snap: Snapshot; now: number; nowEvent?: SimEvent; onPick: (a: Assignment) => void; picked: Assignment | null }) {
  const aircraft = useMemo(() => new Map(snap.aircraft.map((a) => [a.id, a])), [snap.aircraft]);
  const missions = useMemo(() => new Map(snap.missions.map((m) => [m.id, m])), [snap.missions]);
  const end = Math.max(snap.scenario.horizon_min, ...plan.assignments.map((a) => a.land_min));
  const x = (m: number) => `${(Math.max(0, Math.min(end, m)) / end) * 100}%`;
  const ticks: number[] = [];
  for (let m = 0; m <= end; m += 120) ticks.push(m);

  // Rows: aircraft with at least one sortie, grouped by base.
  const groups = useMemo(() => {
    const byAc = new Map<string, Assignment[]>();
    for (const a of plan.assignments) byAc.set(a.aircraft_id, [...(byAc.get(a.aircraft_id) ?? []), a]);
    const byBase = new Map<string, [string, Assignment[]][]>();
    for (const [ac, sorties] of byAc) {
      const base = aircraft.get(ac)?.base_id ?? sorties[0].base_from;
      byBase.set(base, [...(byBase.get(base) ?? []), [ac, sorties]]);
    }
    return [...byBase.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([b, rows]) => [b, rows.sort(([p], [q]) => p.localeCompare(q))] as const);
  }, [plan.assignments, aircraft]);
  const baseName = new Map(snap.bases.map((b) => [b.id, b.name]));
  const frozen = plan.assignments.filter((a) => a.frozen).length;

  return (
    <Card padded={false} className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-line px-4 py-4 sm:px-6">
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-semibold text-ink">Plan v{plan.version}</span>
          <Badge tone={statusTone(plan.status)} dot>{plan.status === "approved" ? "Approved, active" : plan.status}</Badge>
          <span className="text-[13px] text-ink-3 tnum">· {plan.assignments.length} sorties on {groups.reduce((n, [, r]) => n + r.length, 0)} aircraft{frozen ? ` · ${frozen} frozen` : ""}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px] text-ink-3 xl:ml-auto">
          <span className="flex items-center gap-1.5">
            Priority
            {[1, 2, 3, 4, 5].map((p) => <span key={p} className="h-3 w-5 rounded-[3px]" style={{ background: `var(--color-p${p})` }} title={`P${p}`} />)}
            <span className="text-xs">1 → 5</span>
          </span>
          <span className="flex items-center gap-1.5"><Icon name="lock" size={14} /> Frozen (airborne)</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-0.5 bg-red-500" /> Simulated now</span>
          <span className="flex items-center gap-1.5">
            Risk
            <span className="h-2 w-2 rounded-full bg-emerald-500" /><span className="h-2 w-2 rounded-full bg-amber-400" /><span className="h-2 w-2 rounded-full bg-red-500" />
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="relative min-w-[1100px]">
          {/* Axis */}
          <div className="sticky top-0 z-10 flex border-b border-line bg-subtle">
            <div className="shrink-0 px-6 py-2.5 text-xs font-semibold text-ink-3" style={{ width: LABEL_W }}>Aircraft</div>
            <div className="relative h-11 flex-1 mr-6">
              {ticks.map((m) => (
                <div key={m} className="absolute top-1.5 -translate-x-1/2 text-center" style={{ left: x(m) }}>
                  <div className="text-xs font-semibold text-ink-2 tnum">{tmin(m)}</div>
                  <div className="text-[10px] text-ink-4 tnum">{istAt(snap.scenario.t0, m).replace(/^\d+ \w+, /, "")}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Rows */}
          <div className="relative">
            {groups.map(([base, rows], gi) => (
              <div key={base}>
                <div className="flex items-center gap-2 border-b border-line bg-surface px-6 py-2">
                  <Icon name="home" size={14} className="text-ink-4" />
                  <span className="text-xs font-semibold uppercase tracking-[0.06em] text-ink-3">{baseName.get(base) ?? base}</span>
                  <span className="text-xs text-ink-4">{base} · {rows.length} aircraft</span>
                </div>
                {rows.map(([ac, sorties], ri) => {
                  const info = aircraft.get(ac);
                  return (
                    <div key={ac} className="flex border-b border-line last:border-b-0 hover:bg-subtle/70" style={{ height: ROW_H }}>
                      <div className="flex shrink-0 flex-col justify-center px-6" style={{ width: LABEL_W }}>
                        <span className="text-sm font-medium text-ink">{ac}</span>
                        <span className="text-[11px] text-ink-3">{info ? `${info.type_id} · ${info.tail}` : ""}</span>
                      </div>
                      <div className="relative mr-6 flex-1">
                        {ticks.map((m) => <div key={m} className="absolute inset-y-0 border-l border-dashed border-line" style={{ left: x(m) }} />)}
                        <div className="enter-grow-x absolute inset-y-0 left-0 bg-[repeating-linear-gradient(135deg,transparent_0_6px,rgb(16_24_40/0.035)_6px_12px)]" style={{ width: x(now), ["--d" as string]: 300 }} />
                        {sorties.map((a, si) => {
                          const p = missions.get(a.mission_id)?.priority ?? 3;
                          const light = p >= 4;
                          const sel = picked?.id === a.id;
                          return (
                            <div key={a.id} className="enter-grow-x absolute inset-y-[7px]" style={{ left: x(a.takeoff_min), width: `max(14px, calc(${x(a.land_min)} - ${x(a.takeoff_min)}))`, ["--d" as string]: 150 + (gi * 4 + ri) * 45 + si * 60 }}>
                              <Tooltip
                                className="h-full w-full"
                                content={
                                  <>
                                    <div className="font-semibold">{a.mission_id} · {missions.get(a.mission_id)?.name ?? ""}</div>
                                    <div className="mt-0.5 text-white/80">{tmin(a.takeoff_min)} → {tmin(a.land_min)} ({dur(a.land_min - a.takeoff_min)}) · priority {p}</div>
                                    <div className="text-white/80">Risk {a.risk.total.toFixed(2)} ({riskWord(a.risk.total).toLowerCase()}){a.frozen ? " · frozen, airborne" : ""}</div>
                                    <div className="mt-1 text-white/60">Click for details</div>
                                  </>
                                }
                              >
                                <button
                                  onClick={() => onPick(a)}
                                  className={`@container flex h-full w-full items-center gap-1 overflow-hidden rounded-md pl-1.5 pr-1 text-left text-[11px] font-semibold shadow-card transition-[filter,box-shadow] hover:brightness-110 ${light ? "text-p1" : "text-white"} ${sel ? "ring-2 ring-ink ring-offset-2" : ""}`}
                                  style={{ background: `var(--color-p${p})` }}
                                >
                                  {a.frozen && <Icon name="lock" size={12} strokeWidth={2.25} />}
                                  <span className="overflow-hidden whitespace-nowrap">{a.mission_id}</span>
                                  <span className={`ml-auto h-2 w-2 shrink-0 @max-[72px]:hidden rounded-full ring-2 ring-white/80 ${RISK_DOT[riskTone(a.risk.total)]}`} />
                                </button>
                              </Tooltip>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}

            {/* Now line spans every row. */}
            <div className="enter-fade pointer-events-none absolute inset-y-0 mr-6" style={{ left: LABEL_W, right: 24, ["--d" as string]: 700 }}>
              <div className="absolute inset-y-0 w-0.5 -translate-x-1/2 bg-red-500" style={{ left: x(now) }}>
                <span className="absolute top-1.5 left-1.5 whitespace-nowrap rounded-full bg-red-500 px-2 py-0.5 text-[11px] font-semibold text-white shadow-card tnum">
                  Now {tmin(now)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 border-t border-line bg-subtle px-6 py-3 text-[13px] text-ink-3">
        <Icon name="clock" size={15} />
        {nowEvent
          ? `Simulated now is the time of the latest event: ${EVENTS[nowEvent.type] ?? nowEvent.type} at ${tmin(nowEvent.time_min)} (${istAt(snap.scenario.t0, nowEvent.time_min)}). Shaded time is in the past.`
          : "Simulated now is scenario start: no events have been injected yet."}
      </div>
    </Card>
  );
}

function SortieDrawer({ a, snap, onClose }: { a: Assignment; snap: Snapshot; onClose: () => void }) {
  const m = snap.missions.find((x) => x.id === a.mission_id);
  const ac = snap.aircraft.find((x) => x.id === a.aircraft_id);
  const t0 = snap.scenario.t0;
  return (
    <Drawer
      open
      onClose={onClose}
      title={
        <span className="flex items-center gap-2.5">
          {m && <PriorityChip p={m.priority} />}
          {a.mission_id} · {a.aircraft_id}
        </span>
      }
      subtitle={m ? `${m.name} · ${CAPABILITIES[m.capability_required] ?? m.capability_required}` : undefined}
    >
      <div className="flex flex-col gap-6">
        {a.frozen && (
          <div className="flex items-center gap-2 rounded-lg border border-brand-200 bg-brand-50/60 px-3 py-2 text-sm text-brand-900">
            <Icon name="lock" size={16} className="text-brand-600" />
            Frozen: this sortie has taken off, so re-plans keep it as it is.
          </div>
        )}
        <section>
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-3">Sortie</h3>
          <DetailRows
            rows={[
              ["Aircraft", ac ? `${a.aircraft_id} · ${ac.type_id} · ${ac.tail}` : a.aircraft_id],
              ["Base", a.base_from],
              ["Take-off", `${tmin(a.takeoff_min)} · ${istAt(t0, a.takeoff_min)}`],
              ["Landing", `${tmin(a.land_min)} · ${istAt(t0, a.land_min)}`],
              ["Flight time", dur(a.land_min - a.takeoff_min)],
              ["Crew", a.crew_ids.join(", ")],
              ["Loadout", a.loadout_id],
            ]}
          />
        </section>
        <section>
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-3">Risk</h3>
          <div className="mt-3 flex flex-col gap-3">
            {(["threat", "weather", "service"] as const).map((k) => (
              <div key={k} className="grid grid-cols-[80px_1fr_44px] items-center gap-3 text-sm">
                <span className="capitalize text-ink-3">{k}</span>
                <Meter value={a.risk[k]} color={k === "threat" ? "var(--color-threat)" : k === "weather" ? "var(--color-brand-500)" : "var(--color-amber-500)"} />
                <span className="text-right font-medium text-ink tnum">{a.risk[k].toFixed(2)}</span>
              </div>
            ))}
            <div className="flex items-center justify-between border-t border-line pt-3 text-sm">
              <span className="font-medium text-ink">Total</span>
              <Badge tone={riskTone(a.risk.total)} dot>{a.risk.total.toFixed(2)} · {riskWord(a.risk.total)}</Badge>
            </div>
          </div>
        </section>
        <section>
          <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-3">Why this sortie</h3>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {a.reasons.map((c) => <ReasonChip key={c} code={c} tone={c === "FROZEN_AIRBORNE" ? "blue" : "grey"} />)}
          </div>
          <p className="mt-3 rounded-lg bg-subtle p-4 text-sm leading-6 text-ink-2">{a.explanation}</p>
        </section>
      </div>
    </Drawer>
  );
}

function GanttSkeleton() {
  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface shadow-card" role="status" aria-label="Loading">
      <div className="flex items-center gap-4 border-b border-line px-6 py-4"><Skeleton className="h-5 w-56" /><Skeleton className="ml-auto h-4 w-80" /></div>
      {Array.from({ length: 9 }, (_, i) => (
        <div key={i} className="flex items-center gap-6 border-b border-line px-6 py-3">
          <Skeleton className="h-4 w-24" />
          <div className="relative h-6 flex-1">
            <div className="skeleton absolute h-6" style={{ left: `${(i * 13) % 60}%`, width: `${12 + ((i * 7) % 18)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}
